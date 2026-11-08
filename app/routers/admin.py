"""管理端路由。"""
import csv
import io
import json
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from .. import config
from ..db import get_db, get_setting, set_setting
from ..security import (csrf_check, gen_password, hash_password, require_role,
                        verify_password)
from ..services import importer as importer_svc
from ..services import llm as llm_svc
from ..services.grading import low_group_ranking, quiz_ranking
from ..utils import now_str

router = APIRouter(prefix="/api/admin", tags=["admin"])

admin_dep = require_role("admin")


# ---------- 概览 ----------

@router.get("/overview")
def overview(request: Request):
    admin_dep(request)
    with get_db() as conn:
        stats = {}
        for g in config.GROUP_NAMES:
            row = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS submitted "
                "FROM students WHERE group_code=?", (g,)
            ).fetchone()
            graded = conn.execute(
                "SELECT COUNT(DISTINCT sc.student_id) AS n FROM scores sc "
                "JOIN students s ON s.id=sc.student_id WHERE s.group_code='low'",
            ).fetchone()["n"] if g == "low" else None
            attempts = None
            if g != "low":
                attempts = conn.execute(
                    "SELECT COUNT(*) AS n FROM attempts WHERE group_code=? AND status='submitted'", (g,)
                ).fetchone()["n"]
            stats[g] = {"total": row["total"] or 0, "submitted": row["submitted"] or 0,
                        "graded": graded, "attempt_submitted": attempts}
        judges = conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='judge'").fetchone()["n"]
        ag_row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS submitted, "
            "SUM(CASE WHEN check_status='ok' THEN 1 ELSE 0 END) AS ok_cnt, "
            "SUM(CASE WHEN check_status='revise' THEN 1 ELSE 0 END) AS revise_cnt "
            "FROM student_agents"
        ).fetchone()
        agent_stats = {
            "started": ag_row["total"] or 0,
            "submitted": ag_row["submitted"] or 0,
            "ok": ag_row["ok_cnt"] or 0,
            "revise": ag_row["revise_cnt"] or 0,
        }
        settings = {k: get_setting(conn, k) for k in ("site", "submission", "exams", "publish", "quota", "agent_exam")}
    return {"stats": stats, "agent_stats": agent_stats, "judges": judges, "settings": settings,
            "groups": config.GROUP_NAMES}


# ---------- 学生管理 ----------

