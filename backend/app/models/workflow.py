from uuid import uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Workflow(Base, TimestampMixin):
    """工作流：Agent 步骤编排（线性或带分支的图）+ 可选定时调度。

    steps: [{"label": str, "agent_key": str, "params": {…}, "node_id": str}, …]
        步骤 = 画布上的节点。node_id 是 edges 的引用锚点。
    edges: [{"source": node_id, "target": node_id, "when": {…}|null}, …]
        **NULL = 线性**：按 steps 顺序自动连成一条链。这是升级前的存量形态，
        不做事后回填（NULL 本身就是「线性」的合法表达，回填反而多一次写库风险）。
        when 为空即无条件边，条件 DSL 见 app/workflows/conditions.py。
    schedule: {"cron": "0 9 * * 1"} 或 {"interval_minutes": N}，None=仅手动触发
    """

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default="default", index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    edges: Mapped[list | None] = mapped_column(JSON, nullable=True)
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
