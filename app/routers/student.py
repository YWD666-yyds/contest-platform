"""学生端路由：工作台概览 / 成绩查询。

注：本届平台仅开放小学高段组（线上答题 + 智能体实操），低段组作品提交流程已随单组别化移除。
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, security
from ..db import get_db, get_setting
from ..security import require_role

router = APIRouter(prefix="/api/student", tags=["student"])

student_dep = Depends(require_role("student"))


def _get_student(conn, user: dict):
    st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
    if not st:
        raise HTTPException(404, "学生档案不存在")
    return st


@router.get("/overview")
def overview(request: Request, _=student_dep):
    user = security.require_user(request)
    with get_db() as conn:
        st = _get_student(conn, user)
        subs = get_setting(conn, "submission")
        exams = get_setting(conn, "exams")
        publish = get_setting(conn, "publish")
        attempt = conn.execute(
            "SELECT id,status,started_at,deadline,submitted_at,score,duration_seconds,suspicious_events "
            "FROM attempts WHERE student_id=?", (st["id"],)
        ).fetchone()
        my_score = None
        rank = None
        if publish.get(st["group_code"]):
            rows = [r for r in grading_rank(conn, st["group_code"]) if r["student_id"] == st["id"]]
            if rows:
                my_score = rows[0]
                rank = rows[0]["rank"]
        return {
            "student": {
                "id": st["id"], "entry_no": st["entry_no"], "name": st["name"],
                "school": st["school"], "grade": st["grade"], "group_code": st["group_code"],
                "teacher_name": st["teacher_name"],
                "status": st["status"], "submitted_at": st["submitted_at"],
                "disqualified": bool(st["disqualified"]),
            },
            "submission": subs,
            "exam": exams.get(st["group_code"]),
            "attempt": dict(attempt) if attempt else None,
            "publish": {"published": bool(publish.get(st["group_code"])), "score": my_score, "rank": rank},
            "group_name": config.GROUP_NAMES.get(st["group_code"], st["group_code"]),
        }


def grading_rank(conn, group):
    from ..services import grading
    return grading.quiz_ranking(conn, group)