@router.get("/students")
def students(request: Request, group: str = "", q: str = "", status: str = "", page: int = 1, size: int = 20):
    admin_dep(request)
    where, args = ["1=1"], []
    if group in config.GROUP_NAMES:
        where.append("s.group_code=?")
        args.append(group)
    if status in ("draft", "submitted"):
        where.append("s.status=?")
        args.append(status)
    if q.strip():
        where.append("(s.name LIKE ? OR s.school LIKE ? OR s.entry_no LIKE ?)")
        args.extend([f"%{q.strip()}%"] * 3)
    w = " AND ".join(where)
    with get_db() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM students s WHERE {w}", args).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT s.*, a.score AS exam_score, a.status AS attempt_status,
                       a.duration_seconds, a.suspicious_events,
                       (SELECT COUNT(*) FROM scores sc WHERE sc.student_id=s.id) AS judge_count
                FROM students s LEFT JOIN attempts a ON a.student_id=s.id
                WHERE {w} ORDER BY s.group_code, s.entry_no LIMIT ? OFFSET ?""",
            args + [size, (page - 1) * size],
        ).fetchall()
    return {"total": total, "page": page, "size": size,
            "items": [_student_row(r) for r in rows]}


def _student_row(r) -> dict:
    return {
        "id": r["id"], "entry_no": r["entry_no"], "name": r["name"], "school": r["school"],
        "grade": r["grade"], "group_code": r["group_code"], "teacher_name": r["teacher_name"],
        "work_title": r["work_title"], "status": r["status"], "submitted_at": r["submitted_at"],
        "edit_locked": bool(r["edit_locked"]), "disqualified": bool(r["disqualified"]),
        "judge_count": r["judge_count"], "exam_score": r["exam_score"],
        "attempt_status": r["attempt_status"], "duration_seconds": r["duration_seconds"],
        "suspicious_events": r["suspicious_events"],
        "has_design": bool(r["design_image"]),
        "process_count": len(json.loads(r["process_images"] or "[]")),
    }


class StudentCreate(BaseModel):
    name: str
    school: str
    grade: str
    group: str = ""      # 仅三年级需要
    teacher_name: str = ""
    work_title: str = ""


@router.post("/students", dependencies=[Depends(csrf_check)])
def create_student(body: StudentCreate, request: Request):
    admin_dep(request)
    grade_no = importer_svc.parse_grade(body.grade)
    if grade_no is None:
        raise HTTPException(400, "无法识别年级")
    group = importer_svc._resolve_group(grade_no, body.group)
    if group is None:
        raise HTTPException(400, "本届仅开放小学高段组（4—6 年级；3 年级须在组别中注明「高段组」）")
    with get_db() as conn:
        dup = conn.execute("SELECT 1 FROM students WHERE name=? AND school=?", (body.name.strip(), body.school.strip())).fetchone()
        if dup:
            raise HTTPException(400, "该姓名+学校已存在")
        entry_no = importer_svc.next_entry_no(conn, group)
        init_pwd = gen_password(8)
        cur = conn.execute(
            "INSERT INTO users(username,password_hash,role,must_change_pwd) VALUES(?,?,?,1)",
            (entry_no, hash_password(init_pwd), "student"),
        )
        conn.execute(
            "INSERT INTO students(user_id,entry_no,name,school,grade,grade_no,group_code,teacher_name,work_title) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (cur.lastrowid, entry_no, body.name.strip(), body.school.strip(), body.grade.strip(),
             grade_no, group, body.teacher_name.strip(), body.work_title.strip()),
        )
    return {"ok": True, "entry_no": entry_no, "initial_password": init_pwd}


class StudentUpdate(BaseModel):
    name: str | None = None
    school: str | None = None
    grade: str | None = None
    teacher_name: str | None = None
    work_title: str | None = None
    edit_locked: bool | None = None
    disqualified: bool | None = None
    disqualify_reason: str | None = None


@router.put("/students/{student_id}", dependencies=[Depends(csrf_check)])
def update_student(student_id: int, body: StudentUpdate, request: Request):
    admin_dep(request)
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not st:
            raise HTTPException(404, "学生不存在")
        updates, args = [], []
        for field in ("name", "school", "grade", "teacher_name", "work_title", "disqualify_reason"):
            v = getattr(body, field)
            if v is not None:
                updates.append(f"{field}=?")
                args.append(v.strip())
        if body.edit_locked is not None:
            updates.append("edit_locked=?")
            args.append(1 if body.edit_locked else 0)
        if body.disqualified is not None:
            updates.append("disqualified=?")
            args.append(1 if body.disqualified else 0)
        if updates:
            updates.append("updated_at=?")
            args.append(now_str())
            args.append(student_id)
            conn.execute(f"UPDATE students SET {', '.join(updates)} WHERE id=?", args)
    return {"ok": True}


@router.delete("/students/{student_id}", dependencies=[Depends(csrf_check)])
def delete_student(student_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        st = conn.execute("SELECT user_id FROM students WHERE id=?", (student_id,)).fetchone()
        if not st:
            raise HTTPException(404, "学生不存在")
        conn.execute("DELETE FROM users WHERE id=?", (st["user_id"],))  # 级联删除 students/attempts
        conn.execute("DELETE FROM scores WHERE student_id=?", (student_id,))
    return {"ok": True}


@router.post("/students/{student_id}/reset-password", dependencies=[Depends(csrf_check)])
def reset_password(student_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        st = conn.execute("SELECT user_id FROM students WHERE id=?", (student_id,)).fetchone()
        if not st:
            raise HTTPException(404, "学生不存在")
        new_pwd = gen_password(8)
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_pwd=1 WHERE id=?",
            (hash_password(new_pwd), st["user_id"]),
        )
    return {"ok": True, "new_password": new_pwd}


@router.post("/students/import", dependencies=[Depends(csrf_check)])
async def import_students(request: Request, file: UploadFile):
    admin_dep(request)
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "文件过大（≤2MB）")
    result = importer_svc.import_students(data)
    if result["created"]:
        # 审计不含密码
        pass
    return result


@router.get("/students/export")
def export_students(request: Request, group: str = ""):
    admin_dep(request)
    where, args = "1=1", []
    if group in config.GROUP_NAMES:
        where, args = "s.group_code=?", [group]
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT s.*, a.score AS exam_score, a.duration_seconds
                FROM students s LEFT JOIN attempts a ON a.student_id=s.id WHERE {where}
                ORDER BY s.group_code, s.entry_no""",
            args,
        ).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["参赛编号", "姓名", "学校", "年级", "组别", "指导教师", "作品名称",
                     "提交状态", "提交时间", "答题得分", "答题用时(秒)"])
    for r in rows:
        writer.writerow([
            r["entry_no"], r["name"], r["school"], r["grade"], config.GROUP_NAMES[r["group_code"]],
            r["teacher_name"], r["work_title"], "已提交" if r["status"] == "submitted" else "未提交",
            r["submitted_at"] or "", r["exam_score"] if r["exam_score"] is not None else "",
            r["duration_seconds"] if r["duration_seconds"] is not None else "",
        ])
    buf.seek(0)
    from urllib.parse import quote
    filename = quote(f"学生名单_{group or '全部'}.csv")
    return Response(
        content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/submission/{student_id}")
def submission_detail(student_id: int, request: Request):
    admin_dep(request)
    from .judge import submission_detail as jd
    return jd(student_id, request)


# ---------- 题库管理 ----------

@router.get("/questions")
def list_questions(request: Request, group: str = "high"):
    admin_dep(request)
    if group not in config.GROUP_NAMES:
        raise HTTPException(400, "参数错误")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM questions WHERE group_code=? ORDER BY id", (group,)
        ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"], "type": r["type"], "stem": r["stem"],
            "options": json.loads(r["options"]), "answer": json.loads(r["answer"]),
            "score": r["score"], "topic": r["topic"], "enabled": bool(r["enabled"]),
        })
    return {"items": items}


