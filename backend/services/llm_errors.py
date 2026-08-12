"""把"用户没配 Key"翻译成前端能识别的 HTTP 响应。

单独抽出来是因为匹配、问答、简历改写三条链都要用同一套语义。
散在各个 router 里迟早会写出三种不同的提示语和三种不同的状态码，
前端就得为每条链各写一个分支。

选 409 而不是 400/403：
- 400 是"请求本身有问题"，但用户的问题没问题，是账号状态没准备好。
- 403 是"你无权"，会让人以为是权限问题，跑去找管理员。
- 409 Conflict 表达的是"当前资源状态与该操作冲突"，配好 Key 后同样的
  请求就能成功——这正是这里的情况。

响应体带 `code` 字段，前端按 code 分支，不去匹配中文提示语。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException

from services.llm_credentials import LLMCredential, NoUserKey, UserKeyUnreadable

T = TypeVar("T")

MISSING_KEY_CODE = "model_key_missing"
UNREADABLE_KEY_CODE = "model_key_unreadable"


def raise_for_missing_key(resolve: Callable[[], LLMCredential]) -> LLMCredential:
    """执行凭据解析，把两类"配置没准备好"翻译成 409。

    传的是 callable 而不是已解析好的凭据：解析动作本身会抛异常，
    调用方若先解析再传进来，就得在每个 router 里各写一遍 try/except。
    """
    try:
        return resolve()
    except NoUserKey:
        raise HTTPException(409, {
            "code": MISSING_KEY_CODE,
            "detail": "请先前往「我的 → 模型配置」添加 DeepSeek API Key",
        }) from None
    except UserKeyUnreadable:
        raise HTTPException(409, {
            "code": UNREADABLE_KEY_CODE,
            "detail": "已保存的 Key 无法解密，请到「我的 → 模型配置」重新保存一次",
        }) from None
