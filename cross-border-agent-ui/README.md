# 跨境售后客服 Agent V1

一个用于技术面试演示的 FastAPI MVP。所有店铺、买家、订单、物流和知识库内容都是**演示数据**；未接入真实店铺、支付、物流或消息平台。

## 已实现

- PostgreSQL + SQLAlchemy + Alembic 的多租户表结构；业务查询都以当前用户 `tenant_id` 限定。
- JWT 登录（`admin`、`agent` 两角色），前端 token 只保存在运行内存。
- 演示会话、订单上下文、知识库关键词检索和最多 3 条引用。
- 买家消息处理链：邮箱/电话最小化脱敏、语言/意图/风险规则、模拟订单物流查询、确定性草稿、审计日志。
- 退款、赔付、结算、支付、地址修改自动创建人工审核单；客服不能审批，管理员可写理由通过或驳回。
- 低风险草稿可采纳为“待发送记录”。没有任何外发、退款、赔付或改地址动作。
- JSON 请求/Agent 日志，带 `request_id`/`run_id`，不记录消息原文、密码、JWT、邮箱或电话。
- 静态资源仅从 `web/` 挂载，源码、测试、迁移和环境文件不可通过 HTTP 访问。

## 演示数据边界

- 账号：`admin` / `agent`；默认密码均为 `demo1234`（可用 `SEED_PASSWORD` 修改）。
- `#CB-20512` 等订单、`Buyer-A（演示）` 等买家均为虚构演示数据。
- 默认是本地确定性草稿生成器；DeepSeek 是可选适配器。其调用失败时回退草稿并只记脱敏错误类别。

### 接入中心（V1.1）边界

「接入中心」是一个**接入配置的草稿管理台**，不是接入本身：

- 仅 admin 可访问；agent 前端不显示入口，后端对每个端点返回 403。草稿按 tenant 隔离，跨租户访问返回 404。
- **不接收、不存储任何 API Key / Access Token / Client Secret**：请求模型里没有这些字段（`extra="forbid"`），表里没有对应列，422 响应也已剥离 `input` 字段以免回显被拒的值。
- **不发起任何外部请求**，也不提供「测试连通性」端点——没有出口就没有 SSRF。
- 状态只有 `draft` 一种取值（schema、路由、数据库 CHECK 三处共同保证），**不存在 connected 或同步中**。
- 「引导配置」生成的是本地静态接入清单，其中的回调路径标注为「V2 预留回调路径（当前未启用）」；环境变量只给**名称**，不给值。
- OAuth 授权、Webhook 接收与验签、真实订单同步**全部属于 V2**，需真实店铺授权后实施。

## 未实现 / 上线前缺口

- 没有 OAuth、Webhook、真实订单/物流/支付/消息 API，也没有任何真实写平台能力。
- 没有生产级密钥托管、限流、监控告警、数据保留/删除流程、备份恢复演练或部署编排。
- 脱敏仅覆盖邮箱和常见电话号码；不声称覆盖人名、地址等全部 PII。

## 启动与测试

依赖通过 `uv` 安装；数据库必须是 PostgreSQL，项目不会静默换成 SQLite 或内存数据库。

```bash
cd /Users/rhgic/Documents/teacher-job-finder-claude/cross-border-agent-ui
cp .env.example .env

# 生成 JWT 签名密钥，把输出填进 .env 的 JWT_SECRET=
openssl rand -hex 32
```

`.env.example` 里的 `JWT_SECRET` 是**空值**，必须先填好再启动：该项为必填，且少于 32 字节会被拒绝启动（弱默认最容易被原样带上线，所以不提供默认值）。填好后继续：

```bash
docker compose up -d db
uv sync
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload --port 8099
```

打开 `http://127.0.0.1:8099`。另开终端运行测试：

```bash
uv run pytest
```

测试会连接 `localhost:5433` 并创建独立的 `cbagent_test` PostgreSQL 数据库；若 Docker 不可用，先启动一个可访问的 PostgreSQL，再在运行测试前设置 `DATABASE_URL` 为测试库连接串（示例：`postgresql+psycopg://user:password@host:5432/cbagent_test`）。应用启动则设置为业务库连接串。

### 本机验证记录

以下为实际执行结果，未经修饰：

- `docker compose up -d db`：使用 `postgres:16-alpine`，映射 `localhost:5433`，容器健康。
- 在**空白数据库**上执行 `alembic upgrade head`：成功，当前版本为 `7b460981f19c`（单一 head）。
- `python -m app.seed`：成功，5 个演示订单、35 条知识条目、4 个会话。
- `pytest -q`：`87 passed`，另有 2 条第三方依赖的弃用警告（starlette / python-json-logger），与本项目断言无关。
- `ruff check app/ tests/`：`All checks passed!`。
- 浏览器已验证：登录页、客服工作台、演示数据横幅，页面中不存在 GMV、商品、市场洞察等伪造业务模块；`/favicon.svg` 返回 200，控制台无错误。
- **浏览器已完整验证高风险退款链路**（在 `docker compose down -v` 重置后的空白演示库上从头走完）：
  1. 客服登录后选择 Buyer-B / `#CB-20485`，录入退款诉求；
  2. 草稿标记为「需人工审核 / blocked」，**不提供采纳按钮**，顶部「人工审核」计数变为 (1)，并弹出「系统未执行任何外部操作」；
  3. 客服打开人工审核页可看到该单，但**没有任何通过/驳回表单或按钮**；
  4. 退出后管理员登录，填写理由并通过；
  5. 该单状态变为 `approved`，页面展示审核人 `admin` 与审核理由，审批表单消失。
- 上述结论同时有 API 层测试覆盖：客服调用审批接口 403，管理员带理由审批 200，重复审批 409。
- 审核仅记录内部结论与责任人，不执行退款、赔付、地址修改，也不发送任何外部消息。
- 浏览器已验证接入中心：admin 可见入口并完成接入草稿的创建 → 列表展示 → 删除；agent 无入口（tab 隐藏）。页面无任何凭证输入框，`localStorage` / `sessionStorage` 均为空，列表只显示「草稿」，未出现 connected 或同步中。

## 建议的面试演示

1. 用 `agent / demo1234` 登录，选择 Buyer-A，输入 `Where is order #CB-20512?`。
2. 展示订单上下文、带知识库引用的低风险草稿，点击“采纳为待发送记录”；强调不会外发。
3. 输入 `I want a refund for order #CB-20512`，展示自动创建的退款审核单。
4. 仍用 agent 打开审核页，说明没有审批按钮；退出后用 `admin / demo1234` 登录，填写理由并通过或驳回。
