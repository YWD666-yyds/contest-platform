"""学生名单导入测试（本届仅开放小学高段组：4—6 年级，3 年级选报）。"""
import csv
import io

from app.services.importer import import_students


def _csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["姓名", "学校", "年级", "组别", "指导教师", "作品名称"])
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def test_import_high_grades_ok():
    r = import_students(_csv([
        ["测试甲", "学校A", "四年级", "", "王老师", ""],
        ["测试乙", "学校A", "五年级", "", "王老师", ""],
        ["测试丙", "学校A", "六年级", "", "王老师", ""],
        ["测试丁", "学校A", "三年级", "高段组", "李老师", ""],
    ]))
    assert r["created"] == 4 and r["errors"] == []
    groups = {row[0]: row[2] for row in csv.reader(io.StringIO(r["accounts_csv"])) if row[0] != "姓名"}
    assert all(g == "小学高段组" for g in groups.values())


def test_import_rejects_other_grades():
    r = import_students(_csv([
        ["测试低段", "学校A", "二年级", "", "", ""],      # 低段组不接收
        ["测试中学", "学校A", "初一", "", "", ""],         # 中学组不接收
        ["测试三默认", "学校A", "三年级", "", "", ""],     # 3 年级未选报高段组 → 拒绝
        ["测试高中", "学校A", "高一", "", "", ""],         # 高中不接收
    ]))
    assert r["created"] == 0 and len(r["errors"]) == 4
    assert all("仅开放小学高段组" in e for e in r["errors"])


def test_import_duplicates():
    r1 = import_students(_csv([["测试重复", "学校D", "五年级", "", "", ""]]))
    assert r1["created"] == 1
    r2 = import_students(_csv([["测试重复", "学校D", "五年级", "", "", ""]]))
    assert r2["created"] == 0 and any("重复报名" in e for e in r2["errors"])


def test_entry_no_prefix_sequence():
    r = import_students(_csv([
        ["测试序1", "学校C", "四年级", "", "", ""],
        ["测试序2", "学校C", "六年级", "", "", ""],
    ]))
    rows = list(csv.reader(io.StringIO(r["accounts_csv"])))[1:]
    nums = [row[3] for row in rows]
    assert all(n.startswith("H") for n in nums) and nums[0] != nums[1]


def test_gb2312_decoding():
    raw = "姓名,学校,年级\n测辛,学校D,五年级\n".encode("gb18030")
    r = import_students(raw)
    assert r["created"] == 1
