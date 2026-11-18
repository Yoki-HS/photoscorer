import json
import re
import time
import io
import base64
import hashlib
import threading
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageOps
from google import genai
from google.genai import types
from db import get_db

# 採点・タグ生成・検索・チャットで使う標準モデル
# （gemini-2.5-flash は 2026-12-01 に終了するので 3.8-flash に移行）
MODEL_NAME = "gemini-3.8-flash"

# 採点ページで選べるモデル（表示名: モデルID）
# 2026-11 に写真10枚×2回で比較：3.8-flash と 4-hydrogen は順位がほぼ同じ（相関0.88）で、
# 3.8-flash のほうが約4分の1の料金。lite系は採点が甘く、点差が小さいので外した。
SCORING_MODELS = {
    "gemini-3.8-flash（標準・1枚約0.23円）": "gemini-3.8-flash",
    "gemini-4-hydrogen（点差が少し広い・1枚約0.9円）": "gemini-4-hydrogen",
}

# モデルごとのthinking設定（どちらも MINIMAL は非対応）
#   3.8-flash：thinking_budget=0 が使えて、出力トークンが減って安くなる
#   4-hydrogen：budget=0 にしても実際は考えるので、明示的に low にする
_THINKING = {
    "gemini-3.8-flash": types.ThinkingConfig(thinking_budget=0),
    "gemini-4-hydrogen": types.ThinkingConfig(thinking_level="low"),
}


# ─── レート制御 ─────────────────────────────────────────────
class RateLimiter:
    """1分あたりのリクエスト数を守るための簡単なリミッタ（スレッドセーフ）"""

    def __init__(self, rpm: float):
        self.interval = 60.0 / max(rpm, 1)
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self.interval
        if wait > 0:
            time.sleep(wait)

    def pause(self, seconds: float) -> None:
        """429を受けたとき、全スレッドの次の送信をまとめて遅らせる"""
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


def _is_rate_limit(e: Exception) -> bool:
    s = str(e)
    return "429" in s or "RESOURCE_EXHAUSTED" in s


def _retry_delay(e: Exception, default: float) -> float:
    """エラーに含まれる retryDelay（例: '23s'）を読む。なければ default"""
    m = re.search(r"retry(?:Delay|\s+in)['\"]?\s*[:=]?\s*['\"]?([\d.]+)\s*s", str(e), re.I)
    return float(m.group(1)) + 1 if m else default


def _gen_config(model: str, schema: dict = None) -> types.GenerateContentConfig:
    """thinkingを最小にして、JSONで返させる設定"""
    if model in _THINKING:
        thinking = _THINKING[model]
    elif model.startswith("gemini-2.5"):
        thinking = types.ThinkingConfig(thinking_budget=0)
    else:
        thinking = types.ThinkingConfig(thinking_level="low")
    kwargs = {"thinking_config": thinking}
    if schema is not None:
        # 画像を読む細かさを中くらいにする（点数はほぼ同じで、入力トークンが約2〜3割減る）
        kwargs["media_resolution"] = "MEDIA_RESOLUTION_MEDIUM"
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = schema
    return types.GenerateContentConfig(**kwargs)


SCORE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "technical_score": {"type": "INTEGER"},
        "composition_score": {"type": "INTEGER"},
        "total_score": {"type": "INTEGER"},
        "technical_reason": {"type": "STRING"},
        "composition_reason": {"type": "STRING"},
        "overall_comment": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["technical_score", "composition_score", "technical_reason",
                 "composition_reason", "overall_comment", "tags"],
}

