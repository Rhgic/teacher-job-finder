"""FastAPI 应用：异常处理、请求日志、静态前端挂载。

安全要点：只托管 web/ 目录。
原实现是 StaticFiles(directory=HERE)，把整个项目根目录当静态资源暴露——
意味着 backend.py、test_backend.py、.env 都能被 HTTP 直接下载。
这里改为只挂 web/，后端源码、测试、迁移与种子文件都不在可访问路径上。
"""

import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pythonjsonlogger import jsonlogger

from app.config import get_settings
from app.routers import auth, conversations, health, integrations, knowledge, reviews

settings = get_settings()

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())


_setup_logging()
log = logging.getLogger("app.request")

app = FastAPI(
    title="跨境售后客服 Agent · V1",
    version="1.0.0",
    description="演示数据，未接入真实店铺、物流或支付平台。AI 只生成草稿，不执行资金操作。",
    # 生产环境关掉交互文档，减少信息暴露面
    docs_url="/docs" if settings.app_env == "dev" else None,
    redoc_url=None,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """给每个请求生成 request_id，并记录耗时与状态。

    刻意不记录请求体：买家消息可能含 PII，日志不是它该待的地方。
    """
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception(
            "request_failed",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        raise
    log.info(
        "request",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """统一 500：不把堆栈或异常原文返回给客户端。"""
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务内部错误",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 响应里剔除 input / ctx——绝不回显被拒绝的原始值。

    踩过的坑：接入中心用 extra="forbid" 拒收 api_key 等凭证字段，
    值确实没落库，但 Pydantic 默认会把它放进 `input` 字段回显给调用方。
    只要有任何环节记录响应体（网关日志、前端埋点、错误上报），凭证就泄了。
    "不落库"不等于"不泄露"——出站方向同样要堵。
    """
    safe = [
        {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": safe, "request_id": getattr(request.state, "request_id", None)},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(reviews.router)
app.include_router(knowledge.router)
app.include_router(integrations.router)

# 只暴露 web/ —— 必须放在所有 API 路由之后挂载，否则会吞掉 /api/*
class NoStoreStaticFiles(StaticFiles):
    """静态资源一律 no-store。

    为什么不在 index.html 手写 `?v=1`：那要求每次改完样式都记得递增，
    忘一次就前功尽弃——而"忘记"恰恰是最容易发生的。实测踩过一次：
    styles.css 已修好、服务端也返回了新内容，浏览器却仍在用缓存的旧版，
    差点据此得出"修复无效"的错误结论。

    演示项目没有 CDN、没有构建指纹，正确性远比缓存命中率重要，
    所以直接在响应层关掉缓存，让"刷新即最新"成为不需要记忆的默认行为。

    同时覆盖 is_not_modified：否则 StaticFiles 仍会按 ETag/Last-Modified
    回 304，浏览器照样复用本地旧副本，no-store 就形同虚设。
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store"
        return response

    def is_not_modified(self, *args, **kwargs) -> bool:  # type: ignore[override]
        return False


if WEB_DIR.is_dir():
    # 仍然只挂 web/：后端源码、测试、迁移与 .env 都不在可访问路径上。
    app.mount("/", NoStoreStaticFiles(directory=str(WEB_DIR), html=True), name="web")
