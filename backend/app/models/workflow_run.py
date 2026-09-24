from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class WorkflowRun(Base, TimestampMixin):
    """一次工作流执行记录。

    results: [{"label": str, "agent_key": str, "output": str, "node_id": str}, …]
        按**步骤在 steps 中的下标**排序，而不是执行完成顺序 —— 并行分支下两者不同，
        而前端按顺序读结果才符合直觉（见 app/workflows/graph.py 的排序收口）。
    triggered_by: manual | scheduled
    resumed_at: 最后一次从断点续跑的时间；None = 从未续跑过
        续跑不新建 run：thread_id 恒等于 run.id，同一个 run 在同一线程上接着跑，
        已完成步骤的 LLM 花费才不会白花。
    """

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default="default", index=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|succeeded|failed
    results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), default="manual")  # manual|scheduled
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
