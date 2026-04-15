from supabase import create_client, Client
import streamlit as st

_client: Client = None


def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"],
        )
    return _client


def has_supabase() -> bool:
    try:
        return "SUPABASE_URL" in st.secrets
    except Exception:
        return False
