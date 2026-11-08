"""判分与排名规则测试（规则 7.2 / 7.3 / 7.6）。"""
from app.db import get_db, init_db
from app.services.grading import grade_attempt, low_group_ranking, quiz_ranking


def test_grade_attempt_scoring():
    questions = [
        {"id": 1, "answer": ["A"], "score": 2},
        {"id": 2, "answer": ["A", "C"], "score": 3},
        {"id": 3, "answer": ["B"], "score": 1},
    ]
    answers = {"1": ["a"], "2": ["C", "A"], "3": ["A"]}  # 大小写与顺序无关
    score, detail, answered = grade_attempt(answers, questions)
    assert score == 5.0            # 第1、2题对，第3题错
    assert answered == 3
    assert [d["correct"] for d in detail] == [True, True, False]


def test_grade_attempt_multiple_all_or_nothing():
    questions = [{"id": 1, "answer": ["A", "B", "D"], "score": 3}]
    score, _, _ = grade_attempt({"1": ["A", "B"]}, questions)   # 少选不得分
    assert score == 0.0
    score, _, _ = grade_attempt({"1": ["A", "B", "D"]}, questions)
    assert score == 3.0


def _seed_low_student(conn, entry_no, name, status="submitted", disqualified=0, school="测试学校"):
    cur = conn.execute(
        "INSERT INTO users(username,password_hash,role) VALUES(?,?, 'student')",
        (entry_no, "x"),
    )
    conn.execute(
        "INSERT INTO students(user_id,entry_no,name,school,grade,grade_no,group_code,status,disqualified) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (cur.lastrowid, entry_no, name, school, "三年级", 3, "low", status, disqualified),
    )
    return conn.execute("SELECT id FROM students WHERE entry_no=?", (entry_no,)).fetchone()["id"]


def _seed_judge(conn, username):
    cur = conn.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,'judge')", (username, "x"))
    return cur.lastrowid


def _score(conn, sid, jid, theme, creative, expr, process):
    conn.execute(
        "INSERT INTO scores(student_id,judge_id,s_theme,s_creative,s_expression,s_process,total,comment) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (sid, jid, theme, creative, expr, process, theme + creative + expr + process, ""),
    )


def test_low_ranking_average_and_tie_break():
    """两位评委平均分；总分相同按 创意构思→主题契合→设计表达→创作过程 排序（规则 7.2）。"""
    init_db()
    with get_db() as conn:
        # 清理本测试数据（幂等）
        conn.execute("DELETE FROM scores WHERE student_id IN (SELECT id FROM students WHERE school='测试学校T')")
        conn.execute("DELETE FROM users WHERE role='student' AND username LIKE 'LT%'")
        conn.execute("DELETE FROM students WHERE school='测试学校T'")
        conn.execute("DELETE FROM users WHERE username LIKE 'JT%'")

        j1 = _seed_judge(conn, "JT1")
        j2 = _seed_judge(conn, "JT2")
        # A 与 B 总分均为 50，但 A 创意构思 20 > B 创意构思 15 → A 列前
        a = _seed_low_student(conn, "LTA01", "甲", school="测试学校T")
        b = _seed_low_student(conn, "LTA02", "乙", school="测试学校T")
        c = _seed_low_student(conn, "LTA03", "丙", school="测试学校T")  # 总分更高，第一
        for j in (j1, j2):
            _score(conn, a, j, 10, 20, 10, 10)   # 50
            _score(conn, b, j, 15, 15, 12, 8)    # 50
            _score(conn, c, j, 20, 20, 20, 15)   # 75
        rows = low_group_ranking(conn)
        rows = [r for r in rows if r["school"] == "测试学校T"]
        assert [r["entry_no"] for r in rows] == ["LTA03", "LTA01", "LTA02"]
        assert rows[0]["total"] == 75.0
        assert rows[1]["s_theme"] == 10.0 and rows[1]["judge_count"] == 2


def test_quiz_ranking_score_then_duration():
    """得分高者列前；同分用时短者列前（规则 7.3）。"""
    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM attempts WHERE group_code='middle'")
        conn.execute("DELETE FROM users WHERE role='student' AND username LIKE 'MT%'")
        conn.execute("DELETE FROM students WHERE school='测试学校Q'")
        import json
        for entry, score, dur in [("MTA01", 10, 300), ("MTA02", 12, 900), ("MTA03", 12, 600), ("MTA04", 8, 100)]:
            cur = conn.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,'student')", (entry, "x"))
            conn.execute(
                "INSERT INTO students(user_id,entry_no,name,school,grade,grade_no,group_code,status) "
                "VALUES(?,?,?,?,?,?,'middle','submitted')",
                (cur.lastrowid, entry, entry, "测试学校Q", "初一", 7))
            sid = conn.execute("SELECT id FROM students WHERE entry_no=?", (entry,)).fetchone()["id"]
            conn.execute(
                "INSERT INTO attempts(student_id,group_code,question_order,option_order,started_at,deadline,"
                "answers,score,duration_seconds,status,submitted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (sid, "middle", "[]", "{}", "2026-01-01 09:00:00", "2026-01-01 09:40:00",
                 json.dumps({"1": ["A"]}), score, dur, "submitted", "2026-01-01 09:30:00"))
        rows = [r for r in quiz_ranking(conn, "middle") if r["school"] == "测试学校Q"]
        assert [r["entry_no"] for r in rows] == ["MTA03", "MTA02", "MTA01", "MTA04"]
