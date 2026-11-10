#!/usr/bin/env bash
# 数据库备份（配合 cron 每日运行）
# 保留最近 14 份，自动清理更早的备份
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$APP_DIR/data/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
KEEP=14

mkdir -p "$BACKUP_DIR"

# 1. SQLite 在线备份（WAL 安全，不锁库）
"$APP_DIR/venv/bin/python" - "$APP_DIR/data/contest.db" "$BACKUP_DIR/db_$STAMP.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dst)
s.backup(d)
d.close(); s.close()
PY

# 2. 清理旧备份
ls -1t "$BACKUP_DIR"/db_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "$(date '+%F %T') 备份完成: db_$STAMP.db"
