import streamlit as st
import base64
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import (MODEL_NAME, load_all_sessions, score_badge,
                   build_multi_chat_parts, pick_chat_images)
from google import genai
from google.genai import types

st.title("💬 写真についてチャット")
st.caption("1枚ずつでも、まとめて全体の傾向でも質問できます")

api_key = st.session_state.get("api_key", "")
if not api_key:
    st.warning("APIキーが設定されていないため、チャットは使えません（管理者に連絡してください）")
    st.stop()

sessions = load_all_sessions(username=st.session_state.get("username"))
if not any(s.get("results") for s in sessions):
    st.info("まず「採点」ページで写真を採点してください。")
    st.stop()

# ─── モード選択 ─────────────────────────────────────────────
MODES = {"single": "📷 1枚について", "multi": "🗂️ まとめて（全体の傾向・アドバイス）"}
mode = st.radio(
    "質問の対象", list(MODES.keys()), format_func=MODES.get, horizontal=True,
    index=list(MODES.keys()).index(st.session_state.get("chat_mode", "single")),
)
st.session_state["chat_mode"] = mode


def session_label(s: dict) -> str:
    scores = [r["total_score"] for r in s.get("results", [])]
    avg = f"・平均{sum(scores) / len(scores):.0f}点" if scores else ""
    return f"📅 {s.get('timestamp', '?')}（{s.get('count', len(scores))}枚{avg}）"


# ─── 1枚モード：写真の選択と表示 ───────────────────────────────
if mode == "single":
    all_photos = []
    for session in sessions:
        for result in session.get("results", []):
            all_photos.append({
                "label": f"{result['filename']}  (スコア {result['total_score']}/100) — {session.get('timestamp','')}",
                "data": result,
            })

    # 採点・履歴・検索ページから来た場合は自動選択
    preset = st.session_state.get("chat_photo")
    default_idx = 0
    if preset:
        for i, p in enumerate(all_photos):
            if p["data"].get("filename") == preset.get("filename"):
                default_idx = i
                break

    labels = [p["label"] for p in all_photos]
    selected_label = st.selectbox("写真を選択", labels, index=default_idx)
    selected = all_photos[labels.index(selected_label)]["data"]
    chat_key = f"single::{selected_label}"

    col_img, col_eval = st.columns([1, 2])
    with col_img:
        thumb = selected.get("thumbnail_b64")
        if thumb:
            st.image(base64.b64decode(thumb), caption=selected["filename"])
        else:
            st.caption("(プレビューなし)")

    with col_eval:
        total = selected["total_score"]
        st.markdown(f"**{score_badge(total)}　{total} / 100点**")
        st.progress(total / 100)
        st.caption(f"🔍 技術品質 {selected['technical_score']}/50　— {selected.get('technical_reason','')}")
        st.caption(f"🎨 構図 {selected['composition_score']}/50　— {selected.get('composition_reason','')}")
        st.info(f"💬 {selected.get('overall_comment','')}")

    placeholder = "質問を入力してください（例：構図を改善するには？　ピントが甘い原因は？）"
    suggestions = []

# ─── まとめてモード：対象の写真を選ぶ ──────────────────────────
else:
    ALL = "__all__"
    options = [str(i) for i, s in enumerate(sessions) if s.get("results")] + [ALL]
    default_opt = str(st.session_state.get("chat_session_idx", 0))
    if default_opt not in options:
        default_opt = options[0]

    def fmt(opt: str) -> str:
        if opt == ALL:
            return f"🗃️ すべての履歴（{len(sessions)}回分）"
        return session_label(sessions[int(opt)])

    scope = st.selectbox("どの写真について聞く？", options, index=options.index(default_opt), format_func=fmt)
    st.session_state["chat_session_idx"] = int(scope) if scope != ALL else 0

    if scope == ALL:
        # 同じ写真が何回も採点されていたら1枚にまとめる
        photos, seen = [], set()
        for s in sessions:
            for r in s.get("results", []):
                key = r.get("file_hash") or (r["filename"], r["total_score"])
                if key not in seen:
                    seen.add(key)
                    photos.append(r)
    else:
        photos = list(sessions[int(scope)]["results"])
    photos.sort(key=lambda r: -r["total_score"])
    chat_key = f"multi::{scope}::{len(photos)}"

    scores = [p["total_score"] for p in photos]
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("枚数", f"{len(photos)}枚")
    col_b.metric("平均スコア", f"{sum(scores) / len(scores):.1f}")
    col_c.metric("最高 / 最低", f"{max(scores)} / {min(scores)}")

    with_image = pick_chat_images(photos)
    if len(with_image) < len(photos):
        st.caption(f"※ 枚数が多いので、点数の高い順から均等に{len(with_image)}枚だけ画像も送ります。"
                   "残りは点数とコメントだけで考えます")
    st.caption("⏱ 全部の写真を見てから答えるので、1回の回答に20〜30秒ほどかかります")

    with st.expander("対象の写真を見る（番号はチャットでの呼び方）"):
        cols = st.columns(6)
        for i, p in enumerate(photos):
            with cols[i % 6]:
                if p.get("thumbnail_b64"):
                    st.image(base64.b64decode(p["thumbnail_b64"]))
                st.caption(f"写真{i + 1}・{p['total_score']}点")

    placeholder = "全体について質問してください（例：私の写真の弱点は？　次に練習すべきことは？）"
    suggestions = [
        "全体を通した傾向（得意なこと・苦手なこと）を教えて",
        "よくあるミスと、次の撮影で意識すべきことは？",
        "ベスト3とワースト3を選んで、それぞれの理由を教えて",
    ]

