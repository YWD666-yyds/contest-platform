"""平台配置：路径、环境变量、常量。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CONTEST_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"          # 原图按 design/<sid>/uuid.ext 存放
THUMB_DIR = DATA_DIR / "thumbs"            # 评审列表缩略图
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "contest.db"

for _d in (DATA_DIR, UPLOAD_DIR, THUMB_DIR, BACKUP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---- 会话 / 安全 ----
SESSION_COOKIE = "contest_session"
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "72"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"   # HTTPS 部署时置 1
ADMIN_INITIAL_PASSWORD = os.environ.get("ADMIN_INITIAL_PASSWORD", "admin@2026")

# ---- 业务常量（依据竞赛规则 4.2.1）----
DESIGN_MAX_BYTES = 20 * 1024 * 1024        # 设计图 ≤ 20MB
DESIGN_MIN_W, DESIGN_MIN_H = 1920, 1080    # ≥ 1920×1080
PROCESS_MAX_BYTES = 20 * 1024 * 1024       # 过程记录单张上限（规则未限定，取同设计图）
PROCESS_MIN_COUNT, PROCESS_MAX_COUNT = 1, 3
DESCRIPTION_MIN_CHARS = 100                # 作品说明 ≥ 100 字

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

# 评分表（规则 7.2）：维度 key → (名称, 满分)
SCORE_DIMENSIONS = {
    "s_theme": ("主题契合", 30),
    "s_creative": ("创意构思", 35),
    "s_expression": ("设计表达", 20),
    "s_process": ("创作过程", 15),
}
