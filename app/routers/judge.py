"""评审端路由（小学低段组作品评审）。"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import config
from ..db import get_db
from ..security import csrf_check, require_role
from ..utils import now_str

router = APIRouter(prefix="/api/judge", tags=["judge"])

judge_dep = require_role("judge", "admin")

DIMS = config.SCORE_DIMENSIONS  # s_theme 等


class ScoreBody(BaseModel):
    student_id: int
    s_theme: float
    s_creative: float
    s_expression: float
    s_process: float
    comment: str = ""


@router.get("/queue")
def queue(request: Request, filter: str = "all"):
    """评审队列：低段组已提交作品（缩略图）。filter: all | pending | done"""
    user = require_role("judge", "admin")(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT s.id, s.entry_no, s.work_title, s.school, s.design_image, s.status, "
            "s.submitted_at, s.description, sc.id AS my_score_id "
            "FROM students s "
            "LEFT JOIN scores sc ON sc.student_id = s.id AND sc.judge_id = ? "
            "WHERE s.group_code='low' AND s.status='submitted' "
            "ORDER BY s.submitted_at ASC",
            (user["id"],),
        ).fetchall()
        items = []
        for r in rows:
            done = r["my_score_id"] is not None
            if filter == "pending" and done:
                continue
            if filter == "done" and not done:
                continue
            desc = r["description"] or ""
            items.append({
                "id": r["id"], "entry_no": r["entry_no"], "work_title": r["work_title"],
                "school": r["school"], "thumb": _thumb_path(r["design_image"]),
                "submitted_at": r["submitted_at"], "scored": done,
                "desc_preview": desc[:80] + ("…" if len(desc) > 80 else ""),
            })
        progress = {
            "total": len(rows),
            "done": sum(1 for r in rows if r["my_score_id"] is not None),
        }
    return {"items": items, "progress": progress, "dimensions": DIMS}


def _thumb_path(design_path: str) -> str:
    """缩略图路径（同文件名，位于 /uploads/thumbs/）。"""
    if not design_path:
        return ""
    return design_path.rsplit("/", 1)[-1]


@router.get("/submission/{student_id}")
def submission_detail(student_id: int, request: Request):
    require_role("judge", "admin")(request)
    with get_db() as conn:
        st = conn.execute(
            "SELECT * FROM students WHERE id=? AND group_code='low'", (student_id,)
        ).fetchone()
        if not st:
            raise HTTPException(404, "作品不存在")
        scores = conn.execute(
            "SELECT sc.*, u.username AS judge_no FROM scores sc JOIN users u ON u.id=sc.judge_id "
            "WHERE sc.student_id=?",
            (st["id"],),
        ).fetchall()
        return {
            "student": {
                "id": st["id"], "entry_no": st["entry_no"], "work_title": st["work_title"],
                "ai_platform": st["ai_platform"], "description": st["description"],
                "design_image": "/uploads/" + st["design_image"] if st["design_image"] else "",
                "process_images": ["/uploads/" + p for p in json.loads(st["process_images"] or "[]")],
                "submitted_at": st["submitted_at"],
            },
            # 评审界面隐藏选手姓名与学校，避免先入为主（评分表以材料为依据）
            "my_score": _my_score(scores, user_id_from(request)),
            "all_scores_count": len(scores),
            "dimensions": DIMS,
        }


def user_id_from(request: Request) -> int:
    from ..security import get_current_user
    return get_current_user(request)["id"]


def _my_score(scores, user_id: int):
    for s in scores:
        if s["judge_id"] == user_id:
            return dict(s)
    return None


@router.post("/score", dependencies=[Depends(csrf_check)])
def save_score(body: ScoreBody, request: Request):
    user = require_role("judge", "admin")(request)
    values = {"s_theme": body.s_theme, "s_creative": body.s_creative,
              "s_expression": body.s_expression, "s_process": body.s_process}
    total = 0.0
    for key, (label, max_v) in DIMS.items():
        v = values[key]
        if v is None or v < 0 or v > max_v:
            raise HTTPException(400, f"「{label}」得分需在 0—{max_v} 之间")
        total += v
    total = round(total + 1e-9, 2)
    with get_db() as conn:
        st = conn.execute(
            "SELECT * FROM students WHERE id=? AND group_code='low' AND status='submitted'",
            (body.student_id,),
        ).fetchone()
        if not st:
            raise HTTPException(404, "作品不存在或未提交")
        conn.execute(
            "INSERT INTO scores(student_id,judge_id,s_theme,s_creative,s_expression,s_process,total,comment,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(student_id,judge_id) DO UPDATE SET "
            "s_theme=excluded.s_theme, s_creative=excluded.s_creative, "
            "s_expression=excluded.s_expression, s_process=excluded.s_process, "
            "total=excluded.total, comment=excluded.comment, updated_at=excluded.updated_at",
            (body.student_id, user["id"], body.s_theme, body.s_creative,
             body.s_expression, body.s_process, total, body.comment.strip(), now_str()),
        )
    return {"ok": True, "total": total}


@router.get("/progress")
def progress(request: Request):
    require_role("judge", "admin")(request)
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM students WHERE group_code='low' AND status='submitted'"
        ).fetchone()["n"]
        by_judge = conn.execute(
            "SELECT u.id, u.username AS judge_no, COUNT(sc.id) AS scored "
            "FROM users u LEFT JOIN scores sc ON sc.judge_id=u.id "
            "WHERE u.role IN ('judge','admin') GROUP BY u.id ORDER BY u.id"
        ).fetchall()
    return {"total": total, "by_judge": [dict(r) for r in by_judge]}
