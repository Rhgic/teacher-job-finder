"""用户 API Key 的服务端加密。

用 Fernet（AES-128-CBC + HMAC-SHA256）而不是裸 AES：它是**认证加密**，
密文被改动后解密会直接抛 InvalidToken，而不是悄悄给出一段垃圾明文。
库来自 cryptography，已因 MySQL 的 caching_sha2 认证在依赖里，不新增。

主密钥来自环境变量 APP_ENCRYPTION_KEY，必须是 Fernet 格式
（32 字节 urlsafe-base64）。生成方式：

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

**缺失时拒绝启动，不做静默降级。** 一个"没配密钥就明文存"的兜底分支，
出事时只会让所有人的 Key 一起裸奔，而且没人会注意到。测试环境由
tests/conftest.py 显式注入固定测试密钥——显式注入和静默降级的区别在于
前者必须有人写一行代码，后者只要忘记配就自动发生。
"""
from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config import settings


class EncryptionNotConfigured(RuntimeError):
    """APP_ENCRYPTION_KEY 缺失或格式非法。"""


def _fernet() -> Fernet:
    raw = (settings.APP_ENCRYPTION_KEY or "").strip()
    if not raw:
        raise EncryptionNotConfigured(
            "APP_ENCRYPTION_KEY 未配置。用户 API Key 必须加密存储，"
            "不允许在未配置密钥的情况下运行。生成方法见 services/crypto.py 文档字符串。"
        )
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise EncryptionNotConfigured(
            "APP_ENCRYPTION_KEY 格式非法，需要 32 字节 urlsafe-base64。"
        ) from exc


def verify_configured() -> None:
    """启动时调用：密钥缺失或非法就让进程起不来。"""
    _fernet()


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """解密。密文被篡改或换过主密钥会抛 InvalidToken，调用方需处理。"""
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def fingerprint(plaintext: str) -> str:
    """明文指纹，用于判断"是否换了 Key"而不必解密比较。

    这是不可逆摘要，不能反推明文；但它足以让攻击者验证某个猜测的 Key
    是否就是库里那个，所以同样不该出现在响应或日志里。
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:32]


def mask(plaintext_or_last4: str) -> str:
    """展示用掩码：sk-****abcd。传完整 Key 或只传后四位都可以。"""
    last4 = plaintext_or_last4[-4:] if plaintext_or_last4 else "????"
    return f"sk-****{last4}"


__all__ = [
    "EncryptionNotConfigured", "InvalidToken",
    "verify_configured", "encrypt", "decrypt", "fingerprint", "mask",
]
