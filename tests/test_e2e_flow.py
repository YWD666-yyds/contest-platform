"""端到端流程测试：管理导入 → 低段组提交 → 评审 → 考试 → 公示。"""
import csv
import io
import json

from app.db import get_db, get_setting, set_setting
from tests.conftest import login, make_jpeg, make_png

XHR = {"X-Requested-With": "XMLHttpRequest"}


def test_full_contest_flow(client):
    # ---------- 0. 管理员登录 ----------
    admin = login(client, "admin", "test-admin-pwd")
    assert admin["role"] == "admin"

    # ---------- 1. 批量导入 ----------
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["姓名", "学校", "年级", "组别", "指导教师", "作品名称"])
    w.writerow(["端到端甲", "E2E学校", "五年级", "", "指导甲", ""])
    w.writerow(["端到端乙", "E2E学校", "六年级", "", "指导甲", ""])
    r = client.post("/api/admin/students/import", files={"file": ("s.csv", buf.getvalue().encode("utf-8-sig"), "text/csv")}, headers=XHR)
    assert r.status_code == 200, r.text
    rows = list(csv.reader(io.StringIO(r.json()["accounts_csv"])))[1:]
    by_name = {row[0]: row for row in rows}
    high_no, high_pwd = by_name["端到端乙"][3], by_name["端到端乙"][4]
    assert high_no.startswith("H")

    # ---------- 2/3. 低段组作品与评审流程：本届不开放，略 ----------

    # ---------- 4. 高段组考试 ----------
    with get_db() as conn:
        from app.utils import now_str
        from datetime import datetime, timedelta
        now = datetime.now()
        set_setting(conn, "exams", {"high": {
            "enabled": True, "start_at": (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
            "end_at": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": 40, "show_score_after": True, "allow_resubmit": True},
            "middle": {"enabled": False, "start_at": "", "end_at": "", "duration_minutes": 40}})

    login(client, high_no, high_pwd)
    client.post("/api/auth/change-password", json={"old_password": high_pwd, "new_password": "student-pwd-2"}, headers=XHR)
    r = client.post("/api/exam/start", headers=XHR)
    assert r.status_code == 200, r.text
    state = r.json()
    qs = state["questions"]
    assert len(qs) == 16, "高段组题库应有 16 题"
    # 题目不含答案字段
    assert all("answer" not in q for q in qs)

    # 保存部分答案
    ans = {str(qs[0]["id"]): ["A"], str(qs[1]["id"]): ["B"]}
    r = client.post("/api/exam/save", json={"answers": ans}, headers=XHR)
    assert r.status_code == 200
    # 非法选项键被清洗
    r = client.post("/api/exam/save", json={"answers": {str(qs[2]["id"]): ["Z"], "99999": ["A"]}}, headers=XHR)
    assert r.json()["saved_count"] == 0

    # 提交全部正确答案（按题目实际选项无法直接得知正确项 → 用 judge 帐号查题库答案再作答）
    login(client, "admin", "test-admin-pwd")
    bank = client.get("/api/admin/questions?group=high").json()["items"]
    correct = {str(q["id"]): q["answer"] for q in bank}
    login(client, high_no, "student-pwd-2")
    r = client.post("/api/exam/submit", json={"answers": correct}, headers=XHR)
    assert r.status_code == 200
    exam_score = r.json()["score"]
    assert exam_score == sum(q["score"] for q in bank), "全对应得满分"

    # 已交卷后 show_score_after → 状态 submitted
    state = client.get("/api/exam/state").json()
    assert state["status"] == "submitted"

    # ---------- 5. 管理端排名 + 公示 ----------
    login(client, "admin", "test-admin-pwd")
    r = client.get("/api/admin/ranking?group=high")
    assert r.status_code == 200
    assert any(x["entry_no"] == high_no and x["score"] == exam_score for x in r.json()["items"])

    # 公示未开启 → 403
    assert client.get("/api/public/scores?group=high").status_code == 403
    client.put("/api/admin/settings", json={"publish": {"low": False, "high": True, "middle": False, "mask_names": True}}, headers=XHR)
    r = client.get("/api/public/scores?group=high")
    assert r.status_code == 200
    lst = r.json()["list"]
    mine = next(x for x in lst if x["entry_no"] == high_no)
    assert mine["name"] != "端到端乙", "公示名单应脱敏"
    r = client.get(f"/api/public/scores?group=high&entry_no={high_no}")
    assert r.status_code == 200 and r.json()["mine"]["score"] == exam_score

    # ---------- 6. 导出与日志 ----------
    r = client.get("/api/admin/students/export")
    assert r.status_code == 200 and "端到端乙".encode("utf-8") in r.content
    assert client.get("/api/admin/logs").status_code == 200
