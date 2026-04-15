import streamlit as st
import base64
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import score_badge, load_all_sessions

st.title("📋 採点履歴")

sessions = load_all_sessions(username=st.session_state.get("username"))

if not sessions:
    st.info("まだ採点履歴がありません。「採点」ページで写真を採点してください。")
    st.stop()

st.caption(f"過去 {len(sessions)} 回の採点結果")

for i, session in enumerate(sessions):
    folder_name = Path(session.get("folder", "不明")).name
    label = f"📅 {session.get('timestamp', '?')}　|　📁 {folder_name}　|　📷 {session.get('count', 0)}枚"

    with st.expander(label, expanded=(i == 0)):
        results = session.get("results", [])
        if not results:
            st.warning("データがありません")
            continue

        scores = [r["total_score"] for r in results]
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("平均スコア", f"{sum(scores)/len(scores):.1f}")
        col_b.metric("最高スコア", f"{max(scores)}")
        col_c.metric("最低スコア", f"{min(scores)}")
        st.divider()

        for rank, result in enumerate(results, 1):
            medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
            total = result["total_score"]

            col_img, col_info = st.columns([1, 3])
            with col_img:
                thumb = result.get("thumbnail_b64")
                if thumb:
                    st.image(base64.b64decode(thumb))
                else:
                    st.caption("(画像なし)")

            with col_info:
                st.markdown(f"**{medal} {result['filename']}** — {score_badge(total)} **{total}/100**")
                st.caption(f"🔍 技術: {result['technical_score']}/50　🎨 構図: {result['composition_score']}/50")
                st.caption(f"💬 {result.get('overall_comment', '')}")
                if st.button("💬 チャットで詳しく聞く", key=f"hist_chat_{i}_{rank}"):
                    st.session_state["chat_photo"] = result
                    st.switch_page("pages/chat.py")
