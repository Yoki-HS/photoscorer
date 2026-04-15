import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from auth import register, authenticate

st.title("📸 写真採点ツール")
st.caption("ログインまたは新規登録してください")

st.info(
    "⚠️ このアプリはGemini APIの従量課金制を利用しています。\n\n"
    "APIコストを皆で分担するため、**1人あたり150枚程度を目安**にご利用ください。"
)

st.divider()

# ─── タブ ─────────────────────────────────────────────────
tab_login, tab_register = st.tabs(["ログイン", "新規登録"])

# ── ログインタブ ───────────────────────────────────────────
with tab_login:
    st.subheader("ログイン")
    with st.form("login_form"):
        username = st.text_input("ユーザー名", placeholder="例: alice")
        password = st.text_input(
            "パスワード",
            type="password",
            placeholder="パスワードなしの場合は空欄のままログイン"
        )
        submitted = st.form_submit_button("ログイン", type="primary", use_container_width=True)

    if submitted:
        if not username.strip():
            st.error("ユーザー名を入力してください")
        else:
            ok, msg = authenticate(username.strip(), password)
            if ok:
                st.session_state["username"] = username.strip()
                st.rerun()
            else:
                st.error(msg)

# ── 新規登録タブ ───────────────────────────────────────────
with tab_register:
    st.subheader("新規登録")
    st.caption("パスワードは任意です。設定しない場合は空欄のままで登録できます。")

    with st.form("register_form"):
        new_username = st.text_input("ユーザー名", placeholder="例: alice（英数字・日本語・_・-）")
        new_password = st.text_input(
            "パスワード（任意）",
            type="password",
            placeholder="設定しない場合は空欄でOK"
        )
        new_password2 = st.text_input(
            "パスワード（確認）",
            type="password",
            placeholder="同じパスワードを再入力"
        )
        submitted2 = st.form_submit_button("登録する", type="primary", use_container_width=True)

    if submitted2:
        if new_password != new_password2:
            st.error("パスワードが一致しません")
        else:
            ok, msg = register(new_username.strip(), new_password)
            if ok:
                st.success(f"✅ {msg}　→ ログインしてください")
                st.session_state["username"] = new_username.strip()
                st.session_state["api_key"] = ""
                st.rerun()
            else:
                st.error(msg)
