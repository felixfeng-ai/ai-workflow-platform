"""add workflow edges

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-23 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """工作流从「线性 steps」升级为「图」：新增 edges，运行记录加续跑时间。

    edges 为 NULL 表示存量工作流 —— 执行器按 steps 顺序自动连成一条链，
    行为与升级前逐字一致（见 app/workflows/graph.py 的 normalize_edges）。
    因此本迁移不需要任何数据回填：NULL 本身就是「线性」的合法表达。

    edges 结构：[{"source": node_id, "target": node_id, "when": {…}|null}, …]
    when 为空即无条件边；条件 DSL 见 app/workflows/conditions.py。
    """
    op.add_column('workflows', sa.Column('edges', sa.JSON(), nullable=True))
    # 续跑标记：失败后从断点接着跑过的话记下时间，前端据此显示「已续跑」
    op.add_column(
        'workflow_runs', sa.Column('resumed_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workflow_runs', 'resumed_at')
    op.drop_column('workflows', 'edges')
