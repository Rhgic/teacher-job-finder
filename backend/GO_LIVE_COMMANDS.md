# 腾讯云 IP 部署命令清单

目标服务器：`42.194.146.44`（Ubuntu 22.04，已安装 Docker）。本项目只通过
IP 的 80 端口展示，不绑定域名、不申请 HTTPS 证书。

> 所有命令都在服务器执行。不要把命令中生成或输入的密钥复制进仓库、聊天记录或截图。

## 1. 拉取 v2 分支并安装 Python 依赖

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip
sudo docker compose version
sudo git clone --branch v2 --single-branch https://github.com/Rhgic/teacher-job-finder.git /opt/teacher-job-api
sudo chown -R "$USER":"$USER" /opt/teacher-job-api
cd /opt/teacher-job-api/backend
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

如果目录已经存在，不要重新 clone，也不要删除数据，改用：

```bash
cd /opt/teacher-job-api
git switch v2
git pull --ff-only origin v2
cd backend
```

## 2. 在服务器生成数据库和应用密钥

以下四个随机值只保存在当前 shell 变量和 `.env` 中，不会打印到终端。数据库密码使用
十六进制，写进 `DATABASE_URL` 时无需额外 URL 编码。

```bash
cd /opt/teacher-job-api/backend
TJF_DB_ROOT_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
TJF_DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
TJF_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
TJF_ADMIN_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"

.venv/bin/python scripts/set_env_value.py .env MYSQL_ROOT_PASSWORD "$TJF_DB_ROOT_PASSWORD"
.venv/bin/python scripts/set_env_value.py .env MYSQL_PASSWORD "$TJF_DB_PASSWORD"
.venv/bin/python scripts/set_env_value.py .env DATABASE_URL "mysql+pymysql://teacher:${TJF_DB_PASSWORD}@127.0.0.1:3306/teacher_jobs?charset=utf8mb4"
.venv/bin/python scripts/set_env_value.py .env SESSION_SECRET "$TJF_SESSION_SECRET"
.venv/bin/python scripts/set_env_value.py .env ADMIN_API_TOKEN "$TJF_ADMIN_API_TOKEN"
.venv/bin/python scripts/set_env_value.py .env AUTH_DEV_MODE 0

unset TJF_DB_ROOT_PASSWORD TJF_DB_PASSWORD TJF_SESSION_SECRET TJF_ADMIN_API_TOKEN
chmod 600 .env
```

交互输入微信与 DeepSeek 密钥，避免密钥进入 shell 历史：

```bash
read -r -s -p "微信 AppSecret: " TJF_WECHAT_SECRET; echo
.venv/bin/python scripts/set_env_value.py .env WECHAT_SECRET "$TJF_WECHAT_SECRET"
unset TJF_WECHAT_SECRET

read -r -s -p "DeepSeek API Key: " TJF_DEEPSEEK_API_KEY; echo
.venv/bin/python scripts/set_env_value.py .env DEEPSEEK_API_KEY "$TJF_DEEPSEEK_API_KEY"
.venv/bin/python scripts/set_env_value.py .env LLM_STUB_MODE 0
unset TJF_DEEPSEEK_API_KEY
```

## 3. 启动 MySQL 与 Redis，执行迁移

```bash
cd /opt/teacher-job-api/backend
sudo docker compose up -d
sudo docker compose ps
```

确认两个容器都是 `healthy` 后，对全新数据库执行：

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
```

只有“表已经存在、第一次接入 Alembic”的旧库才执行下面这条，不能与上面的
`upgrade head` 混用：

```bash
.venv/bin/alembic stamp head
```

不要在生产库运行 `python seed.py`，该脚本会先清空全部表。

## 4. 上线配置检查与 systemd

```bash
cd /opt/teacher-job-api/backend
.venv/bin/python scripts/check_release_env.py .env
sudo bash deploy/server-setup.sh
sudo systemctl status teacher-job-api --no-pager
```

`check_release_env.py` 必须显示“必填项通过”再继续。

## 5. 安装 IP-only Nginx 配置

```bash
cd /opt/teacher-job-api/backend
sudo cp deploy/nginx.teacher-job-api.conf /etc/nginx/sites-available/teacher-job-api.conf
sudo ln -sf /etc/nginx/sites-available/teacher-job-api.conf /etc/nginx/sites-enabled/teacher-job-api.conf
sudo nginx -t
sudo systemctl reload nginx
```

腾讯云轻量应用服务器控制台只放行 SSH 和 TCP 80；不要放行 3306、6379、8000。
Compose 已把 MySQL 与 Redis 绑定到 `127.0.0.1`，Uvicorn 也只监听本机。

## 6. 首次抓取与验收

先手动跑一次有边界的抓取，确认日志正常并让岗位页有数据：

```bash
cd /opt/teacher-job-api/backend
.venv/bin/python scripts/run_scheduled_crawl.py --source all --max-detail-pages 12 --no-match
```

检查服务、指标、定时器和备份：

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://42.194.146.44/health
curl -fsS http://42.194.146.44/metrics | head -40
systemctl list-timers teacher-job-crawl.timer teacher-job-backup.timer
sudo systemctl start teacher-job-backup.service
sudo journalctl -u teacher-job-backup.service -n 40 --no-pager
ls -lh /opt/teacher-job-api/backend/backups
```

浏览器逐页打开，确认没有白屏：

```text
http://42.194.146.44/web/
http://42.194.146.44/web/recommend.html
http://42.194.146.44/web/ask.html
http://42.194.146.44/web/applications.html
http://42.194.146.44/web/me.html
```

未创建体验身份时，推荐页与投递页应显示去「我的」页创建身份的引导；点击创建后，
两页应恢复正常空态或数据列表。

## 7. 隔天复查

```bash
sudo journalctl -u teacher-job-crawl.service --since yesterday --no-pager
systemctl list-timers teacher-job-crawl.timer teacher-job-backup.timer
curl -fsS 'http://42.194.146.44/jobs?size=100' | python3 -c 'import json,sys; print("岗位数:", len(json.load(sys.stdin)))'
```

定时抓取必须没有异常，岗位数应保持或增长。备份能否恢复将在 T4 使用临时库单独演练，
不拿生产库做恢复测试。
