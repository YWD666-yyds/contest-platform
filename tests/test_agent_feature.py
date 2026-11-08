"""设计智能体功能测试：设计保存 / 对话（mock LLM）/ 错误友好化 / 管理端配置。"""
import csv
import io
import json

import urllib.error

from app.db import get_db, set_setting
from app.services import llm as llm_svc
from tests.conftest import login

XHR = {"X-Requested-With": "XMLHttpRequest"}

AGENT_BODY = {
    "name": "垃圾分类小管家", "audience": "社区居民",
    "scenario": "社区垃圾投放点，居民不确定垃圾类别时询问",
    "role": "你是一名耐心的垃圾分类指导员",
    "problem": "居民分不清垃圾类别，投错率高",
    "skills": "判断垃圾类别并说明原因", "knowledge": "厨余垃圾：剩饭剩菜、果皮…",
    "tone": "亲切耐心", "welcome": "您好！我是垃圾分类小管家",
}


_import_seq = [0]


def _import_one_student(client):
    _import_seq[0] += 1
    name = f"智能体测试生{_import_seq[0]}"
    login(client, "admin", "test-admin-pwd")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["姓名", "学校", "年级", "组别", "指导教师", "作品名称"])
    w.writerow([name, "AG学校", "五年级", "", "T老师", ""])
    r = client.post("/api/admin/students/import",
                    files={"file": ("s.csv", buf.getvalue().encode("utf-8-sig"), "text/csv")}, headers=XHR)
    data = r.json()
    assert data["created"] == 1, f"导入失败: {data}"
    rows = list(csv.reader(io.StringIO(data["accounts_csv"])))[1:]
    return rows[0][3], rows[0][4]


def _enable_llm(client, base="https://mock.example/v1", key="sk-test123456"):
    login(client, "admin", "test-admin-pwd")
    with get_db() as conn:
        set_setting(conn, "llm", {
            "enabled": True, "provider": "自定义", "api_base": base, "api_key": key,
            "model": "test-model", "temperature": 0.5, "max_tokens": 100, "system_prefix": "",
        })


def test_task_default_and_agent_lifecycle(client):
    _enable_llm(client)                     # 先启用 LLM，chat_enabled 应为 True
    entry, pwd = _import_one_student(client)
    login(client, entry, pwd)
    client.post("/api/auth/change-password", json={"old_password": pwd, "new_password": "agent-pwd-1"}, headers=XHR)

    # 题目要求默认内容可读
    t = client.get("/api/student/task").json()
    assert "设计智能体" in t["task"]["title"]
    assert "便民" in t["task"]["content"]
    assert t["agent"] is None and t["chat_enabled"] is True  # 上一步已启用 LLM

    # 必填缺失 → 400
    r = client.put("/api/student/agent", json={"name": "只有名字"}, headers=XHR)
    assert r.status_code == 400 and "必填" in r.json()["detail"]

    # 完整保存 → 200，且能读回
    r = client.put("/api/student/agent", json=AGENT_BODY, headers=XHR)
    assert r.status_code == 200 and r.json()["ok"] is True
    t = client.get("/api/student/task").json()
    assert t["agent"]["name"] == "垃圾分类小管家" and t["agent"]["status"] == "saved"

    # 再次保存 = 更新
    r = client.put("/api/student/agent", json={**AGENT_BODY, "name": "分类小管家2.0"}, headers=XHR)
    assert r.status_code == 200
    t = client.get("/api/student/task").json()
    assert t["agent"]["name"] == "分类小管家2.0"


