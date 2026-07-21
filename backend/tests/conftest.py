"""测试全局夹具。

单元测试不得依赖外部服务的在场与否：本机开着 Redis 和 CI 里没有 Redis，
必须跑出同样的结果。ratelimit 模块用模块级变量缓存连接，
一旦某个用例连上真实 Redis，这个连接会泄漏给后续用例，
表现为"本地偶发失败、CI 却正常"这类最难查的问题。

因此默认把每个用例都置于"Redis 不可用"状态；
需要验证计数逻辑的用例自行注入假客户端（见 test_ratelimit.py）。
"""
import pytest


@pytest.fixture(autouse=True)
def isolate_redis(monkeypatch):
    from services import ratelimit

    # 指向不可路由地址，兜住任何绕过 get_client 的直连尝试
    monkeypatch.setattr(ratelimit, "REDIS_URL", "redis://127.0.0.1:1/0")
    ratelimit.reset_client_for_tests()
    monkeypatch.setattr(ratelimit, "get_client", lambda: None)
    yield
    ratelimit.reset_client_for_tests()
