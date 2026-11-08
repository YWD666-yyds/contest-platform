"""FastAPI 应用入口。本地开发：python -m uvicorn app.main:app --reload --port 8000"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .db import init_db
from .routers import admin, agent, auth, exam, public, student

app = FastAPI(title="人工智能应用赛项 · 市级初赛平台", docs_url=None, redoc_url=None)

init_db()

app.include_router(auth.router)
app.include_router(public.router)
app.include_router(student.router)
app.include_router(agent.router)
app.include_router(exam.router)
app.include_router(admin.router)

STATIC_DIR = config.BASE_DIR / "static"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "service": "contest-platform"}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """前端 SPA 入口：未知路径返回 index.html。"""
    target = STATIC_DIR / full_path
    if full_path and target.is_file() and str(target.resolve()).startswith(str(STATIC_DIR.resolve())):
        return FileResponse(target)
    return FileResponse(STATIC_DIR / "index.html")
