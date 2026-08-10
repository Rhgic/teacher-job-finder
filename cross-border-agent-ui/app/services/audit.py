"""审计记录。

只写结构化元数据：谁、对什么、做了什么。
禁止写入消息正文、邮箱、电话、密码或 token——审计表往往是权限最宽的表之一，
把敏感内容塞进去等于绕开了前面所有脱敏工作。
"""

from sqlalchemy.orm import Session

from app.models import AuditLog

# 允许出现在 meta 里的键。白名单而非黑名单：
# 黑名单挡不住以后新增的字段，白名单会强制你在加字段时想一下该不该记。
_ALLOWED_META_KEYS = {
    "risk_type",
    "risk_level",
    "intent",
    "lang",
    "draft_id",
    "review_id",
    "conversation_id",
    "generator",
    "citations_count",
    "decision",
    "reason_length",
    "run_id",
}


def _clean_meta(meta: dict | None) -> dict:
    if not meta:
        return {}
    return {k: v for k, v in meta.items() if k in _ALLOWED_META_KEYS}


def record(
    db: Session,
    *,
    tenant_id: int,
    actor_id: int | None,
    action: str,
    object_type: str,
    object_id: int | None = None,
    meta: dict | None = None,
) -> AuditLog:
    """写一条审计。调用方负责提交事务——审计必须与业务写在同一个事务里，
    否则会出现"业务成功、审计丢失"或反过来的不一致。"""
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        meta=_clean_meta(meta),
    )
    db.add(entry)
    return entry
