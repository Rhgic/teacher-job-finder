# 深圳教师求职助手

抓取深圳公开教师招聘岗位，用**规则粗筛 + LLM 精排**两层管道生成可解释推荐，
并在用户逐条确认后辅助投递。Web 全栈 + 真实上线运行。

**在线体验**：<http://42.194.146.44/>（免注册，点「创建体验身份」即可，数据只存在你的浏览器）

> 定位：面试作品，不是运营中的招聘服务。刻意保留三条红线——不做全自动投递、
> 不编造简历内容、爬虫遵守 robots 与限速。这些约束在代码里是硬拦截，不是文档承诺。

---

## 这个项目想证明什么

不是"我会调大模型 API"。真正花力气的是**在成本、可靠性和真实性之间做取舍，并且用数字说话**：

| 问题 | 做法 | 实测结果 |
|---|---|---|
| LLM 按次付费，怎么不被刷爆 | 规则层先筛掉不可能的岗位，只把候选交给模型；再叠加 IP 限流 / 单人日配额 / 全局熔断 / 结果缓存 | 重复提问 3041ms → **30ms 且零费用** |
| 护栏本身挂了怎么办 | **降级优先于保护**：Redis 连不上时放行并告警，而不是拒绝服务 | 停掉 Redis 后 `/health` `/jobs` `/rag/ask` `/metrics` 全部照常 200 |
| RAG 会不会一本正经胡说 | 检索不到就短路，不进模型 | 4 道语料里没有答案的题，**拒答率 100%**；查询扩展把召回从 95% 提到 100% 而拒答率不变 |
| 高并发下会怎么死 | 压测定位到连接池耗尽，等待超时从 30s 压到 5s，过载返回 **503 + Retry-After** 而非 500 | 128 并发从「QPS 3、全部失败、等满 60 秒」变为「**QPS 257、零错误、P50 483ms**」 |
| 备份到底能不能恢复 | 写了恢复演练脚本，真的恢复到临时库并逐表比对 | **RTO 1.3 秒**，11 张表全到；同时诚实记录 **RPO = 24 小时**是短板 |
| 用户点一次匹配要等几十秒 | 改为 arq 异步队列 + 进度轮询；队列不可用时退回同步执行 | 点击即返回任务 ID，前端显示「已评 37/91 个岗位」 |

每一条背后的推理都写在对应文件的注释和 commit message 里，不是事后补的说明。

---

## 架构

```mermaid
flowchart TB
  subgraph sgTimer["定时任务 · systemd timer"]
    CR["爬虫<br/>robots + 2s 限速 + 30min 缓存"]
    BK["每日备份 → 恢复演练"]
  end

  subgraph sgOnline["在线请求"]
    WEB["Web 前端 · 8 页<br/>免注册体验身份"]
    API["FastAPI<br/>JSON 日志 · request_id · /metrics"]
  end

  subgraph sgAsync["异步"]
    WK["arq worker<br/>LLM 批量匹配"]
  end

  SRC["公开招聘站点"] --> CR
  CR -->|"(source, external_id) 去重"| DB[("MySQL 8<br/>Alembic 迁移")]
  BK --> DB

  WEB <--> API
  API --> DB
  API -->|入队| RD[("Redis<br/>限流 · 配额 · 缓存 · 队列")]
  RD --> WK
  WK -->|"进度 done/total"| RD
  WK --> DB

  API --> RULE["第一层：规则过滤<br/>区域 / 学段 / 学科 / 编制"]
  RULE --> LLM["第二层：DeepSeek 精排<br/>分数 + 理由 + 求职信"]
  LLM --> DB

  API --> CONF["用户逐条确认<br/>来源 / 材料 / 简历真实性"]
  CONF --> APP[("投递记录")]
```

**两层管道是成本控制的核心**：规则层是确定性 SQL，零成本地砍掉大部分岗位；
只有可能匹配的才进模型。这不是性能优化，是让这个项目在真实 API 计费下跑得起来的前提。

---

## 界面

岗位页把区域、学段、学科与编制收进筛选条，卡片集中展示薪资、截止时间与公告原文入口。

![岗位浏览与多条件筛选](docs/screenshots/jobs.png)

推荐页用"成绩单"式卡片呈现匹配分、评语与确认状态，让两阶段匹配的结果可被解释。

![AI 匹配成绩单](docs/screenshots/recommendations.png)

公告问答只依据已收录内容作答，并可展开查看实际命中的公告片段。

![RAG 公告问答与出处](docs/screenshots/rag-qa.png)

「我的」页支持粘贴或上传简历，用学段、学科、区域、编制圈定求职范围。

