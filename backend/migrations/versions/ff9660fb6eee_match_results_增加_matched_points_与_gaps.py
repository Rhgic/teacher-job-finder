"""match_results 增加 matched_points 与 gaps

Revision ID: ff9660fb6eee
Revises: 6c8f83ccd7f0
Create Date: 2026-07-23 18:56:18.794506

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff9660fb6eee'
down_revision: Union[str, Sequence[str], None] = '6c8f83ccd7f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加两列存 LLM 已经算出来的命中点与差距。

    这两项模型一直在输出、token 也一直在付，只是之前没有列可落，
    写库时被丢掉了，推荐页因此只能显示一个无法解释的分数。
    历史行这两列为 NULL，前端按"无拆解"渲染，不需要回填。
    """
    op.add_column('match_results', sa.Column('matched_points', sa.JSON(), nullable=True))
    op.add_column('match_results', sa.Column('gaps', sa.JSON(), nullable=True))


def downgrade() -> None:
    """纯加列，回滚就是删列；不涉及索引，没有 MySQL 1553 那个问题。"""
    op.drop_column('match_results', 'gaps')
    op.drop_column('match_results', 'matched_points')
