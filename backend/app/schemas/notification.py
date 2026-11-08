from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    """站内通知出参：不暴露 dedupe_key/tenant_id（内部去重与隔离细节）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str  # agent_run|workflow_run|team|knowledge|due_reminder|code_analysis
    title: str
    body: str | None
    ref_id: str | None
    read_at: datetime | None  # 为空即未读
    created_at: datetime


class UnreadCount(BaseModel):
    count: int


class ReadAllResult(BaseModel):
    updated: int
