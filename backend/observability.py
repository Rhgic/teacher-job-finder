"""可观测性：结构化日志、请求追踪、指标采集。

设计目标是"线上出问题能定位"：
1. 每个请求分配 request_id，贯穿日志与错误响应，用户报错时报这个 ID 就能捞到全链路。
2. 日志输出 JSON，可直接被 Loki / ELK / CloudWatch 解析，不用写正则。
3. 记录每个请求的耗时与状态码，慢接口和错误率一眼可见。

依赖保持零外部包：指标用标准库自实现，避免为一个演示项目引入 prometheus_client。
输出格式遵循 Prometheus 文本协议，Grafana 可直接抓取。
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

# 贯穿单个请求生命周期的追踪 ID。用 ContextVar 而非线程局部，
# 因为 FastAPI 是 async 的，同一线程会交错处理多个请求。
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class JsonLogFormatter(logging.Formatter):
    """把日志渲染成单行 JSON，并自动带上当前请求的 request_id。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        # 通过 logger.info(..., extra={"extra_fields": {...}}) 传入的结构化字段
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """把根 logger 换成 JSON 输出。重复调用安全（先清空已有 handler）。

    需要调用两次：模块导入时一次（保证早期日志也是 JSON），
    应用 startup 时再一次 —— 因为 uvicorn 是在导入之后才配置自己的 logger，
    会重新装上原生格式的 handler，把多行堆栈直接打到 stdout，
    污染结构化日志流（日志采集端就再也解析不了了）。
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn 自带的 access 日志是非结构化的，且与我们的请求日志重复，直接关掉。
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False

    # uvicorn / uvicorn.error 保留（服务器级错误仍需可见），
    # 但摘掉它们自己的 handler，改为向上冒泡到根 logger，统一走 JSON 格式。
    for name in ("uvicorn", "uvicorn.error"):
        target = logging.getLogger(name)
        target.handlers.clear()
        target.propagate = True


class Metrics:
    """极简指标仓库，输出 Prometheus 文本格式。

    只保留够用的三类：请求计数（按路由/方法/状态码）、
    耗时直方图（固定分桶）、当前进行中的请求数。
    """

    # 单位秒，覆盖从 5ms 到 5s 的常见区间
    BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)
        self._in_progress = 0

    def request_started(self) -> None:
        with self._lock:
            self._in_progress += 1

    def request_finished(self, method: str, route: str, status: int, duration: float) -> None:
        with self._lock:
            self._in_progress -= 1
            self._requests[(method, route, status)] += 1
            self._duration_sum[(method, route)] += duration
            self._duration_count[(method, route)] += 1
            for bucket in self.BUCKETS:
                if duration <= bucket:
                    self._duration_buckets[(method, route, bucket)] += 1

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []
            lines.append("# HELP http_requests_total 按方法/路由/状态码统计的请求总数")
            lines.append("# TYPE http_requests_total counter")
            for (method, route, status), count in sorted(self._requests.items()):
                lines.append(
                    f'http_requests_total{{method="{method}",route="{route}",status="{status}"}} {count}'
                )

            lines.append("# HELP http_request_duration_seconds 请求耗时分布")
            lines.append("# TYPE http_request_duration_seconds histogram")
            for (method, route), count in sorted(self._duration_count.items()):
                cumulative = 0
                for bucket in self.BUCKETS:
                    cumulative = self._duration_buckets.get((method, route, bucket), 0)
                    lines.append(
                        f'http_request_duration_seconds_bucket{{method="{method}",'
                        f'route="{route}",le="{bucket}"}} {cumulative}'
                    )
                lines.append(
                    f'http_request_duration_seconds_bucket{{method="{method}",'
                    f'route="{route}",le="+Inf"}} {count}'
                )
                lines.append(
                    f'http_request_duration_seconds_sum{{method="{method}",route="{route}"}} '
                    f"{self._duration_sum[(method, route)]:.6f}"
                )
                lines.append(
                    f'http_request_duration_seconds_count{{method="{method}",route="{route}"}} {count}'
                )

            lines.append("# HELP http_requests_in_progress 当前正在处理的请求数")
            lines.append("# TYPE http_requests_in_progress gauge")
            lines.append(f"http_requests_in_progress {self._in_progress}")
            return "\n".join(lines) + "\n"


metrics = Metrics()
logger = logging.getLogger("app.request")


def _route_template(request: Request) -> str:
    """取路由模板而非真实路径。

    /jobs/abc-123 与 /jobs/def-456 必须归并成 /jobs/{job_id}，
    否则每个 ID 都会生成一条独立时间序列，把指标基数撑爆。
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """分配 request_id、记录耗时与结果、回写追踪响应头。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 上游（网关/前端）传了就复用，便于跨服务串联；没有就新建
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id

        metrics.request_started()
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            route = _route_template(request)
            metrics.request_finished(request.method, route, status, duration)
            logger.info(
                "request",
                extra={
                    "extra_fields": {
                        "method": request.method,
                        "path": request.url.path,
                        "route": route,
                        "status": status,
                        "duration_ms": round(duration * 1000, 2),
                        "client": request.client.host if request.client else None,
                    }
                },
            )
            request_id_ctx.reset(token)


def _llm_metrics() -> str:
    """LLM 用量指标。

    大模型是这个系统里唯一按次付费的依赖，只观测 HTTP 层看不到钱花在哪，
    因此把调用数、token 消耗、缓存命中单独暴露出来。
    计数存在 Redis，Redis 不可用时整段省略而不是报错。
    """
    from services import ratelimit

    snap = ratelimit.usage_snapshot()
    if not snap.get("available"):
        return ""
    hits, misses = snap["cache_hits_today"], snap["cache_misses_today"]
    lines = [
        "# HELP llm_calls_today 当日 LLM 调用次数（含被缓存挡下的）",
        "# TYPE llm_calls_today gauge",
        f"llm_calls_today {snap['calls_today']}",
        "# HELP llm_daily_quota 当日全局配额上限，超过即自动降级为占位实现",
        "# TYPE llm_daily_quota gauge",
        f"llm_daily_quota {snap['global_quota']}",
        "# HELP llm_tokens_today 当日 token 消耗总量",
        "# TYPE llm_tokens_today gauge",
        f"llm_tokens_today {snap['tokens_today']}",
        "# HELP llm_cache_events_today 当日 LLM 结果缓存命中与未命中",
        "# TYPE llm_cache_events_today gauge",
        f'llm_cache_events_today{{result="hit"}} {hits}',
        f'llm_cache_events_today{{result="miss"}} {misses}',
    ]
    return "\n".join(lines) + "\n"


async def metrics_endpoint(_: Request) -> PlainTextResponse:
    """Prometheus 抓取端点。"""
    body = metrics.render() + _llm_metrics()
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")
