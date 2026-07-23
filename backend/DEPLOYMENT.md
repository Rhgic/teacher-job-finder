# 后端部署说明

当前部署目标是腾讯云轻量服务器 `42.194.146.44`。项目定位为面试作品，只通过
IP 的 80 端口展示 Web 端，不绑定域名、不申请 HTTPS 证书，也不提交微信公开审核。
可直接复制执行的服务器命令见 [`GO_LIVE_COMMANDS.md`](GO_LIVE_COMMANDS.md)。

## 部署结构

```text
公网 :80
  └─ Nginx
       └─ 127.0.0.1:8000  teacher-job-api.service
            ├─ 127.0.0.1:3306  MySQL 8（Docker）
            └─ 127.0.0.1:6379  Redis 7（Docker）
```

代码直接从 GitHub 的 `v2` 分支 clone 到 `/opt/teacher-job-api`，后端工作目录为
`/opt/teacher-job-api/backend`。`main` 与 `legacy-v1` 是无共同祖先的废弃版本，
不能与 `v2` 合并。

MySQL、Redis 和 Uvicorn 都只监听 `127.0.0.1`；腾讯云防火墙只需放行 SSH 与
TCP 80，不要放行 3306、6379、8000。

## 环境变量与密钥

服务器先复制 `.env.example` 为 `.env`。以下值必须换成真实配置：

```text
MYSQL_ROOT_PASSWORD=随机数据库 root 密码
MYSQL_PASSWORD=随机应用数据库密码
DATABASE_URL=mysql+pymysql://teacher:与 MYSQL_PASSWORD 相同的密码@127.0.0.1:3306/teacher_jobs?charset=utf8mb4
AUTH_DEV_MODE=0
SESSION_SECRET=随机会话签名密钥
ADMIN_API_TOKEN=另一条随机管理令牌
LLM_STUB_MODE=0
DEEPSEEK_API_KEY=真实 DeepSeek Key
```

Web 端使用 `/auth/guest` 创建匿名体验身份，不依赖微信配置。只有同时发布微信
小程序时才额外填写 `WECHAT_APPID` 与 `WECHAT_SECRET`。

`SESSION_SECRET` 与 `ADMIN_API_TOKEN` 必须分别生成，不能相同。`.env` 权限设为
`600`，不能提交到 Git。配置后运行：

```bash
cd /opt/teacher-job-api/backend
.venv/bin/python scripts/check_release_env.py .env
```

脚本只报告配置状态，不输出密钥；显示“必填项通过”才可开放公网。

连接池使用压测后的 `20 + 30 = 50`、等待超时 5 秒。MySQL 默认
`max_connections=151` 时最多并排运行 3 个 API 实例；当前只部署单实例。

## 数据库迁移

全新数据库：

```bash
cd /opt/teacher-job-api/backend
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
```

已有表的旧库首次接入 Alembic，只运行 `.venv/bin/alembic stamp head`，不能再跑
初始 `upgrade`，否则会因表已存在而冲突。

生产库绝对不能运行 `python seed.py`：该脚本是本地演示初始化工具，会先
`drop_all` 清空全部表。

## systemd 服务与定时器

`deploy/server-setup.sh` 安装以下单元：

```text
teacher-job-api.service
teacher-job-crawl.service
teacher-job-crawl.timer
teacher-job-backup.service
teacher-job-backup.timer
```

定时爬虫每天 07:10 后随机延迟最多 45 分钟执行；每个来源最多抓 12 个详情页，
继续遵守 robots、2 秒礼貌限速和 30 分钟缓存。Redis 不可用时限流会降级放行，
不会拖垮主功能。

```bash
systemctl list-timers teacher-job-crawl.timer teacher-job-backup.timer
sudo journalctl -u teacher-job-crawl.service -n 80 --no-pager
```

定时备份每天 03:20 后随机延迟最多 20 分钟执行，`scripts/backup_db.py` 根据
`DATABASE_URL` 自动选择 MySQL `mysqldump` 或 SQLite 在线备份，保留最近 14 份：

```bash
cd /opt/teacher-job-api/backend
.venv/bin/python scripts/backup_db.py --output-dir ./backups --keep 14
sudo journalctl -u teacher-job-backup.service -n 80 --no-pager
```

备份恢复演练见后续“备份恢复”章节；演练只使用本地或临时库，不在生产库操作。

## Nginx 与公网检查

`deploy/nginx.teacher-job-api.conf` 是 IP-only HTTP 配置，直接复制即可，不需要替换
域名或配置证书。

```bash
cd /opt/teacher-job-api/backend
sudo cp deploy/nginx.teacher-job-api.conf /etc/nginx/sites-available/teacher-job-api.conf
sudo ln -sf /etc/nginx/sites-available/teacher-job-api.conf /etc/nginx/sites-enabled/teacher-job-api.conf
sudo nginx -t
sudo systemctl reload nginx
curl -fsS http://42.194.146.44/health
```

