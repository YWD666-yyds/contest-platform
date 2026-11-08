"""学生端路由：工作台概览 / 作品提交（低段组）/ 成绩查询。"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .. import config, security
from ..db import get_db, get_setting
from ..security import csrf_check, require_role
from ..services import image_check
from ..utils import now_str, parse_dt

router = APIRouter(prefix="/api/student", tags=["student"])

student_dep = Depends(require_role("student"))


def _get_student(conn, user: dict):
    st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
    if not st:
        raise HTTPException(404, "学生档案不存在")
    return st


def _check_window(conn):
    subs = get_setting(conn, "submission")
    if not subs.get("open"):
        raise HTTPException(403, "作品提交通道已关闭")
    deadline = parse_dt(subs.get("deadline"))
    if deadline and now_str() > deadline.strftime("%Y-%m-%d %H:%M:%S"):
        raise HTTPException(403, "作品提交已截止")
    return subs


class WorkBody(BaseModel):
    work_title: str = ""
    ai_platform: str = ""
    description: str = ""


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
        desc_len = len(st["description"].strip())
        my_score = None
        rank = None
        if publish.get(st["group_code"]):
            if st["group_code"] == "low":
                rows = [r for r in _rank_low(conn) if r["student_id"] == st["id"]]
            else:
                rows = [r for r in grading_rank(conn, st["group_code"]) if r["student_id"] == st["id"]]
            if rows:
                my_score = rows[0]
                rank = rows[0]["rank"]
        return {
            "student": {
                "id": st["id"], "entry_no": st["entry_no"], "name": st["name"],
                "school": st["school"], "grade": st["grade"], "group_code": st["group_code"],
                "teacher_name": st["teacher_name"], "work_title": st["work_title"],
                "ai_platform": st["ai_platform"], "description": st["description"],
                "design_image": st["design_image"], "process_images": json.loads(st["process_images"] or "[]"),
                "status": st["status"], "submitted_at": st["submitted_at"],
                "edit_locked": bool(st["edit_locked"]),
                "disqualified": bool(st["disqualified"]),
                "description_chars": desc_len,
            },
            "submission": subs,
            "exam": exams.get(st["group_code"]),
            "attempt": dict(attempt) if attempt else None,
            "publish": {"published": bool(publish.get(st["group_code"])), "score": my_score, "rank": rank},
            "group_name": config.GROUP_NAMES[st["group_code"]],
            "score_dimensions": config.SCORE_DIMENSIONS,
        }


def _rank_low(conn):
    from ..services import grading
    return grading.low_group_ranking(conn)


def grading_rank(conn, group):
    from ..services import grading
    return grading.quiz_ranking(conn, group)


@router.put("/work", dependencies=[Depends(csrf_check)])
def save_work(body: WorkBody, request: Request):
    user = security.require_user(request)
    if len(body.work_title) > 60 or len(body.ai_platform) > 60:
        raise HTTPException(400, "作品名称 / AI平台名称过长")
    if len(body.description) > 3000:
        raise HTTPException(400, "作品说明过长（≤3000字）")
    with get_db() as conn:
        st = _get_student(conn, user)
        if st["group_code"] != "low":
            raise HTTPException(403, "仅小学低段组需要提交作品材料")
        if st["edit_locked"]:
            raise HTTPException(403, "资料已锁定，如需修改请联系组委会")
        if st["status"] == "submitted":
            raise HTTPException(403, "作品已提交，请先撤回再修改")
        _check_window(conn)
        conn.execute(
            "UPDATE students SET work_title=?, ai_platform=?, description=?, updated_at=? WHERE id=?",
            (body.work_title.strip(), body.ai_platform.strip(), body.description.strip(), now_str(), st["id"]),
        )
    return {"ok": True, "description_chars": len(body.description.strip())}


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > config.DESIGN_MAX_BYTES + 1024 * 1024:
        raise HTTPException(400, "文件过大")
    return data


@router.post("/design-image", dependencies=[Depends(csrf_check)])
async def upload_design(request: Request, file: UploadFile):
    user = security.require_user(request)
    data = await _read_upload(file)
    with get_db() as conn:
        st = _get_student(conn, user)
        if st["group_code"] != "low":
            raise HTTPException(403, "仅小学低段组需要提交作品材料")
        if st["edit_locked"] or st["status"] == "submitted":
            raise HTTPException(403, "作品已提交或锁定，请先撤回再修改")
        _check_window(conn)
        saved = image_check.save_image(data, "design", st["id"])
        old = st["design_image"]
        conn.execute(
            "UPDATE students SET design_image=?, updated_at=? WHERE id=?",
            (saved["path"], now_str(), st["id"]),
        )
    if old:
        image_check.delete_saved(old)
    return {"ok": True, "path": saved["path"], "w": saved["w"], "h": saved["h"]}


@router.delete("/design-image", dependencies=[Depends(csrf_check)])
def delete_design(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = _get_student(conn, user)
        if st["edit_locked"] or st["status"] == "submitted":
            raise HTTPException(403, "作品已提交或锁定，无法删除")
        _check_window(conn)
        old = st["design_image"]
        conn.execute("UPDATE students SET design_image='' WHERE id=?", (st["id"],))
    if old:
        image_check.delete_saved(old)
    return {"ok": True}


@router.post("/process-image", dependencies=[Depends(csrf_check)])
async def upload_process(request: Request, file: UploadFile):
    user = security.require_user(request)
    data = await _read_upload(file)
    with get_db() as conn:
        st = _get_student(conn, user)
        if st["group_code"] != "low":
            raise HTTPException(403, "仅小学低段组需要提交作品材料")
        if st["edit_locked"] or st["status"] == "submitted":
            raise HTTPException(403, "作品已提交或锁定，请先撤回再修改")
        _check_window(conn)
        images = json.loads(st["process_images"] or "[]")
        if len(images) >= config.PROCESS_MAX_COUNT:
            raise HTTPException(400, f"创作过程记录最多 {config.PROCESS_MAX_COUNT} 张")
        saved = image_check.save_image(data, "process", st["id"])
        images.append(saved["path"])
        conn.execute(
            "UPDATE students SET process_images=?, updated_at=? WHERE id=?",
            (json.dumps(images), now_str(), st["id"]),
        )
    return {"ok": True, "path": saved["path"], "count": len(images)}


@router.delete("/process-image/{index}", dependencies=[Depends(csrf_check)])
def delete_process(index: int, request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = _get_student(conn, user)
        if st["edit_locked"] or st["status"] == "submitted":
            raise HTTPException(403, "作品已提交或锁定，无法删除")
        _check_window(conn)
        images = json.loads(st["process_images"] or "[]")
        if index < 0 or index >= len(images):
            raise HTTPException(404, "图片不存在")
        removed = images.pop(index)
        conn.execute(
            "UPDATE students SET process_images=?, updated_at=? WHERE id=?",
            (json.dumps(images), now_str(), st["id"]),
        )
    image_check.delete_saved(removed)
    return {"ok": True, "count": len(images)}


@router.post("/submit", dependencies=[Depends(csrf_check)])
def submit_work(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = _get_student(conn, user)
        if st["group_code"] != "low":
            raise HTTPException(403, "仅小学低段组需要提交作品材料")
        if st["edit_locked"]:
            raise HTTPException(403, "资料已锁定")
        if st["status"] == "submitted":
            raise HTTPException(400, "作品已提交")
        _check_window(conn)
        problems = []
        if not st["work_title"].strip():
            problems.append("缺少作品名称")
        desc = st["description"].strip()
        if len(desc) < config.DESCRIPTION_MIN_CHARS:
            problems.append(f"作品说明不少于 {config.DESCRIPTION_MIN_CHARS} 字（当前 {len(desc)} 字）")
        if not st["ai_platform"].strip():
            problems.append("缺少所使用的人工智能创作平台名称")
        if not st["design_image"]:
            problems.append("缺少创意设计图")
        images = json.loads(st["process_images"] or "[]")
        if not (config.PROCESS_MIN_COUNT <= len(images) <= config.PROCESS_MAX_COUNT):
            problems.append(f"创作过程记录需 {config.PROCESS_MIN_COUNT}—{config.PROCESS_MAX_COUNT} 张（当前 {len(images)} 张）")
        if problems:
            raise HTTPException(400, "；".join(problems))
        conn.execute(
            "UPDATE students SET status='submitted', submitted_at=?, updated_at=? WHERE id=?",
            (now_str(), now_str(), st["id"]),
        )
    security.audit(request, user, "submit_work", st["entry_no"])
    return {"ok": True}


@router.post("/retract", dependencies=[Depends(csrf_check)])
def retract_work(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = _get_student(conn, user)
        if st["status"] != "submitted":
            raise HTTPException(400, "作品未在提交状态")
        subs = get_setting(conn, "submission")
        if not subs.get("allow_retract"):
            raise HTTPException(403, "本届比赛不允许撤回已提交作品")
        if st["edit_locked"]:
            raise HTTPException(403, "资料已锁定，如需修改请联系组委会")
        _check_window(conn)
        conn.execute(
            "UPDATE students SET status='draft', submitted_at=NULL, updated_at=? WHERE id=?",
            (now_str(), st["id"]),
        )
    security.audit(request, user, "retract_work", st["entry_no"])
    return {"ok": True}
