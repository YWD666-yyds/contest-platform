"""智能体（设计 + 对话 + 任务提交/检测）路由。

学生端：查看题目要求 → 引导式设计智能体 → 保存 → 对话测试 → 交任务（可撤回）
管理端：配置 LLM 并测试连接；任务列表/详情/检测结论/导出
"""
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from .. import config, security
from ..db import get_db, get_setting, set_setting
from ..security import csrf_check, require_role
from ..services import judge as judge_svc
from ..services import llm as llm_svc
from ..utils import now_str, parse_dt

router = APIRouter(prefix="/api", tags=["agent"])

student_dep = Depends(require_role("student"))
admin_dep = require_role("admin")

# 字段校验规则：key → (名称, 是否必填, 最大长度)
FIELDS = {
    "name": ("智能体名称", True, 30),
    "audience": ("服务对象", True, 50),
    "scenario": ("应用场景", True, 200),
    "role": ("角色定位", True, 500),
    "problem": ("要解决的便民问题", True, 500),
    "skills": ("功能与技能", False, 500),
    "knowledge": ("知识资料", False, 2000),
    "tone": ("语气风格", True, 50),
    "welcome": ("开场白", False, 200),
}

# 学生端对话频率限制（秒）——基于对话记录持久化，多 worker / 重启均生效
CHAT_COOLDOWN_SECONDS = 2


class AgentBody(BaseModel):
    name: str = ""
    audience: str = ""
    scenario: str = ""
    role: str = ""
    problem: str = ""
    skills: str = ""
    knowledge: str = ""
    tone: str = ""
    welcome: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def _str(cls, v):
        return "" if v is None else str(v).strip()


class ChatBody(BaseModel):
    message: str

    @field_validator("message", mode="before")
    @classmethod
    def _clean(cls, v):
        return ("" if v is None else str(v)).strip()


# ---------------- 学生端 ----------------

