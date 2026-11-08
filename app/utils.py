"""通用工具：时间处理。全站使用本地时间字符串 YYYY-MM-DD HH:MM:SS。"""
from datetime import datetime

FMT = "%Y-%m-%d %H:%M:%S"


def now_str() -> str:
    return datetime.now().strftime(FMT)


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], FMT)
    except ValueError:
        try:
            return datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return None


def fmt_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}时{m:02d}分{s:02d}秒" if h else f"{m}分{s:02d}秒"
