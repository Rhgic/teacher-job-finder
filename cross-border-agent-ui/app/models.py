"""ORM 模型。

多租户约定：每张业务表都带 tenant_id，且所有查询必须从当前登录用户的租户开始。
V1 只演示一个租户，但表结构和查询习惯从第一天就按多租户写——事后再补 tenant_id
需要动到每一条 SQL，是最贵的返工之一。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Tenant(Base):
    """店铺租户。V1 只种一个，但隔离逻辑按多租户实现。"""

    __tablename__ = "tenants"

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    # 只存哈希。明文密码不进库、不进种子、不进日志。
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    # 仅两个角色：admin 可审批，agent 只能处理会话与采纳低风险草稿。
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()

    # 用户名在**租户内**唯一，而不是全局唯一。
    # 全局唯一在多租户下是错的：两家店都想有个叫 admin 的账号，
    # 第二家就建不出来——而这正是 SaaS 化时必然遇到的第一个冲突。
    __table_args__ = (Index("ix_users_tenant_username", "tenant_id", "username", unique=True),)


class Order(Base):
    """演示订单。数据来自 seed，不对接任何真实平台。"""

    __tablename__ = "orders"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    order_no: Mapped[str] = mapped_column(String(40), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    country: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    shipping_summary: Mapped[str | None] = mapped_column(Text)
    # 物流轨迹用 JSONB 存字符串数组；V1 没有独立轨迹表的必要。
    logistics_steps: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_orders_tenant_order_no", "tenant_id", "order_no", unique=True),)


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    keywords: Mapped[list | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    buyer_name: Mapped[str] = mapped_column(String(80), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("orders.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = _created()


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False, index=True
    )
    # buyer / agent；V1 不外发，agent 消息也只是内部记录
    sender: Mapped[str] = mapped_column(String(16), nullable=False)
    # 已脱敏正文。原始正文不入库——V1 没有任何业务需要它。
    body: Mapped[str] = mapped_column(Text, nullable=False)
    was_redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False, index=True
    )
    message_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("messages.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    intent: Mapped[str] = mapped_column(String(20), nullable=False)
    # 引用的 knowledge_articles.id 列表；空数组表示这条草稿没有政策依据。
    citations: Mapped[list | None] = mapped_column(JSONB)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    # pending_agent（待客服采纳）/ accepted（已采纳待发送）/ blocked（高风险，须审批）
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_agent")
    # deterministic / deepseek / deepseek_fallback——回退过的草稿必须能看出来
    generator: Mapped[str] = mapped_column(String(24), nullable=False, default="deterministic")
    created_at: Mapped[datetime] = _created()


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    draft_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drafts.id"), nullable=False)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False
    )
    # refund / compensation / settlement / payment / address_change
    risk_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    """审计：谁、在什么时间、对什么对象、做了什么。

    审批与采纳这类有业务后果的动作必须留痕，否则"人工兜底"只是句口号——
    出了问题无法回溯是谁放行的。
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    actor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    object_id: Mapped[int | None] = mapped_column(BigInteger)
    # 结构化元数据；禁止写入消息正文、邮箱、电话、token
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)


class IntegrationConfig(Base):
    """平台接入草稿。

    这张表只存**接入配置的草稿**，不存凭证、不代表任何已建立的连接：
    - 没有 api_key / access_token / client_secret 列，写不进来就漏不出去。
      不靠"记得别存"，靠表结构本身不给位置。
    - status 只有 draft 一种取值，刻意不提供 connected——
      本系统不做 OAuth、不发外部请求，任何"已连接"的展示都会是假的。
    真实平台授权与订单同步属于 V2，需真实店铺授权后实施。
    """

    __tablename__ = "integration_configs"

    id: Mapped[int] = _pk()
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    # shopify / amazon / tiktok_shop
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # manual（人工填写）/ guided（按平台自动生成接入清单）
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    store_identifier: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_scopes: Mapped[list | None] = mapped_column(JSONB)
    # 恒为 draft；取值范围由 schema 与 CHECK 约束共同守住
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # 同一租户下同平台同店铺只留一份草稿，避免演示时刷出一堆重复条目
        Index(
            "ix_integration_tenant_provider_store",
            "tenant_id",
            "provider",
            "store_identifier",
            unique=True,
        ),
        CheckConstraint(
            "provider in ('shopify','amazon','tiktok_shop')", name="ck_integration_provider"
        ),
        CheckConstraint("mode in ('manual','guided')", name="ck_integration_mode"),
        # 数据库层再兜一道：即使有人绕过 API 直接写库，也写不出 connected
        CheckConstraint("status = 'draft'", name="ck_integration_status_draft"),
    )