@router.get("/student/task")
def task_and_agent(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        task = get_setting(conn, "task") or {}
        llm_cfg = get_setting(conn, "llm") or {}
        window_open = _agent_window(conn)
        row = conn.execute("SELECT * FROM student_agents WHERE student_id=(SELECT id FROM students WHERE user_id=?)",
                           (user["id"],)).fetchone()
        chats = conn.execute(
            "SELECT role, content, created_at FROM agent_chats WHERE student_id=(SELECT id FROM students WHERE user_id=?) ORDER BY id",
            (user["id"],)).fetchall() if row else []
    return {
        "task": {"title": task.get("title") or "设计智能体 · 题目要求", "content": task.get("content") or ""},
        "agent": dict(row) if row else None,
        "chat_enabled": llm_svc.llm_ready(llm_cfg),
        "window_open": window_open,
        "history": [dict(c) for c in chats][-50:],
    }


@router.put("/student/agent", dependencies=[Depends(csrf_check)])
def save_agent(body: AgentBody, request: Request):
    user = security.require_user(request)
    missing = [label for key, (label, required, _) in FIELDS.items()
               if required and not getattr(body, key)]
    if missing:
        raise HTTPException(400, "请先完成必填项：" + "、".join(missing))
    values = {key: getattr(body, key)[:max_len] for key, (_, _, max_len) in FIELDS.items()}

    with get_db() as conn:
        st = conn.execute("SELECT id FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if not st:
            raise HTTPException(404, "学生档案不存在")
        if not _agent_window(conn):
            raise HTTPException(403, "答题时间已结束，智能体配置已锁定（仍可查看与体验）")
        exists = conn.execute(
            "SELECT id, status, check_status FROM student_agents WHERE student_id=?",
            (st["id"],),
        ).fetchone()
        if exists:
            if exists["check_status"] == "ok":
                raise HTTPException(403, "任务已检测合格并锁定，如需修改请联系老师")
            if exists["status"] == "submitted":
                raise HTTPException(400, "任务已提交，请先撤回再修改")
            sets = ", ".join(f"{k}=?" for k in values)
            conn.execute(f"UPDATE student_agents SET {sets}, status='saved', updated_at=? WHERE student_id=?",
                         [*values.values(), now_str(), st["id"]])
        else:
            keys = ", ".join(values)
            marks = ", ".join("?" * len(values))
            conn.execute(
                f"INSERT INTO student_agents(student_id, {keys}, status) VALUES(?, {marks}, 'saved')",
                [st["id"], *values.values()])
    security.audit(request, user, "save_agent", values["name"])
    return {"ok": True, "agent": values}


@router.post("/student/agent/chat", dependencies=[Depends(csrf_check)])
def agent_chat(body: ChatBody, request: Request):
    user = security.require_user(request)
    if not body.message:
        raise HTTPException(400, "消息不能为空")
    if len(body.message) > 500:
        raise HTTPException(400, "单条消息不超过 500 字，请分条发送")

    # 频率限制：查该学生最近一条发言时间（持久化，多 worker 生效）
    with get_db() as conn:
        st = conn.execute("SELECT id FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if not st:
            raise HTTPException(404, "学生档案不存在")
        last = conn.execute(
            "SELECT created_at FROM agent_chats WHERE student_id=? AND role='user' ORDER BY id DESC LIMIT 1",
            (st["id"],)).fetchone()
        if last:
            lt = parse_dt(last["created_at"])
            if lt and 0 <= (datetime.now() - lt).total_seconds() < CHAT_COOLDOWN_SECONDS:
                raise HTTPException(429, "发送太频繁了，请休息一下再试")
        agent = conn.execute("SELECT * FROM student_agents WHERE student_id=?", (st["id"],)).fetchone()
        if not agent:
            raise HTTPException(400, "请先保存你的智能体设计，再开始对话")
        in_window = _agent_window(conn)
        if in_window:
            # 设计期：提交/检测合格后限制对话（保持评审记录干净）
            if agent["check_status"] == "ok":
                raise HTTPException(403, "任务已检测合格并锁定，无法继续修改对话")
            if agent["status"] == "submitted":
                raise HTTPException(400, "任务已提交，如需继续对话测试请先撤回修改")
            if agent["status"] != "saved":
                raise HTTPException(400, "请先保存你的智能体设计，再开始对话")
        # 体验期（答题时间结束）：不再限制状态，对话不落库，仅供展示与老师线下验证
        llm_cfg = get_setting(conn, "llm") or {}
        history = conn.execute(
            "SELECT role, content FROM agent_chats WHERE student_id=? ORDER BY id DESC LIMIT 12",
            (st["id"],)).fetchall()
        history = [dict(h) for h in reversed(history)]

        if in_window:
            # 记录学生发言（无论成败，便于老师复盘）
            conn.execute("INSERT INTO agent_chats(student_id, role, content) VALUES(?, 'user', ?)",
                         (st["id"], body.message))

        try:
            reply = llm_svc.chat(dict(agent), llm_cfg, history, body.message)
        except llm_svc.LLMError as e:
            security.audit(request, user, "agent_chat_error", f"kind={e.kind}")
            # 以 200 返回错误提示，让前端以对话气泡形式展示（学生可读、老师可操作）
            return {"ok": False, "error": e.message}
        if in_window:
            conn.execute("INSERT INTO agent_chats(student_id, role, content) VALUES(?, 'assistant', ?)",
                         (st["id"], reply))
    return {"ok": True, "reply": reply}


@router.post("/student/agent/chat/clear", dependencies=[Depends(csrf_check)])
def clear_chat(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = conn.execute("SELECT id FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if st:
            agent = conn.execute(
                "SELECT status, check_status FROM student_agents WHERE student_id=?",
                (st["id"],),
            ).fetchone()
            if agent and (agent["status"] == "submitted" or agent["check_status"] == "ok"):
                raise HTTPException(400, "任务已提交或已锁定，无法清空对话记录")
            if not _agent_window(conn):
                raise HTTPException(403, "答题时间已结束，无法清空对话记录")
            conn.execute("DELETE FROM agent_chats WHERE student_id=?", (st["id"],))
    return {"ok": True}


# ---------------- 管理端：LLM 配置 ----------------

class LLMBody(BaseModel):
    enabled: bool = False
    provider: str = ""
    api_base: str = ""
    api_key: str = ""      # 留空表示保持原 key 不变
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 800
    system_prefix: str = ""


@router.get("/admin/llm")
def get_llm(request: Request):
    admin_dep(request)
    with get_db() as conn:
        cfg = dict(get_setting(conn, "llm") or {})
    key = cfg.get("api_key", "")
    cfg["api_key"] = ""                        # 从不返回明文
    cfg["api_key_masked"] = llm_svc.mask_key(key)
    cfg["api_key_set"] = bool(key)
    return {"llm": cfg}


@router.put("/admin/llm", dependencies=[Depends(csrf_check)])
def save_llm(body: LLMBody, request: Request):
    admin_dep(request)
    if body.enabled and not (body.api_base.strip() and body.model.strip()):
        raise HTTPException(400, "启用 LLM 需要填写「接口地址」和「模型名称」")
    with get_db() as conn:
        old = dict(get_setting(conn, "llm") or {})
        new = {
            "enabled": body.enabled,
            "provider": body.provider.strip()[:60],
            "api_base": llm_svc.normalize_base_url(body.api_base)[:300],
            "api_key": body.api_key.strip() or old.get("api_key", ""),  # 留空保持不变
            "model": body.model.strip()[:120],
            "temperature": min(max(float(body.temperature), 0), 2),
            "max_tokens": min(max(int(body.max_tokens), 100), 8000),
            "system_prefix": body.system_prefix.strip()[:1000],
        }
        set_setting(conn, "llm", new)
        # 管理端查看时附带 key 掩码（不返回明文）
        view = dict(new)
        view["api_key"] = ""
        view["api_key_masked"] = llm_svc.mask_key(new["api_key"])
        view["api_key_set"] = bool(new["api_key"])
    security.audit(request, security.require_user(request), "save_llm", f"enabled={body.enabled} model={new['model']}")
    return {"ok": True, "llm": view}


class LLMTestBody(BaseModel):
    """测试连接使用表单当前值，不写入配置；API Key 留空则沿用已保存的 Key。"""
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 300
    system_prefix: str = ""


@router.post("/admin/llm/test", dependencies=[Depends(csrf_check)])
def test_llm(request: Request, body: LLMTestBody | None = None):
    admin_dep(request)
    with get_db() as conn:
        cfg = dict(get_setting(conn, "llm") or {})
    if body is not None:
        cfg["api_base"] = body.api_base.strip()
        cfg["model"] = body.model.strip()
        cfg["temperature"] = body.temperature
        cfg["max_tokens"] = body.max_tokens
        cfg["system_prefix"] = body.system_prefix
        if body.api_key.strip():
            cfg["api_key"] = body.api_key.strip()
    cfg["enabled"] = True  # 测试时按启用对待
    cfg["api_base"] = llm_svc.normalize_base_url(body.api_base if body else cfg.get("api_base"))
    ok, message = llm_svc.test_connection(cfg)
    suffix = f"　[被测地址 {llm_svc.full_chat_url(cfg.get('api_base'))} · 模型 {cfg.get('model') or '（空）'} · {now_str()}]"
    return {"ok": ok, "message": message + suffix}


# ---------------- 管理端：题目要求 ----------------

class TaskBody(BaseModel):
    title: str = ""
    content: str = ""


@router.put("/admin/task", dependencies=[Depends(csrf_check)])
def save_task(body: TaskBody, request: Request):
    admin_dep(request)
    if not body.content.strip():
        raise HTTPException(400, "题目要求内容不能为空")
    with get_db() as conn:
        set_setting(conn, "task", {"title": body.title.strip()[:80], "content": body.content.strip()[:8000]})
    security.audit(request, security.require_user(request), "save_task")
    return {"ok": True}

# ---------------- 学生端：交任务 / 撤回 ----------------

# 检测门槛：提交前须与智能体完成的最少对话轮数（学生消息数）
MIN_CHAT_ROUNDS = 2


def _agent_and_deadline(conn, user: dict):
    st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
    if not st:
        raise HTTPException(404, "学生档案不存在")
    agent = conn.execute("SELECT * FROM student_agents WHERE student_id=?", (st["id"],)).fetchone()
    return st, agent


def _agent_window(conn) -> bool:
    """智能体设计窗口（答题时间）：以「实操考试」设置的起止时间为准。

    仅在启用实操考试且配置了完整起止时间时启用窗口限制；
    未启用或时间未配置 = 始终开放（向后兼容测试与未配置的部署）。
    窗口外 = 体验期：配置锁定，仅可查看与对话体验。
    """
    cfg = get_setting(conn, "agent_exam") or {}
    if not cfg.get("enabled"):
        return True
    start, end = parse_dt(cfg.get("start_at")), parse_dt(cfg.get("end_at"))
    if not start or not end:
        return True
    return start <= parse_dt(now_str()) <= end


@router.post("/student/agent/submit", dependencies=[Depends(csrf_check)])
def submit_agent(request: Request):
    """交任务：校验设计完整性 + 对话轮数门槛，状态 → submitted。仅限答题时间（agent_exam 窗口）内。"""
    user = security.require_user(request)
    with get_db() as conn:
        st, agent = _agent_and_deadline(conn, user)
        if not agent:
            raise HTTPException(400, "请先完成并保存智能体设计")
        if agent["status"] == "submitted":
            raise HTTPException(400, "任务已提交，请先撤回再修改")
        if agent["status"] != "saved":
            raise HTTPException(400, "请先完成并保存智能体设计")
        if agent["check_status"] == "ok":
            raise HTTPException(403, "任务已检测合格并锁定，如需修改请联系老师")
        if not _agent_window(conn):
            raise HTTPException(403, "答题时间已结束，不能再提交任务")
        rounds = conn.execute(
            "SELECT COUNT(*) AS n FROM agent_chats WHERE student_id=? AND role='user'",
            (st["id"],)).fetchone()["n"]
        if rounds < MIN_CHAT_ROUNDS:
            raise HTTPException(400, f"对话测试不足：已提问 {rounds} 次，至少完成 {MIN_CHAT_ROUNDS} 轮对话后再提交")
        conn.execute(
            "UPDATE student_agents SET status='submitted', submitted_at=?, updated_at=? WHERE id=?",
            (now_str(), now_str(), agent["id"]))
    security.audit(request, user, "submit_agent", agent["name"])
    return {"ok": True, "chat_rounds": rounds}


@router.post("/student/agent/retract", dependencies=[Depends(csrf_check)])
def retract_agent(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st, agent = _agent_and_deadline(conn, user)
        if not agent or agent["status"] != "submitted":
            raise HTTPException(400, "任务未在提交状态")
        if agent["check_status"] == "ok":
            raise HTTPException(403, "任务已检测合格并锁定，如需修改请联系老师")
        if not _agent_window(conn):
            raise HTTPException(403, "答题时间已结束，不能再撤回修改")
        conn.execute(
            "UPDATE student_agents SET status='saved', submitted_at=NULL, updated_at=? WHERE id=?",
            (now_str(), agent["id"]))
    security.audit(request, user, "retract_agent", agent["name"])
    return {"ok": True}


# ---------------- 管理端：任务检测 ----------------

@router.get("/admin/agents")
def admin_agents_list(request: Request, group: str = "", check: str = ""):
    admin_dep(request)
    where, args = [f"s.group_code IN ({','.join('?' * len(config.GROUP_NAMES))})"], list(config.GROUP_NAMES)
    if group in config.GROUP_NAMES:
        where.append("s.group_code=?")
        args.append(group)
    if check == "none":
        where.append("a.id IS NULL")
    elif check == "pending":
        where.append("a.status='submitted' AND COALESCE(a.check_status,'pending')='pending'")
    elif check in ("ok", "revise"):
        where.append("a.check_status=?")
        args.append(check)
    w = " AND ".join(where)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT s.id AS student_id, s.entry_no, s.name, s.school, s.grade, s.group_code,
                       s.teacher_name, a.name AS agent_name, a.status AS agent_status, a.role,
                       a.problem, a.audience, a.scenario, a.tone,
                       a.submitted_at, a.check_status, a.check_comment, a.checked_at, a.checked_by,
                       (SELECT COUNT(*) FROM agent_chats c WHERE c.student_id=s.id AND c.role='user') AS chat_rounds
                FROM students s LEFT JOIN student_agents a ON a.student_id=s.id
                WHERE {w} ORDER BY s.group_code, s.entry_no""",
            args).fetchall()
    items = []
    for r in rows:
        design_ok = bool(r["agent_name"] and r["role"] and r["problem"] and r["audience"] and r["scenario"] and r["tone"])
        auto = {
            "design_ok": design_ok,
            "chat_ok": (r["chat_rounds"] or 0) >= MIN_CHAT_ROUNDS,
            "chat_rounds": r["chat_rounds"] or 0,
        }
        auto["all_ok"] = design_ok and auto["chat_ok"] and r["agent_status"] == "submitted"
        items.append({
            "student_id": r["student_id"], "entry_no": r["entry_no"], "name": r["name"],
            "school": r["school"], "grade": r["grade"], "group_code": r["group_code"],
            "teacher_name": r["teacher_name"], "agent_name": r["agent_name"] or "",
            "agent_status": r["agent_status"] or "none",
            "submitted_at": r["submitted_at"],
            "check_status": r["check_status"] or "pending", "check_comment": r["check_comment"],
            "checked_at": r["checked_at"], "checked_by": r["checked_by"],
            "auto": auto,
        })
    return {"items": items, "min_rounds": MIN_CHAT_ROUNDS}


@router.get("/admin/agents/export")
def admin_agents_export(request: Request, group: str = ""):
    admin_dep(request)
    data = admin_agents_list(request, group=group)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["参赛编号", "姓名", "学校", "年级", "组别", "指导教师", "智能体名称",
                     "任务状态", "对话轮数", "自动检测", "检测结论", "检测备注", "检测人", "提交时间"])
    for r in data["items"]:
        writer.writerow([
            r["entry_no"], r["name"], r["school"], r["grade"], config.GROUP_NAMES[r["group_code"]],
            r["teacher_name"], r["agent_name"] or "—",
            {"none": "未开始", "draft": "设计中", "saved": "已保存", "submitted": "已提交"}[r["agent_status"]],
            r["auto"]["chat_rounds"], "通过" if r["auto"]["all_ok"] else "待关注",
            {"pending": "未检测", "ok": "合格", "revise": "需修改"}[r["check_status"]],
            r["check_comment"], r["checked_by"] or "", r["submitted_at"] or "",
        ])
    buf.seek(0)
    from urllib.parse import quote
    filename = quote(f"智能体任务_{group or '全部'}.csv")
    return Response(
        content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )

@router.get("/admin/agents/{student_id}")
def admin_agent_detail(student_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not st:
            raise HTTPException(404, "学生不存在")
        a = conn.execute("SELECT * FROM student_agents WHERE student_id=?", (student_id,)).fetchone()
        chats = conn.execute(
            "SELECT role, content, created_at FROM agent_chats WHERE student_id=? ORDER BY id",
            (student_id,)).fetchall()
    return {
        "student": {"id": st["id"], "entry_no": st["entry_no"], "name": st["name"],
                    "school": st["school"], "grade": st["grade"], "group_code": st["group_code"],
                    "teacher_name": st["teacher_name"]},
        "agent": dict(a) if a else None,
        "chats": [dict(c) for c in chats],
        "min_rounds": MIN_CHAT_ROUNDS,
    }


class AgentCheckBody(BaseModel):
    check_status: str
    check_comment: str = ""

    @field_validator("check_status")
    @classmethod
    def _valid(cls, v):
        if v not in ("pending", "ok", "revise"):
            raise ValueError("检测结论只能是 pending/ok/revise")
        return v


@router.put("/admin/agents/{student_id}/check", dependencies=[Depends(csrf_check)])
def admin_agent_check(student_id: int, body: AgentCheckBody, request: Request):
    user = admin_dep(request)
    with get_db() as conn:
        a = conn.execute("SELECT id, status FROM student_agents WHERE student_id=?", (student_id,)).fetchone()
        if not a:
            raise HTTPException(404, "该学生尚未开始智能体任务")
        conn.execute(
            "UPDATE student_agents SET check_status=?, check_comment=?, checked_at=?, checked_by=? WHERE id=?",
            (body.check_status, body.check_comment.strip()[:500], now_str(), user["username"], a["id"]))
    security.audit(request, user, "agent_check", f"student={student_id} → {body.check_status}")
    return {"ok": True}


# ---------------- OJ 实操考试（智能体作品） ----------------

def _exam_window_ok(cfg: dict) -> bool:
    from ..utils import parse_dt as _pd
    start, end = _pd(cfg.get("start_at")), _pd(cfg.get("end_at"))
    if not start or not end:
        return False
    now = _pd(now_str())
    return start <= now <= end


def _agent_exam_payload(conn, st):
    cfg = get_setting(conn, "agent_exam") or {}
    qs = [dict(r) for r in conn.execute(
        "SELECT * FROM agent_exam_questions WHERE enabled=1 ORDER BY id")]
    # 面向学生隐藏参考答案要点（points），只给标准问题清单
    pub = [{"id": q["id"], "title": q["title"], "scene": q["scene"], "task_desc": q["task_desc"],
            "total_score": q["total_score"],
            "test_questions": [t["q"] for t in json.loads(q["test_questions"] or "[]")]} for q in qs]
    result = conn.execute("SELECT * FROM agent_judge_results WHERE student_id=?", (st["id"],)).fetchone()
    res = None
    if result:
        detail = json.loads(result["detail"] or "[]")
        res = {"status": result["status"], "score": result["score"], "error": result["error"],
               "judged_at": result["judged_at"], "detail": detail}
    return {"exam": cfg, "window_open": _exam_window_ok(cfg),
            "questions": pub, "max_total": sum(q["total_score"] for q in qs), "result": res,
            "llm_ready": llm_svc.llm_ready(get_setting(conn, "llm") or {}),
            "agent_status": (conn.execute("SELECT status FROM student_agents WHERE student_id=?",
                                          (st["id"],)).fetchone() or {"status": "none"})["status"]}


@router.get("/student/agent-exam")
def student_agent_exam(request: Request):
    user = security.require_user(request)
    with get_db() as conn:
        st = conn.execute("SELECT id FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if not st:
            raise HTTPException(404, "学生档案不存在")
        return _agent_exam_payload(conn, st)


@router.post("/student/agent-exam/submit", dependencies=[Depends(csrf_check)])
def submit_agent_exam(request: Request):
    """提交实操考试：校验后启动后台自动判题，前端轮询结果。"""
    user = security.require_user(request)
    with get_db() as conn:
        st = conn.execute("SELECT * FROM students WHERE user_id=?", (user["id"],)).fetchone()
        if not st:
            raise HTTPException(404, "学生档案不存在")
        cfg = get_setting(conn, "agent_exam") or {}
        if not cfg.get("enabled"):
            raise HTTPException(403, "实操考试暂未开放")
        if not _exam_window_ok(cfg):
            raise HTTPException(403, "不在实操考试时间范围内")
        agent = conn.execute("SELECT * FROM student_agents WHERE student_id=?", (st["id"],)).fetchone()
        if not agent or agent["status"] == "draft":
            raise HTTPException(400, "请先在操作台完成并保存智能体配置")
        if not llm_svc.llm_ready(get_setting(conn, "llm") or {}):
            raise HTTPException(400, "判题服务未就绪：老师尚未配置大模型，请联系老师")
        result = conn.execute("SELECT * FROM agent_judge_results WHERE student_id=?", (st["id"],)).fetchone()
        if result and result["status"] == "running":
            return {"ok": True, "status": "running"}  # 已在判题中，避免重复提交
    judge_svc.start_judging(st["id"])
    security.audit(request, user, "agent_exam_submit")
    return {"ok": True, "status": "running"}


class ExamQuestionBody(BaseModel):
    title: str
    scene: str
    task_desc: str
    test_questions: list   # [{q, points, score}]
    enabled: bool = True


@router.get("/admin/agent-exam/questions")
def admin_exam_questions(request: Request):
    admin_dep(request)
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM agent_exam_questions ORDER BY id")]
    for r in rows:
        r["test_questions"] = json.loads(r["test_questions"] or "[]")
    return {"items": rows}


@router.post("/admin/agent-exam/questions", dependencies=[Depends(csrf_check)])
def create_exam_question(body: ExamQuestionBody, request: Request):
    admin_dep(request)
    if not body.title.strip() or not body.task_desc.strip():
        raise HTTPException(400, "标题与任务要求不能为空")
    if not body.test_questions:
        raise HTTPException(400, "至少一道标准测试问题")
    total = sum(float(t.get("score", 0)) for t in body.test_questions)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO agent_exam_questions(title,scene,task_desc,test_questions,total_score,enabled) "
            "VALUES(?,?,?,?,?,?)",
            (body.title.strip(), body.scene.strip(), body.task_desc.strip(),
             json.dumps(body.test_questions, ensure_ascii=False), total, 1 if body.enabled else 0))
    return {"ok": True, "total_score": total}


@router.put("/admin/agent-exam/questions/{qid}", dependencies=[Depends(csrf_check)])
def update_exam_question(qid: int, body: ExamQuestionBody, request: Request):
    admin_dep(request)
    total = sum(float(t.get("score", 0)) for t in body.test_questions)
    with get_db() as conn:
        conn.execute(
            "UPDATE agent_exam_questions SET title=?, scene=?, task_desc=?, test_questions=?, "
            "total_score=?, enabled=? WHERE id=?",
            (body.title.strip(), body.scene.strip(), body.task_desc.strip(),
             json.dumps(body.test_questions, ensure_ascii=False), total, 1 if body.enabled else 0, qid))
    return {"ok": True}


@router.delete("/admin/agent-exam/questions/{qid}", dependencies=[Depends(csrf_check)])
def delete_exam_question(qid: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        conn.execute("DELETE FROM agent_exam_questions WHERE id=?", (qid,))
    return {"ok": True}


@router.get("/admin/agent-exam/results")
def admin_exam_results(request: Request):
    admin_dep(request)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.id AS student_id, s.entry_no, s.name, s.school, s.status AS student_status,
                      r.status, r.score, r.error, r.judged_at
               FROM students s LEFT JOIN agent_judge_results r ON r.student_id=s.id
               ORDER BY s.entry_no""").fetchall()
        qtotal = conn.execute("SELECT COALESCE(SUM(total_score),0) AS n FROM agent_exam_questions "
                              "WHERE enabled=1").fetchone()["n"]
    return {"items": [dict(r) for r in rows], "max_total": qtotal}


@router.get("/admin/agent-exam/results/{student_id}")
def admin_exam_result_detail(student_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        r = conn.execute("SELECT * FROM agent_judge_results WHERE student_id=?", (student_id,)).fetchone()
        s = conn.execute("SELECT entry_no,name,school FROM students WHERE id=?", (student_id,)).fetchone()
    if not r:
        raise HTTPException(404, "该学生暂无判题记录")
    return {"student": dict(s), "status": r["status"], "score": r["score"], "error": r["error"],
            "judged_at": r["judged_at"], "detail": json.loads(r["detail"] or "[]")}


@router.post("/admin/agent-exam/results/{student_id}/rejudge", dependencies=[Depends(csrf_check)])
def admin_exam_rejudge(student_id: int, request: Request):
    admin_dep(request)
    with get_db() as conn:
        agent = conn.execute("SELECT status FROM student_agents WHERE student_id=?", (student_id,)).fetchone()
        if not agent or agent["status"] == "draft":
            raise HTTPException(400, "该学生尚未保存智能体设计")
    judge_svc.start_judging(student_id)
    return {"ok": True, "status": "running"}
