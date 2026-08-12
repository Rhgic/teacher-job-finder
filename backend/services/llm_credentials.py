"""解析"这次调用该用谁的 Key 和哪个模型"。

设计要点：凭据是**显式参数**，不是从全局配置里捞。

原先 `_call_deepseek` 直接读 `settings.DEEPSEEK_API_KEY`，等于所有用户
共用服务器那把 Key。改成自带 Key 之后，最危险的不是"忘了改某个调用点"，
而是"改漏了但没人发现"——因为漏掉的那条路径会**静默地继续用服务器的 Key**
并正常返回结果，账单也照常产生，没有任何报错。

所以这里把凭据做成必填参数：调用方必须显式给出用谁的 Key。
漏改的地方会在导入或调用时直接 TypeError，而不是悄悄走老路。

Stub 模式仍然保留，但它是一个**显式的凭据种类**（`is_stub=True`），
不是"没有 Key 时的兜底"。生产逻辑不会把 stub 结果当成真实模型输出。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models import UserModelConfig
from services import crypto


class NoUserKey(Exception):
    """当前用户还没配置可用的 DeepSeek Key。

    这不是错误状态，是产品上的正常分支：前端据此引导用户去
    「我的 → 模型配置」，而不是显示一个失败的 AI 结果。
    """


class UserKeyUnreadable(Exception):
    """配置存在但解不开（主密钥换过、或密文被改动）。

    与 NoUserKey 分开：前者让用户去添加，后者要让用户重新保存一次 Key，
    引导语不同，混在一起会让用户反复添加却总是失败。
    """


@dataclass(frozen=True)
class LLMCredential:
    """一次 LLM 调用要用的凭据。api_key 只在内存中流转。"""

    api_key: str
    model: str
    is_stub: bool = False

    def __repr__(self) -> str:  # pragma: no cover - 只为防误打印
        """永远不要在 repr 里暴露 Key。

        调试时一句 print(cred) 或异常回溯里的局部变量展示就能把 Key
        写进日志。这里让它连自己都说不出口。
        """
        kind = "stub" if self.is_stub else "user"
        return f"<LLMCredential {kind} model={self.model} key=***>"


def stub_credential(model: str | None = None) -> LLMCredential:
    """开发/测试用的占位凭据。不会发出任何网络请求。"""
    return LLMCredential(
        api_key="", model=model or settings.DEEPSEEK_MODEL, is_stub=True,
    )


def resolve_for_user(db: Session, user_id: str) -> LLMCredential:
    """取该用户自己的 Key。

    LLM_STUB_MODE=1 时直接返回占位凭据——本地开发不配 Key 也要能跑通全链路。
    这条分支只在显式打开 stub 开关时生效，不是"用户没配 Key 时的兜底"。
    """
    if settings.LLM_STUB_MODE:
        return stub_credential()

    cfg = db.scalar(
        select(UserModelConfig).where(UserModelConfig.user_id == user_id)
    )
    if cfg is None:
        raise NoUserKey("尚未配置 DeepSeek API Key")

    try:
        api_key = crypto.decrypt(cfg.encrypted_key)
    except Exception as exc:  # noqa: BLE001 — InvalidToken 及其它解密失败
        raise UserKeyUnreadable("已保存的 Key 无法解密，请重新保存一次") from exc

    return LLMCredential(api_key=api_key, model=cfg.model)
