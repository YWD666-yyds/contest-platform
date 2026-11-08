"""公众路由：首页信息 / 公告 / 成绩公示查询。"""
import json

from fastapi import APIRouter, HTTPException

from .. import config
from ..db import get_db, get_setting
from ..services import grading

router = APIRouter(prefix="/api/public", tags=["public"])


def _site_merged(conn):
    site = dict(config.SITE_DEFAULT)
    site.update(get_setting(conn, "site") or {})
    return site


@router.get("/home")
def home():
    with get_db() as conn:
        site = _site_merged(conn)
        subs = get_setting(conn, "submission")
        exams = get_setting(conn, "exams")
        publish = get_setting(conn, "publish")
        stats = {}
        for g in config.GROUP_NAMES:
            row = conn.execute(
                "SELECT COUNT(*) AS n, SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS s "
                "FROM students WHERE group_code=?", (g,)
            ).fetchone()
            submitted_cnt = row["s"] or 0
            if g != "low":
                submitted_cnt = conn.execute(
                    "SELECT COUNT(*) AS n FROM attempts WHERE group_code=? AND status='submitted'", (g,)
                ).fetchone()["n"] or 0
            stats[g] = {"total": row["n"] or 0, "submitted": submitted_cnt}
        ann = [dict(r) for r in conn.execute(
            "SELECT id,title,body,pinned,created_at FROM announcements ORDER BY pinned DESC, id DESC LIMIT 10"
        )]
    return {"site": site, "submission": subs, "exams": exams, "publish": publish,
            "stats": stats, "announcements": ann,
            "groups": config.GROUP_NAMES, "theme_directions": THEME_DIRECTIONS}


THEME_DIRECTIONS = [
    {"icon": "🚦", "title": "城市道路智能设施",
     "items": ["感应路灯", "智慧斑马线", "智能停车引导装置", "道路积水提示装置"]},
    {"icon": "🏘️", "title": "社区便民智能装置",
     "items": ["智能垃圾分类站", "社区快递取件提示装置", "独居老人关怀提醒装置", "无障碍通道提示装置"]},
    {"icon": "🚏", "title": "公共服务智能设备",
     "items": ["智能公交站台", "智能售卖机", "图书馆智能导览", "景区智能导览设施"]},
    {"icon": "🏫", "title": "校园与家庭智能服务",
     "items": ["校园安全提示", "教室智能照明", "家庭节能助手"]},
]


@router.get("/announcements")
def announcements():
    with get_db() as conn:
        ann = [dict(r) for r in conn.execute(
            "SELECT id,title,body,pinned,created_at FROM announcements ORDER BY pinned DESC, id DESC LIMIT 50"
        )]
    return {"list": ann}


def _mask_name(name: str) -> str:
    if len(name) <= 1:
        return name + "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


@router.get("/scores")
def public_scores(group: str, entry_no: str = ""):
    """成绩公示：按组别返回排名（可脱敏），或按参赛编号查询个人。"""
    if group not in config.GROUP_NAMES:
        raise HTTPException(400, "参数错误")
    with get_db() as conn:
        publish = get_setting(conn, "publish")
        if not publish.get(group):
            raise HTTPException(403, "该组别成绩尚未公布")
        if group == "low":
            rows = grading.low_group_ranking(conn)
            fields = ["rank", "entry_no", "name", "school", "work_title", "total",
                      "s_theme", "s_creative", "s_expression", "s_process", "judge_count"]
        else:
            rows = grading.quiz_ranking(conn, group)
            fields = ["rank", "entry_no", "name", "school", "grade", "score", "duration_seconds"]
        if publish.get("mask_names", True):
            for r in rows:
                r["name"] = _mask_name(r["name"])
        rows = [{k: r.get(k) for k in fields} for r in rows]
        mine = None
        if entry_no.strip():
            for r in rows:
                if r["entry_no"].upper() == entry_no.strip().upper():
                    mine = r
                    break
            if mine is None:
                raise HTTPException(404, "未找到该参赛编号的公示成绩，请核对编号或联系组委会")
        quota = (get_setting(conn, "quota") or {}).get(group, 0)
    return {"list": rows, "mine": mine, "quota": quota, "group_name": config.GROUP_NAMES[group],
            "mask": publish.get("mask_names", True)}


@router.get("/exam-schedule")
def exam_schedule():
    """公众可见的考试安排（不含题目）。"""
    with get_db() as conn:
        return {"exams": get_setting(conn, "exams"), "groups": config.GROUP_NAMES}
