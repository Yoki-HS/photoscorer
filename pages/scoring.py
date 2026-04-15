import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import score_photo, score_badge, save_session
from google import genai

st.title("📸 写真採点")
st.caption("写真をアップロードして採点を開始してください")

with st.sidebar:
    st.divider()
    st.subheader("処理オプション")
    max_photos = st.number_input("最大処理枚数", min_value=1, max_value=1000, value=50)
    parallel = st.slider("並列処理数", min_value=1, max_value=10, value=5,
                         help="同時処理数。エラーが多い場合は減らしてください")
    st.caption("⏱ 並列5で50枚 → 約30秒")

# ─── ファイルアップロード ─────────────────────────────────────
uploaded_files = st.file_uploader(
    "📁 写真をアップロード",
    type=["jpg", "jpeg", "png", "webp", "bmp", "tiff"],
    accept_multiple_files=True,
    help="複数ファイルを一度に選択できます（Ctrl+クリックで複数選択）"
)

api_key = st.session_state.get("api_key", "")

if uploaded_files:
    count = min(len(uploaded_files), int(max_photos))
    st.success(f"📷 {len(uploaded_files)}枚選択済み（最大{int(max_photos)}枚を処理）")

start_btn = st.button(
    "▶ 採点開始",
    type="primary",
    disabled=not (api_key and uploaded_files)
)

if start_btn and uploaded_files:
    target = uploaded_files[:int(max_photos)]
    file_data = [(f.name, f.read()) for f in target]

    client = genai.Client(api_key=api_key)
    custom_tags = st.session_state.get("custom_tags") or None
    results = []
    errors = []
    completed = 0

    progress_bar = st.progress(0, text="採点を開始します...")
    status_text = st.empty()

    with ThreadPoolExecutor(max_workers=int(parallel)) as executor:
        future_to_name = {
            executor.submit(score_photo, client, name, data, custom_tags): name
            for name, data in file_data
        }
        for future in as_completed(future_to_name):
            fname = future_to_name[future]
            completed += 1
            status_text.markdown(f"**処理中... {completed}/{len(file_data)}**　`{fname}`")
            progress_bar.progress(completed / len(file_data), text=f"{completed}/{len(file_data)} 枚処理中")
            try:
                results.append(future.result())
            except Exception as e:
                errors.append(f"{fname}: {e}")

    progress_bar.progress(1.0, text="✅ 採点完了！")
    status_text.empty()

    if errors:
        with st.expander(f"⚠️ {len(errors)}枚の処理に失敗しました"):
            for err in errors:
                st.text(err)

    if results:
        results.sort(key=lambda x: x["total_score"], reverse=True)
        save_session(
            folder_name=f"{len(results)}枚",
            results=results,
            username=st.session_state.get("username")
        )
        st.session_state["results"] = results

# ─── 結果表示 ──────────────────────────────────────────────
if "results" in st.session_state:
    results = st.session_state["results"]

    st.divider()
    st.subheader(f"🏆 採点結果ランキング（{len(results)}枚）")

    scores = [r["total_score"] for r in results]
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("平均スコア", f"{sum(scores)/len(scores):.1f} / 100")
    col_b.metric("最高スコア", f"{max(scores)} / 100")
    col_c.metric("最低スコア", f"{min(scores)} / 100")
    st.divider()

    for rank, result in enumerate(results, 1):
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
        total = result["total_score"]

        with st.container():
            col_img, col_info = st.columns([1, 2])
            with col_img:
                thumb = result.get("thumbnail_b64")
                if thumb:
                    st.image(base64.b64decode(thumb))
                else:
                    st.caption("(プレビューなし)")

            with col_info:
                st.markdown(f"### {medal} {result['filename']}")
                st.markdown(f"**総合評価: {score_badge(total)}**")
                bar_color = "🟢" if total >= 70 else "🟡" if total >= 50 else "🔴"
                st.markdown(f"{bar_color} **総合スコア: {total} / 100**")
                st.progress(total / 100)

                col_t, col_c2 = st.columns(2)
                with col_t:
                    st.metric("🔍 技術品質", f"{result['technical_score']} / 50")
                    st.caption(result.get("technical_reason", ""))
                with col_c2:
                    st.metric("🎨 構図", f"{result['composition_score']} / 50")
                    st.caption(result.get("composition_reason", ""))
                st.info(f"💬 {result.get('overall_comment', '')}")

                tags = result.get("tags", [])
                if tags:
                    st.caption("🏷️ " + "　".join(f"`{t}`" for t in tags))

                if st.button("💬 この写真についてチャットで詳しく聞く", key=f"to_chat_{rank}"):
                    st.session_state["chat_photo"] = result
                    st.switch_page("pages/chat.py")

            st.divider()
