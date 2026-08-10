"""登录相关：密码哈希、微信登录、会话令牌。

hash_password / verify_password: scrypt 口令哈希（标准库，无额外依赖）。
wechat_code_to_openid: 用小程序 wx.login 拿到的 code 换 openid。
make_token / verify_token: 用 HMAC 签发/校验会话令牌（无状态）。
真实运行需在环境变量配置 WECHAT_APPID / WECHAT_SECRET / SESSION_SECRET。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from config import settings

# --------------------------------------------------------------------------- #
# 口令哈希（scrypt）                                                            #
# --------------------------------------------------------------------------- #
# 选 scrypt 而非 bcrypt/argon2 是为了不引入依赖——它在标准库里。
#
# 参数：N=2^15, r=8, p=1，实测单次约 46ms（macOS arm64 / Python 3.12）。
# 内存占用 = 128 * N * r = 32MB。
#
# 一个必须显式处理的坑：hashlib.scrypt 的 maxmem 默认值会套用 OpenSSL 的
# 32MB 上限，而 N=2^15 恰好要 32MB，于是**默认参数下直接 ValueError**。
# N=2^14 (16MB) 可以不传 maxmem，2^15 及以上必须显式传。这里显式给 64MB。
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
SCRYPT_DKLEN = 32
SALT_BYTES = 16


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
        dklen=SCRYPT_DKLEN, maxmem=SCRYPT_MAXMEM,
    )


def hash_password(password: str) -> str:
    """产出自描述的哈希串：scrypt$N$r$p$salt_b64$hash_b64。

    把参数写进串里而不是只存哈希，是为了日后调高 N 时老用户仍能登录——
    验证时按**存储时的**参数重算，而不是按当前常量。
    盐用 secrets（CSPRNG），每个用户独立，不共用全局盐。
    """
    salt = secrets.token_bytes(SALT_BYTES)
    dk = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str | None) -> bool:
    """校验口令。任何解析失败都返回 False，不抛异常。

    用 hmac.compare_digest 而非 == ：后者是短路比较，比较耗时会随
    前缀匹配长度变化，理论上可被用来逐字节猜哈希。
    """
    if not stored:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _b64d(hash_b64)
        actual = _derive(password, _b64d(salt_b64), int(n_s), int(r_s), int(p_s))
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str | None) -> bool:
    """存储参数低于当前标准时返回 True，供登录成功后透明升级。"""
    if not stored:
        return False
    try:
        scheme, n_s, r_s, p_s, _salt, _hash = stored.split("$")
    except ValueError:
        return True
    if scheme != "scrypt":
        return True
    try:
        stored_n, stored_r, stored_p = int(n_s), int(r_s), int(p_s)
    except ValueError:
        return True
    # r、p 不是可以放在 tuple 里做字典序比较的"等级"参数；任何一项
    # 低于当前基线都应该在成功登录后升级，避免出现 N 升了而 r 降了却误判
    # 为"足够强"的情况。
    return (
        stored_n < SCRYPT_N
        or stored_r < SCRYPT_R
        or stored_p < SCRYPT_P
    )

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