st.divider()

# ─── チャット ────────────────────────────────────────────────
# 対象が切り替わったらチャット履歴をリセット
if st.session_state.get("_chat_key") != chat_key:
    st.session_state["_chat_key"] = chat_key
    st.session_state["_chat_messages"] = []
    st.session_state["_gemini_chat"] = None

col_title, col_reset = st.columns([4, 1])
with col_title:
    st.subheader("チャット")
with col_reset:
    if st.button("🔄 リセット"):
        st.session_state["_chat_messages"] = []
        st.session_state["_gemini_chat"] = None
        st.rerun()

# 会話履歴の表示
for msg in st.session_state.get("_chat_messages", []):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 質問の例（まとめてモードで、まだ何も聞いていないとき）
clicked = None
if suggestions and not st.session_state.get("_chat_messages"):
    st.caption("質問の例")
    for j, s in enumerate(suggestions):
        if st.button(s, key=f"suggest_{j}"):
            clicked = s

user_input = st.chat_input(placeholder) or clicked

if user_input:
    messages = st.session_state.setdefault("_chat_messages", [])
    messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("回答を生成中..." if mode == "single" else f"{len(photos)}枚を見ながら考えています..."):
            try:
                client = genai.Client(api_key=api_key)

                if st.session_state.get("_gemini_chat") is None:
                    # 初回：写真＋採点結果をコンテキストとして送信
                    if mode == "single":
                        thumb_b64 = selected.get("thumbnail_b64", "")
                        context = f"""あなたは写真評価の専門家です。
この写真の採点結果は以下の通りです：
- 技術品質: {selected['technical_score']}/50 — {selected.get('technical_reason','')}
- 構図: {selected['composition_score']}/50 — {selected.get('composition_reason','')}
- 総合スコア: {selected['total_score']}/100
- 総合コメント: {selected.get('overall_comment','')}

写真を見ながら、改善点・良い点・撮影技術について詳しく日本語で回答してください。
最初の質問: {user_input}"""
                        msg_parts = []
                        if thumb_b64:
                            msg_parts.append(types.Part.from_bytes(
                                data=base64.b64decode(thumb_b64), mime_type="image/jpeg"))
                        msg_parts.append(context)
                    else:
                        msg_parts = build_multi_chat_parts(photos, user_input)

                    # サムネイルは200pxしかないので、画像は低解像度で読ませる
                    # （60枚で入力トークンが約1/3になり、回答の質はほぼ同じだった）
                    chat = client.chats.create(
                        model=MODEL_NAME,
                        config=types.GenerateContentConfig(media_resolution="MEDIA_RESOLUTION_LOW"),
                    )
                    response = chat.send_message(msg_parts)
                    st.session_state["_gemini_chat"] = chat
                else:
                    # 2回目以降：テキストのみ（写真は最初のメッセージで渡済み）
                    response = st.session_state["_gemini_chat"].send_message(user_input)

                reply = response.text
                st.write(reply)
                messages.append({"role": "assistant", "content": reply})

            except Exception as e:
                messages.pop()
                st.error(f"エラーが発生しました: {e}")