![简历上传与求职范围](docs/screenshots/profile-and-resume.png)

---

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | 原生 HTML/CSS/JS，8 个页面 | 由后端 StaticFiles 同源托管，无构建步骤、无 CORS |
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic v2 | `routers/` 与 `services/` 分层 |
| 数据库 | MySQL 8（utf8mb4）+ Alembic 迁移 | CI 有模型漂移检测；可切 SQLite 供单测 |
| 缓存/队列 | Redis 7 | 限流、日配额、LLM 结果缓存、arq 任务队列 |
| AI | DeepSeek（OpenAI 兼容） | `LLM_STUB_MODE=1` 时无需密钥即可端到端演示 |
| 爬虫 | httpx + 自研 `BaseCrawler` | robots、限速、缓存、去重做成基类能力 |
| 可观测 | JSON 结构化日志 + `request_id` 全链路 + `/metrics` | 含 LLM 调用数与 token 消耗 |
| 部署 | 云服务器 + systemd（API/worker/爬虫/备份）+ Nginx | |
| 质量 | pytest 122 项 + ruff + GitHub Actions | 含 31 项穿过完整栈的接口测试 |

> 仓库里的 `miniprogram/` 是早期的小程序版本，已不是主线，保留作演进记录。

---

## 本地运行

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d          # MySQL + Redis
.venv/bin/alembic upgrade head
.venv/bin/python seed.py
.venv/bin/uvicorn main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000/> 即是 Web 前端。默认 `LLM_STUB_MODE=1`、
`MAILER_DRY_RUN=1`、`AUTH_DEV_MODE=1`，**不配任何外部密钥就能端到端跑通**。

异步匹配需要另起 worker（不起也能用，会自动退回同步执行）：

```bash
cd backend && .venv/bin/arq services.tasks.WorkerSettings
```

## 测试与评测

```bash
cd backend
.venv/bin/python -m pytest              # 122 项
.venv/bin/ruff check .
.venv/bin/python scripts/eval_rag.py    # RAG 检索质量基线，出数字
.venv/bin/python scripts/verify_backup_restore.py   # 备份恢复演练
```

测试分两类：`test_api_endpoints.py` 走真实 HTTP 穿过路由、鉴权、序列化、
异常处理器；其余测纯函数逻辑。**接口层此前零覆盖，改坏了只能靠手工点页面才发现。**

## 目录

```text
backend/
  main.py            FastAPI 入口（含 503 过载处理、静态前端挂载）
  routers/           岗位、推荐、投递、档案、规则、爬虫、问答、状态
  services/          规则过滤、LLM 匹配、爬虫、简历改写、RAG、限流、任务队列
  web/               Web 前端（8 页 + assets）
  tests/             pytest（122 项，含 31 项接口级）
  scripts/           RAG 评测、压测、备份、恢复演练、定时抓取、上线检查
  migrations/        Alembic 迁移
  deploy/            systemd / Nginx 模板
docs/screenshots/    界面截图
miniprogram/         早期小程序版本（非主线）
```

详细的后端说明见 [backend/README.md](backend/README.md)，部署与故障恢复见
[backend/DEPLOYMENT.md](backend/DEPLOYMENT.md)。

---

## 合规边界

- 投递必须用户逐条确认，**不做全自动投递**。
- 简历改写只能重组、突出、润色**真实内容**，严禁编造学历、证书、经历、年限或技能；
  产出可核对的改动清单，草稿经审核才可投递。
- 爬虫优先官方来源，遵守 robots、限速与缓存；招聘方邮箱按个人信息谨慎处理。
- 后台接口 `/crawl/run`、`/pipeline/run` 在正式模式下需要 `X-Admin-Token`。

## 已知边界

写在这里是因为这些是清楚的取舍，不是没想到的疏漏：

- **RPO 24 小时**。每天备份一次，最坏丢一天数据。岗位可重爬，投递记录与简历不可再生；
  真要压低需要 binlog 增量备份或主从，当前规模下不值得。
- **单实例**。`/metrics` 的请求计数在进程内存里，多副本时各报各的数，
  需要改用 Redis 或 Prometheus 多进程模式才能汇总。连接池按单实例占 50 连接配置，
  并排跑超过 3 个实例要先调大 MySQL 的 `max_connections`。
- **RAG 未用向量检索**。DeepSeek 不提供 embedding 模型，改用查询扩展 + 词法打分；
  实测召回已到 100%，接真实 embedding 是增强而非补漏。
- **IP-only HTTP**，未备案故无域名与 HTTPS。
- 简历 PDF 结构化抽取仅覆盖常见排版；COS 上传留了接口未接密钥。
