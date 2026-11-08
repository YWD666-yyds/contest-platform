"""学生名单批量导入（CSV）。

模板列：姓名,学校,年级,组别(可选,仅三年级需填写),指导教师,作品名称(可选)
- 年级自动映射组别：1-3 年级→小学低段组；3 年级可经「组别」列选报高段组；4-6→高段组；7-12→中学组。
- 系统生成参赛编号（L/H/M + 四位序号）与随机初始密码，首登强制改密。
- 返回逐行错误报告与一次性可下载的账号单 CSV。
"""
import csv
import io
import secrets

from .. import config
from ..db import get_db
from ..security import hash_password

GRADE_MAP = {
    "一年级": 1, "二年级": 2, "三年级": 3, "四年级": 4, "五年级": 5, "六年级": 6,
    "1年级": 1, "2年级": 2, "3年级": 3, "4年级": 4, "5年级": 5, "6年级": 6,
    "七年级": 7, "八年级": 8, "九年级": 9, "7年级": 7, "8年级": 8, "9年级": 9,
    "初一": 7, "初二": 8, "初三": 9,
    "高一": 10, "高二": 11, "高三": 12,
    "中职一年级": 10, "中职二年级": 11, "中职三年级": 12,
}

GROUP_ALIAS = {
    "低段": "low", "低段组": "low", "小学低段": "low", "小学低段组": "low",
    "高段": "high", "高段组": "high", "小学高段": "high", "小学高段组": "high",
    "中学": "middle", "中学组": "middle", "初中": "middle", "高中": "middle",
}

CSV_COLUMNS = ["姓名", "学校", "年级", "组别", "指导教师", "作品名称"]


def _resolve_group(grade_no: int, group_text: str) -> str | None:
    """本届仅开放小学高段组：4—6 年级直接录取；3 年级须在「组别」列明确选报高段组；其余年级不接收。"""
    if grade_no == 3:
        return "high" if GROUP_ALIAS.get(group_text.strip()) == "high" else None
    if 4 <= grade_no <= 6:
        return "high"
    return None


def parse_grade(text: str) -> int | None:
    t = (text or "").strip()
    if t in GRADE_MAP:
        return GRADE_MAP[t]
    if t.isdigit() and 1 <= int(t) <= 12:
        return int(t)
    return None


def next_entry_no(conn, group_code: str) -> str:
    prefix = config.GROUP_ENTRY_PREFIX[group_code]
    rows = conn.execute(
        "SELECT entry_no FROM students WHERE entry_no LIKE ?", (prefix + "%",)
    ).fetchall()
    max_seq = 0
    for r in rows:
        suffix = r["entry_no"][len(prefix):]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:04d}"


def import_students(csv_bytes: bytes) -> dict:
    """导入 CSV，返回 {created, errors, accounts_csv, skipped}。"""
    text = _decode(csv_bytes)
    errors, accounts, created = [], [], 0
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {"created": 0, "errors": ["文件为空"], "accounts_csv": "", "skipped": 0}
    header = [h.strip().lstrip("\ufeff") for h in rows[0]]
    col_idx = {c: header.index(c) for c in CSV_COLUMNS if c in header}
    if "姓名" not in col_idx or "学校" not in col_idx or "年级" not in col_idx:
        return {"created": 0, "errors": [f"表头缺少必需列（需要：{'、'.join(CSV_COLUMNS[:3])}）"], "accounts_csv": "", "skipped": 0}

    with get_db() as conn:
        existing = {(r["name"], r["school"]) for r in conn.execute("SELECT name,school FROM students")}
        for ln, raw in enumerate(rows[1:], start=2):
            if not raw or not any(c.strip() for c in raw):
                continue
            def cell(col):
                i = col_idx.get(col)
                return raw[i].strip() if i is not None and i < len(raw) else ""
            name, school = cell("姓名"), cell("学校")
            grade_text, group_text = cell("年级"), cell("组别")
            teacher, work_title = cell("指导教师"), cell("作品名称")
            if not name or not school:
                errors.append(f"第{ln}行：姓名或学校为空"); continue
            grade_no = parse_grade(grade_text)
            if grade_no is None:
                errors.append(f"第{ln}行（{name}）：无法识别年级「{grade_text}」"); continue
            group = _resolve_group(grade_no, group_text)
            if group is None:
                errors.append(f"第{ln}行（{name}）：本届仅开放小学高段组（4—6 年级；3 年级须在组别列注明「高段组」），不接收{grade_text}"); continue
            if (name, school) in existing:
                errors.append(f"第{ln}行（{name}）：该姓名+学校已存在，疑似重复报名"); continue
            entry_no = next_entry_no(conn, group)
            init_pwd = secrets.token_hex(3)  # 6 位十六进制，如 a3f9c2
            cur = conn.execute(
                "INSERT INTO users(username,password_hash,role,must_change_pwd) VALUES(?,?,?,1)",
                (entry_no, hash_password(init_pwd), "student"),
            )
            conn.execute(
                "INSERT INTO students(user_id,entry_no,name,school,grade,grade_no,group_code,teacher_name,work_title) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (cur.lastrowid, entry_no, name, school, grade_text, grade_no, group, teacher, work_title),
            )
            existing.add((name, school))
            accounts.append([name, school, config.GROUP_NAMES[group], entry_no, init_pwd])
            created += 1

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["姓名", "学校", "组别", "参赛编号", "初始密码"])
    writer.writerows(accounts)
    return {"created": created, "errors": errors, "accounts_csv": out.getvalue(), "skipped": len(rows) - 1 - created - len(errors)}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")
