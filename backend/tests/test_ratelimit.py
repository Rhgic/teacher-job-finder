"""配额、限流与降级测试。

最关键的一条是降级：限流是护栏而非业务本身，
Redis 挂掉时必须放行并记日志，绝不能把主功能一起带走。
单测不连真实 Redis，用假客户端覆盖各分支。
"""
import pytest

from services import ratelimit


class FakeRedis:
    """够用的内存版 Redis：只实现被用到的命令与 pipeline 语义。"""

    def __init__(self, fail: bool = False):
        self.store: dict[str, int] = {}
        self.fail = fail

    def ping(self):
        if self.fail:
            raise ConnectionError("down")
        return True

    def get(self, key):
        if self.fail:
            raise ConnectionError("down")
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, client: FakeRedis):
        self.client = client
        self.ops: list = []

    def incr(self, key):
        self.ops.append(("incr", key, 1))
        return self

    def incrby(self, key, amount):
        self.ops.append(("incr", key, amount))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    def execute(self):
        if self.client.fail:
            raise ConnectionError("down")
        results = []
        for op, key, val in self.ops:
            if op == "incr":
                self.client.store[key] = int(self.client.store.get(key, 0)) + val
                results.append(self.client.store[key])
            else:
                results.append(True)
        self.ops.clear()
        return results


@pytest.fixture
def fake(monkeypatch):
    client = FakeRedis()
    ratelimit.reset_client_for_tests()
    monkeypatch.setattr(ratelimit, "get_client", lambda: client)
    return client


@pytest.fixture
def no_redis(monkeypatch):
    ratelimit.reset_client_for_tests()
    monkeypatch.setattr(ratelimit, "get_client", lambda: None)


def test_quota_allows_until_limit(fake, monkeypatch):
    monkeypatch.setattr(ratelimit, "USER_DAILY_LLM_QUOTA", 3)
    for _ in range(3):
        assert ratelimit.check_and_consume_llm_quota("u1").allowed
    verdict = ratelimit.check_and_consume_llm_quota("u1")
    assert not verdict.allowed
    assert verdict.reason == "user_quota_exceeded"


def test_quota_is_per_identity(fake, monkeypatch):
    """一个用户刷爆自己的额度，不该影响其他用户。"""
    monkeypatch.setattr(ratelimit, "USER_DAILY_LLM_QUOTA", 2)
    for _ in range(3):
        ratelimit.check_and_consume_llm_quota("noisy")
    assert ratelimit.check_and_consume_llm_quota("quiet").allowed


def test_global_quota_trips_before_user_quota(fake, monkeypatch):
    """全局熔断是保护账户余额的最后一道闸，优先于个人配额生效。"""
    monkeypatch.setattr(ratelimit, "USER_DAILY_LLM_QUOTA", 100)
    monkeypatch.setattr(ratelimit, "GLOBAL_DAILY_LLM_QUOTA", 2)
    ratelimit.check_and_consume_llm_quota("a")
    ratelimit.check_and_consume_llm_quota("b")
    verdict = ratelimit.check_and_consume_llm_quota("c")
    assert not verdict.allowed
    assert verdict.reason == "global_quota_exceeded"


def test_ip_rate_limit(fake, monkeypatch):
    monkeypatch.setattr(ratelimit, "IP_RATE_PER_MINUTE", 2)
    assert ratelimit.check_ip_rate("1.2.3.4")
    assert ratelimit.check_ip_rate("1.2.3.4")
    assert not ratelimit.check_ip_rate("1.2.3.4")


def test_degrades_open_when_redis_missing(no_redis):
    """Redis 不可用时放行——护栏故障不该让主功能不可用。"""
    verdict = ratelimit.check_and_consume_llm_quota("u1")
    assert verdict.allowed
    assert verdict.reason == "redis_unavailable"
    assert ratelimit.check_ip_rate("1.2.3.4")


def test_degrades_open_when_redis_errors(monkeypatch):
    """连上了但命令失败，同样放行而不是抛异常。"""
    broken = FakeRedis(fail=True)
    ratelimit.reset_client_for_tests()
    monkeypatch.setattr(ratelimit, "get_client", lambda: broken)
    assert ratelimit.check_and_consume_llm_quota("u1").allowed
    assert ratelimit.check_ip_rate("1.2.3.4")
    assert ratelimit.cache_get("k") is None      # 不抛异常
    ratelimit.cache_set("k", "v")                # 不抛异常
    ratelimit.record_tokens(100)                 # 不抛异常


def test_cache_roundtrip(fake):
    assert ratelimit.cache_get("k1") is None
    ratelimit.cache_set("k1", "answer")
    assert ratelimit.cache_get("k1") == "answer"


def test_usage_snapshot_reports_counts(fake, monkeypatch):
    monkeypatch.setattr(ratelimit, "GLOBAL_DAILY_LLM_QUOTA", 500)
    ratelimit.check_and_consume_llm_quota("u1")
    ratelimit.record_tokens(1234)
    ratelimit.record_cache_event(hit=True)
    snap = ratelimit.usage_snapshot()
    assert snap["available"] is True
    assert snap["calls_today"] == 1
    assert snap["tokens_today"] == 1234
    assert snap["cache_hits_today"] == 1
    assert snap["global_quota"] == 500


def test_usage_snapshot_when_unavailable(no_redis):
    assert ratelimit.usage_snapshot() == {"available": False}
