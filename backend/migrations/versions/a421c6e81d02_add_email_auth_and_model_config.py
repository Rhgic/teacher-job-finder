"""add email auth and user model config

Revision ID: a421c6e81d02
Revises: ff9660fb6eee
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a421c6e81d02"
down_revision: Union[str, Sequence[str], None] = "ff9660fb6eee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加邮箱登录字段，并创建用户模型配置表。

    users.openid 的 NOT NULL 约束需要放宽：已有微信用户仍用 openid，新邮箱
    用户没有 openid。SQLite 由 Alembic 的 batch 模式处理，MySQL 直接 ALTER。
    """
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "openid", existing_type=sa.String(length=64), nullable=True,
        )
        batch_op.add_column(sa.Column("email", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
        batch_op.create_index("ix_users_email", ["email"], unique=True)

    op.create_table(
        "user_model_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.String(length=4), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=32), nullable=False, server_default="deepseek-chat"),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("last_call_status", sa.String(length=32), nullable=True),
        sa.Column("last_call_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_model_configs_user_id", "user_model_configs", ["user_id"])


def downgrade() -> None:
    """此迁移故意不提供危险的在线回滚。

    回滚会删除用户密码字段与全部已加密 API Key；在 MySQL 还会遇到 unique
    索引依赖的差异。对这类包含用户凭据的数据结构，正确做法是新迁移修复，
    而不是让一次 downgrade 静默销毁数据。
    """
    raise RuntimeError(
        "a421c6e81d02 涉及用户凭据与加密 Key，禁止 downgrade；请用新迁移修复。"
    )
