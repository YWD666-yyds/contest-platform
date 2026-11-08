"""判分与排名。

  创意构思 → 主题契合 → 设计表达 → 创作过程。
- 小学高段组：得分高者列前；同分作答用时短者列前；
  再同分比较作答完整度。
"""
import json

from ..db import get_db

DIMS = ["s_theme", "s_creative", "s_expression", "s_process"]
# 规则 7.2 同分比较优先级：创意构思 → 主题契合 → 设计表达 → 创作过程
TIE_BREAK = ["s_creative", "s_theme", "s_expression", "s_process"]


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
