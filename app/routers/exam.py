"""线上答题路由（小学高段组 / 中学组）。

服务端权威计时：deadline = min(开始 + 时长, 窗口截止)；超时宽限 60s 自动收卷。
每生题目与选项乱序；可多次保存；提交后（窗口内）可继续作答再次提交，成绩以最后一次提交为准。
"""
import json
import random
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import config, security
from ..db import get_db, get_setting
from ..security import csrf_check, require_role
from ..services.grading import grade_attempt
from ..utils import now_str, parse_dt, fmt_duration

router = APIRouter(prefix="/api/exam", tags=["exam"])

student_dep = Depends(require_role("student"))


class AnswersBody(BaseModel):
    answers: dict


class EventBody(BaseModel):
    type: str


def _exam_cfg(conn, group_code: str) -> dict:
    cfg = (get_setting(conn, "exams") or {}).get(group_code)
    if not cfg or not cfg.get("enabled"):
        raise HTTPException(403, "本场考试未开放")
    return cfg


def _check_window(cfg):
    start, end = parse_dt(cfg.get("start_at")), parse_dt(cfg.get("end_at"))
    now = parse_dt(now_str())
    if not start or not end:
        raise HTTPException(403, "考试时间未配置完整，请联系组委会")
    if now < start:
        raise HTTPException(403, f"考试尚未开始，开始时间：{cfg['start_at']}")
    if now > end:
        raise HTTPException(403, "本场考试已结束")
    return start, end


def _finalize(conn, attempt: dict, cfg: dict, forced: bool):
    """用已保存答案收卷并判分。"""
    questions = _load_questions(conn, attempt["group_code"], attempt["question_order"])
    answers = json.loads(attempt["answers"] or "{}")
    score, detail, answered = grade_attempt(answers, questions)
    started = parse_dt(attempt["started_at"])
    deadline = parse_dt(attempt["deadline"])
    submitted = parse_dt(now_str())
    # 用时上限 = min(本 attempt 时间预算, 单场限时)，恢复作答重发时钟后也不会超过限时
    cap = min(
        max(0.0, (deadline - started).total_seconds()),
        float(cfg.get("duration_minutes", 40)) * 60,
    )
    duration = min(max(0.0, (submitted - started).total_seconds()), cap)
    conn.execute(
        "UPDATE attempts SET status='submitted', submitted_at=?, score=?, detail=?, "
        "duration_seconds=?, last_saved_at=COALESCE(last_saved_at, ?) WHERE id=?",
        (now_str(), score, json.dumps(detail, ensure_ascii=False), int(duration), now_str(), attempt["id"]),
    )
    return score, detail, int(duration)


def _load_questions(conn, group_code: str, order_json: str) -> list[dict]:
    qids = json.loads(order_json)
    rows = conn.execute(
        f"SELECT * FROM questions WHERE id IN ({','.join('?' * len(qids))})",
        qids,
    ).fetchall()
    by_id = {r["id"]: dict(r) for r in rows}
    result = [by_id[i] for i in qids if i in by_id]
    for q in result:
        q["answer"] = json.loads(q["answer"])  # DB 存 JSON 字符串，判分需数组
    return result


@router.post("/start", dependencies=[Depends(csrf_check)])
def start_exam(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if not st:
            raise HTTPException(404, "学生档案不存在")
        if st["group_code"] == "low":
            raise HTTPException(403, "小学低段组参加作品评审，不参加线上答题")
        cfg = _exam_cfg(conn, st["group_code"])
        start, end = _check_window(cfg)
        attempt = conn.execute("SELECT * FROM attempts WHERE student_id=?", (st["id"],)).fetchone()

        if attempt and attempt["status"] == "submitted" and not cfg.get("allow_resubmit", True):
            raise HTTPException(403, "已交卷，不能再进入考试")
        if attempt and attempt["status"] == "submitted":
            # 允许再次作答：恢复进行中并重发一个考试时钟（仍受窗口截止约束），成绩以最后一次提交为准
            new_deadline = min(
                parse_dt(now_str()) + timedelta(minutes=int(cfg.get("duration_minutes", 40))),
                end,
            )
            conn.execute(
                "UPDATE attempts SET status='running', deadline=? WHERE id=?",
                (new_deadline.strftime("%Y-%m-%d %H:%M:%S"), attempt["id"]),
            )
            attempt = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt["id"],)).fetchone()

        if not attempt:
            questions = conn.execute(
                "SELECT * FROM questions WHERE group_code=? AND enabled=1", (st["group_code"],)
            ).fetchall()
            if not questions:
                raise HTTPException(403, "题库尚未配置，请联系组委会")
            qids = [q["id"] for q in questions]
            rng = random.Random(secrets.token_hex(8))
            rng.shuffle(qids)
            option_order = {}
            for qrow in questions:
                keys = [o["key"] for o in json.loads(qrow["options"])]
                rng.shuffle(keys)
                option_order[str(qrow["id"])] = keys
            start_at = now_str()
            deadline = min(
                parse_dt(start_at) + timedelta(minutes=int(cfg.get("duration_minutes", 40))),
                end,
            )
            cur = conn.execute(
                "INSERT INTO attempts(student_id,group_code,question_order,option_order,started_at,deadline) "
                "VALUES(?,?,?,?,?,?)",
                (st["id"], st["group_code"], json.dumps(qids),
                 json.dumps(option_order, ensure_ascii=False), start_at, deadline.strftime("%Y-%m-%d %H:%M:%S")),
            )
            attempt = conn.execute("SELECT * FROM attempts WHERE id=?", (cur.lastrowid,)).fetchone()
        return _state_payload(conn, st, cfg, dict(attempt))


