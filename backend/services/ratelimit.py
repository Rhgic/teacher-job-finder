"""LLM 调用的配额、限流与结果缓存，计数落在 Redis。

设计前提：**Redis 不可用不能让主功能挂掉**。
限流是护栏而非业务本身，Redis 连不上时按"放行 + 记日志"处理——
宁可短时间失去保护，也不能因为护栏故障把整个服务打死。
唯一的例外是全局熔断：那是花钱的最后一道闸，宁可误伤也不能漏。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger("ratelimit")

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

# 单个身份每日 LLM 调用上限（体验用户按令牌隔离，防止一人刷爆）
USER_DAILY_LLM_QUOTA = int(os.getenv("USER_DAILY_LLM_QUOTA", "30"))
# 全局每日 LLM 调用上限，超过即自动降级到 stub，保护账户余额
GLOBAL_DAILY_LLM_QUOTA = int(os.getenv("GLOBAL_DAILY_LLM_QUOTA", "2000"))
# 单 IP 每分钟请求上限，挡住脚本刷接口
IP_RATE_PER_MINUTE = int(os.getenv("IP_RATE_PER_MINUTE", "60"))
# LLM 结果缓存有效期：相同输入不重复付费
LLM_CACHE_TTL_SEC = int(os.getenv("LLM_CACHE_TTL_SEC", "86400"))

_client = None
_client_failed = False


def get_client():
    """惰性建连。失败只记一次日志，之后静默降级，避免刷屏。"""
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    try:
        import redis

        client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True,
            socket_connect_timeout=1, socket_timeout=1,
        )
        client.ping()
        _client = client
    except Exception as exc:  # noqa: BLE001 - 任何连接问题都降级，不区分类型
        _client_failed = True
        logger.warning(
            "redis unavailable, rate limiting disabled",
            extra={"extra_fields": {"error": str(exc)}},
        )
    return _client


def reset_client_for_tests() -> None:
    """测试用：清掉惰性缓存的连接与失败标记。"""
    global _client, _client_failed
    _client = None
    _client_failed = False


def _today() -> str:
    return time.strftime("%Y%m%d")


@dataclass
class QuotaVerdict:
    allowed: bool
    reason: str = ""
    remaining: int | None = None


def check_and_consume_llm_quota(identity: str) -> QuotaVerdict:
    """校验并占用一次 LLM 配额。identity 为用户 ID，缺省时用 anonymous。

    先查全局熔断再查个人配额：全局是保护账户余额的最后一道闸。
    """
    client = get_client()
    if client is None:
        return QuotaVerdict(allowed=True, reason="redis_unavailable")

    day = _today()
    global_key = f"llm:global:{day}"
    user_key = f"llm:user:{identity or 'anonymous'}:{day}"
    try:
        pipe = client.pipeline()
        pipe.incr(global_key)
        pipe.expire(global_key, 172800)
        pipe.incr(user_key)
        pipe.expire(user_key, 172800)
        global_count, _, user_count, _ = pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("quota check failed, allowing",
                       extra={"extra_fields": {"error": str(exc)}})
        return QuotaVerdict(allowed=True, reason="redis_error")

    if global_count > GLOBAL_DAILY_LLM_QUOTA:
        return QuotaVerdict(False, "global_quota_exceeded", 0)
    if user_count > USER_DAILY_LLM_QUOTA:
        return QuotaVerdict(False, "user_quota_exceeded", 0)
    return QuotaVerdict(True, remaining=max(0, USER_DAILY_LLM_QUOTA - user_count))


def check_ip_rate(ip: str) -> bool:
    """单 IP 每分钟请求数限制。Redis 不可用时放行。"""
    client = get_client()
    if client is None or not ip:
        return True
    key = f"rate:ip:{ip}:{int(time.time() // 60)}"
    try:
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 120)
        count, _ = pipe.execute()
        return count <= IP_RATE_PER_MINUTE
    except Exception:  # noqa: BLE001
        return True


def cache_get(key: str) -> str | None:
    client = get_client()
    if client is None:
        return None
    try:
        return client.get(f"llmcache:{key}")
    except Exception:  # noqa: BLE001
        return None


def cache_set(key: str, value: str) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.setex(f"llmcache:{key}", LLM_CACHE_TTL_SEC, value)
    except Exception:  # noqa: BLE001
        pass


def usage_snapshot() -> dict:
    """当日用量快照，供 /metrics 与运维查看。"""
    client = get_client()
    if client is None:
        return {"available": False}
    day = _today()
    try:
        used = int(client.get(f"llm:global:{day}") or 0)
        tokens = int(client.get(f"llm:tokens:{day}") or 0)
        hits = int(client.get(f"llm:cachehit:{day}") or 0)
        misses = int(client.get(f"llm:cachemiss:{day}") or 0)
    except Exception:  # noqa: BLE001
        return {"available": False}
    return {
        "available": True,
        "calls_today": used,
        "global_quota": GLOBAL_DAILY_LLM_QUOTA,
        "tokens_today": tokens,
        "cache_hits_today": hits,
        "cache_misses_today": misses,
    }


def record_tokens(total_tokens: int) -> None:
    client = get_client()
    if client is None or total_tokens <= 0:
        return
    try:
        key = f"llm:tokens:{_today()}"
        pipe = client.pipeline()
        pipe.incrby(key, total_tokens)
        pipe.expire(key, 172800)
        pipe.execute()
    except Exception:  # noqa: BLE001
        pass


def record_cache_event(hit: bool) -> None:
    client = get_client()
    if client is None:
        return
    try:
        key = f"llm:{'cachehit' if hit else 'cachemiss'}:{_today()}"
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 172800)
        pipe.execute()
    except Exception:  # noqa: BLE001
        pass