`/readiness` 只显示非敏感配置状态、岗位数量与备份状态，不会返回任何密钥；
`/metrics` 显示请求计数、LLM 调用数、token 用量和缓存命中情况。

## 更新代码

```bash
cd /opt/teacher-job-api
git switch v2
git pull --ff-only origin v2
cd backend
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
sudo docker compose up -d
sudo cp deploy/teacher-job-*.service deploy/teacher-job-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart teacher-job-api
sudo systemctl restart teacher-job-crawl.timer teacher-job-backup.timer
sudo nginx -t
sudo systemctl reload nginx
```

## 备份恢复

**没演练过的备份等于没有备份。** 备份任务跑得再规律，只要没验证过
"能不能恢复回来"，那就只是在定时产出一堆没人用过的文件。

### 定期演练（推荐每月一次，改动过备份流程后必须跑）

```bash
cd /opt/teacher-job-api
.venv/bin/python backend/scripts/verify_backup_restore.py
```

脚本做五件事：找最近一份备份 → 校验是真 gzip 且不含跨库语句 →
建临时库 `teacher_jobs_restore_drill` → 恢复并计时 → 逐表比对行数，
跑完自动删掉临时库。**全程不写生产库**，只读 `COUNT(*)` 做比对。
加 `--keep-temp` 可保留临时库便于排查。

需要 `.env` 里的 `MYSQL_ROOT_PASSWORD`：建库是管理操作，应用账号
`teacher` 没有 `CREATE DATABASE` 权限——这是正确的最小权限配置，
不要为了让脚本跑通去给应用账号提权。

**本机与另一个小程序共用同一个 MySQL 实例**，所以恢复前会扫描 dump 里的
`USE` / `CREATE DATABASE` 语句并在发现时中止：恢复的目标库只由命令行参数
决定，dump 里一旦带这类语句，以 root 恢复就会越过临时库静默写到别的库上。
当前 `backup_db.py` 是单库 `mysqldump`（传库名，不是 `--databases`），
不产生这类语句；这道校验是防止以后有人改参数把它变成静默破坏。

### 实测基线（2026-07-23，生产库 11 表 / 160 行，备份 0.18 MB）

| 指标 | 实测值 |
| --- | --- |
| RTO（恢复耗时） | **1.3 秒** |
| RPO（最坏数据丢失） | **24 小时**，等于备份间隔 |
| 恢复完整性 | 11 表全到，行数差异仅来自备份后的新增写入 |

RPO 是这里的短板：每天备份一次，意味着最坏情况丢一整天的投递记录和
抓取结果。岗位数据可以重爬，`applications` / `resumes` 丢了不可再生。
真要压低得上 binlog 增量备份或主从，当前规模下先记录清楚这个取舍。

### 真的要恢复生产库时

演练脚本只写临时库，**不会**替你恢复生产库。真出事时按下面走，
每一步都确认完再进行下一步：

```bash
sudo systemctl stop teacher-job-api          # 1. 先停写入，避免边恢复边写
cd /opt/teacher-job-api/backend
ls -lt backups/                              # 2. 挑一份，确认时间戳符合预期
```

```bash
# 3. 先恢复到临时库验一遍，确认这份备份可用（别直接往生产库倒）
.venv/bin/python scripts/verify_backup_restore.py --keep-temp
```

```bash
# 4. 把现在的生产库先另存一份——恢复是覆盖操作，错了没有回头路
MYSQL_PWD='<MYSQL_ROOT_PASSWORD>' mysqldump -h127.0.0.1 -uroot \
  --single-transaction teacher_jobs | gzip > backups/before-restore-$(date +%Y%m%d-%H%M%S).sql.gz
```

```bash
# 5. 恢复。teacher_jobs 会被备份里的内容整体覆盖
gzip -dc backups/teacher_jobs-<时间戳>.sql.gz \
  | MYSQL_PWD='<MYSQL_ROOT_PASSWORD>' mysql -h127.0.0.1 -uroot teacher_jobs
```

```bash
# 6. 校验后再放流量进来
.venv/bin/alembic current
sudo systemctl start teacher-job-api
curl -fsS http://42.194.146.44/health
curl -fsS http://42.194.146.44/readiness
```

第 4 步不能省。恢复覆盖生产库之后，"备份其实是三天前的"这种事
就再也补救不了了。

## 合规边界

- 投递必须由用户人工确认，不做全自动投递。
- 简历改写只能基于用户真实内容，不能虚构学历、证书、经历或年限。
- 爬虫只访问 robots 允许的公开来源，保持限速和缓存。
- 招聘方邮箱按现有方式处理，不额外暴露。