def _state_payload(conn, st, cfg, attempt: dict) -> dict:
    now = now_str()
    remaining = -1
    if attempt["status"] == "running":
        deadline = parse_dt(attempt["deadline"])
        remaining = max(0, int((deadline - parse_dt(now)).total_seconds()))
    questions = _load_questions(conn, attempt["group_code"], attempt["question_order"])
    option_order = json.loads(attempt["option_order"])
    answers = json.loads(attempt["answers"] or "{}")
    payload_questions = []
    total_score = 0
    for qrow in questions:
        opts = json.loads(qrow["options"])
        keys = option_order.get(str(qrow["id"]), [o["key"] for o in opts])
        by_key = {o["key"]: o["text"] for o in opts}
        total_score += float(qrow["score"])
        payload_questions.append({
            "id": qrow["id"], "type": qrow["type"], "stem": qrow["stem"],
            "topic": qrow["topic"], "score": qrow["score"],
            "options": [{"key": k, "text": by_key[k]} for k in keys if k in by_key],
        })
    return {
        "status": attempt["status"],
        "started_at": attempt["started_at"],
        "deadline": attempt["deadline"],
        "remaining_seconds": remaining,
        "server_now": now,
        "duration_minutes": cfg.get("duration_minutes", 40),
        "total_score": round(total_score + 1e-9, 2),
        "answers": answers,
        "questions": payload_questions,
        "grace_seconds": config.EXAM_GRACE_SECONDS,
        "allow_resubmit": bool(cfg.get("allow_resubmit", True)),
        "show_score_after": bool(cfg.get("show_score_after", True)),
        "score": attempt["score"],
        "duration_seconds": attempt["duration_seconds"],
        "window_end": cfg.get("end_at"),
        "duration_text": fmt_duration(attempt["duration_seconds"]) if attempt["duration_seconds"] is not None else None,
    }


@router.get("/state")
def exam_state(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if not st:
            raise HTTPException(404, "学生档案不存在")
        if st["group_code"] == "low":
            raise HTTPException(403, "小学低段组不参加线上答题")
        attempt = conn.execute("SELECT * FROM attempts WHERE student_id=?", (st["id"],)).fetchone()
        if not attempt:
            return {"status": "not_started"}
        cfg = (get_setting(conn, "exams") or {}).get(st["group_code"]) or {}

        # 超过宽限期仍未提交 → 自动收卷
        deadline = parse_dt(attempt["deadline"])
        if attempt["status"] == "running" and parse_dt(now_str()) > deadline:
            if (parse_dt(now_str()) - deadline).total_seconds() > config.EXAM_GRACE_SECONDS:
                _finalize(conn, dict(attempt), cfg, forced=True)
                attempt = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt["id"],)).fetchone()
            else:
                remaining = max(0, int((deadline - parse_dt(now_str())).total_seconds()))
                return {**_state_payload(conn, st, cfg, dict(attempt)), "overtime_grace": True}
        return _state_payload(conn, st, cfg, dict(attempt))


def _validate_answers(conn, attempt, answers: dict) -> dict:
    qids = set(json.loads(attempt["question_order"]))
    option_order = json.loads(attempt["option_order"])
    clean = {}
    for qid, keys in (answers or {}).items():
        try:
            qid_i = int(qid)
        except (TypeError, ValueError):
            continue
        if qid_i not in qids:
            continue
        allowed = set(option_order.get(str(qid_i), []))
        picked = sorted({str(k).upper() for k in (keys or []) if str(k).upper() in allowed})
        if picked:
            clean[str(qid_i)] = picked
    return clean


