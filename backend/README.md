# 后端骨架（已搭好，Codex 填空）

框架、目录、路由、服务层已接好线并可启动。**机械逻辑已实现**，
**需要动脑的部分留成带说明的 stub**，照下表填即可，不要改动整体结构与既有约定。

## 启动（先确认骨架能跑）
```bash
pip install -r requirements.txt
python seed.py                 # 建表 + 种子数据（1 用户 + 12 岗位 + 1 规则）
uvicorn main:app --reload      # 访问 http://127.0.0.1:8000/docs
```
默认 `LLM_STUB_MODE=1`、`MAILER_DRY_RUN=1`：无需任何外部 Key/网络即可端到端跑通。
试一下：`POST /pipeline/run` → `GET /recommendations` 能看到带占位评分的推荐。
开发模式手动抓取深圳本地教师岗位：`POST /crawl/run?source=all&max_detail_pages=12`；生产模式需带 `X-Admin-Token: ADMIN_API_TOKEN`，避免公开域名被外部反复触发。
查看抓取源合规策略：`GET /crawl/sources`。
查看非敏感上线准备状态：`GET /readiness`。
服务器定时抓取一次：`python scripts/run_scheduled_crawl.py --source all --max-detail-pages 12`；也可单独用 `--source sz910` 或 `--source shenzhenjiaoshi`。
手动备份一次：`python scripts/backup_db.py --output-dir ./backups --keep 14`（按 `DATABASE_URL` 自动分派 SQLite / mysqldump）。

本地起 MySQL：`docker compose up -d db`，然后把 `.env` 的 `DATABASE_URL` 换成
`mysql+pymysql://teacher:teacher_dev_pwd@127.0.0.1:3306/teacher_jobs?charset=utf8mb4`。
已有 SQLite 数据可整库搬迁：`python scripts/migrate_sqlite_to_mysql.py --source sqlite:///./teacher_jobs.db --target "<MySQL URL>" --truncate`。

## 容量：压测实测与连接池

单实例压测（本机 MySQL 8 + 105 条岗位，打最重的读路径 `GET /jobs?size=100`）：

| 并发 | QPS | P50 | P95 |
| --- | --- | --- | --- |
| 1 | 240 | 4 ms | 5 ms |
| 4 | **299（峰值）** | 13 ms | 16 ms |
| 32 | 275 | 116 ms | 151 ms |
| 128 | 257 | 483 ms | 623 ms |

**吞吐在并发 4 左右见顶（约 300 QPS），之后延迟随并发线性增长**——
说明这个量级上已经跑满，加并发只是排队。

**压测发现的真问题**：原配置（`pool_size=10` + `max_overflow=20`，
超时 30 秒）在 128 并发下会**整体退化为等满 60 秒**，日志里 360 次
QueuePool 超时。路由是同步的，Session 从首次查询一直持有连接到请求结束，
所以并发一超过池容量就排队；而 30 秒的等待超时让它表现为"慢性死亡"
而不是快速失败——比直接拒绝更糟。

两处调整：

- 容量提到 `20 + 30 = 50`。MySQL `max_connections` 默认 151，
  单实例占 50 尚有余量，但这也意味着**最多并排跑 3 个实例**，
  再多要先调大 MySQL 侧上限。
- 等待超时压到 **5 秒**，超出容量时快速失败。
  `main.py` 捕获 `sqlalchemy.exc.TimeoutError` 返回 **503 + `Retry-After: 2`**
  而非 500——过载不是 bug，语义上分开才能让客户端知道值得重试、
  也能让监控把过载和真实故障分开统计。

调整后 128 并发从「QPS 3、全部失败、60.4 秒」变为
「QPS 257、零错误、P50 483 ms」；400 并发（8 倍于池容量）下
82 个成功、318 个拿到 503 + Retry-After，没有请求卡死。

**已知的扩展上限**：`/metrics` 的计数存在进程内存里，
多实例部署时每个副本各报各的数，需要改用 Redis 或
Prometheus 多进程模式才能汇总。当前单实例部署不受影响。

## 限流、配额与 LLM 成本护栏（Redis）

大模型是本项目唯一按次付费的依赖，且 `/rag/ask`、`/matches/refresh` 都公开可达，
没有闸门的话任何人写个循环就能刷爆 API 余额。计数落在 Redis：

```bash
docker compose up -d          # 同时起 MySQL 与 Redis
```

三道闸，逐层收紧：

| 闸门 | 默认值 | 作用 |
| --- | --- | --- |
| `IP_RATE_PER_MINUTE` | 60 | 单 IP 每分钟请求数，挡脚本刷接口 |
| `USER_DAILY_LLM_QUOTA` | 30 | 单身份每日 LLM 调用数，防一人刷爆 |
| `GLOBAL_DAILY_LLM_QUOTA` | 2000 | 全局每日上限，保护账户余额的最后一道 |

另有 LLM 结果缓存（`LLM_CACHE_TTL_SEC`，默认 24h）：相同输入直接复用，
实测重复提问从 3041ms 降到 30ms 且不产生费用。

