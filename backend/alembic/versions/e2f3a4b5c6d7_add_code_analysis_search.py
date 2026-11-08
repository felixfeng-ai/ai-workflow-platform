"""add code analysis search and risk summary

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "code_analysis_runs",
        sa.Column("search_text", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "code_analysis_runs",
        sa.Column("max_severity", sa.String(length=20), server_default="none", nullable=False),
    )
    op.add_column(
        "code_analysis_runs",
        sa.Column("finding_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "ix_code_analysis_project_risk",
        "code_analysis_runs",
        ["project_id", "max_severity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_code_analysis_project_risk", table_name="code_analysis_runs")
    op.drop_column("code_analysis_runs", "finding_count")
    op.drop_column("code_analysis_runs", "max_severity")
    op.drop_column("code_analysis_runs", "search_text")
