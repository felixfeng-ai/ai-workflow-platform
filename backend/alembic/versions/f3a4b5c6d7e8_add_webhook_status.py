"""add webhook connection status

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_repo_connections",
        sa.Column("webhook_connected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "project_repo_connections",
        sa.Column("webhook_last_event", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_repo_connections", "webhook_last_event")
    op.drop_column("project_repo_connections", "webhook_connected_at")