**设计前提：Redis 不可用不能让主功能挂掉。** 限流是护栏而非业务本身，
连不上时按"放行 + 记一条告警"处理——宁可短时间失去保护，
也不能因为护栏故障把整个服务打死。已实测：停掉 Redis 后
`/health`、`/jobs`、`/rag/ask`、`/metrics` 全部照常返回 200。

用量可在 `GET /metrics` 查看：当日调用数、token 消耗、缓存命中/未命中、配额上限。

## 数据库迁移（Alembic）

结构变更一律走迁移，不要靠 `init_db()` 的 `create_all` —— 后者只补建缺失的表，
改列、加索引它一概不管，久了库结构会和 `models.py` 悄悄分叉。

连接串从 `DATABASE_URL` 读（与 `database.py` 同源），`alembic.ini` 里不配、配了也不生效。

```bash
alembic upgrade head                      # 建库/升级到最新
alembic downgrade -1                      # 回滚一步
alembic current                           # 当前版本
alembic check                             # 模型与库是否有差异（CI 会跑）

# 改完 models.py 后生成迁移，然后必须人工核对生成结果
alembic revision --autogenerate -m "描述"
```

两个已踩过的坑：

1. **已有数据的库首次接入用 `alembic stamp head`**，不要直接 `upgrade` ——
   表已存在会冲突。stamp 只写版本号，不碰表结构与数据。
2. **autogenerate 生成的 `downgrade()` 在 MySQL 上跑不通**：它会在 `drop_table`
   前逐个 `drop_index`，而 MySQL 拒绝删除被外键依赖的索引（错误 1553）。
   删表本就会连带删索引，所以初始迁移里那些 `drop_index` 已被手工移除。
   以后新增迁移若涉及删表，同样要检查这一点。

## 目录
```
main.py          应用入口，挂载路由（已实现）
config.py        环境变量配置（已实现）
database.py      引擎/会话（已实现）
models.py        11 张表（已实现，勿改字段约定；改动须配套 Alembic 迁移）
schemas.py       Pydantic DTO（已实现）
deps.py          当前用户依赖（stub：见下）
seed.py          种子数据（已实现）
routers/         jobs/profile/rules/matches/applications（CRUD 与流程已实现）
services/        业务逻辑（部分实现，部分 stub）
migrations/      Alembic 迁移脚本（env.py 从 DATABASE_URL 取连接串）
```

## 已实现（直接用，别重写）
- 全部 CRUD：岗位、配置、简历、模板、订阅规则。
- `services/rule_filter.py`：第一层规则过滤。
- `services/pipeline.py`：管道编排（规则→LLM→写 match_results，幂等）。
- `services/crawler.py:upsert_jobs`：岗位去重入库。
- 投递接口：单条 `POST /applications` 与 `POST /applications/batch-confirm`（批量确认，非全自动）。

## 待填/待接真实配置
> ✅ 已实现：`llm_match`（匹配）、`resume_tailor`（改写 + 反虚构 + PDF 渲染）、
> `mailer`（真实 SMTP）、微信登录（`services/auth.py` + `routers/auth.py` + `deps.py`）、
> 爬虫框架、限速、robots 检查、缓存、深圳教师人才网 `sz910`、深圳教师招聘网 `shenzhenjiaoshi` 抓取、来源策略接口。
> 服务器定时抓取模板（systemd service/timer）也已加入。
> SQLite 自动备份模板（systemd service/timer）也已加入。
> 剩余主要是你的真实账号配置和后续增加更多来源：

| 文件 | 函数 | 要做什么 | 为何留给后续 |
|------|------|---------|-------------|
| `services/crawler.py` | 新增更多官方/本土来源 | 当前 `sz910`、`shenzhenjiaoshi` 可抓；`sz_edu_bureau` 因 robots 限制会跳过。后续可增加允许抓取的官方源。 | 要逐站核对 robots 与真实 HTML 结构 |
| `services/resume_tailor.py` | `_maybe_upload_cos` | 用 cos-python-sdk-v5 上传 PDF 返回 URL | 需你的 COS 桶与密钥 |
| 阶段 3 | 简历 PDF→结构化 | 把上传 PDF 解析进 `resumes.structured_content`（可 LLM 抽取；先支持手填） | 增强项，非阻塞 |

**真实运行需配置的环境变量**：`DEEPSEEK_API_KEY`（设 `LLM_STUB_MODE=0`）、
`SMTP_*`（设 `MAILER_DRY_RUN=0`）、`WECHAT_APPID`/`WECHAT_SECRET`/`SESSION_SECRET`/`ADMIN_API_TOKEN`（设 `AUTH_DEV_MODE=0`）、
可选 `COS_*`。全不配时默认开发模式仍可端到端跑通。

## 红线（实现时不可破）
- 投递必须用户确认（单条或批量），**不做全自动投递**。
- 简历改写只能重组/突出/改措辞真实内容，**严禁虚构**经历/学历/证书/年限/技能；产出可核对的改动清单；draft 经审核才可投递。
- 爬虫合规：优先官方源，遵守 robots、限速、缓存；招聘方邮箱属个人信息，谨慎处理。

> 完整背景见同目录上层的 `实施方案_IMPLEMENTATION_PLAN.md`。