@router.post("/save", dependencies=[Depends(csrf_check)])
def save_answers(body: AnswersBody, request: Request):
    user = security.require_user(request)
    if len(json.dumps(body.answers)) > 65536:
        raise HTTPException(400, "答案数据异常")
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        attempt = conn.execute("SELECT * FROM attempts WHERE student_id=?", (st["id"],)).fetchone() if st else None
        if not attempt:
            raise HTTPException(400, "考试尚未开始")
        if attempt["status"] != "running":
            raise HTTPException(400, "已交卷，如需修改请先在考试页恢复作答")
        deadline = parse_dt(attempt["deadline"])
        if parse_dt(now_str()) > deadline:
            raise HTTPException(400, "考试时间已到")
        clean = _validate_answers(conn, attempt, body.answers)
        conn.execute(
            "UPDATE attempts SET answers=?, last_saved_at=? WHERE id=?",
            (json.dumps(clean, ensure_ascii=False), now_str(), attempt["id"]),
        )
    return {"ok": True, "saved_count": len(clean), "server_now": now_str()}


@router.post("/submit", dependencies=[Depends(csrf_check)])
def submit_exam(body: AnswersBody, request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        attempt = conn.execute("SELECT * FROM attempts WHERE student_id=?", (st["id"],)).fetchone() if st else None
        if not attempt:
            raise HTTPException(400, "考试尚未开始")
        if attempt["status"] != "running":
            raise HTTPException(400, "已交卷")
        cfg = (get_setting(conn, "exams") or {}).get(st["group_code"]) or {}
        deadline = parse_dt(attempt["deadline"])
        now = parse_dt(now_str())
        grace_over = now > deadline and (now - deadline).total_seconds() > config.EXAM_GRACE_SECONDS
        clean = _validate_answers(conn, attempt, body.answers)
        conn.execute("UPDATE attempts SET answers=?, last_saved_at=? WHERE id=?",
                     (json.dumps(clean, ensure_ascii=False), now_str(), attempt["id"]))
        attempt = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt["id"],)).fetchone()
        score, detail, duration = _finalize(conn, dict(attempt), cfg, forced=grace_over)
        security.audit(request, user, "exam_submit",
                       f"score={score} duration={duration}s forced={grace_over}")
        resp = {"ok": True, "score": score, "duration_seconds": duration}
        if cfg.get("show_score_after", True):
            resp["detail"] = detail
        return resp


@router.post("/resume", dependencies=[Depends(csrf_check)])
def resume_exam(request: Request):
    """窗口期内再次作答（恢复时重发一个考试时钟，仍受窗口截止约束；成绩以最后一次提交为准）。"""
    user = security.require_user(request)
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        attempt = conn.execute("SELECT * FROM attempts WHERE student_id=?", (st["id"],)).fetchone() if st else None
        if not attempt or attempt["status"] != "submitted":
            raise HTTPException(400, "当前状态无法恢复作答")
        cfg = (get_setting(conn, "exams") or {}).get(st["group_code"]) or {}
        if not cfg.get("allow_resubmit", True):
            raise HTTPException(403, "本届考试不允许重复提交")
        _, end = _check_window(cfg)  # 窗口已结束会在此拦截（"本场考试已结束"）
        new_deadline = min(
            parse_dt(now_str()) + timedelta(minutes=int(cfg.get("duration_minutes", 40))),
            end,
        )
        conn.execute(
            "UPDATE attempts SET status='running', deadline=? WHERE id=?",
            (new_deadline.strftime("%Y-%m-%d %H:%M:%S"), attempt["id"]),
        )
    return {"ok": True}


@router.post("/event", dependencies=[Depends(csrf_check)])
def exam_event(body: EventBody, request: Request):
    """记录考试期间异常事件（切屏等），作为原创性佐证，不自动扣分。"""
    user = security.require_user(request)
    if body.type not in ("leave", "paste", "devtools"):
        return {"ok": False}
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        attempt = conn.execute("SELECT * FROM attempts WHERE student_id=?", (st["id"],)).fetchone() if st else None
        if not attempt or attempt["status"] != "running":
            return {"ok": False}
        log = json.loads(attempt["extra_log"] or "[]")
        if len(log) < 500:
            log.append({"t": now_str(), "type": body.type})
        conn.execute(
            "UPDATE attempts SET suspicious_events=suspicious_events+1, extra_log=? WHERE id=?",
            (json.dumps(log, ensure_ascii=False), attempt["id"]),
        )
    return {"ok": True}
