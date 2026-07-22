"""FastAPI 应用入口。

启动：
    pip install -r requirements.txt
    python seed.py            # 建表 + 种子数据
    uvicorn main:app --reload # 启动后访问 http://127.0.0.1:8000/docs

可观测性：
    每个请求分配 request_id，写入 JSON 日志并通过 X-Request-ID 响应头回传；
    5xx 响应体也带上该 ID，用户报错时凭这个 ID 就能在日志里捞到完整堆栈。
    指标见 GET /metrics（Prometheus 文本格式）。
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import TimeoutError as PoolTimeout

from database import init_db
from observability import (
    ObservabilityMiddleware,
    metrics_endpoint,
    request_id_ctx,
    setup_logging,
)
from routers import jobs, profile, rules, matches, applications, auth, crawl, meta, settings, rag

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 再接管一次日志：uvicorn 在模块导入之后才装自己的 handler，
    # 不重新配置的话它会用原生格式把多行堆栈打进来，冲掉 JSON 结构。
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    # 开发期自动建表；生产请改用 Alembic 迁移，移除此调用。
    init_db()
    logger.info("startup", extra={"extra_fields": {"event": "app_started"}})
    yield
    logger.info("shutdown", extra={"extra_fields": {"event": "app_stopped"}})


app = FastAPI(title="教师求职小程序 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(ObservabilityMiddleware)


@app.exception_handler(PoolTimeout)
async def pool_timeout_handler(request: Request, exc: PoolTimeout):
    """数据库连接池被占满时的响应。

    这不是"服务器内部错误"，而是"当前太忙"——语义上属于 503 而非 500，
    区分开才能让客户端知道值得重试，也能让监控把过载与真实 bug 分开统计。
    带 Retry-After，避免客户端立刻重试把过载放大。
    """
    request_id = getattr(request.state, "request_id", request_id_ctx.get())
    logger.warning(
        "db_pool_exhausted",
        extra={"extra_fields": {
            "request_id": request_id,
            "path": request.url.path,
            "hint": "并发已超出连接池容量，可调大 DB_POOL_SIZE / DB_MAX_OVERFLOW",
        }},
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "服务繁忙，请稍后重试。", "request_id": request_id},
        headers={"X-Request-ID": request_id, "Retry-After": "2"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底异常处理。

    默认行为是返回一句无上下文的 "Internal Server Error"，排查时只能去翻日志、
    还未必对得上是哪一次请求。这里把完整堆栈按 request_id 记进日志，
    响应体只回该 ID —— 既不泄露内部细节，又能让报障用户提供可定位的线索。
    """
    # 必须显式带上 request_id，不能依赖 ContextVar：
    # 处理 Exception 的 ServerErrorMiddleware 在本应用中间件的更外层，
    # 异常先穿过 ObservabilityMiddleware（其 finally 已 reset 掉 ContextVar），
    # 才会到达这里 —— 此时 request_id_ctx 取到的是默认值 "-"，
    # 日志就与请求对不上号，排障时凭用户报的 ID 反而查不到堆栈。
    request_id = getattr(request.state, "request_id", request_id_ctx.get())
    logger.exception(
        "unhandled_exception",
        extra={
            "extra_fields": {
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "exc_type": type(exc).__name__,
            }
        },
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误，请稍后重试。",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


app.add_route("/metrics", metrics_endpoint, methods=["GET"])

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(profile.router)
app.include_router(rules.router)
app.include_router(matches.router)
app.include_router(applications.router)
app.include_router(crawl.router)
app.include_router(meta.router)
app.include_router(settings.router)
app.include_router(rag.router)

# Web 演示前端：静态文件与 API 同源同端口，免配 CORS。
# 用 __file__ 定位目录，uvicorn 从任意 cwd 启动都能找到。
app.mount("/web", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")


@app.get("/", include_in_schema=False)
def root_to_web():
    return RedirectResponse("/web/")
