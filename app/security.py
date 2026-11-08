"""认证与安全：scrypt 口令哈希、服务端会话、CSRF 头校验、登录失败锁定、审计日志。"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request

from . import config, db
from .db import get_db

# ---- 口令哈希（stdlib scrypt）----

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def gen_password(length: int = 8) -> str:
    """生成可读初始密码（去掉易混淆字符）。"""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---- 会话 ----

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(request: Request, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=config.SESSION_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))  # 单点登录：新登录踢旧会话
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,ip,ua) VALUES(?,?,?,?,?)",
            (_hash_token(token), user_id, expires,
             request.client.host if request.client else "",
             request.headers.get("user-agent", "")[:200]),
        )
    return token


def destroy_session(request: Request):
    token = request.cookies.get(config.SESSION_COOKIE)
    if token:
        with get_db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))


def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def get_current_user(request: Request):
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        return None
    th = _hash_token(token)
    with get_db() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at > ?",
            (th, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()
    return dict(row) if row else None


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "登录已失效，请重新登录")
    return user


def require_role(*roles: str):
    def dep(request: Request) -> dict:
        user = require_user(request)
        if user["role"] not in roles:
            raise HTTPException(403, "没有权限执行此操作")
        return user
    return dep


# ---- CSRF：写请求必须带自定义头（跨站无法伪造自定义头） ----

async def csrf_check(request: Request):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.headers.get("x-requested-with") != "XMLHttpRequest":
            raise HTTPException(403, "缺少 CSRF 校验头")


# ---- 登录失败锁定 ----

def login_locked(conn, key: str) -> int:
    """返回剩余锁定秒数；0 表示未锁定。"""
    row = conn.execute("SELECT fails, locked_until FROM login_fails WHERE key=?", (key,)).fetchone()
    if not row or not row["locked_until"]:
        return 0
    until = _parse_dt(row["locked_until"])
    remain = (until - datetime.now()).total_seconds()
    return max(0, int(remain))


def record_login_fail(conn, key: str):
    row = conn.execute("SELECT fails FROM login_fails WHERE key=?", (key,)).fetchone()
    fails = (row["fails"] if row else 0) + 1
    locked_until = None
    if fails >= config.LOGIN_MAX_FAILS:
        locked_until = (datetime.now() + timedelta(minutes=config.LOGIN_LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        fails = 0
    conn.execute(
        "INSERT INTO login_fails(key,fails,locked_until) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET fails=excluded.fails, locked_until=excluded.locked_until",
        (key, fails, locked_until),
    )


def clear_login_fails(conn, key: str):
    conn.execute("DELETE FROM login_fails WHERE key=?", (key,))


# ---- 审计 ----

def audit(request: Request, user: dict | None, action: str, detail: str = ""):
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO audit_logs(user_id,actor,action,detail,ip) VALUES(?,?,?,?,?)",
                (user["id"] if user else None,
                 user["username"] if user else "-",
                 action, detail[:500],
                 request.client.host if request.client else ""),
            )
    except Exception:
        pass
