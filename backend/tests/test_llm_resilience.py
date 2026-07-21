"""LLM 调用的重试、缓存与用量记账测试。

重点是重试边界：5xx 与超时值得重试，4xx 是请求本身有问题，
重试一百次也是同样结果，只会白白拖慢响应并浪费配额。
"""
import httpx
import pytest

from services import llm_match, ratelimit


class _Resp:
    def __init__(self, status_code=200, content="ok", usage=None):
        self.status_code = status_code
        self._content = content
        self._usage = usage or {"total_tokens": 42, "prompt_tokens": 30}
        self.request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        self.text = str(content)

    def json(self):
        return {"choices": [{"message": {"content": self._content}}], "usage": self._usage}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=self.request, response=self)


@pytest.fixture(autouse=True)
def _no_redis_no_sleep(monkeypatch):
    """隔离 Redis 与真实退避等待，让用例快速且独立。"""
    ratelimit.reset_client_for_tests()
    monkeypatch.setattr(ratelimit, "get_client", lambda: None)
    monkeypatch.setattr(llm_match.time, "sleep", lambda _s: None)


def _patch_post(monkeypatch, responses):
    """按序返回预设响应；元素是异常则抛出。返回调用计数器。"""
    calls = {"n": 0}

    def fake_post(*a, **k):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_succeeds_on_first_try(monkeypatch):
    calls = _patch_post(monkeypatch, [_Resp(content="hello")])
    assert llm_match._call_deepseek("sys", "user") == "hello"
    assert calls["n"] == 1


def test_retries_on_server_error_then_succeeds(monkeypatch):
    calls = _patch_post(monkeypatch, [_Resp(status_code=503), _Resp(content="recovered")])
    assert llm_match._call_deepseek("sys", "user") == "recovered"
    assert calls["n"] == 2


def test_retries_on_timeout(monkeypatch):
    calls = _patch_post(monkeypatch, [httpx.ReadTimeout("slow"), _Resp(content="ok")])
    assert llm_match._call_deepseek("sys", "user") == "ok"
    assert calls["n"] == 2


def test_does_not_retry_client_error(monkeypatch):
    """4xx 立即抛出：参数或鉴权问题重试无意义。"""
    calls = _patch_post(monkeypatch, [_Resp(status_code=400)])
    with pytest.raises(httpx.HTTPStatusError):
        llm_match._call_deepseek("sys", "user")
    assert calls["n"] == 1


def test_gives_up_after_max_attempts(monkeypatch):
    calls = _patch_post(monkeypatch, [_Resp(status_code=500)])
    with pytest.raises(httpx.HTTPStatusError):
        llm_match._call_deepseek("sys", "user")
    assert calls["n"] == llm_match.LLM_MAX_ATTEMPTS


def test_cache_hit_skips_network(monkeypatch):
    """相同输入第二次直接命中缓存，不再发请求，也就不再付费。"""
    store: dict[str, str] = {}
    monkeypatch.setattr(ratelimit, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(ratelimit, "cache_set", lambda k, v: store.__setitem__(k, v))

    calls = _patch_post(monkeypatch, [_Resp(content="cached-answer")])
    assert llm_match._call_deepseek("sys", "same") == "cached-answer"
    assert llm_match._call_deepseek("sys", "same") == "cached-answer"
    assert calls["n"] == 1


def test_different_prompt_misses_cache(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(ratelimit, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(ratelimit, "cache_set", lambda k, v: store.__setitem__(k, v))

    calls = _patch_post(monkeypatch, [_Resp(content="a"), _Resp(content="b")])
    llm_match._call_deepseek("sys", "prompt-1")
    llm_match._call_deepseek("sys", "prompt-2")
    assert calls["n"] == 2


def test_records_token_usage(monkeypatch):
    """DeepSeek 返回的 usage 必须记账，否则成本无从核算。"""
    recorded: list[int] = []
    monkeypatch.setattr(ratelimit, "record_tokens", recorded.append)
    _patch_post(monkeypatch, [_Resp(usage={"total_tokens": 777})])
    llm_match._call_deepseek("sys", "user")
    assert recorded == [777]


def test_json_mode_toggles_response_format(monkeypatch):
    """rag_qa 走自然语言，必须不带 response_format，否则 DeepSeek 直接 400。"""
    seen: list[dict] = []

    def fake_post(*a, **k):
        seen.append(k["json"])
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    llm_match._call_deepseek("sys", "u", json_mode=True)
    llm_match._call_deepseek("sys", "u", json_mode=False)
    assert "response_format" in seen[0]
    assert "response_format" not in seen[1]
