"""Initial V1 customer-support MVP schema.

Revision ID: 20260809_0001
Revises:
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260809_0001"
down_revision = None
branch_labels = None
depends_on = None


def _created_column() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False, unique=True),
        _created_column(),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _created_column(),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("order_no", sa.String(length=40), nullable=False),
        sa.Column("platform", sa.String(length=30), nullable=False),
        sa.Column("country", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("shipping_summary", sa.Text()),
        sa.Column("logistics_steps", postgresql.JSONB()),
        _created_column(),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_index("ix_orders_tenant_order_no", "orders", ["tenant_id", "order_no"], unique=True)
    op.create_table(
        "knowledge_articles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("keywords", postgresql.JSONB()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _created_column(),
    )
    op.create_index("ix_knowledge_articles_tenant_id", "knowledge_articles", ["tenant_id"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("buyer_name", sa.String(length=80), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("order_id", sa.BigInteger(), sa.ForeignKey("orders.id")),
        sa.Column("status", sa.String(length=20), nullable=False),
        _created_column(),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("sender", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("was_redacted", sa.Boolean(), nullable=False),
        _created_column(),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table(
        "drafts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("message_id", sa.BigInteger(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("generator", sa.String(length=24), nullable=False),
        _created_column(),
    )
    op.create_index("ix_drafts_tenant_id", "drafts", ["tenant_id"])
    op.create_index("ix_drafts_conversation_id", "drafts", ["conversation_id"])
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("draft_id", sa.BigInteger(), sa.ForeignKey("drafts.id"), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("risk_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewer_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("review_reason", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        _created_column(),
    )
    op.create_index("ix_review_tasks_tenant_id", "review_tasks", ["tenant_id"])
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("object_type", sa.String(length=30), nullable=False),
        sa.Column("object_id", sa.BigInteger()),
        sa.Column("meta", postgresql.JSONB()),
        _created_column(),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_tenant_created", "audit_logs", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("review_tasks")
    op.drop_table("drafts")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("knowledge_articles")
    op.drop_table("orders")
    op.drop_table("users")
    op.drop_table("tenants")
