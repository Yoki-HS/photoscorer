import streamlit as st

st.set_page_config(page_title="写真採点ツール", page_icon="📸", layout="wide")

# ─── APIキーをSecretsから自動取得 ────────────────────────────
if "api_key" not in st.session_state:
    try:
        st.session_state["api_key"] = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        st.session_state["api_key"] = ""

# ─── ログインチェック ────────────────────────────────────────
if "username" not in st.session_state:
    login = st.Page("pages/login.py", title="ログイン", icon="🔑")
    st.navigation([login]).run()
    st.stop()

# ─── サイドバー ──────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")

    # Secretsにキーがなければ手動入力欄を表示
    if not st.session_state.get("api_key"):
        def _save_api_key():
            val = st.session_state.get("_api_key_widget", "")
            if val:
                st.session_state["api_key"] = val

        st.text_input(
            "Gemini APIキー",
            type="password",
            placeholder="AIza...",
            key="_api_key_widget",
            on_change=_save_api_key,
        )
        if st.session_state["api_key"]:
            st.caption("✅ APIキー設定済み")
        else:
            st.caption("⚠️ APIキーを入力してEnterを押してください")

    st.divider()
    st.subheader("🏷️ タグ設定")
    use_custom = st.toggle("カスタムタグを使用する", value=False)
    if use_custom:
        custom_input = st.text_area(
            "タグリスト（1行に1つ またはカンマ区切り）",
            placeholder="例:\n夕焼け\n海\nライブ\nステージ\n笑顔\n山",
            height=150,
            key="custom_tags_input",
        )
        raw = custom_input.replace("、", ",").replace("\n", ",")
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        st.session_state["custom_tags"] = tags
        if tags:
            st.caption(f"設定済み: {len(tags)}個")
    else:
        st.session_state["custom_tags"] = []
        st.caption("AIが自由にタグを生成します")

    st.divider()
    st.caption(f"👤 {st.session_state['username']}")
    if st.button("ログアウト", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ─── ページ定義 ──────────────────────────────────────────────
scoring = st.Page("pages/scoring.py", title="採点",    icon="📸", default=True)
history = st.Page("pages/history.py", title="履歴",    icon="📋")
search  = st.Page("pages/search.py",  title="検索",    icon="🔍")
chat    = st.Page("pages/chat.py",    title="チャット", icon="💬")

pg = st.navigation([scoring, history, search, chat])
pg.run()