TAGS_SCHEMA = {
    "type": "OBJECT",
    "properties": {"tags": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["tags"],
}


def file_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()

SCORING_BASE = """
あなたはプロの写真家であり、厳格な写真品質評価の専門家です。
風景写真・音楽ライブ写真の評価を専門とします。

【採点基準（必ず厳格に適用すること）】
- 一般的なアマチュア写真の平均は50〜65点程度
- 70点以上は明確に優れた点がある写真のみ
- 85点以上は非常に例外的な高品質写真のみ
- ブレ・ピンぼけ・白飛び・黒潰れがある場合は積極的に大きく減点すること
- 「まあまあ良い」程度の写真を高得点にしないこと

【評価項目】
1. 技術的品質 (0〜50点)
   - ピントの正確さとシャープネス（ぼけ・甘ピンは大きく減点）
   - 露出の適切さ（白飛び・黒潰れは大きく減点）
   - ノイズ・粒状感（暗部のノイズも減点）
   - ブレ（手ブレ・被写体ブレは大きく減点）

2. 構図の美しさ (0〜50点)
   - 主題が明確で視線を強く引きつけるか
   - 構図ルール（三分割法・対称性・リーディングライン）の効果的な活用
   - 前景・背景・フレーミングのバランス
   - 余分な要素・煩雑さの排除
"""

JSON_FORMAT_COMBINED = """
【重要】必ず以下のJSON形式のみで回答してください。他のテキストは絶対に含めないこと：
{
  "technical_score": <0〜50の整数>,
  "composition_score": <0〜50の整数>,
  "total_score": <0〜100の整数（上の2つの合計と一致すること）>,
  "technical_reason": "<技術品質の評価理由（25字以内）>",
  "composition_reason": "<構図の評価理由（25字以内）>",
  "overall_comment": "<総合コメント（40字以内）>",
  "tags": ["タグ1", "タグ2", ...]
}
"""


def build_scoring_prompt(custom_tags: list = None) -> str:
    if custom_tags:
        tag_list = "　/　".join(custom_tags)
        tag_section = f"""
【タグ分類】
以下のタグリストから、この写真に該当するものをすべて選んでください。
該当しないタグは絶対に含めないこと。
タグリスト: {tag_list}
"""
    else:
        tag_section = """
【タグ生成】
この写真の内容を表す日本語キーワードを15個以内で生成してください。
被写体・場所・時間帯・天気・色調・雰囲気・撮影シーンなどを含めること。
"""
    return SCORING_BASE + tag_section + JSON_FORMAT_COMBINED


def build_tag_only_prompt(custom_tags: list = None) -> str:
    if custom_tags:
        tag_list = "　/　".join(custom_tags)
        return f"""以下のタグリストから、この写真に該当するものをすべて選んでください。
タグリスト: {tag_list}
以下のJSON形式のみで回答してください：
{{"tags": ["該当タグ1", "該当タグ2", ...]}}"""
    else:
        return """この写真の内容を表す日本語キーワードを15個以内で生成してください。
以下のJSON形式のみで回答してください：
{"tags": ["キーワード1", "キーワード2", ...]}"""


def parse_json_response(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except Exception:
                continue
    return json.loads(text)


def prepare_image(raw_bytes: bytes) -> tuple:
    """画像バイトを受け取り (API用bytes, サムネイルb64文字列) を返す"""
    img = Image.open(io.BytesIO(raw_bytes))
    if img.format == "JPEG":
        # 大きいJPEGは縮小しながらデコードする（読み込みが数倍速い）
        # 送るのは最大1024pxなので、それ以上の解像度は保ったまま縮小される
        img.draft("RGB", (1024, 1024))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    # API用（最大1024px）
    api_img = img.copy()
    if max(api_img.size) > 1024:
        api_img.thumbnail((1024, 1024), Image.LANCZOS)
    api_buf = io.BytesIO()
    api_img.save(api_buf, format="JPEG", quality=85)
    api_bytes = api_buf.getvalue()

    # サムネイル（200x200, 表示・チャット用）
    thumb_img = img.copy()
    thumb_img.thumbnail((200, 200), Image.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb_img.save(thumb_buf, format="JPEG", quality=55)
    thumb_b64 = base64.b64encode(thumb_buf.getvalue()).decode()

    return api_bytes, thumb_b64


def score_photo(client, filename: str, raw_bytes: bytes, custom_tags: list = None,
                model: str = MODEL_NAME, limiter: RateLimiter = None) -> dict:
    """採点＋タグ生成を1回のAPI呼び出しで実行する"""
    api_bytes, thumb_b64 = prepare_image(raw_bytes)
    prompt = build_scoring_prompt(custom_tags)
    config = _gen_config(model, SCORE_SCHEMA)

    other_errors = 0
    rate_errors = 0
    while True:
        if limiter:
            limiter.acquire()
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=api_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
                config=config,
            )
            text = response.text if response.text else ""
            if not text.strip():
                raise ValueError("empty response")
            result = parse_json_response(text)
            result["technical_score"] = max(0, min(50, int(result["technical_score"])))
            result["composition_score"] = max(0, min(50, int(result["composition_score"])))
            result["total_score"] = result["technical_score"] + result["composition_score"]
            result["filename"] = filename
            result["thumbnail_b64"] = thumb_b64
            result["file_hash"] = file_hash(raw_bytes)
            if "tags" not in result:
                result["tags"] = []
            return result
        except Exception as e:
            if _is_rate_limit(e):
                # 無料枠の上限：指定された秒数だけ全体を止めてから再送（失敗回数には数えすぎない）
                rate_errors += 1
                if rate_errors > 6:
                    raise
                delay = _retry_delay(e, 15)
                if limiter:
                    limiter.pause(delay)
                else:
                    time.sleep(delay)
            else:
                other_errors += 1
                if other_errors > 2:
                    raise
                time.sleep(2 * other_errors)


def generate_tags(client, image_bytes: bytes, custom_tags: list = None) -> list:
    """既存写真の遡及タグ生成（thumbnail_b64をdecodeしたbytesを渡す）"""
    prompt = build_tag_only_prompt(custom_tags)
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
                config=_gen_config(MODEL_NAME, TAGS_SCHEMA),
            )
            text = response.text.strip() if response.text else ""
            if not text:
                raise ValueError("empty response")
            data = parse_json_response(text)
            return data.get("tags", [])
        except Exception as e:
            if attempt < 2:
                time.sleep(_retry_delay(e, 5 * (2 ** attempt)) if _is_rate_limit(e) else 2)
    return []


MAX_CHAT_IMAGES = 60  # まとめてチャットで画像として送る最大枚数（残りは点数・コメントだけ送る）


def pick_chat_images(photos: list, limit: int = MAX_CHAT_IMAGES) -> set:
    """画像として送る写真の番号（0始まり）を選ぶ。多すぎるときは点数順に均等に間引く"""
    n = len(photos)
    if n <= limit:
        return set(range(n))
    order = sorted(range(n), key=lambda i: -photos[i].get("total_score", 0))
    step = (n - 1) / (limit - 1)
    return {order[round(k * step)] for k in range(limit)}


def build_multi_chat_parts(photos: list, question: str) -> list:
    """複数の写真について質問するための、最初のメッセージ（文章＋サムネイル）を作る"""
    from collections import Counter
    n = len(photos)
    totals = [p["total_score"] for p in photos]
    techs = [p.get("technical_score", 0) for p in photos]
    comps = [p.get("composition_score", 0) for p in photos]
    tag_count = Counter(t for p in photos for t in p.get("tags", []))
    top_tags = "、".join(f"{t}({c})" for t, c in tag_count.most_common(15)) or "なし"
    with_image = pick_chat_images(photos)

    lines = []
    for i, p in enumerate(photos, 1):
        lines.append(
            f"写真{i}: {p['filename']} | 総合 {p['total_score']}/100"
            f"（技術 {p.get('technical_score', '?')}/50・構図 {p.get('composition_score', '?')}/50）"
            f" | 技術: {p.get('technical_reason', '')} | 構図: {p.get('composition_reason', '')}"
            f" | コメント: {p.get('overall_comment', '')} | タグ: {'、'.join(p.get('tags', []))}"
            + ("" if (i - 1) in with_image else " | （画像なし）")
        )

    header = f"""あなたはプロの写真家で、写真の講評と上達のアドバイスの専門家です。
ユーザーが撮った写真{n}枚の採点結果と、写真のサムネイルを渡します。
個々の写真ではなく、全体を通して見える傾向（得意・苦手、よくあるミス、撮影シーンの偏りなど）や、
次の撮影で意識するとよいことを、具体的な写真番号を挙げながら日本語で答えてください。
サムネイルは小さいので、ピントやノイズなど細かい点は採点結果の文章も参考にしてください。

【全体の数字】
- 枚数: {n}枚（うち画像つき {len(with_image)}枚）
- 総合: 平均 {sum(totals) / n:.1f} / 最高 {max(totals)} / 最低 {min(totals)}
- 技術品質の平均: {sum(techs) / n:.1f}/50、構図の平均: {sum(comps) / n:.1f}/50
- よく出るタグ: {top_tags}

【写真ごとの採点結果】
""" + "\n".join(lines)

    parts = [header, "\n【サムネイル】"]
    for i, p in enumerate(photos):
        thumb = p.get("thumbnail_b64")
        if i in with_image and thumb:
            parts.append(f"写真{i + 1}: {p['filename']}")
            parts.append(types.Part.from_bytes(data=base64.b64decode(thumb), mime_type="image/jpeg"))
    parts.append(f"\n【最初の質問】\n{question}")
    return parts


def score_badge(score: int) -> str:
    if score >= 85:
        return "🌟 優秀"
    elif score >= 70:
        return "✅ 良好"
    elif score >= 50:
        return "🔶 普通"
    else:
        return "❌ 要改善"


def save_session(folder_name: str, results: list, username: str = None) -> None:
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    get_db().table("sessions").insert({
        "username": username or "anonymous",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "folder_name": folder_name,
        "count": len(clean),
        "results": clean,
    }).execute()


def load_all_sessions(username: str = None) -> list:
    q = get_db().table("sessions").select("*")
    if username:
        q = q.eq("username", username)
    rows = q.order("created_at", desc=True).execute().data
    sessions = []
    for row in rows:
        sessions.append({
            "timestamp": row["timestamp"],
            "folder": row.get("folder_name", ""),
            "count": row["count"],
            "results": row["results"],
            "_db_id": row["id"],
        })
    return sessions


def update_session_file(session: dict) -> None:
    db_id = session.get("_db_id")
    if not db_id:
        return
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in session["results"]]
    get_db().table("sessions").update({
        "results": clean,
        "count": len(clean),
    }).eq("id", db_id).execute()


def search_photos(client, query: str, all_photos: list) -> list:
    if not all_photos:
        return []
    photo_list = "\n".join(
        f"{i+1}. {p['filename']}: {p.get('tags', [])}"
        for i, p in enumerate(all_photos)
    )
    prompt = f"""以下の写真コレクションから「{query}」に最も合致する写真を選んでください。

写真一覧（ファイル名: タグ）:
{photo_list}

上位5枚を合致度の高い順に選び、以下のJSON形式のみで回答してください：
{{
  "results": [
    {{"filename": "ファイル名.JPG", "score": <0-100の整数>, "reason": "<合致する理由（20字以内）>"}},
    ...
  ]
}}"""
    response = client.models.generate_content(
        model=MODEL_NAME, contents=[prompt], config=_gen_config(MODEL_NAME))
    data = parse_json_response(response.text)
    return data.get("results", [])
