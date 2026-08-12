"""LLM 调用的重试、缓存与用量记账测试。

重点是重试边界：5xx 与超时值得重试，4xx 是请求本身有问题，
重试一百次也是同样结果，只会白白拖慢响应并浪费配额。
"""
import httpx
import pytest

from services import llm_match, ratelimit
from services.llm_credentials import LLMCredential

# 测试用凭据：显式给出，不依赖任何全局配置。
# 这正是这次改造的目的——调用方必须说清用谁的 Key。
CRED = LLMCredential(api_key="sk-test-key", model="deepseek-chat")


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
    assert llm_match._call_deepseek("sys", "user", cred=CRED) == "hello"
    assert calls["n"] == 1


def test_retries_on_server_error_then_succeeds(monkeypatch):
    calls = _patch_post(monkeypatch, [_Resp(status_code=503), _Resp(content="recovered")])
    assert llm_match._call_deepseek("sys", "user", cred=CRED) == "recovered"
    assert calls["n"] == 2


def test_retries_on_timeout(monkeypatch):
    calls = _patch_post(monkeypatch, [httpx.ReadTimeout("slow"), _Resp(content="ok")])
    assert llm_match._call_deepseek("sys", "user", cred=CRED) == "ok"
    assert calls["n"] == 2


def test_does_not_retry_client_error(monkeypatch):
    """4xx 立即抛出：参数或鉴权问题重试无意义。"""
    calls = _patch_post(monkeypatch, [_Resp(status_code=400)])
    with pytest.raises(httpx.HTTPStatusError):
        llm_match._call_deepseek("sys", "user", cred=CRED)
    assert calls["n"] == 1


def test_gives_up_after_max_attempts(monkeypatch):
    calls = _patch_post(monkeypatch, [_Resp(status_code=500)])
    with pytest.raises(httpx.HTTPStatusError):
        llm_match._call_deepseek("sys", "user", cred=CRED)
    assert calls["n"] == llm_match.LLM_MAX_ATTEMPTS


def test_cache_hit_skips_network(monkeypatch):
    """相同输入第二次直接命中缓存，不再发请求，也就不再付费。"""
    store: dict[str, str] = {}
    monkeypatch.setattr(ratelimit, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(ratelimit, "cache_set", lambda k, v: store.__setitem__(k, v))

    calls = _patch_post(monkeypatch, [_Resp(content="cached-answer")])
    assert llm_match._call_deepseek("sys", "same", cred=CRED) == "cached-answer"
    assert llm_match._call_deepseek("sys", "same", cred=CRED) == "cached-answer"
    assert calls["n"] == 1


def test_different_prompt_misses_cache(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(ratelimit, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(ratelimit, "cache_set", lambda k, v: store.__setitem__(k, v))

    calls = _patch_post(monkeypatch, [_Resp(content="a"), _Resp(content="b")])
    llm_match._call_deepseek("sys", "prompt-1", cred=CRED)
    llm_match._call_deepseek("sys", "prompt-2", cred=CRED)
    assert calls["n"] == 2


def test_records_token_usage(monkeypatch):
    """DeepSeek 返回的 usage 必须记账，否则成本无从核算。"""
    recorded: list[int] = []
    monkeypatch.setattr(ratelimit, "record_tokens", recorded.append)
    _patch_post(monkeypatch, [_Resp(usage={"total_tokens": 777})])
    llm_match._call_deepseek("sys", "user", cred=CRED)
    assert recorded == [777]


def test_match_does_not_stack_another_retry_layer(monkeypatch):
    """match_resume_to_job 不得在 _call_deepseek 外面再套一层重试。

    内层已经重试 LLM_MAX_ATTEMPTS 次；外面再包一层会让最坏尝试次数翻倍
    （单次 timeout 60s，管道逐个岗位串行跑），这正是演示时"点了没反应"
    的来源。断言总的 HTTP 次数就等于内层上限。
    """
    calls = _patch_post(monkeypatch, [_Resp(status_code=500)])

    result = llm_match.match_resume_to_job("简历", "岗位JD", cred=CRED)

    assert calls["n"] == llm_match.LLM_MAX_ATTEMPTS
    assert result["score"] is None


def test_match_failure_reason_does_not_leak_exception_text(monkeypatch):
    """兜底文案会存进 match_results 并显示在推荐页，不能带异常原文。

    原实现是 f"LLM 匹配失败：{last_err}"，401 时异常里带着请求 URL。
    """
    _patch_post(monkeypatch, [_Resp(status_code=401)])

    reason = llm_match.match_resume_to_job("简历", "岗位JD", cred=CRED)["reason"]

    assert "api.deepseek.com" not in reason
    assert "HTTPStatusError" not in reason


def test_unparseable_response_is_evicted_from_cache(monkeypatch):
    """模型返回解析不了的内容时，不能把它留在缓存里。

    缓存是拿到 200 就写的（那时还没解析）。不删的话这份坏结果会被钉住
    一个 TTL，期间同一对（简历, 岗位）每次都命中缓存、每次都失败。
    """
    store: dict[str, str] = {}
    monkeypatch.setattr(ratelimit, "cache_get", lambda k: store.get(k))
    monkeypatch.setattr(ratelimit, "cache_set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(ratelimit, "cache_delete", lambda k: store.pop(k, None))

    _patch_post(monkeypatch, [_Resp(content="这不是 JSON")])
    assert llm_match.match_resume_to_job("简历", "岗位JD", cred=CRED)["score"] is None
    assert store == {}, "坏结果仍留在缓存里，后续请求会一直复现同一个失败"


def test_json_mode_toggles_response_format(monkeypatch):
    """rag_qa 走自然语言，必须不带 response_format，否则 DeepSeek 直接 400。"""
    seen: list[dict] = []

    def fake_post(*a, **k):
        seen.append(k["json"])
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    llm_match._call_deepseek("sys", "u", cred=CRED, json_mode=True)
    llm_match._call_deepseek("sys", "u", cred=CRED, json_mode=False)
    assert "response_format" in seen[0]
    assert "response_format" not in seen[1]
