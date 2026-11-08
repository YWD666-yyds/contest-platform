"""判分与排名规则测试（规则 7.2 / 7.3 / 7.6）。"""
from app.db import get_db, init_db
from app.services.grading import grade_attempt, quiz_ranking


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