def test_chat_mock_success_and_history(client):
    entry, pwd = _import_one_student(client)
    login(client, entry, pwd)
    r = client.put("/api/student/agent", json=AGENT_BODY, headers=XHR)
    assert r.status_code == 200, f"保存设计失败: {r.text}"

    calls = {}
    def fake_post(cfg, payload):
        calls["payload"] = payload
        return {"choices": [{"message": {"content": "剩饭剩菜属于厨余垃圾哦！"}}]}
    orig = llm_svc._post_chat
    llm_svc._post_chat = fake_post
    try:
        r = client.post("/api/student/agent/chat", json={"message": "剩饭剩菜是什么垃圾？"}, headers=XHR)
        assert r.status_code == 200, f"chat 失败: {r.text}"
        assert "厨余垃圾" in r.json()["reply"]
        # 系统提示词应包含学生的设计
        sys_msg = calls["payload"]["messages"][0]["content"]
        assert "垃圾分类小管家" in sys_msg and "社区垃圾投放点" in sys_msg
    finally:
        llm_svc._post_chat = orig

    # 历史已记录（user + assistant）
    t = client.get("/api/student/task").json()
    roles = [m["role"] for m in t["history"]]
    assert roles.count("user") >= 1 and roles.count("assistant") >= 1

    # 清空对话
    assert client.post("/api/student/agent/chat/clear", headers=XHR).status_code == 200
    t = client.get("/api/student/task").json()
    assert t["history"] == []


def test_chat_error_mapping_friendly(client):
    entry, pwd = _import_one_student(client)
    login(client, entry, pwd)
    client.put("/api/student/agent", json=AGENT_BODY, headers=XHR)

    def make_401(cfg, payload):
        raise urllib.error.HTTPError("https://mock", 401, "Unauthorized", {}, None)

    orig = llm_svc._post_chat
    llm_svc._post_chat = make_401
    try:
        r = client.post("/api/student/agent/chat", json={"message": "你好"}, headers=XHR)
        assert r.status_code == 200            # 以 200 + ok=False 返回，前端以气泡展示
        body = r.json()
        assert body["ok"] is False
        assert "API Key" in body["error"] and "老师" in body["error"]   # 友好提示
        assert "Unauthorized" not in body["error"]                       # 不泄露上游信息
    finally:
        llm_svc._post_chat = orig

    # 禁用 LLM → 提示未开放（先解除频率限制，便于连续对话测试）
    from app.routers import agent as agent_router
    orig_cooldown = agent_router.CHAT_COOLDOWN_SECONDS
    agent_router.CHAT_COOLDOWN_SECONDS = 0
    try:
        with get_db() as conn:
            set_setting(conn, "llm", {"enabled": False})
        r = client.post("/api/student/agent/chat", json={"message": "你好"}, headers=XHR)
        assert r.json()["ok"] is False and "老师" in r.json()["error"]
        with get_db() as conn:  # 恢复，避免影响其他测试
            set_setting(conn, "llm", {"enabled": True, "api_base": "https://mock.example/v1",
                                      "api_key": "sk-test", "model": "m"})
    finally:
        agent_router.CHAT_COOLDOWN_SECONDS = orig_cooldown


def test_admin_llm_config_key_never_leaks(client):
    login(client, "admin", "test-admin-pwd")
    r = client.put("/api/admin/llm", json={
        "enabled": True, "provider": "SiliconFlow 硅基流动",
        "api_base": "https://api.siliconflow.cn/v1", "api_key": "sk-secret-abcdef123456",
        "model": "Qwen/Qwen2.5-7B-Instruct", "temperature": 0.7, "max_tokens": 800,
        "system_prefix": "请用简体中文",
    }, headers=XHR)
    assert r.status_code == 200
    view = r.json()["llm"]
    assert view["api_key"] == ""                    # 明文永不返回
    assert "abc" not in json.dumps(view)            # 掩码不包含完整 key
    assert view["api_key_set"] is True and "*" in view["api_key_masked"]

    # GET 同样不泄露
    got = client.get("/api/admin/llm").json()["llm"]
    assert got["api_key"] == "" and got["api_key_set"] is True

    # 留空 key 再次保存 → 保持原 key（配置不丢失）
    r = client.put("/api/admin/llm", json={
        "enabled": True, "provider": "SiliconFlow 硅基流动",
        "api_base": "https://api.siliconflow.cn/v1", "api_key": "",
        "model": "Qwen/Qwen2.5-7B-Instruct", "temperature": 0.7, "max_tokens": 800,
    }, headers=XHR)
    assert r.json()["llm"]["api_key_set"] is True