class QuestionBody(BaseModel):
    group_code: str
    type: str
    stem: str
    options: list = []
    answer: list
    score: float = 1
    topic: str = ""
    enabled: bool = True


def _validate_question(body: QuestionBody):
    if body.group_code not in ("high", "middle"):
        raise HTTPException(400, "组别错误")
    if body.type not in ("single", "multiple", "judge"):
        raise HTTPException(400, "题型错误")
    if not body.stem.strip():
        raise HTTPException(400, "题干不能为空")
    if not body.answer or not all(a in "ABCD" for a in body.answer):
        raise HTTPException(400, "答案格式错误")
    if body.type in ("single", "judge") and len(body.answer) != 1:
        raise HTTPException(400, "单选/判断题只能有一个答案")
    if body.type == "single" and len(body.options) < 2:
        raise HTTPException(400, "单选题至少两个选项")
    if body.type == "multiple" and len(body.answer) < 2:
        raise HTTPException(400, "多选题答案至少两项")
    keys = {o.get("key") for o in body.options}
    if body.type != "judge" and not set(body.answer).issubset(keys):
        raise HTTPException(400, "答案不在选项中")
    if body.score <= 0 or body.score > 100:
        raise HTTPException(400, "分值需在 0—100 之间")


@router.post("/questions", dependencies=[Depends(csrf_check)])
def create_question(body: QuestionBody, request: Request):
    admin_dep(request)
    _validate_question(body)
    if body.type == "judge":
        body.options = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO questions(group_code,type,stem,options,answer,score,topic,enabled) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (body.group_code, body.type, body.stem.strip(),
             json.dumps(body.options, ensure_ascii=False), json.dumps(body.answer),
             body.score, body.topic.strip(), 1 if body.enabled else 0),
        )
    return {"ok": True}


