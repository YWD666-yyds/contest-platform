# Ubuntu 服务器部署指南

人工智能应用赛项 · 市级初赛平台（FastAPI + SQLite + Nginx）

## 一、环境要求

| 项目 | 要求 |
|------|------|
| 系统 | Ubuntu 20.04 / 22.04 / 24.04 |
| 配置 | 最低 1 核 1G（推荐 2 核 2G，可支撑千人级初赛） |
| 软件 | Python 3.10+、Nginx（脚本自动安装） |

## 二、一键部署

把整个 `contest-platform` 目录上传到服务器（scp / git / 面板均可），然后：

```bash
sudo bash deploy/deploy.sh            # 默认安装到 /opt/contest
```

脚本自动完成：装依赖 → 创建 `contest` 服务账号 → Python 虚拟环境 → 初始化数据库与管理员 → systemd 服务 → Nginx 站点 → UFW 放行 → 每日凌晨 3 点自动备份。

完成后：

- 打开 `http://<服务器IP>/` 检查首页
- **管理员初始密码**写在 `/opt/contest/.env`（`ADMIN_INITIAL_PASSWORD=...`），立即登录 `/#/admin` 修改！
- 修改管理员密码后，建议删除 `.env` 中的密码行（仅首次初始化使用）

## 三、目录结构

```
/opt/contest/
├── app/                # 后端代码
├── static/             # 前端（Nginx 直接服务）
├── data/
│   ├── contest.db      # SQLite 数据库（WAL 模式）
│   └── backups/        # 自动备份
├── deploy/             # 部署脚本与配置
└── venv/               # Python 虚拟环境
```

## 四、日常运维

```bash
systemctl status contest        # 服务状态
journalctl -u contest -f        # 实时日志
journalctl -u contest --since "1 hour ago"   # 近期日志
sudo systemctl restart contest  # 重启（改代码/配置后）
sudo bash deploy/backup.sh      # 手动备份
```

更新代码：覆盖 `/opt/contest` 下的 `app/`、`static/` 后 `sudo systemctl restart contest`（`data/` 不会被覆盖）。

## 五、启用 HTTPS（强烈建议）

考试涉及学生作答，正式使用请配置域名 + HTTPS：

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d 你的域名
```

然后在 `/etc/systemd/system/contest.service` 中设置 `Environment="COOKIE_SECURE=1"`，并：

```bash
sudo systemctl daemon-reload && sudo systemctl restart contest
```

certbot 会自动续期并重载 Nginx。

## 六、性能与容量说明（已内置的优化）

- **Nginx**：前端静态资源直接由 Nginx 服务（7 天缓存），gzip 压缩，`client_max_body_size 10m`（CSV 名单导入余量），登录接口 10 次/分钟限速、API 30 r/s 限速
- **Uvicorn**：4 worker（可按 `nproc` 核数调整 `contest.service` 中 `--workers`）
- **SQLite**：WAL 模式 + `busy_timeout`，读写并发良好；关键词查询均已建索引
- **systemd 加固**：`ProtectSystem=strict`、`MemoryMax=1G`、崩溃 3 秒自动拉起

**容量参考**：2 核 2G 服务器可轻松支撑「上千人报名 + 数百人同时在线答题」（答题请求为纯内存/SQLite 毫秒级操作）。若单场考试同屏超过 1000 人，可将 worker 数调为 CPU 核数 × 2。

## 七、数据安全

- 每日 03:00 自动备份到 `data/backups/`（保留 14 份），建议定期把备份下载到本机或对象存储
- 手动恢复数据库：停止服务 → 用备份的 `db_*.db` 覆盖 `data/contest.db` → 重启
- 密码使用 scrypt 加盐哈希存储；会话为服务端 Token，改密/重置即刻生效

## 八、赛前检查清单

- [ ] 「赛事设置」：填写考试窗口与时长（知识测试）、实操考试窗口与两部分成绩权重、公示开关与晋级名额
- [ ] 「🤖 智能体设置」：配置 LLM（接口地址/API Key/模型）并点「测试连接」；编辑「题目要求」正文
- [ ] 「🧪 实操考试」：导入/核对智能体考题与标准测试问题
- [ ] 「题库管理」：核对/替换内置样题（正式赛题赛前导入）
- [ ] 「学生管理」：批量导入名单（CSV 模板见平台），下载账号单分发给学校
- [ ] 首页通知公告、赛程安排是否更新
- [ ] 用一个测试学生账号完整走一遍：登录 → 答题交卷 → 设计智能体 → 对话测试 → 交任务
- [ ] 考试前 30 分钟 `systemctl status contest` 确认服务健康，`df -h` 确认磁盘余量

## 九、常见问题

| 现象 | 处理 |
|------|------|
| 502 Bad Gateway | `systemctl status contest` 看后端是否崩溃；`journalctl -u contest -n 50` 找原因 |
| 导入 CSV 报 413 | Nginx `client_max_body_size`（本配置 10m），检查是否有其他 server 块覆盖 |
| 登录提示“失败次数过多” | 15 分钟后自动解锁；管理员可让学生用“重置密码” |
| 考试中倒计时与手表有偏差 | 以服务端时间为准，请校准服务器时区：`sudo timedatectl set-timezone Asia/Shanghai` |
| 想换端口 | 改 `contest.service` 的 `--port` 与 nginx conf 的 `proxy_pass`，重启两者 |