def test_admin_task_edit(client):
    login(client, "admin", "test-admin-pwd")
    r = client.put("/api/admin/task", json={"title": "自定义题目", "content": "请设计一个帮助老人的智能体。"}, headers=XHR)
    assert r.status_code == 200
    # 学生端能读到新题目
    entry, pwd = _import_one_student(client)
    login(client, entry, pwd)
    t = client.get("/api/student/task").json()
    assert t["task"]["title"] == "自定义题目" and "老人" in t["task"]["content"]


def test_build_system_prompt_assembly():
    agent = {"name": "小智", "role": "导览员", "audience": "游客", "scenario": "图书馆",
             "problem": "找书难", "skills": "查询馆藏", "knowledge": "开馆时间 9:00",
             "tone": "温和", "welcome": "你好", "system_prefix": "统一前缀"}
    prompt = llm_svc.build_system_prompt(agent)
    assert prompt.startswith("统一前缀")
    for part in ("小智", "导览员", "游客", "图书馆", "找书难", "查询馆藏", "9:00", "温和"):
        assert part in prompt


def _setup_saved_agent(client, chat_rounds=2):
    """导入学生 + 保存设计 + 用 mock LLM 补足对话轮数，返回 (entry_no, pwd)。"""
    from app.routers import agent as agent_router
    _enable_llm(client)  # 自给自足：不依赖上游测试的 LLM 状态
    entry, pwd = _import_one_student(client)
    login(client, entry, pwd)
    assert client.put("/api/student/agent", json=AGENT_BODY, headers=XHR).status_code == 200
    orig = llm_svc._post_chat
    orig_cd = agent_router.CHAT_COOLDOWN_SECONDS
    llm_svc._post_chat = lambda cfg, payload: {"choices": [{"message": {"content": "好的，我来帮你。"}}]}
    agent_router.CHAT_COOLDOWN_SECONDS = 0
    try:
        for i in range(chat_rounds):
            r = client.post("/api/student/agent/chat", json={"message": f"测试问题 {i + 1}"}, headers=XHR)
            assert r.status_code == 200 and r.json().get("ok") is True, f"chat {i + 1}: {r.text}"
    finally:
        llm_svc._post_chat = orig
        agent_router.CHAT_COOLDOWN_SECONDS = orig_cd
    return entry, pwd


def test_agent_task_submit_flow(client):
    entry, pwd = _setup_saved_agent(client, chat_rounds=1)  # 只有 1 轮，低于门槛

    # 对话轮数不足 → 拒绝并提示
    r = client.post("/api/student/agent/submit", headers=XHR)
    assert r.status_code == 400 and "对话测试不足" in r.json()["detail"]

    # 补足轮数后提交成功
    from app.routers import agent as agent_router
    orig = llm_svc._post_chat
    orig_cd = agent_router.CHAT_COOLDOWN_SECONDS
    llm_svc._post_chat = lambda cfg, payload: {"choices": [{"message": {"content": "回复"}}]}
    agent_router.CHAT_COOLDOWN_SECONDS = 0
    try:
        r = client.post("/api/student/agent/chat", json={"message": "再问一个"}, headers=XHR)
        assert r.status_code == 200
    finally:
        llm_svc._post_chat = orig
        agent_router.CHAT_COOLDOWN_SECONDS = orig_cd
    r = client.post("/api/student/agent/submit", headers=XHR)
    assert r.status_code == 200 and r.json()["chat_rounds"] == 2

    # 已提交后重复提交 → 拒绝
    r = client.post("/api/student/agent/submit", headers=XHR)
    assert r.status_code == 400 and "已提交" in r.json()["detail"]

    # 撤回 → 可重新保存
    assert client.post("/api/student/agent/retract", headers=XHR).status_code == 200
    r = client.put("/api/student/agent", json={**AGENT_BODY, "name": "改名后的智能体"}, headers=XHR)
    assert r.status_code == 200


