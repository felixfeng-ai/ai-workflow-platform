"""widen notification dedupe_key

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-28 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """放宽 notifications.dedupe_key：varchar(64) 装不下实际的幂等键。

    键形如 due:{user_id}:{task_id}:{yyyy-mm-dd}，两个 UUID + 日期共 88 字符。
    64 是到期提醒上线时凭直觉定的；SQLite 不校验 varchar 长度（本地单测全绿），
    PostgreSQL 会硬拒（StringDataRightTruncationError），而 create_notification
    是 best-effort 写入 —— 异常被吞成 return False，于是**线上的到期提醒一条都没落库**，
    只是日志里有一行 ERROR。取 128 给后续格式变化留余量。

    用 batch_alter_table 是为了同一段迁移在 SQLite 上也能跑（SQLite 不支持
    ALTER COLUMN TYPE，batch 模式会重建表）；PG 上它退化成普通 ALTER。
    """
    with op.batch_alter_table('notifications') as batch:
        batch.alter_column(
            'dedupe_key',
            existing_type=sa.String(length=64),
            type_=sa.String(length=128),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema。注意：超过 64 字符的存量键会在此步被截断/报错。"""
    with op.batch_alter_table('notifications') as batch:
        batch.alter_column(
            'dedupe_key',
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=True,
        )
