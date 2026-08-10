"""用户自带 DeepSeek Key 的配置接口。

安全边界（本文件的全部要点）：
- 明文 Key 只在**单次请求的内存里**存在：进来做校验、加密、写库，然后丢弃。
- 响应体永远只回掩码，任何字段都不含明文或密文。
- 不写日志。这里刻意不加 logger.info(body) 之类的调试语句——
  一行随手加的日志就能把所有用户的 Key 写进磁盘。
- 读写都以当前登录用户为准，URL 上没有 user_id，也就不存在越权取别人配置的路径。
"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from deps import require_registered_user
from models import User, UserModelConfig
from services import crypto, deepseek_verify

router = APIRouter(prefix="/model-config", tags=["model-config"])

ALLOWED_MODELS = ("deepseek-chat", "deepseek-reasoner")


class ModelConfigIn(BaseModel):
    api_key: str
    model: Literal["deepseek-chat", "deepseek-reasoner"] = "deepseek-chat"

    @field_validator("api_key")
    @classmethod
    def _check_shape(cls, v: str) -> str:
        v = v.strip()
        # 只做形状检查，真假由下面的实际调用决定。
        # 报错信息里绝不能回显用户输入，否则错误响应就成了 Key 泄漏通道。
        if not v.startswith("sk-") or len(v) < 20:
            raise ValueError("DeepSeek API Key 格式不正确，应以 sk- 开头")
        return v


class ModelSelectIn(BaseModel):
    model: Literal["deepseek-chat", "deepseek-reasoner"]


def _view(cfg: UserModelConfig | None) -> dict:
    """对外视图。只有掩码，没有明文，没有密文，没有指纹。"""
    if cfg is None:
        return {
            "configured": False,
            "masked_key": None,
            "model": None,
            "last_verified_at": None,
            "last_call_status": None,
            "last_call_at": None,
            "allowed_models": list(ALLOWED_MODELS),
        }
    return {
        "configured": True,
        "masked_key": crypto.mask(cfg.key_last4),
        "model": cfg.model,
        "last_verified_at": cfg.last_verified_at.isoformat() if cfg.last_verified_at else None,
        "last_call_status": cfg.last_call_status,
        "last_call_at": cfg.last_call_at.isoformat() if cfg.last_call_at else None,
        "allowed_models": list(ALLOWED_MODELS),
    }


def _load(db: Session, user: User) -> UserModelConfig | None:
    return db.scalar(
        select(UserModelConfig).where(UserModelConfig.user_id == user.id)
    )


@router.get("")
def get_config(
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """当前用户的模型配置状态。未配置时 configured=False，前端据此引导。"""
    return _view(_load(db, user))


@router.put("")
def save_config(
    body: ModelConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """保存 Key：先向 DeepSeek 实际验证一次，**校验不过不写库**。

    顺序很重要——先验证后加密写库。反过来会让一个错 Key 先落库，
    用户以为配好了，直到第一次真正用 AI 功能才失败。
    """
    ok, reason = deepseek_verify.verify_key(body.api_key, body.model)
    if not ok:
        # reason 来自我们自己的分类（invalid_key / insufficient_balance / network），
        # 不是上游原文，避免把可能含 Key 片段的错误信息透回前端。
        raise HTTPException(400, {
            "invalid_key": "这个 API Key 无法通过 DeepSeek 验证，请检查后重试",
            "insufficient_balance": "Key 有效但账户余额不足，请先充值",
            "network": "暂时联系不上 DeepSeek，请稍后重试",
        }.get(reason, "Key 校验失败"))

    cfg = _load(db, user)
    # 项目现有表使用无时区的 UTC 时间；显式从 aware UTC 转换，避免 utcnow
    # 在 Python 3.12+ 的弃用警告，也不混入服务器本地时区。
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if cfg is None:
        cfg = UserModelConfig(user_id=user.id)
        db.add(cfg)

    cfg.encrypted_key = crypto.encrypt(body.api_key)
    cfg.key_last4 = body.api_key[-4:]
    cfg.key_fingerprint = crypto.fingerprint(body.api_key)
    cfg.model = body.model
    cfg.last_verified_at = now
    cfg.last_call_status = "verified"
    cfg.last_call_at = now
    db.commit()
    db.refresh(cfg)
    return _view(cfg)


@router.patch("")
def switch_model(
    body: ModelSelectIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """只换模型，不重新提交 Key。"""
    cfg = _load(db, user)
    if cfg is None:
        raise HTTPException(404, "尚未配置 API Key")
    cfg.model = body.model
    db.commit()
    db.refresh(cfg)
    return _view(cfg)


@router.delete("")
def delete_config(
    db: Session = Depends(get_db),
    user: User = Depends(require_registered_user),
):
    """删除 Key。整行删掉，不保留密文残留。"""
    cfg = _load(db, user)
    if cfg is not None:
        db.delete(cfg)
        db.commit()
    return {"configured": False, "deleted": True}
