"""平台配置：路径、环境变量、常量。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CONTEST_DATA_DIR", BASE_DIR / "data"))
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "contest.db"

for _d in (DATA_DIR, BACKUP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---- 会话 / 安全 ----
SESSION_COOKIE = "contest_session"
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "72"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"   # HTTPS 部署时置 1
ADMIN_INITIAL_PASSWORD = os.environ.get("ADMIN_INITIAL_PASSWORD", "admin@2026")

# ---- 业务常量（依据竞赛规则 4.2.1）----
DESIGN_MIN_W, DESIGN_MIN_H = 1920, 1080    # ≥ 1920×1080
# 考试：服务端超时宽限（秒），宽限期内允许收尾提交/自动收卷
EXAM_GRACE_SECONDS = 60
EXAM_AUTOSAVE_INTERVAL = 20                # 前端自动保存间隔（秒）

# ---- 登录保护 ----
LOGIN_MAX_FAILS = 8
LOGIN_LOCK_MINUTES = 15

SITE_DEFAULT = {
    "title": "2026年广东省青少年创新思维及科技实践大赛 · 人工智能应用赛项",
    "subtitle": "市级初赛服务平台",
    "theme": "智绘城市 · AI便民智慧设施",
    "banner": "",
    "schedule": (
        "报名及作品提交：线上进行，截止时间以本站首页提示为准\n"
        "线上答题（小学高段组）：以本站考试安排为准\n"
        "初赛评审：2026年12月中旬\n"
        "成绩公示：2026年12月下旬（本站「成绩公示」栏目）"
    ),
    "contact": "咨询电话 020-87683296 · 邮箱 gdfamingxh@126.com",
}

GROUP_NAMES = {"high": "小学高段组"}   # 本届平台仅开放小学高段组（4—6 年级，3 年级可自愿选报）
GROUP_ENTRY_PREFIX = {"high": "H"}
OPEN_GRADES = (3, 4, 5, 6)             # 3 年级须选报高段组；4—6 年级默认高段组

