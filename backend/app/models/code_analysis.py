from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ProjectRepoConnection(Base, TimestampMixin):
    """项目与 GitHub 仓库的连接。Token 和 Webhook Secret 只存密文。"""

    __tablename__ = "project_repo_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "repository_id", name="uq_repo_connection_tenant_repo"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default="default", index=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20), default="github")
    auth_type: Mapped[str] = mapped_column(String(20), default="pat")
    repository_id: Mapped[int] = mapped_column(BigInteger)
    repo_full_name: Mapped[str] = mapped_column(String(200))
    source_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(120), default="main")
    branch_patterns: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    webhook_secret_encrypted: Mapped[str] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    webhook_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    webhook_last_event: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CodeAnalysisRun(Base, TimestampMixin):
    """一次 GitHub push 范围分析。报告以 JSON 保存，V1 不拆 findings 表。"""

    __tablename__ = "code_analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "delivery_id", name="uq_code_analysis_connection_delivery"
        ),
        UniqueConstraint(
            "connection_id",
            "branch",
            "before_sha",
            "after_sha",
            name="uq_code_analysis_connection_range",
        ),
        Index("ix_code_analysis_project_created", "project_id", "created_at"),
        Index("ix_code_analysis_tenant_status", "tenant_id", "status"),
        Index("ix_code_analysis_project_risk", "project_id", "max_severity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default="default", index=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("project_repo_connections.id", ondelete="CASCADE"),
        index=True,
    )
    trigger_type: Mapped[str] = mapped_column(String(20), default="webhook")
    delivery_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    repo_full_name: Mapped[str] = mapped_column(String(200))
    branch: Mapped[str] = mapped_column(String(200), index=True)
    before_sha: Mapped[str] = mapped_column(String(40))
    after_sha: Mapped[str] = mapped_column(String(40), index=True)
    pusher_login: Mapped[str | None] = mapped_column(String(100), nullable=True)
    head_commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    change_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_version: Mapped[str] = mapped_column(String(20), default="1.0")
    # 冗余搜索与风险摘要：避免列表搜索时解析完整 report JSON，也兼容 SQLite/PG。
    search_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    max_severity: Mapped[str] = mapped_column(String(20), default="none")
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
