"""add code analysis connections and runs

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-11-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_repo_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("auth_type", sa.String(length=20), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_full_name", sa.String(length=200), nullable=False),
        sa.Column("default_branch", sa.String(length=120), nullable=False),
        sa.Column("branch_patterns", sa.JSON(), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("installation_id", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "repository_id", name="uq_repo_connection_tenant_repo"
        ),
    )
    op.create_index(
        op.f("ix_project_repo_connections_created_by"),
        "project_repo_connections",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_repo_connections_project_id"),
        "project_repo_connections",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_repo_connections_tenant_id"),
        "project_repo_connections",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "code_analysis_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("delivery_id", sa.String(length=100), nullable=True),
        sa.Column("repo_full_name", sa.String(length=200), nullable=False),
        sa.Column("branch", sa.String(length=200), nullable=False),
        sa.Column("before_sha", sa.String(length=40), nullable=False),
        sa.Column("after_sha", sa.String(length=40), nullable=False),
        sa.Column("pusher_login", sa.String(length=100), nullable=True),
        sa.Column("head_commit_message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("change_stats", sa.JSON(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("report_markdown", sa.Text(), nullable=True),
        sa.Column("analysis_version", sa.String(length=20), nullable=False),
        sa.Column("ai_provider", sa.String(length=40), nullable=True),
        sa.Column("ai_model", sa.String(length=100), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["project_repo_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id", "delivery_id", name="uq_code_analysis_connection_delivery"
        ),
        sa.UniqueConstraint(
            "connection_id",
            "branch",
            "before_sha",
            "after_sha",
            name="uq_code_analysis_connection_range",
        ),
    )
    op.create_index(
        "ix_code_analysis_project_created",
        "code_analysis_runs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_code_analysis_tenant_status",
        "code_analysis_runs",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_analysis_runs_after_sha"),
        "code_analysis_runs",
        ["after_sha"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_analysis_runs_branch"),
        "code_analysis_runs",
        ["branch"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_analysis_runs_connection_id"),
        "code_analysis_runs",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_analysis_runs_project_id"),
        "code_analysis_runs",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_analysis_runs_tenant_id"),
        "code_analysis_runs",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_code_analysis_runs_tenant_id"), table_name="code_analysis_runs")
    op.drop_index(op.f("ix_code_analysis_runs_project_id"), table_name="code_analysis_runs")
    op.drop_index(op.f("ix_code_analysis_runs_connection_id"), table_name="code_analysis_runs")
    op.drop_index(op.f("ix_code_analysis_runs_branch"), table_name="code_analysis_runs")
    op.drop_index(op.f("ix_code_analysis_runs_after_sha"), table_name="code_analysis_runs")
    op.drop_index("ix_code_analysis_tenant_status", table_name="code_analysis_runs")
    op.drop_index("ix_code_analysis_project_created", table_name="code_analysis_runs")
    op.drop_table("code_analysis_runs")

    op.drop_index(
        op.f("ix_project_repo_connections_tenant_id"),
        table_name="project_repo_connections",
    )
    op.drop_index(
        op.f("ix_project_repo_connections_project_id"),
        table_name="project_repo_connections",
    )
    op.drop_index(
        op.f("ix_project_repo_connections_created_by"),
        table_name="project_repo_connections",
    )
    op.drop_table("project_repo_connections")
