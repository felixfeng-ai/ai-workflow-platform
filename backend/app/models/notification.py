from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    """站内通知：用户级收件箱，查询按 user_id（不按 tenant_id，被移出团队仍可见）。

    type 枚举：agent_run|workflow_run|team|knowledge|due_reminder
    read_at 为空即未读；dedupe_key 供到期提醒按日历天幂等（同 user+task+day 只落一条）。
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default="default", index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # run/task/doc/成员 id，跳转锚点
    # 列宽必须 ≥ due_reminder_dedupe_key 的实际长度（两个 UUID + 日期 = 88），
    # 留了余量到 128；改小之前先看 services/notification.py 里的那条断言。
    dedupe_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
