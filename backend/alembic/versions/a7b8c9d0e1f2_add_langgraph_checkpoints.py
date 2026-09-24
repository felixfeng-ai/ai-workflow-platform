"""add langgraph checkpoints

Revision ID: a7b8c9d0e1f2
Revises: f2a3b4c5d6e7
Create Date: 2026-09-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """LangGraph 图状态持久化的两张表。

    这是「自研 checkpointer」的存储层：官方 langgraph-checkpoint-postgres 靠运行时
    调 .setup() 建表，与本项目「Alembic 是唯一建表来源」冲突，所以表结构由这里定义，
    由 app/llm/checkpointer.py 的 SqlAlchemyCheckpointer 读写。

    checkpoint / metadata / value 用 BLOB（PG 上是 BYTEA）而非 JSON：内容来自
    msgpack 序列化，不保证是合法 UTF-8，走 JSON 列会在入库时炸。

    不建额外索引：主键 (thread_id, checkpoint_ns, checkpoint_id) 的复合索引已覆盖
    「同 thread 同 ns 按 id 倒序取最近一条」这一唯一查询形态。
    """
    op.create_table(
        'langgraph_checkpoints',
        sa.Column('thread_id', sa.String(length=72), nullable=False),
        sa.Column('checkpoint_ns', sa.String(length=120), nullable=False),
        sa.Column('checkpoint_id', sa.String(length=72), nullable=False),
        sa.Column('parent_checkpoint_id', sa.String(length=72), nullable=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=True),
        sa.Column('checkpoint', sa.LargeBinary(), nullable=False),
        sa.Column('metadata_type', sa.String(length=20), nullable=True),
        sa.Column('metadata', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'checkpoint_id'),
    )
    op.create_index(
        op.f('ix_langgraph_checkpoints_tenant_id'), 'langgraph_checkpoints', ['tenant_id'], unique=False
    )
    op.create_table(
        'langgraph_checkpoint_writes',
        sa.Column('thread_id', sa.String(length=72), nullable=False),
        sa.Column('checkpoint_ns', sa.String(length=120), nullable=False),
        sa.Column('checkpoint_id', sa.String(length=72), nullable=False),
        sa.Column('task_id', sa.String(length=72), nullable=False),
        sa.Column('idx', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(length=120), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=True),
        sa.Column('value', sa.LargeBinary(), nullable=False),
        sa.Column('task_path', sa.String(length=240), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('thread_id', 'checkpoint_ns', 'checkpoint_id', 'task_id', 'idx'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('langgraph_checkpoint_writes')
    op.drop_index(op.f('ix_langgraph_checkpoints_tenant_id'), table_name='langgraph_checkpoints')
    op.drop_table('langgraph_checkpoints')
