from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.messages import HumanMessage

from app.ai.base import AiEngine
from app.llm.chat_model import AiEngineChatModel, content_text
from app.models import Note, Project, Task, User


@dataclass(frozen=True)
class AgentParam:
    """Agent 参数声明：前端据此渲染表单。

    type: text|textarea|number|select|project_id
    options: [{"value": str, "label": str}, …]（type=select 时使用）
    """

    name: str
    label: str
    type: str = "text"
    required: bool = False
    default: Any = None
    options: list[dict[str, str]] = field(default_factory=list)
    placeholder: str = ""


class AgentToolError(Exception):
    """Agent 工具错误（如引用的项目不存在、必填参数缺失）。"""


class AgentContext:
    """Agent 运行上下文：会话 + 当前用户 + AI 引擎 + 租户。

    提供按 tenant_id 过滤的数据检索工具，供各 Agent 收集上下文。
    """

    def __init__(
        self,
        db: AsyncSession,
        user: User,
        engine: AiEngine,
        tenant_id: str = "default",
    ) -> None:
        self.db = db
        self.user = user
        self.engine = engine
        self.tenant_id = tenant_id
        # 模型门面在这里一次性构造：Agent 仍然只写 ctx.chat(prompt)，但调用链变成
        # BaseChatModel → AiEngine —— 于是 LangChain 的回调/流式能力对全部 Agent 生效，
        # 而 Dify ↔ OpenAI 兼容端点的可替换性由底层 engine 保住。
        self.chat_model = AiEngineChatModel(engine=engine, user_id=user.id)

    async def get_projects(self) -> list[Project]:
        result = await self.db.execute(
            select(Project).where(Project.tenant_id == self.tenant_id)
        )
        return list(result.scalars().all())

    async def get_project(self, project_id: str) -> Project | None:
        result = await self.db.execute(
            select(Project).where(
                Project.tenant_id == self.tenant_id, Project.id == project_id
            )
        )
        return result.scalar_one_or_none()

    async def get_tasks(
        self,
        project_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Task]:
        stmt = select(Task).where(Task.tenant_id == self.tenant_id)
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)
        if since:
            stmt = stmt.where(Task.created_at >= since)
        if until:
            stmt = stmt.where(Task.created_at < until)
        stmt = stmt.order_by(Task.created_at)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_notes(self, project_id: str | None = None) -> list[Note]:
        stmt = select(Note).where(Note.tenant_id == self.tenant_id)
        if project_id:
            stmt = stmt.where(Note.project_id == project_id)
        stmt = stmt.order_by(Note.created_at)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def chat(self, query: str) -> str:
        """调用底层 AI 引擎生成。经 LangChain 模型门面（见 __init__ 的说明）转发。"""
        message = await self.chat_model.ainvoke([HumanMessage(content=query)])
        return content_text(message.content)


class Agent(Protocol):
    """Agent 协议：所有内置 Agent 实现此接口。"""

    key: str
    name: str
    description: str
    param_schema: list[AgentParam]

    async def run(self, ctx: AgentContext, params: dict) -> str: ...
