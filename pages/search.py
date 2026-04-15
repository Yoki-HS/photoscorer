import streamlit as st
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import (load_all_sessions, generate_tags, update_session_file,
                   search_photos, score_badge)
from google import genai

st.title("🔍 写真検索")
st.caption("キーワードで過去に採点した写真を検索します")

api_key = st.session_state.get("api_key", "")
if not api_key:
    st.warning("左サイドバーにAPIキーを入力してください")
    st.stop()

# ─── 全写真をロード ─────────────────────────────────────────
sessions = load_all_sessions(username=st.session_state.get("username"))
all_results = []
for session in sessions:
    for result in session.get("results", []):
        all_results.append(result)

if not all_results:
    st.info("まず「採点」ページで写真を採点してください。")
    st.stop()

untagged = [r for r in all_results if not r.get("tags")]
tagged_count = len(all_results) - len(untagged)

col_stat1, col_stat2 = st.columns(2)
col_stat1.metric("検索対象", f"{len(all_results)} 枚")
col_stat2.metric("タグ生成済み", f"{tagged_count} 枚")


def run_tag_generation(target: list):
    """タグ生成を実行してセッションファイルに保存する共通関数"""
    client = genai.Client(api_key=api_key)
    custom_tags = st.session_state.get("custom_tags") or None
    completed = 0
    progress = st.progress(0, text="タグを生成中...")
    status = st.empty()
    failed = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_result = {
            executor.submit(generate_tags, client,
                            base64.b64decode(r["thumbnail_b64"]) if r.get("thumbnail_b64") else b"",
                            custom_tags): r
            for r in target
        }
        for future in as_completed(future_to_result):
            r = future_to_result[future]
            completed += 1
            status.text(f"{completed}/{len(target)}　{r['filename']}")
            progress.progress(completed / len(target), text=f"タグ生成中... {completed}/{len(target)}")
            try:
                tags = future.result()
                r["tags"] = tags
                if not tags:
                    failed.append(r["filename"])
            except Exception as e:
                r["tags"] = []
                failed.append(r["filename"])

    # セッションJSONに保存（余分なキーを除いて保存）
    save_errors = []
    for session in sessions:
        try:
            update_session_file(session)
        except Exception as e:
            save_errors.append(str(e))

    progress.progress(1.0, text="✅ 完了！")
    status.empty()

    if save_errors:
        st.error(f"保存エラー: {save_errors}")
    elif failed:
        st.warning(f"タグ生成に失敗した写真が{len(failed)}枚あります: {', '.join(failed[:5])}")
    else:
        st.success(f"✅ {len(target)}枚のタグを保存しました。")

    st.rerun()


# ─── タグ生成エリア ─────────────────────────────────────────
st.divider()
st.subheader("🏷️ タグ管理")

col_btn1, col_btn2 = st.columns(2)

with col_btn1:
    label1 = f"タグを生成する（未生成: {len(untagged)}枚）"
    disabled1 = len(untagged) == 0
    if st.button(label1, type="primary", disabled=disabled1,
                 help="タグがまだない写真にのみタグを付けます"):
        run_tag_generation(untagged)

with col_btn2:
    label2 = f"全写真を再タグ付けする（{len(all_results)}枚）"
    if st.button(label2, type="secondary",
                 help="カスタムタグを変更したときや、タグを一括で更新したいときに使用"):
        run_tag_generation(all_results)

if untagged:
    st.caption(f"⚠️ {len(untagged)}枚にタグが未生成です。検索精度のため生成を推奨します。")
else:
    st.caption("✅ 全写真にタグが生成されています")

custom_tags = st.session_state.get("custom_tags") or []
if custom_tags:
    st.caption(f"現在のカスタムタグ: " + "　".join(f"`{t}`" for t in custom_tags))

# ─── 検索UI ────────────────────────────────────────────────
st.divider()

tagged_photos = [r for r in all_results if r.get("tags")]
if not tagged_photos:
    st.info("タグが生成されていません。上のボタンでタグを生成してください。")
    st.stop()

query = st.text_input(
    "🔍 検索キーワード",
    placeholder="例：夕焼けの風景　/　ステージのライト　/　笑顔　/　青空と山",
)
search_btn = st.button("検索する", type="primary", disabled=not query)

if search_btn and query:
    with st.spinner(f"「{query}」で検索中..."):
        try:
            client = genai.Client(api_key=api_key)
            results = search_photos(client, query, tagged_photos)
            st.session_state["search_results"] = results
            st.session_state["search_query"] = query
            st.session_state["search_photo_map"] = {r["filename"]: r for r in all_results}
        except Exception as e:
            st.error(f"検索エラー: {e}")

# ─── 検索結果 ───────────────────────────────────────────────
if "search_results" in st.session_state:
    results = st.session_state["search_results"]
    photo_map = st.session_state.get("search_photo_map", {r["filename"]: r for r in all_results})
    last_query = st.session_state.get("search_query", "")

    st.divider()
    st.subheader(f"「{last_query}」の検索結果 — 上位 {len(results)} 枚")

    if not results:
        st.info("条件に合致する写真が見つかりませんでした。キーワードを変えてみてください。")
        st.stop()

    for rank, r in enumerate(results, 1):
        photo = photo_map.get(r["filename"])
        if not photo:
            continue

        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
        relevance = r.get("score", 0)

        with st.container():
            col_img, col_info = st.columns([1, 2])

            with col_img:
                thumb = photo.get("thumbnail_b64")
                if thumb:
                    st.image(base64.b64decode(thumb))
                else:
                    st.caption("(画像なし)")

            with col_info:
                st.markdown(f"### {medal} {r['filename']}")

                bar_color = "🟢" if relevance >= 70 else "🟡" if relevance >= 40 else "🔴"
                st.markdown(f"{bar_color} **合致度: {relevance}%**")
                st.progress(relevance / 100)
                st.caption(f"🔎 {r.get('reason', '')}")

                st.divider()

                total = photo.get("total_score", 0)
                st.markdown(f"採点: {score_badge(total)} **{total}/100**")
                col_t, col_c = st.columns(2)
                with col_t:
                    st.caption(f"🔍 技術 {photo.get('technical_score', 0)}/50")
                with col_c:
                    st.caption(f"🎨 構図 {photo.get('composition_score', 0)}/50")
                st.caption(f"💬 {photo.get('overall_comment', '')}")

                tags = photo.get("tags", [])
                if tags:
                    st.caption("🏷️ " + "　".join(f"`{t}`" for t in tags))

                if st.button("💬 チャットで詳しく聞く", key=f"srch_chat_{rank}"):
                    st.session_state["chat_photo"] = photo
                    st.switch_page("pages/chat.py")

            st.divider()
