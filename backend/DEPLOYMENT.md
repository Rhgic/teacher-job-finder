# 后端正式部署说明

当前后端已经可以本地跑通。要让微信小程序正式上线，需要把它部署到公网 HTTPS 域名，例如：

```text
https://api.your-domain.com
```

## 推荐路线

1. 买一台腾讯云轻量服务器。
2. 准备一个已备案域名，并解析 `api` 子域名到服务器。
3. 在服务器安装 Python、Nginx、Certbot。
4. 用 `deploy/teacher-job-api.service` 把后端注册成系统服务。
5. 用 `deploy/teacher-job-crawl.timer` 注册每日岗位刷新定时任务。
6. 用 `deploy/nginx.teacher-job-api.conf` 配 HTTPS 反向代理到 `127.0.0.1:8000`。
7. 访问 `https://api.your-domain.com/health`，看到 `{"status":"ok"}` 说明基础健康接口通了。
8. 到微信公众平台把 `https://api.your-domain.com` 加到「开发管理 - 开发设置 - 服务器域名 - request 合法域名」。

## 服务器部署骨架

先在本机生成部署包：

```bash
cd /Users/rhgic/Downloads/backend
bash scripts/make_release_bundle.sh
```

把生成的 `dist/teacher-job-api-时间.tar.gz` 上传到服务器，然后解压到 `/opt/teacher-job-api`。

在服务器上：

```bash
sudo mkdir -p /opt/teacher-job-api
sudo tar -xzf teacher-job-api-时间.tar.gz -C /opt/teacher-job-api
sudo chown -R $USER:$USER /opt/teacher-job-api
cd /opt/teacher-job-api
cp .env.example .env
# 编辑 .env，填 WECHAT_SECRET / SESSION_SECRET 等真实配置
sudo bash deploy/server-setup.sh
```

Nginx 配置模板在：

```text
deploy/nginx.teacher-job-api.conf
```

把里面的 `api.your-domain.com` 换成你的真实域名，再放到 Nginx 配置目录。

## 公网接口检查

正式提交审核前，在本机跑：

```bash
cd /Users/rhgic/Downloads/backend
python3 scripts/check_public_api.py https://api.your-domain.com
```

这个脚本会检查：

- `/health` 是否正常。
- `/readiness` 必填项是否通过。
- `/jobs` 是否能返回岗位数组。
- `/auth/login` 是否已经挂载。
- `/crawl/sources` 是否能返回抓取源策略，且每个源都开启 robots。

看到“公网后端基础接口检查通过”再去微信后台提交审核。

也可以直接打开：

```text
https://api.your-domain.com/readiness
```

这个接口只显示非敏感状态，比如微信密钥是否已配置、是否仍在开发登录模式、岗位数量和最新岗位时间，不会输出任何密钥。

## 定时抓取岗位

部署脚本会安装两个 systemd 单元：

```text
teacher-job-crawl.service
teacher-job-crawl.timer
```

默认每天早上 7:10 左右抓一次全部已启用来源（当前包含 `sz910`、`shenzhenjiaoshi`，教育局源若 robots 限制会合规跳过），并带最多 45 分钟随机延迟，避免固定时间访问外部站点。抓取仍然使用 robots 检查、2 秒礼貌限速和 30 分钟缓存。

手动跑一次：

```bash
cd /opt/teacher-job-api
.venv/bin/python scripts/run_scheduled_crawl.py --source all --max-detail-pages 12
.venv/bin/python scripts/run_scheduled_crawl.py --source sz910 --max-detail-pages 12
.venv/bin/python scripts/run_scheduled_crawl.py --source shenzhenjiaoshi --max-detail-pages 12
```

查看定时器：

```bash
systemctl list-timers teacher-job-crawl.timer
journalctl -u teacher-job-crawl.service -n 80 --no-pager
```

## SQLite 自动备份

早期如果继续使用 SQLite，部署脚本会额外安装：

```text
teacher-job-backup.service
teacher-job-backup.timer
```

默认每天凌晨 3:20 后随机延迟最多 20 分钟备份一次，保留最近 14 份，目录：

```text
/opt/teacher-job-api/backups
```

手动备份一次：

```bash
cd /opt/teacher-job-api
.venv/bin/python scripts/backup_sqlite.py --output-dir /opt/teacher-job-api/backups --keep 14
```

查看定时器和日志：

```bash
systemctl list-timers teacher-job-backup.timer
journalctl -u teacher-job-backup.service -n 80 --no-pager
```

## 环境变量检查

在服务器或本机后端目录运行：

```bash
cd /opt/teacher-job-api
python3 scripts/check_release_env.py .env
```

如果是在本机检查部署包里的配置：

```bash
cd /Users/rhgic/Downloads/backend
python3 scripts/check_release_env.py .env
```

这个脚本不会打印密钥，只会告诉你哪些配置还没填、哪些仍是开发模式。

## 本地打包测试

如果服务器选择 Docker，可以用下面方式测试；当前电脑没有安装 Docker，这一步可以先跳过。

```bash
cd /Users/rhgic/Downloads/backend
docker build -t teacher-job-api .
docker run --rm -p 8000:8000 --env-file .env teacher-job-api
```

另开终端检查：

```bash
curl http://127.0.0.1:8000/health
```

## 生产环境变量

先复制样例：

```bash
cp .env.example .env
```

正式发布前建议至少改这些：

```text
AUTH_DEV_MODE=0
WECHAT_APPID=wx2dcd7d67c642d4cb
WECHAT_SECRET=你的小程序 AppSecret
SESSION_SECRET=一串很长的随机字符串
```

这四项是微信登录和线上用户隔离的硬要求。`AUTH_DEV_MODE=1` 只能用于开发调试，正式上线不能保留。

可以用下面命令生成 `SESSION_SECRET`：

```bash
cd /Users/rhgic/Downloads/backend
python3 scripts/generate_session_secret.py
```

把输出的整串内容填进服务器 `.env` 的 `SESSION_SECRET=` 后面。

为了避免手动改错 `.env`，也可以用安全更新脚本：

```bash
cd /opt/teacher-job-api
.venv/bin/python scripts/set_env_value.py .env WECHAT_SECRET '你的微信AppSecret'
.venv/bin/python scripts/set_env_value.py .env AUTH_DEV_MODE 0
.venv/bin/python scripts/set_env_value.py .env SESSION_SECRET '刚生成的长字符串'
```

这个脚本会自动备份 `.env`，不会打印密钥。

完整上线命令集中放在：

```text
GO_LIVE_COMMANDS.md
```

如果要启用真实 AI 匹配：

```text
LLM_STUB_MODE=0
DEEPSEEK_API_KEY=你的 DeepSeek Key
```

如果要真实发邮件：

```text
MAILER_DRY_RUN=0
SMTP_HOST=你的 SMTP 地址
SMTP_USER=你的邮箱账号
SMTP_PASSWORD=你的邮箱授权码
SMTP_FROM=你的发件邮箱
```

## 注意

- 投递接口仍然需要用户确认，不能做全自动投递。
- 简历改写只能基于真实简历内容，不能编造学历、证书、经历或年限。
- 爬虫要优先官方源，遵守 robots、限速和缓存；当前可用 `GET /crawl/sources` 查看策略。若某个官方源 robots 不允许抓取，系统会跳过，不做绕行。
