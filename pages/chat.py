import streamlit as st
import base64
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import MODEL_NAME, load_all_sessions, score_badge
from google import genai
from google.genai import types

st.title("💬 写真についてチャット")
st.caption("採点結果について詳しく質問できます")

api_key = st.session_state.get("api_key", "")
if not api_key:
    st.warning("左サイドバーにAPIキーを入力してください")
    st.stop()

# ─── 写真の選択 ─────────────────────────────────────────────
sessions = load_all_sessions(username=st.session_state.get("username"))
all_photos = []
for session in sessions:
    for result in session.get("results", []):
        all_photos.append({
            "label": f"{result['filename']}  (スコア {result['total_score']}/100) — {session.get('timestamp','')}",
            "data": result,
        })

if not all_photos:
    st.info("まず「採点」ページで写真を採点してください。")
    st.stop()

# 採点・履歴ページから来た場合は自動選択
preset = st.session_state.get("chat_photo")
default_idx = 0
if preset:
    for i, p in enumerate(all_photos):
        if p["data"].get("filename") == preset.get("filename"):
            default_idx = i
            break

selected_label = st.selectbox("写真を選択", [p["label"] for p in all_photos], index=default_idx)
selected = next(p["data"] for p in all_photos if p["label"] == selected_label)

# ─── 写真と評価の表示 ────────────────────────────────────────
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

st.divider()

# ─── チャット ────────────────────────────────────────────────
# 写真が切り替わったらチャット履歴をリセット
if st.session_state.get("_chat_photo_name") != selected.get("filename"):
    st.session_state["_chat_photo_name"] = selected.get("filename")
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

# 入力
user_input = st.chat_input("質問を入力してください（例：構図を改善するには？　ピントが甘い原因は？）")

if user_input:
    messages = st.session_state.setdefault("_chat_messages", [])
    messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.write(user_input)

    with st.chat_message("assistant"):
        with st.spinner("回答を生成中..."):
            try:
                client = genai.Client(api_key=api_key)

                if st.session_state.get("_gemini_chat") is None:
                    # 初回：写真＋採点結果をコンテキストとして送信
                    thumb_b64 = selected.get("thumbnail_b64", "")
                    image_bytes = base64.b64decode(thumb_b64) if thumb_b64 else None
                    context = f"""あなたは写真評価の専門家です。
この写真の採点結果は以下の通りです：
- 技術品質: {selected['technical_score']}/50 — {selected.get('technical_reason','')}
- 構図: {selected['composition_score']}/50 — {selected.get('composition_reason','')}
- 総合スコア: {total}/100
- 総合コメント: {selected.get('overall_comment','')}

写真を見ながら、改善点・良い点・撮影技術について詳しく日本語で回答してください。
最初の質問: {user_input}"""

                    chat = client.chats.create(model=MODEL_NAME)
                    msg_parts = []
                    if image_bytes:
                        msg_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                    msg_parts.append(context)
                    response = chat.send_message(msg_parts)
                    st.session_state["_gemini_chat"] = chat
                else:
                    # 2回目以降：テキストのみ
                    response = st.session_state["_gemini_chat"].send_message(user_input)

                reply = response.text
                st.write(reply)
                messages.append({"role": "assistant", "content": reply})

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
