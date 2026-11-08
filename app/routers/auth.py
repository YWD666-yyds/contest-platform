"""认证路由：登录 / 登出 / 当前用户 / 修改密码。"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import config, db, security
from ..db import get_db
from ..security import csrf_check
from ..utils import now_str

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePwdBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/login", dependencies=[Depends(csrf_check)])
def login(body: LoginBody, request: Request, response: Response):
    username = body.username.strip()
    client_ip = request.client.host if request.client else ""
    key = f"{client_ip}|{username.lower()}"
    with get_db() as conn:
        remain = security.login_locked(conn, key)
        if remain > 0:
            raise HTTPException(429, f"失败次数过多，账号已临时锁定，请 {remain // 60 + 1} 分钟后再试")
        user = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        if not user or not security.verify_password(body.password, user["password_hash"]):
            security.record_login_fail(conn, key)
            security.audit(request, None, "login_fail", username)
            raise HTTPException(401, "用户名或密码错误")
        security.clear_login_fails(conn, key)
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_str(), user["id"]))
        student = conn.execute(
            "SELECT id, entry_no, name, group_code, status FROM students WHERE user_id=?", (user["id"],)
        ).fetchone()

    token = security.create_session(request, user["id"])
    response.set_cookie(
        config.SESSION_COOKIE, token,
        max_age=config.SESSION_TTL_HOURS * 3600,
        httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/",
    )
    security.audit(request, dict(user), "login")
    return {
        "role": user["role"],
        "username": user["username"],
        "must_change_pwd": bool(user["must_change_pwd"]),
        "student": dict(student) if student else None,
    }


@router.post("/logout", dependencies=[Depends(csrf_check)])
def logout(request: Request, response: Response):
    user = security.get_current_user(request)
    security.destroy_session(request)
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    if user:
        security.audit(request, user, "logout")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = security.get_current_user(request)
    if not user:
        return {"user": None}
    data = {
        "user": {"id": user["id"], "username": user["username"], "role": user["role"],
                 "must_change_pwd": bool(user["must_change_pwd"])},
    }
    if user["role"] == "student":
        with get_db() as conn:
            st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if st:
            data["student"] = dict(st)
            import json
            data["student"]["process_images"] = json.loads(st["process_images"] or "[]")
    return data


@router.post("/change-password", dependencies=[Depends(csrf_check)])
def change_password(body: ChangePwdBody, request: Request):
    user = security.require_user(request)
    if len(body.new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    with get_db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not security.verify_password(body.old_password, row["password_hash"]):
            raise HTTPException(400, "原密码不正确")
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_pwd=0 WHERE id=?",
            (security.hash_password(body.new_password), user["id"]),
        )
    security.audit(request, user, "change_password")
    return {"ok": True}
