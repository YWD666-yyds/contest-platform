"""OJ 实操考试自动判题服务。

流程（后台线程执行）：
1. 取学生已保存的智能体配置（知识库/角色/语气即学生的"作答"）
2. 对每道启用考题的每个标准问题：用学生 Agent 配置生成回答
3. 再用评分模型把回答与参考答案要点对比打分（允许部分得分，不要求逐字一致）
4. 汇总分并落库；任何失败以 error 状态+友好信息呈现
"""
import json
import re
import threading

from ..db import get_db, get_setting
from ..utils import now_str
from . import llm as llm_svc

JUDGE_SYSTEM = (
    "你是智能体比赛的自动评分器。评分规则：将学生的智能体回答与参考答案要点对比，"
    "按覆盖程度给分——要点覆盖即给分，允许部分得分，表述不必与参考答案逐字一致；"
    "回答切题但遗漏部分要点给部分分；答非所问、编造知识或明显错误给 0 分。"
    "只输出 JSON：{\"score\": 数字, \"comment\": \"一句话评语\"}，不要其他内容。"
)


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    lo, hi = text.find("{"), text.rfind("}")
    if lo == -1 or hi <= lo:
        raise ValueError("no json")
    return json.loads(text[lo:hi + 1])


def _judge_one(agent_cfg: dict, cfg: dict, item: dict) -> dict:
    """运行学生 Agent 回答一道标准问题，再用评分器打分。"""
    reply = llm_svc.chat(agent_cfg, cfg, [], item["q"])
    prompt = (
        f"测试问题：{item['q']}\n"
        f"参考答案要点：{item['points']}\n"
        f"学生智能体的实际回答：{reply}\n"
        f"满分：{item['score']} 分\n"
        f"请按评分规则输出 JSON。"
    )
    raw = llm_svc.chat({"name": "评分器", "system_prefix": JUDGE_SYSTEM}, cfg, [], prompt)
    try:
        verdict = _extract_json(raw)
        score = max(0.0, min(float(verdict.get("score", 0)), float(item["score"])))
        comment = str(verdict.get("comment", ""))[:200]
    except Exception:
        # 评分器输出异常：保守给一半分并注明，避免误伤学生
        score = round(float(item["score"]) / 2, 1)
        comment = "评分器输出异常，按半分保守处理：" + raw[:80]
    return {"q": item["q"], "agent_reply": reply[:1000], "score": round(score, 1),
            "max": item["score"], "comment": comment}


def _run(student_id: int):
    try:
        with get_db() as conn:
            agent = conn.execute("SELECT * FROM student_agents WHERE student_id=?", (student_id,)).fetchone()
            cfg = dict(get_setting(conn, "llm") or {})
            questions = [dict(r) for r in conn.execute(
                "SELECT * FROM agent_exam_questions WHERE enabled=1 ORDER BY id")]
            if not questions:
                raise RuntimeError("暂无启用的实操考题")
            conn.execute("UPDATE agent_judge_results SET status='running', error=NULL WHERE student_id=?",
                         (student_id,))
        if not agent or agent["status"] == "draft":
            raise RuntimeError("学生尚未保存智能体设计")
        agent_cfg = dict(agent)

        detail, total, max_total = [], 0.0, 0.0
        for qrow in questions:
            items = json.loads(qrow["test_questions"] or "[]")
            max_total += float(qrow["total_score"])
            for item in items:
                item["score"] = float(item.get("score", 0))
                item.setdefault("points", "")
                item.setdefault("q", "")
                r = _judge_one(agent_cfg, cfg, item)
                r["exam_title"] = qrow["title"]
                detail.append(r)
                total += r["score"]
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_judge_results SET status='done', detail=?, score=?, judged_at=?, error=NULL "
                "WHERE student_id=?",
                (json.dumps(detail, ensure_ascii=False), round(total, 1), now_str(), student_id))
    except Exception as e:
        msg = str(e)
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE agent_judge_results SET status='error', error=?, judged_at=? WHERE student_id=?",
                    (msg[:300], now_str(), student_id))
        except Exception:
            pass


def start_judging(student_id: int):
    """提交判题：写入 pending 记录并启动后台线程。"""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO agent_judge_results(student_id,status,detail) VALUES(?,'running','[]') "
            "ON CONFLICT(student_id) DO UPDATE SET status='running', detail='[]', score=NULL, error=NULL",
            (student_id,))
    t = threading.Thread(target=_run, args=(student_id,), daemon=True)
    t.start()