def test_agent_task_check_by_admin(client):
    entry, pwd = _setup_saved_agent(client, chat_rounds=2)
    login(client, entry, pwd)
    client.post("/api/student/agent/submit", headers=XHR)

    # 管理端列表：自动检测项齐全
    login(client, "admin", "test-admin-pwd")
    lst = client.get("/api/admin/agents").json()["items"]
    me = next(x for x in lst if x["entry_no"] == entry)
    assert me["agent_status"] == "submitted" and me["auto"]["all_ok"] is True
    assert me["check_status"] == "pending"

    # 详情含设计 + 完整对话记录
    d = client.get(f"/api/admin/agents/{me['student_id']}").json()
    assert d["agent"]["name"] == AGENT_BODY["name"]
    assert len(d["chats"]) >= 4  # 2 轮 user+assistant
    assert any(c["role"] == "assistant" for c in d["chats"])

    # 标记需修改 → 学生提交被锁（可撤回），改完重新提交
    r = client.put(f"/api/admin/agents/{me['student_id']}/check",
                   json={"check_status": "revise", "check_comment": "知识资料太薄，请补充"}, headers=XHR)
    assert r.status_code == 200
    login(client, entry, pwd)
    r = client.post("/api/student/agent/submit", headers=XHR)
    assert r.status_code == 400  # 已提交状态

    # 标记合格 → 任务锁定，撤回被拒
    login(client, "admin", "test-admin-pwd")
    r = client.put(f"/api/admin/agents/{me['student_id']}/check",
                   json={"check_status": "ok", "check_comment": "设计完整"}, headers=XHR)
    assert r.status_code == 200
    login(client, entry, pwd)
    r = client.post("/api/student/agent/retract", headers=XHR)
    assert r.status_code == 403 and "锁定" in r.json()["detail"]

    # 导出 CSV 包含该学生
    login(client, "admin", "test-admin-pwd")
    r = client.get("/api/admin/agents/export")
    assert r.status_code == 200 and "智能体测试生".encode("utf-8") in r.content


def test_agent_check_invalid_status(client):
    login(client, "admin", "test-admin-pwd")
    r = client.put("/api/admin/agents/999999/check", json={"check_status": "ok"}, headers=XHR)
    assert r.status_code == 404


def test_agent_submitted_and_locked_guards(client):
    """验证任务已提交或已检测合格锁定后，禁止未撤回直接修改设计、清空对话或继续对话。"""
    entry, pwd = _setup_saved_agent(client, chat_rounds=2)
    login(client, entry, pwd)
    assert client.post("/api/student/agent/submit", headers=XHR).status_code == 200

    # 已提交状态下：不可直接覆盖保存、不可清空对话、不可继续对话
    r = client.put("/api/student/agent", json={**AGENT_BODY, "name": "绕过撤回"}, headers=XHR)
    assert r.status_code == 400 and "撤回" in r.json()["detail"]
    r = client.post("/api/student/agent/chat/clear", headers=XHR)
    assert r.status_code == 400 and "已提交" in r.json()["detail"]

    # 管理端检测筛选与概览统计、设置含 task
    login(client, "admin", "test-admin-pwd")
    settings = client.get("/api/admin/settings").json()
    assert "task" in settings and settings["task"]["title"]
    ov = client.get("/api/admin/overview").json()
    assert ov["agent_stats"]["submitted"] >= 1

    pending_items = client.get("/api/admin/agents?check=pending").json()["items"]
    assert any(x["entry_no"] == entry for x in pending_items)
    me = next(x for x in pending_items if x["entry_no"] == entry)

    # 标记合格后：不可覆盖保存（403 锁定）
    client.put(f"/api/admin/agents/{me['student_id']}/check",
               json={"check_status": "ok", "check_comment": "通过"}, headers=XHR)
    ok_items = client.get("/api/admin/agents?check=ok").json()["items"]
    assert any(x["entry_no"] == entry for x in ok_items)

    login(client, entry, pwd)
    r = client.put("/api/student/agent", json={**AGENT_BODY, "name": "试图修改已锁定"}, headers=XHR)
    assert r.status_code == 403 and "锁定" in r.json()["detail"]



