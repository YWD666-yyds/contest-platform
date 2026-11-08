"""SQLite 连接与建表。WAL 模式 + 每次调用独立连接（线程安全）。"""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('student','judge','admin')),
    must_change_pwd INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    expires_at TEXT NOT NULL,
    ip         TEXT,
    ua         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS students (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    entry_no     TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    school       TEXT NOT NULL,
    grade        TEXT NOT NULL,
    grade_no     INTEGER NOT NULL,
    group_code   TEXT NOT NULL CHECK(group_code IN ('low','high','middle')),
    teacher_name TEXT NOT NULL DEFAULT '',
    work_title   TEXT NOT NULL DEFAULT '',
    ai_platform  TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    design_image TEXT NOT NULL DEFAULT '',
    process_images TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','submitted')),
    submitted_at TEXT,
    edit_locked  INTEGER NOT NULL DEFAULT 0,
    disqualified INTEGER NOT NULL DEFAULT 0,
    disqualify_reason TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_students_group ON students(group_code, status);

CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_code TEXT NOT NULL CHECK(group_code IN ('high','middle')),
    type       TEXT NOT NULL CHECK(type IN ('single','multiple','judge')),
    stem       TEXT NOT NULL,
    options    TEXT NOT NULL DEFAULT '[]',
    answer     TEXT NOT NULL,
    score      REAL NOT NULL DEFAULT 1,
    topic      TEXT NOT NULL DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_questions_group ON questions(group_code, enabled);

CREATE TABLE IF NOT EXISTS attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    group_code    TEXT NOT NULL,
    question_order TEXT NOT NULL,
    option_order  TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    deadline      TEXT NOT NULL,
    answers       TEXT NOT NULL DEFAULT '{}',
    last_saved_at TEXT,
    submitted_at  TEXT,
    duration_seconds INTEGER,
    score         REAL,
    detail        TEXT,
    status        TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running','submitted')),
    suspicious_events INTEGER NOT NULL DEFAULT 0,
    extra_log     TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_attempts_group ON attempts(group_code, status);

CREATE TABLE IF NOT EXISTS announcements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS login_fails (
    key          TEXT PRIMARY KEY,
    fails        INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);

CREATE TABLE IF NOT EXISTS student_agents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    name         TEXT NOT NULL DEFAULT '',
    audience     TEXT NOT NULL DEFAULT '',
    scenario     TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL DEFAULT '',
    problem      TEXT NOT NULL DEFAULT '',
    skills       TEXT NOT NULL DEFAULT '',
    knowledge    TEXT NOT NULL DEFAULT '',
    tone         TEXT NOT NULL DEFAULT '',
    welcome      TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','saved','submitted')),
    submitted_at TEXT,
    check_status TEXT NOT NULL DEFAULT 'pending' CHECK(check_status IN ('pending','ok','revise')),
    check_comment TEXT NOT NULL DEFAULT '',
    checked_at   TEXT,
    checked_by   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS agent_chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_agent_chats_student ON agent_chats(student_id, id);

-- OJ 实操考试：考题（生活场景 + 标准测试问题，points 为参考答案要点，仅服务端判题使用）
CREATE TABLE IF NOT EXISTS agent_exam_questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    scene        TEXT NOT NULL,
    task_desc    TEXT NOT NULL,
    test_questions TEXT NOT NULL DEFAULT '[]',
    total_score  REAL NOT NULL DEFAULT 50,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 判题结果：每生一条，detail 为逐题 [{q, agent_reply, score, max, comment}]
CREATE TABLE IF NOT EXISTS agent_judge_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL UNIQUE REFERENCES students(id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'none' CHECK(status IN ('none','running','done','error')),
    detail     TEXT NOT NULL DEFAULT '[]',
    score      REAL,
    error      TEXT,
    judged_at  TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    user_id INTEGER,
    actor  TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    ip     TEXT
);
"""

_DEFAULT_SETTINGS = {
    "site": None,        # None 表示使用 config.SITE_DEFAULT
    "submission": {"open": True, "deadline": None, "allow_retract": True},
    "exams": {
        "high":   {"enabled": False, "start_at": "", "end_at": "", "duration_minutes": 40, "show_score_after": True, "allow_resubmit": True},
        "middle": {"enabled": False, "start_at": "", "end_at": "", "duration_minutes": 40, "show_score_after": True, "allow_resubmit": True},
    },
    "publish": {"low": False, "high": False, "middle": False, "mask_names": True},
    "quota": {"low": 0, "high": 0, "middle": 0},
    # 「设计智能体」题目要求（管理员可在后台编辑）
    "task": {
        "title": "设计智能体 · 题目要求",
        "content": (
            "一、任务背景\n"
            "围绕赛事主题「智绘城市 · AI便民智慧设施」，观察身边的城市街道、社区生活与公共便民场景，"
            "发现一个真实的便民问题，设计一个能够帮助居民解决该问题的智能体（AI Agent）。\n\n"
            "二、设计要求\n"
            "1. 选题真实：智能体必须取材于真实生活场景（如社区、校园、公交、图书馆等），所解决的便民问题具体明确；\n"
            "2. 定位清晰：明确智能体的名称、服务对象、应用场景与角色定位；\n"
            "3. 功能合理：说明智能体具备哪些功能与技能，功能要与便民问题一一对应，避免无关堆砌；\n"
            "4. 知识支撑：为智能体提供它需要掌握的知识资料（如社区规定、办事流程、设施说明等）；\n"
            "5. 语气友好：设定符合服务对象的交流风格，如面向老人要耐心、用词简单。\n\n"
            "三、交互验证\n"
            "完成设计并保存后，与你的智能体进行对话测试：\n"
            "· 用居民的口吻提出 2—3 个真实问题，检验智能体是否能按你的设计回答；\n"
            "· 如回答不符合预期，回到设计页修改「功能与技能」或「知识资料」后再测试；\n"
            "· 对话过程中如提示 API Key 或权限问题，请举手告知老师，由老师在管理后台补全配置。"
        ),
    },
    # OJ 实操考试（智能体作品）配置与两部分成绩合并权重
    "agent_exam": {"enabled": False, "start_at": "", "end_at": "", "quiz_weight": 50, "agent_weight": 50},
    # LLM 智能体后端配置（仅管理员可见；api_key 加密存储不明文返回）
    "llm": {
        "enabled": False, "provider": "", "api_base": "", "api_key": "",
        "model": "", "temperature": 0.7, "max_tokens": 800, "system_prefix": "",
    },
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_EXAM_SEED = [
    {
        "title": "图书馆智能导览员",
        "scene": "学校图书馆的借阅服务台，开学季新生和家长前来咨询，人工问答应接不暇。",
        "task_desc": """请配置一个「图书馆智能导览员」智能体：
1. 在知识库中录入下方《图书馆服务须知》的关键信息（开馆时间、借阅规则、续借与补办流程）；
2. 设定合适的角色定位与语气风格（面向学生与家长，友好、简洁、耐心）；
3. 配置完成后，用考官给出的标准问题进行测试，确认它能依据知识库准确回答。
《图书馆服务须知》：开馆时间为周一至周五 8:00—18:00，周末 9:00—16:00；每人可借图书 5 册，借期 30 天；到期前可续借一次，续期 15 天，逾期按天数暂停借阅；借书卡遗失请携带学生证到一层服务台挂失，3 个工作日后免费补办。""",
        "test_questions": [
            {"q": "图书馆几点开门？我一次最多能借几本书？", "points": "开馆时间周一至周五8:00-18:00、周末9:00-16:00；每人可借5册", "score": 20},
            {"q": "我借的书快到期了还没看完，应该怎么办？", "points": "到期前可续借一次，续期15天；逾期按天暂停借阅", "score": 15},
            {"q": "我的借书卡丢了，怎么补办？", "points": "携带学生证到一层服务台挂失；3个工作日后免费补办", "score": 15},
        ],
        "total_score": 50,
    },
    {
        "title": "外卖订单智能客服",
        "scene": "一家外卖平台的客服岗位，高峰期用户咨询集中在订单进度、超时与退单问题上。",
        "task_desc": """请配置一个「外卖订单智能客服」：
1. 在知识库中录入《客服手册》要点（超时赔付规则、退单规则、催单方式）；
2. 设定角色定位与语气（安抚情绪、先道歉再给方案）；
3. 用标准问题测试，确保回答包含关键信息。
《客服手册》：订单超过 40 分钟未送达，自动赔付 5 元无门槛券；商家接单前可无理由退单，接单后需联系商家协商；用户可在订单详情页点击「催单」，系统将优先调度；客服无法解决的投诉可在订单完成后 24 小时内提交人工申诉。""",
        "test_questions": [
            {"q": "我的外卖都一个小时了还没到，怎么办？", "points": "超40分钟未送达自动赔5元无门槛券；可先催单优先调度", "score": 20},
            {"q": "我刚下的订单不想要了，能退吗？", "points": "商家接单前可无理由退单；接单后需联系商家协商", "score": 15},
            {"q": "投诉了没人处理怎么办？", "points": "订单完成后24小时内可提交人工申诉", "score": 15},
        ],
        "total_score": 50,
    },
    {
        "title": "快递驿站智能查询助手",
        "scene": "社区快递驿站的线上查询入口，居民经常询问取件、存放与丢件问题。",
        "task_desc": """请配置一个「快递驿站智能查询助手」：
1. 在知识库中录入《驿站服务规则》（免费存放时长、超时收费、丢件赔付、取件凭证）；
2. 设定服务语气（简洁清晰，给出可执行步骤）；
3. 用标准问题测试，确保关键信息不遗漏。
《驿站服务规则》：包裹免费存放 3 天，第 4 天起每天加收 1 元保管费；取件需提供取件码或手机号后四位；包裹在驿站内丢失，凭取件记录按申明价值赔付，最高 500 元；代取他人包裹需出示取件码与代取人身份信息。""",
        "test_questions": [
            {"q": "我的快递放了四天了，取的时候要加钱吗？", "points": "免费存放3天，第4天起每天1元保管费", "score": 20},
            {"q": "取快递需要出示什么？", "points": "取件码或手机号后四位；代取需取件码与代取人身份信息", "score": 15},
            {"q": "我在驿站的包裹丢了怎么办？", "points": "凭取件记录按申明价值赔付，最高500元", "score": 15},
        ],
        "total_score": 50,
    },
]


def _seed_exam_questions(db):
    """OJ 实操考试样题：仅当考题表为空时插入（生活场景：图书馆 / 外卖订单 / 物流信息）。"""
    import json
    n = db.execute("SELECT COUNT(*) AS n FROM agent_exam_questions").fetchone()["n"]
    if n:
        return
    for q in _EXAM_SEED:
        db.execute(
            "INSERT INTO agent_exam_questions(title,scene,task_desc,test_questions,total_score,enabled) "
            "VALUES(?,?,?,?,?,1)",
            (q["title"], q["scene"], q["task_desc"], json.dumps(q["test_questions"], ensure_ascii=False), q["total_score"]))

def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
        _migrate(db)
        _seed_exam_questions(db)
        for key, value in _DEFAULT_SETTINGS.items():
            row = db.execute("SELECT key FROM settings WHERE key=?", (key,)).fetchone()
            if not row:
                import json
                db.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )


def _migrate(db):
    """存量库轻量迁移：逐列尝试补齐（已存在则忽略）。"""
    migrations = [
        ("students", "disqualify_reason", "TEXT NOT NULL DEFAULT ''"),
        ("student_agents", "submitted_at", "TEXT"),
        ("student_agents", "check_status", "TEXT NOT NULL DEFAULT 'pending'"),
        ("student_agents", "check_comment", "TEXT NOT NULL DEFAULT ''"),
        ("student_agents", "checked_at", "TEXT"),
        ("student_agents", "checked_by", "TEXT"),
    ]
    for table, column, ddl in migrations:
        cols = [r["name"] for r in db.execute(f"PRAGMA table_info({table})")]
        if not cols:
            continue  # 表尚未创建（由 SCHEMA 负责）
        if column not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # student_agents 状态约束升级：旧表 CHECK 不含 'submitted'，SQLite 无法改约束，需重建表
    tbl = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='student_agents'").fetchone()
    if tbl and "'submitted'" not in (tbl["sql"] or ""):
        old_rows = db.execute("SELECT * FROM student_agents").fetchall()
        db.execute("DROP TABLE student_agents")
        db.executescript(SCHEMA)
        new_cols = [r["name"] for r in db.execute("PRAGMA table_info(student_agents)")]
        for r in old_rows:
            data = {k: r[k] for k in r.keys() if k in new_cols}
            data.setdefault("check_status", "pending")
            data.setdefault("status", "draft")
            cols = ",".join(data.keys())
            ph = ",".join("?" * len(data))
            db.execute(f"INSERT INTO student_agents ({cols}) VALUES ({ph})", list(data.values()))


def get_setting(db, key: str):
    import json
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return _DEFAULT_SETTINGS.get(key)
    return json.loads(row["value"])


def set_setting(db, key: str, value):
    import json
    db.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
