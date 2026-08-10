"""保存 Key 时的轻量校验。

为什么要真的调一次：只检查 "sk- 开头、长度够" 挡不住打错一位的 Key，
用户会以为配好了，直到第一次用 AI 功能才发现失败——而那时错误会出现在
匹配或问答的中途，比在设置页当场报错难懂得多。

为什么"轻量"：用 max_tokens=1 的最小请求，成本可忽略，但足以让
DeepSeek 判定鉴权与余额。不用 /models 之类的列表接口，因为那类接口
在部分网关上不校验余额，验证过了照样调不动。
"""
from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger("llm")

# 返回给调用方的失败分类。刻意不透传上游原文：那里面可能带着
# 请求 URL、甚至被回显的 Key 片段，直接抛给前端就是泄漏面。
Reason = str  # "invalid_key" | "insufficient_balance" | "network" | "unknown"

VERIFY_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


def verify_key(api_key: str, model: str) -> tuple[bool, Reason]:
    """向 DeepSeek 发一次最小请求，判断 Key 是否可用。

    返回 (是否可用, 失败原因)。任何情况下都不把 api_key 写进日志。
    """
    url = f"{settings.DEEPSEEK_BASE_URL}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=VERIFY_TIMEOUT,
        )
    except (httpx.TimeoutException, httpx.TransportError):
        # 网络问题不是"Key 无效"，不能因此拒绝保存并让用户以为 Key 错了。
        # 但也不能就此保存——保存了等于把未验证的 Key 当已验证。
        logger.warning("deepseek_verify_network_error", extra={"extra_fields": {
            "model": model}})
        return False, "network"

    if resp.status_code == 200:
        return True, ""

    # 401/403 = 鉴权失败；402 = 余额不足（DeepSeek 用它表示欠费）
    if resp.status_code in (401, 403):
        return False, "invalid_key"
    if resp.status_code == 402:
        return False, "insufficient_balance"

    logger.warning("deepseek_verify_unexpected_status", extra={"extra_fields": {
        "status": resp.status_code, "model": model}})
    return False, "unknown"
