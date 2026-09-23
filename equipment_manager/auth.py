"""Student credentials, revocable sessions and bounded login throttling."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from functools import wraps

from flask import current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, immediate_transaction, utc_now
from .security import constant_time_equal

PASSWORD_METHOD = "pbkdf2:sha256:1000000"
DUMMY_HASH = "pbkdf2:sha256:1000000$login-dummy-salt$" + "0" * 64


class AccountError(ValueError):
    pass


class RateLimited(AccountError):
    def __init__(self, retry_after=300):
        super().__init__(f"요청이 너무 많습니다. {retry_after}초 후 다시 시도해 주세요.")
        self.retry_after = retry_after


def take_attempt(scope: str, identity: str, limit=5, seconds=300) -> str:
    # Do not retain raw user IDs/IP addresses in throttle storage.
    bucket = hashlib.sha256(f"{scope}:{identity[:128]}".encode("utf-8", errors="replace")).hexdigest()
    now = int(time.time())
    db = get_db()
    with immediate_transaction(db):
        db.execute("DELETE FROM auth_attempts WHERE expires_at <= ?", (now,))
        row = db.execute("SELECT * FROM auth_attempts WHERE bucket = ?", (bucket,)).fetchone()
        if row and row["attempts"] >= limit:
            raise RateLimited(max(1, row["expires_at"] - now))
        if not row and db.execute("SELECT COUNT(*) FROM auth_attempts").fetchone()[0] >= 4096:
            raise RateLimited()
        db.execute("""INSERT INTO auth_attempts VALUES (?, 1, ?)
                      ON CONFLICT(bucket) DO UPDATE SET attempts = attempts + 1""", (bucket, now + seconds))
    return bucket


def clear_attempt(bucket: str) -> None:
    db = get_db()
    with db:
        db.execute("DELETE FROM auth_attempts WHERE bucket = ?", (bucket,))


def _delete_expired_sessions(db: sqlite3.Connection, now: int) -> int:
    return db.execute(
        "DELETE FROM auth_sessions WHERE expires_at <= ? OR last_seen <= ?",
        (now, now - current_app.config["AUTH_IDLE_SECONDS"]),
    ).rowcount


def cleanup_expired_auth() -> None:
    """Prune temporary credentials even when no one logs in again."""
    now = int(time.time())
    db = get_db()
    with db:
        _delete_expired_sessions(db, now)
        db.execute("DELETE FROM auth_attempts WHERE expires_at <= ?", (now,))


def credential_tag(role: str, subject: str, credential: str) -> str:
    payload = f"{role}\0{subject}\0{credential}".encode("utf-8", errors="replace")
    return hmac.new(str(current_app.secret_key).encode(), payload, hashlib.sha256).hexdigest()


def end_session() -> None:
    token = session.get("auth_token")
    if isinstance(token, str):
        db = get_db()
        with db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
    session.clear()
    g.user = None


def begin_session(role: str, subject: str, credential: str) -> None:
    end_session()
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db = get_db()
    with db:
        _delete_expired_sessions(db, now)
        db.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?, ?, ?)",
                   (hashlib.sha256(token.encode()).hexdigest(), role, subject,
                    credential_tag(role, subject, credential), now, now + current_app.config["AUTH_MAX_SECONDS"]))
    session["auth_token"] = token
    session["csrf_token"] = secrets.token_urlsafe(24)
    if role in {"teacher", "developer"}:
        session["admin_role"] = role
        session["admin_username"] = subject


def load_user() -> None:
    g.user = None
    token = session.get("auth_token")
    if not isinstance(token, str):
        session.pop("admin_role", None)
        session.pop("admin_username", None)
        return
    db = get_db()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = db.execute("SELECT * FROM auth_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
    now = int(time.time())
    if not row or row["expires_at"] <= now or row["last_seen"] + current_app.config["AUTH_IDLE_SECONDS"] <= now:
        end_session()
        return
    role, subject = row["role"], row["subject"]
    if role == "student":
        account = db.execute("SELECT * FROM student_accounts WHERE id = ? AND status = 'active'", (subject,)).fetchone()
        if not account:
            end_session()
            return
        credential = account["password_hash"]
        user = {"role": role, "id": account["id"], "name": account["name"], "student_id": account["student_id"]}
    else:
        if subject != current_app.config[f"{role.upper()}_USERNAME"]:
            end_session()
            return
        credential = current_app.config[f"{role.upper()}_PASSWORD"]
        user = {"role": role, "name": subject}
    if not constant_time_equal(row["credential_tag"], credential_tag(role, subject, credential)):
        end_session()
        return
    g.user = user
    # Background polling must not keep an unattended login alive forever.
    if request.endpoint not in {"static", "web.api_status", "web.healthz"} and now > row["last_seen"]:
        with db:
            db.execute("UPDATE auth_sessions SET last_seen = ? WHERE token_hash = ?", (now, token_hash))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            if request.path.startswith("/api/"):
                return jsonify(ok=False, code="login_required", error="로그인 후 이용해 주세요."), 401
            return redirect(url_for("web.student_login"))
        return view(*args, **kwargs)
    return wrapped


def transaction_student_id(data: dict) -> str:
    if g.user["role"] == "student":
        return g.user["student_id"]
    return str(data.get("student_id", ""))


def scan_owner() -> str:
    return f"{g.user['role']}:{g.user.get('id', g.user['name'])}"


def validate_new_password(password: str) -> None:
    if not 12 <= len(password) <= 128:
        raise AccountError("비밀번호는 12~128자로 입력해 주세요.")
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        raise AccountError("비밀번호에 사용할 수 없는 문자가 있습니다.") from None


def register_student(student_id: str, name: str, password: str) -> None:
    if not re.fullmatch(r"[0-9]{2,20}", student_id):
        raise AccountError("학번은 숫자 2~20자리로 입력해 주세요.")
    if not 2 <= len(name) <= 40 or not name.isprintable():
        raise AccountError("이름은 2~40자로 입력해 주세요.")
    validate_new_password(password)
    password_hash = generate_password_hash(password, method=PASSWORD_METHOD)
    db = get_db()
    try:
        with db:
            db.execute("INSERT INTO student_accounts(student_id, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                       (student_id, name, password_hash, utc_now()))
    except sqlite3.IntegrityError:
        raise AccountError("가입할 수 없는 학번입니다. 선생님께 문의해 주세요.") from None


def authenticate_student(student_id: str, password: str):
    account = get_db().execute("SELECT * FROM student_accounts WHERE student_id = ?", (student_id,)).fetchone()
    password_ok = check_password_hash(account["password_hash"] if account else DUMMY_HASH, password)
    if not account or not password_ok:
        raise AccountError("학번 또는 비밀번호가 올바르지 않습니다.")
    if account["status"] != "active":
        raise AccountError("승인 대기 또는 사용 중지된 계정입니다. 선생님께 문의해 주세요.")
    return account


def update_student_password(account_id: int, password: str) -> None:
    validate_new_password(password)
    password_hash = generate_password_hash(password, method=PASSWORD_METHOD)
    db = get_db()
    with db:
        if db.execute("UPDATE student_accounts SET password_hash = ? WHERE id = ?", (password_hash, account_id)).rowcount != 1:
            raise AccountError("학생 계정을 찾을 수 없습니다.")
        db.execute("DELETE FROM auth_sessions WHERE role = 'student' AND subject = ?", (str(account_id),))
