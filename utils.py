import json
import time
import io
import base64
from pathlib import Path
from datetime import datetime
from PIL import Image
from google import genai
from google.genai import types
from db import get_db

MODEL_NAME = "gemini-2.5-flash"

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
    try:
        from PIL import ImageOps
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


def score_photo(client, filename: str, raw_bytes: bytes, custom_tags: list = None) -> dict:
    """採点＋タグ生成を1回のAPI呼び出しで実行する"""
    api_bytes, thumb_b64 = prepare_image(raw_bytes)
    prompt = build_scoring_prompt(custom_tags)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    types.Part.from_bytes(data=api_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
            )
            text = response.text if response.text else ""
            if not text.strip():
                raise ValueError("empty response")
            result = parse_json_response(text)
            result["total_score"] = result["technical_score"] + result["composition_score"]
            result["filename"] = filename
            result["thumbnail_b64"] = thumb_b64
            if "tags" not in result:
                result["tags"] = []
            return result
        except Exception:
            if attempt < 4:
                time.sleep(min(5 * (2 ** attempt), 60))
            else:
                raise


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
            )
            text = response.text.strip() if response.text else ""
            if not text:
                raise ValueError("empty response")
            data = parse_json_response(text)
            return data.get("tags", [])
        except Exception:
            if attempt < 2:
                time.sleep(5 * (2 ** attempt))
    return []


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
    response = client.models.generate_content(model=MODEL_NAME, contents=[prompt])
    data = parse_json_response(response.text)
    return data.get("results", [])