def test_normalize_base_url_routing():
    """任意粘贴形式都应路由到正确的完整请求地址（以 Step Plan 为例）。"""
    from app.services.llm import full_chat_url, normalize_base_url
    cases = [
        "https://api.stepfun.com/step_plan/v1",
        "https://api.stepfun.com/step_plan",
        "https://api.stepfun.com/step_plan/v1/chat/completions",
        "https://api.stepfun.com/step_plan/v1/messages",
        "https://api.stepfun.com/step_plan/v1/",
        "https://api.siliconflow.cn/v1/",
        "https://api.deepseek.com",
    ]
    for c in cases:
        assert full_chat_url(c) == "https://api.stepfun.com/step_plan/v1/chat/completions" \
            if "stepfun" in c else full_chat_url(c).endswith("/v1/chat/completions"), c
        assert normalize_base_url(c).endswith("/v1"), c
    assert full_chat_url("https://api.siliconflow.cn/v1") == "https://api.siliconflow.cn/v1/chat/completions"


def test_save_llm_stores_normalized_base(client):
    login(client, "admin", "test-admin-pwd")
    r = client.put("/api/admin/llm", json={
        "enabled": True, "provider": "自定义",
        "api_base": "https://api.stepfun.com/step_plan/v1/chat/completions",
        "api_key": "sk-abc12345", "model": "m", "temperature": 0.7, "max_tokens": 300,
    }, headers=XHR)
    assert r.status_code == 200
    got = client.get("/api/admin/llm").json()["llm"]
    assert got["api_base"] == "https://api.stepfun.com/step_plan/v1", "保存时应归一化掉完整请求路径"


def test_ai_generate_questions_mock(client):
    """AI 智能出题：mock LLM 返回带代码块的 JSON，应解析校验并剔除非法条目。"""
    from app.db import get_db, set_setting
    _enable_llm(client)
    login(client, "admin", "test-admin-pwd")
    reply = (
        "好的，以下是为您生成的题目：\n"
        "```json\n"
        "[{\"type\":\"single\",\"stem\":\"产生式表示法的基本形式是什么？\","
        "\"options\":[{\"key\":\"A\",\"text\":\"IF-THEN\"},{\"key\":\"B\",\"text\":\"ISA\"},"
        "{\"key\":\"C\",\"text\":\"AKO\"},{\"key\":\"D\",\"text\":\"Have\"}],"
        "\"answer\":[\"A\"],\"score\":2,\"topic\":\"产生式表示法\"},"
        "{\"type\":\"judge\",\"stem\":\"判断题干示例。\",\"options\":[],"
        "\"answer\":[\"A\"],\"score\":1,\"topic\":\"测试\"},"
        "{\"type\":\"single\",\"stem\":\"坏题（缺选项）。\",\"options\":[],"
        "\"answer\":[\"A\"],\"score\":2,\"topic\":\"坏题\"}"
        "]\n```"
    )
    orig = llm_svc._post_chat
    llm_svc._post_chat = lambda cfg, payload: {"choices": [{"message": {"content": reply}}]}
    try:
        r = client.post("/api/admin/questions/ai-generate",
                        json={"topic": "产生式表示法", "scene": "垃圾分类", "count": 3, "qtype": "mix"},
                        headers=XHR)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) == 2, "1 条坏题应被剔除"
        assert body["items"][0]["stem"].startswith("产生式")
        assert body["items"][1]["type"] == "judge"
        assert any("剔除" in e for e in body["errors"])
    finally:
        llm_svc._post_chat = orig

    # LLM 未配置 → 明确提示
    with get_db() as conn:
        set_setting(conn, "llm", {"enabled": False})
    r = client.post("/api/admin/questions/ai-generate",
                    json={"topic": "x", "count": 3, "qtype": "mix"}, headers=XHR)
    assert r.status_code == 400 and "智能体设置" in r.json()["detail"]
    with get_db() as conn:  # 恢复
        set_setting(conn, "llm", {"enabled": True, "api_base": "https://mock.example/v1",
                                  "api_key": "sk-test", "model": "m"})


