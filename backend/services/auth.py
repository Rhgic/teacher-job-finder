"""微信登录 + 会话令牌。

wechat_code_to_openid: 用小程序 wx.login 拿到的 code 换 openid。
make_token / verify_token: 用 HMAC 签发/校验会话令牌（无状态）。
真实运行需在环境变量配置 WECHAT_APPID / WECHAT_SECRET / SESSION_SECRET。
"""
from __future__ import annotations

import hashlib
import hmac

from config import settings

_WX_URL = "https://api.weixin.qq.com/sns/jscode2session"


def wechat_code_to_openid(code: str) -> str:
    """用 code 换取 openid。失败抛 ValueError。"""
    import httpx

    r = httpx.get(_WX_URL, params={
        "appid": settings.WECHAT_APPID,
        "secret": settings.WECHAT_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("openid"):
        raise ValueError(f"jscode2session 失败: {data}")
    return data["openid"]


def make_token(user_id: str) -> str:
    """签发会话令牌：user_id.签名。"""
    sig = hmac.new(settings.SESSION_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{sig}"


def verify_token(token: str) -> str | None:
    """校验令牌，返回 user_id；非法返回 None。"""
    try:
        user_id, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(settings.SESSION_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    return user_id if hmac.compare_digest(sig, expected) else None
