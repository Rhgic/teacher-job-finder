"""observability 核心基建的单测。

只验证两块最易回归、又最影响线上排障的能力：
1. ObservabilityMiddleware 必须给每个响应回写 X-Request-ID，且复用上游传入的 ID；
2. JsonLogFormatter 必须把当前请求的 request_id 带进结构化日志。
"""
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

import observability
from observability import JsonLogFormatter, ObservabilityMiddleware, request_id_ctx


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def test_middleware_assigns_request_id_header():
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) == 16  # uuid4().hex[:16]


def test_middleware_reuses_incoming_request_id():
    client = TestClient(_make_app())
    resp = client.get("/ping", headers={"X-Request-ID": "probe-123"})
    assert resp.headers.get("X-Request-ID") == "probe-123"


def test_json_formatter_includes_request_id():
    token = request_id_ctx.set("rid-abc")
    try:
        record = logging.LogRecord(
            "app.request", logging.INFO, "path", 1, "hello", None, None
        )
        payload = json.loads(JsonLogFormatter().format(record))
        assert payload["request_id"] == "rid-abc"
        assert payload["msg"] == "hello"
        assert payload["level"] == "INFO"
    finally:
        request_id_ctx.reset(token)


def _route_labels(collector) -> set[str]:
    return {route for (_method, route, _status) in collector._requests}


def test_unmatched_paths_collapse_into_one_metric_label(monkeypatch):
    """扫描器打的 404 不能每条各占一个时间序列。

    线上 /metrics 曾被扫描器撑到 353 个 route 标签、其中 334 个是 404，
    因为未匹配路由会退回真实路径。计数器存在进程内存里且永不过期，
    所以这既是内存泄漏也让指标不可读。
    """
    collector = observability.Metrics()
    monkeypatch.setattr(observability, "metrics", collector)

    client = TestClient(_make_app())
    for path in ["/.env", "/.git/config", "/admin/storage/1", "/wp-login.php"]:
        assert client.get(path).status_code == 404

    assert _route_labels(collector) == {observability.UNMATCHED_ROUTE}


def test_matched_route_still_uses_its_template(monkeypatch):
    """归并只针对未匹配的路径，正常路由必须保留自己的模板标签。"""
    collector = observability.Metrics()
    monkeypatch.setattr(observability, "metrics", collector)

    client = TestClient(_make_app())
    client.get("/ping")

    assert _route_labels(collector) == {"/ping"}