def test_oj_exam_judge_mock_and_merged_ranking(client):
    """OJ 实操考试：学生提交 → mock 判题（Agent 回答 + 评分器）→ 合并排名。"""
    from app.db import get_db, set_setting
    import json as _json
    _enable_llm(client)
    entry, pwd = _setup_saved_agent(client, chat_rounds=2)

    # 启用实操考试（窗口全天开放）
    login(client, "admin", "test-admin-pwd")
    client.put("/api/admin/settings", json={"agent_exam": {
        "enabled": True, "start_at": "2026-01-01 00:00:00", "end_at": "2030-01-01 00:00:00",
        "quiz_weight": 50, "agent_weight": 50}}, headers=XHR)

    # 学生提交判题（mock 判题全链路：Agent 回答 + 评分器）
    login(client, entry, pwd)
    orig_post = llm_svc._post_chat
    def fake_post(cfg, payload):
        first = str((payload.get("messages") or [{}])[0].get("content", ""))
        if "评分规则" in first:
            return {"choices": [{"message": {"content": '{"score": 18, "comment": "要点覆盖良好"}'}}]}
        return {"choices": [{"message": {"content": "您好，这里是图书馆导览员，开馆时间8:00-18:00，可借5册。"}}]}
    llm_svc._post_chat = fake_post
    r = client.post("/api/student/agent-exam/submit", headers=XHR)
    assert r.status_code == 200 and r.json()["status"] == "running", r.text
    r2 = client.post("/api/student/agent-exam/submit", headers=XHR)
    assert r2.json().get("status") == "running"  # 重复提交去重

    # 等待后台线程完成（mock 下毫秒级）
    import time
    state = None
    for _ in range(50):
        state = client.get("/api/student/agent-exam").json()
        if state["result"]["status"] != "running":
            break
        time.sleep(0.2)
    assert state["result"]["status"] == "done", state["result"]
    assert state["result"]["score"] > 0
    assert len(state["result"]["detail"]) == 9  # 3 道考题 × 3 个标准问题
    llm_svc._post_chat = orig_post  # 判题完成后恢复真实调用
    # 学生侧题目不含参考要点
    for q in state["questions"]:
        assert all("points" not in t for t in q["test_questions"])

    # 合并排名：agent_score 与 merged 出现
    login(client, "admin", "test-admin-pwd")
    rk = client.get("/api/admin/ranking?group=high").json()
    me = next(x for x in rk["items"] if x["entry_no"] == entry)
    assert me["agent_score"] is not None and me["merged"] is not None and me["merged"] > 0

    # 管理端判题记录 + 重判
    res = client.get("/api/admin/agent-exam/results").json()
    mine = next(x for x in res["items"] if x["entry_no"] == entry)
    assert mine["status"] == "done"
    r = client.post(f"/api/admin/agent-exam/results/{mine['student_id']}/rejudge", headers=XHR)
    assert r.status_code == 200

    # LLM 未配置 → 有完整设计的学生提交也会被拒（判题服务未就绪）
    with get_db() as conn:
        set_setting(conn, "llm", {"enabled": False})
    entry2, pwd2 = _import_one_student(client)
    login(client, entry2, pwd2)
    assert client.put("/api/student/agent", json=AGENT_BODY, headers=XHR).status_code == 200
    r = client.post("/api/student/agent-exam/submit", headers=XHR)
    assert r.status_code == 400 and "判题服务未就绪" in r.json()["detail"]
    with get_db() as conn:
        set_setting(conn, "llm", {"enabled": True, "api_base": "https://mock.example/v1",
                                  "api_key": "sk-test", "model": "m"})
