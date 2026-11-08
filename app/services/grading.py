"""判分与排名。

- 低段组（规则 7.2）：评委四维平均分（保留两位小数），同分依次比较
  创意构思 → 主题契合 → 设计表达 → 创作过程。
- 高段/中学组（规则 7.3、7.6）：得分高者列前；同分作答用时短者列前；
  再同分比较作答完整度。
"""
import json

from ..db import get_db

DIMS = ["s_theme", "s_creative", "s_expression", "s_process"]
# 规则 7.2 同分比较优先级：创意构思 → 主题契合 → 设计表达 → 创作过程
TIE_BREAK = ["s_creative", "s_theme", "s_expression", "s_process"]


def low_group_ranking(conn) -> list[dict]:
    students = conn.execute(
        "SELECT * FROM students WHERE group_code='low' AND status='submitted' AND disqualified=0"
    ).fetchall()
    rows = []
    for st in students:
        scores = conn.execute(
            "SELECT s_theme,s_creative,s_expression,s_process,comment,created_at FROM scores WHERE student_id=?",
            (st["id"],),
        ).fetchall()
        if not scores:
            continue  # 尚无评委评分的作品不入排名（评审中）
        n = len(scores)
        avg = {d: round(sum(s[d] for s in scores) / n + 1e-9, 2) for d in DIMS}
        total = round(sum(avg.values()) + 1e-9, 2)
        rows.append({
            "student_id": st["id"], "entry_no": st["entry_no"], "name": st["name"],
            "school": st["school"], "work_title": st["work_title"],
            "judge_count": n, **avg, "total": total, "comment": scores[-1]["comment"],
        })
    # 同分依次比较：创意构思 → 主题契合 → 设计表达 → 创作过程 → 提交时间
    rows.sort(key=lambda r: (-r["total"], -r["s_creative"], -r["s_theme"],
                             -r["s_expression"], -r["s_process"], r["entry_no"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def quiz_ranking(conn, group_code: str) -> list[dict]:
    students = conn.execute(
        "SELECT s.*, a.score, a.duration_seconds, a.submitted_at, a.answers, "
        "a.status AS attempt_status, a.suspicious_events "
        "FROM students s LEFT JOIN attempts a ON a.student_id=s.id "
        "WHERE s.group_code=? AND s.disqualified=0",
        (group_code,),
    ).fetchall()
    rows = []
    for st in students:
        if st["attempt_status"] != "submitted" or st["score"] is None:
            continue
        try:
            answered = len(json.loads(st["answers"] or "{}"))
        except Exception:
            answered = 0
        rows.append({
            "student_id": st["id"], "entry_no": st["entry_no"], "name": st["name"],
            "school": st["school"], "grade": st["grade"],
            "score": round(st["score"] + 1e-9, 2),
            "duration_seconds": st["duration_seconds"] or 0,
            "answered": answered,
            "submitted_at": st["submitted_at"],
            "suspicious_events": st["suspicious_events"],
        })
    rows.sort(key=lambda r: (-r["score"], r["duration_seconds"], -r["answered"], r["submitted_at"] or ""))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def grade_attempt(answers: dict, questions: list[dict]) -> tuple[float, list[dict], int]:
    """answers: {qid: [key,...]}；questions: [{id, answer(list), score}]。
    返回 (总分, 明细列表, 答题数)。多选题全对方可得分。"""
    total, detail, answered = 0.0, [], 0
    for q in questions:
        picked = answers.get(str(q["id"])) or []
        picked = sorted({str(p).upper() for p in picked})
        correct_keys = sorted(str(a).upper() for a in q["answer"])
        is_correct = bool(picked) and picked == correct_keys
        if picked:
            answered += 1
        if is_correct:
            total += float(q["score"])
        detail.append({"qid": q["id"], "picked": picked, "correct": is_correct})
    return round(total + 1e-9, 2), detail, answered
