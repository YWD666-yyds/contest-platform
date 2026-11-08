#!/usr/bin/env bash
# ============================================================
# 一键部署脚本 —— 人工智能应用赛项 · 市级初赛平台（Ubuntu 20.04+）
# 用法：sudo bash deploy/deploy.sh [安装目录，默认 /opt/contest]
# 首次部署后请阅读 deploy/DEPLOY_UBUNTU.md 完成后续步骤
# ============================================================
set -euo pipefail

APP_DIR="${1:-/opt/contest}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="contest"

if [[ $EUID -ne 0 ]]; then echo "请用 sudo 运行"; exit 1; fi

echo "==> 1/8 安装系统依赖"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx sqlite3 >/dev/null

echo "==> 2/8 创建服务账号与目录"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude 'data/' --exclude '.git/' --exclude '__pycache__/' \
    --exclude 'tests/' --exclude '.pytest_cache/' \
    "$SRC_DIR"/ "$APP_DIR"/
mkdir -p "$APP_DIR"/data/{uploads,thumbs,backups}
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

echo "==> 3/8 创建 Python 虚拟环境并安装依赖"
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> 4/8 初始化数据库与管理员（幂等，已有数据不受影响）"
if [[ ! -f "$APP_DIR/.env" ]]; then
    ADMIN_PWD="$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 12)"
    echo "ADMIN_INITIAL_PASSWORD=${ADMIN_PWD}" > "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo "    管理员初始密码已写入 $APP_DIR/.env （admin / ${ADMIN_PWD}），请登录后立即修改！"
fi
sudo -u "$SERVICE_USER" env $(cat "$APP_DIR/.env" | xargs) \
    "$APP_DIR/venv/bin/python" -m app.seed

echo "==> 5/8 安装 systemd 服务"
cp "$APP_DIR/deploy/contest.service" /etc/systemd/system/contest.service
systemctl daemon-reload
systemctl enable --now contest
sleep 2
systemctl --no-pager --lines 5 status contest || true

echo "==> 6/8 安装 Nginx 配置"
cp "$APP_DIR/deploy/proxy_params_contest.conf" /etc/nginx/proxy_params_contest.conf
cp "$APP_DIR/deploy/nginx-contest.conf" /etc/nginx/sites-available/contest
ln -sf /etc/nginx/sites-available/contest /etc/nginx/sites-enabled/contest
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "==> 7/8 配置防火墙（如已启用 UFW）"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 'Nginx Full' >/dev/null
    echo "    UFW 已放行 80/443"
fi

echo "==> 8/8 配置每日凌晨 3 点自动备份"
cat > /etc/cron.d/contest-backup <<CRON
0 3 * * * ${SERVICE_USER} /bin/bash ${APP_DIR}/deploy/backup.sh >> ${APP_DIR}/data/backups/backup.log 2>&1
CRON

echo
echo "✅ 部署完成！访问 http://<服务器IP>/ 验证。"
echo "   - 管理后台：http://<服务器IP>/#/admin （账号 admin，初始密码见 $APP_DIR/.env）"
echo "   - 服务状态：systemctl status contest"
echo "   - 实时日志：journalctl -u contest -f"
echo "   - 后续步骤（HTTPS、调优）：见 deploy/DEPLOY_UBUNTU.md"