@router.put("/questions/{qid}", dependencies=[Depends(csrf_check)])
def update_question(qid: int, body: QuestionBody, request: Request):
    admin_dep(request)
    _validate_question(body)
    if body.type == "judge":
        body.options = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
    with get_db() as conn:
        conn.execute(
            "UPDATE questions SET group_code=?, type=?, stem=?, options=?, answer=?, "
            "score=?, topic=?, enabled=? WHERE id=?",
            (body.group_code, body.type, body.stem.strip(),
             json.dumps(body.options, ensure_ascii=False), json.dumps(body.answer),
             body.score, body.topic.strip(), 1 if body.enabled else 0, qid),
        )
    return {"ok": True}


@router.delete("/questions/{qid}", dependencies=[Depends(csrf_check)])
def delete_question(qid: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        conn.execute("DELETE FROM questions WHERE id=?", (qid,))
    return {"ok": True}


class QuestionsImport(BaseModel):
    group_code: str
    items: list


@router.post("/questions/import", dependencies=[Depends(csrf_check)])
def import_questions(body: QuestionsImport, request: Request):
    """JSON 批量导入（由前端把粘贴的文本解析或 CSV 转换而来）。"""
    admin_dep(request)
    added, errors = 0, []
    with get_db() as conn:
        for i, it in enumerate(body.items):
            try:
                qb = QuestionBody(
                    group_code=body.group_code, type=it.get("type", "single"),
                    stem=it.get("stem", ""), options=it.get("options", []),
                    answer=it.get("answer", []), score=float(it.get("score", 1)),
                    topic=it.get("topic", ""), enabled=True,
                )
                _validate_question(qb)
                if qb.type == "judge":
                    qb.options = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
                conn.execute(
                    "INSERT INTO questions(group_code,type,stem,options,answer,score,topic,enabled) "
                    "VALUES(?,?,?,?,?,?,?,1)",
                    (qb.group_code, qb.type, qb.stem.strip(),
                     json.dumps(qb.options, ensure_ascii=False), json.dumps(qb.answer),
                     qb.score, qb.topic.strip()),
                )
                added += 1
            except HTTPException as e:
                errors.append(f"第{i + 1}条：{e.detail}")
            except Exception as e:
                errors.append(f"第{i + 1}条：数据格式错误")
    return {"ok": True, "added": added, "errors": errors}


# ---------- 赛事设置 ----------

@router.get("/settings")
def get_settings_all(request: Request):
    admin_dep(request)
    with get_db() as conn:
        return {k: get_setting(conn, k) for k in ("site", "submission", "exams", "publish", "quota", "task")}


class SettingsBody(BaseModel):
    site: dict | None = None
    submission: dict | None = None
    exams: dict | None = None
    publish: dict | None = None
    quota: dict | None = None
    agent_exam: dict | None = None


@router.put("/settings", dependencies=[Depends(csrf_check)])
def update_settings(body: SettingsBody, request: Request):
    admin_dep(request)
    with get_db() as conn:
        for key in ("site", "submission", "exams", "publish", "quota", "agent_exam"):
            value = getattr(body, key, None)
            if value is not None:
                old = get_setting(conn, key) or {}
                merged = {**old, **value}
                set_setting(conn, key, merged)
    return {"ok": True}


# ---------- 成绩 / 公示 / 晋级 ----------

@router.get("/ranking")
def ranking(request: Request, group: str):
    admin_dep(request)
    if group not in config.GROUP_NAMES:
        raise HTTPException(400, "参数错误")
    with get_db() as conn:
        if group == "low":
            rows = low_group_ranking(conn)
            fields = ["rank", "student_id", "entry_no", "name", "school", "work_title",
                      "total", "s_theme", "s_creative", "s_expression", "s_process", "judge_count"]
        else:
            rows = quiz_ranking(conn, group)
            fields = ["rank", "student_id", "entry_no", "name", "school", "grade",
                      "score", "duration_seconds", "answered", "suspicious_events",
                      "agent_score", "merged"]
        submitted = conn.execute(
            "SELECT COUNT(*) AS n FROM students WHERE group_code=? AND status='submitted' AND disqualified=0",
            (group,),
        ).fetchone()["n"]
        if group != "low":
            submitted = conn.execute(
                "SELECT COUNT(*) AS n FROM attempts WHERE group_code=? AND status='submitted'", (group,)
            ).fetchone()["n"]
        quota = (get_setting(conn, "quota") or {}).get(group, 0)
        # OJ 实操考试得分与合并总分（两部分按权重折算，合并后重新排名）
        exam_cfg = get_setting(conn, "agent_exam") or {}
        agent_max = conn.execute(
            "SELECT COALESCE(SUM(total_score),0) AS n FROM agent_exam_questions WHERE enabled=1"
        ).fetchone()["n"]
        quiz_max = conn.execute(
            "SELECT COALESCE(SUM(score),0) AS n FROM questions WHERE group_code=? AND enabled=1",
            (group,)).fetchone()["n"]
        amap = {r["student_id"]: r["score"] for r in conn.execute(
            "SELECT student_id, score FROM agent_judge_results WHERE status='done'")}
        qw, aw = float(exam_cfg.get("quiz_weight", 50)), float(exam_cfg.get("agent_weight", 50))
        merge_on = bool(exam_cfg.get("enabled")) and agent_max and quiz_max
        for r in rows:
            a = amap.get(r["student_id"])
            r["agent_score"] = a
            if merge_on and quiz_max:
                r["merged"] = round((r["score"] / quiz_max) * qw + ((a or 0) / agent_max) * aw + 1e-9, 1)
            else:
                r["merged"] = None
        if merge_on:
            # 只做了实操、未参加知识测试的学生也纳入合并排名
            seen = {r["student_id"] for r in rows}
            for m in conn.execute(
                    "SELECT id, entry_no, name, school, grade FROM students "
                    "WHERE group_code=? AND disqualified=0", (group,)):
                if m["id"] in seen or m["id"] not in amap:
                    continue
                rows.append({"student_id": m["id"], "entry_no": m["entry_no"], "name": m["name"],
                             "school": m["school"], "grade": m["grade"], "score": None,
                             "duration_seconds": None, "answered": 0, "suspicious_events": 0,
                             "agent_score": amap[m["id"]],
                             "merged": round((amap[m["id"]] / agent_max) * aw + 1e-9, 1), "rank": 0})
            rows.sort(key=lambda x: (-(x["merged"] or 0), x["duration_seconds"] or 0))
            for i, x in enumerate(rows, 1):
                x["rank"] = i
    rows = [{k: r.get(k) for k in fields} | {"promoted": (quota > 0 and r["rank"] <= quota)} for r in rows]
    return {"items": rows, "quota": quota, "submitted": submitted,
            "group_name": config.GROUP_NAMES[group]}


@router.get("/ranking/export")
def ranking_export(request: Request, group: str):
    admin_dep(request)
    data = ranking(request, group)
    buf = io.StringIO()
    writer = csv.writer(buf)
    if group == "low":
        writer.writerow(["名次", "参赛编号", "姓名", "学校", "作品名称", "总分",
                         "主题契合", "创意构思", "设计表达", "创作过程", "评委数", "晋级"])
        for r in data["items"]:
            writer.writerow([r["rank"], r["entry_no"], r["name"], r["school"], r["work_title"],
                             r["total"], r["s_theme"], r["s_creative"], r["s_expression"],
                             r["s_process"], r["judge_count"], "是" if r["promoted"] else ""])
    else:
        writer.writerow(["名次", "参赛编号", "姓名", "学校", "年级", "知识测试得分", "实操得分",
                         "合并总分", "用时(秒)", "答题数", "晋级"])
        for r in data["items"]:
            writer.writerow([r["rank"], r["entry_no"], r["name"], r["school"], r["grade"],
                             r["score"], r["agent_score"] if r["agent_score"] is not None else "",
                             r["merged"] if r["merged"] is not None else "",
                             r["duration_seconds"], r["answered"], "是" if r["promoted"] else ""])
    buf.seek(0)
    from urllib.parse import quote
    filename = quote(f"成绩排名_{data['group_name']}.csv")
    return Response(
        content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ---------- 评委账号 ----------

@router.get("/judges")
def judges_list(request: Request):
    admin_dep(request)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT u.id, u.username, u.created_at, u.last_login_at,
                      (SELECT COUNT(*) FROM scores sc WHERE sc.judge_id=u.id) AS scored
               FROM users u WHERE u.role='judge' ORDER BY u.id"""
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


class JudgeCreate(BaseModel):
    username: str
    password: str = ""


@router.post("/judges", dependencies=[Depends(csrf_check)])
def create_judge(body: JudgeCreate, request: Request):
    admin_dep(request)
    username = body.username.strip()
    if not username or len(username) < 2:
        raise HTTPException(400, "评委账号名至少 2 位")
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise HTTPException(400, "账号已存在")
        pwd = body.password.strip() or gen_password(8)
        conn.execute(
            "INSERT INTO users(username,password_hash,role,must_change_pwd) VALUES(?,?,?,1)",
            (username, hash_password(pwd), "judge"),
        )
    return {"ok": True, "initial_password": pwd}


@router.post("/judges/{judge_id}/reset-password", dependencies=[Depends(csrf_check)])
def reset_judge_pwd(judge_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        row = conn.execute("SELECT id FROM users WHERE id=? AND role='judge'", (judge_id,)).fetchone()
        if not row:
            raise HTTPException(404, "评委不存在")
        pwd = gen_password(8)
        conn.execute("UPDATE users SET password_hash=?, must_change_pwd=1 WHERE id=?",
                     (hash_password(pwd), judge_id))
    return {"ok": True, "new_password": pwd}


@router.delete("/judges/{judge_id}", dependencies=[Depends(csrf_check)])
def delete_judge(judge_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=? AND role='judge'", (judge_id,))
    return {"ok": True}


# ---------- 公告 ----------

class AnnBody(BaseModel):
    title: str
    body: str
    pinned: bool = False


@router.get("/announcements")
def ann_list(request: Request):
    admin_dep(request)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM announcements ORDER BY pinned DESC, id DESC").fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/announcements", dependencies=[Depends(csrf_check)])
def ann_create(body: AnnBody, request: Request):
    admin_dep(request)
    if not body.title.strip() or not body.body.strip():
        raise HTTPException(400, "标题和内容不能为空")
    with get_db() as conn:
        conn.execute("INSERT INTO announcements(title,body,pinned) VALUES(?,?,?)",
                     (body.title.strip(), body.body.strip(), 1 if body.pinned else 0))
    return {"ok": True}


@router.put("/announcements/{ann_id}", dependencies=[Depends(csrf_check)])
def ann_update(ann_id: int, body: AnnBody, request: Request):
    admin_dep(request)
    with get_db() as conn:
        conn.execute("UPDATE announcements SET title=?, body=?, pinned=? WHERE id=?",
                     (body.title.strip(), body.body.strip(), 1 if body.pinned else 0, ann_id))
    return {"ok": True}


@router.delete("/announcements/{ann_id}", dependencies=[Depends(csrf_check)])
def ann_delete(ann_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    return {"ok": True}


# ---------- 审计日志 ----------

@router.get("/logs")
def logs(request: Request, page: int = 1, size: int = 50):
    admin_dep(request)
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM audit_logs").fetchone()["n"]
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?",
            (size, (page - 1) * size),
        ).fetchall()
    return {"total": total, "items": [dict(r) for r in rows]}


# ---------- AI 智能出题（调用已配置的 LLM） ----------

class AIGenBody(BaseModel):
    topic: str                     # 知识点范围 / 老师要求
    scene: str = ""                # 生活场景提示（可选）
    count: int = 5                 # 题量
    qtype: str = "mix"             # mix | single | multiple | judge

TYPE_SPEC = {
    "single": "只出单选题（4 个选项，恰好 1 个正确）",
    "multiple": "只出多选题（4 个选项，2—3 个正确）",
    "judge": "只出判断题（options 留空数组 []，answer 为 [A]=正确 或 [B]=错误）",
    "mix": "混合出题：单选、多选、判断都要有（判断题 options 留空数组 []）",
}

GEN_SYSTEM = (
    "你是小学高段组（4—6 年级）「词元推理」赛项的命题老师。"
    "考纲范围：框架表示法、产生式表示法、演绎推理（三段论）、归纳推理、提示词基础、人工智能伦理（偏见与隐私）。"
    "你出的题目必须表述准确、无歧义、答案唯一正确，语言通俗易懂，尽量结合真实生活场景。"
)

GEN_FORMAT = (
    '输出要求：只输出一个 JSON 数组，不要任何解释文字或代码块标记。每条格式：'
    '{"type":"single","stem":"题干","options":[{"key":"A","text":"选项内容"}],'
    '"answer":["A"],"score":2,"topic":"知识点标签"}。'
    '其中单选/多选选项恰好 A—D 四个；判断题 options 为空数组、answer 为 [A] 或 [B]。'
)


@router.post("/questions/ai-generate", dependencies=[Depends(csrf_check)])
async def ai_generate_questions(body: AIGenBody, request: Request):
    admin_dep(request)
    with get_db() as conn:
        cfg = dict(get_setting(conn, "llm") or {})
    if not llm_svc.llm_ready(cfg):
        raise HTTPException(400, "请先在「🤖 智能体设置」配置并启用大模型（接口地址、API Key、模型名称），再使用 AI 出题")
    count = min(max(int(body.count), 1), 20)
    spec = TYPE_SPEC.get(body.qtype, TYPE_SPEC["mix"])
    scene = body.scene.strip() or "图书馆、外卖订单、物流信息等真实生活场景"
    user_prompt = (
        f"请围绕以下老师要求出一组练习题：\n"
        f"- 知识点范围：{body.topic.strip()}\n"
        f"- 生活场景：{scene}\n"
        f"- 题型要求：{spec}\n"
        f"- 题目数量：{count} 道\n"
        f"- 每题分值：判断题 1 分、单选题 2 分、多选题 3 分\n\n"
        f"{GEN_FORMAT}"
    )
    try:
        raw = llm_svc.chat({"name": "命题助手", "system_prefix": GEN_SYSTEM}, cfg, [], user_prompt)
    except llm_svc.LLMError as e:
        raise HTTPException(400, e.admin_message)
    # 解析：剥掉代码块标记，截取首个 [ 到最后一个 ]
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    lo, hi = text.find("["), text.rfind("]")
    if lo == -1 or hi <= lo:
        raise HTTPException(400, "AI 返回的内容无法解析为题目数组，请调整要求后重试")
    try:
        items = json.loads(text[lo:hi + 1])
        assert isinstance(items, list)
    except Exception:
        raise HTTPException(400, "AI 返回的 JSON 格式有误，请重试或调整要求")
    # 校验与规整（复用题库校验逻辑），不直接入库——返回给老师预览确认
    valid, errors = [], []
    for i, it in enumerate(items):
        try:
            qb = QuestionBody(
                group_code="high", type=str(it.get("type", "single")),
                stem=str(it.get("stem", "")).strip(),
                options=[{"key": str(o.get("key")), "text": str(o.get("text"))} for o in it.get("options", []) if isinstance(o, dict)],
                answer=[str(a).upper() for a in it.get("answer", [])],
                score=float(it.get("score", 2)), topic=str(it.get("topic", body.topic[:20])).strip(),
            )
            _validate_question(qb)
            if qb.type == "judge":
                qb.options = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
            valid.append(qb.model_dump())
        except HTTPException as e:
            errors.append(f"第{i + 1}条被剔除：{e.detail}")
        except Exception:
            errors.append(f"第{i + 1}条被剔除：格式不完整")
    return {"items": valid, "errors": errors, "raw_reply": raw[:500], "model": cfg.get("model"), "count_requested": count}
