import hashlib
import secrets
import re
from datetime import datetime
from db import get_db


def hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return dk.hex()


def is_valid_username(username: str) -> bool:
    return bool(re.match(r'^[\w\-]+$', username, re.UNICODE)) and 1 <= len(username) <= 30


def register(username: str, password: str = "") -> tuple:
    username = username.strip()
    if not username:
        return False, "ユーザー名を入力してください"
    if not is_valid_username(username):
        return False, "使えない文字が含まれています（英数字・日本語・_・- のみ）"

    db = get_db()
    existing = db.table("users").select("username").eq("username", username).execute()
    if existing.data:
        return False, "そのユーザー名はすでに使われています"

    salt = secrets.token_hex(16)
    db.table("users").insert({
        "username": username,
        "password_hash": hash_password(password, salt),
        "salt": salt,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }).execute()
    return True, "登録しました"


def authenticate(username: str, password: str = "") -> tuple:
    username = username.strip()
    db = get_db()
    result = db.table("users").select("*").eq("username", username).execute()
    if not result.data:
        return False, "ユーザー名が見つかりません"

    user = result.data[0]
    if hash_password(password, user["salt"]) == user["password_hash"]:
        return True, "ログインしました"
    return False, "パスワードが違います"
