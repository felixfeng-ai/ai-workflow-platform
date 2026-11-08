from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents.runner import agent_run_manager
from .api import (
    agents,
    ai,
    auth,
    code_analysis,
    docs,
    github_webhooks,
    health,
    knowledge,
    notes,
    notifications,
    param_templates,
    projects,
    tasks,
    team,
    wechat,
    workflows,
)
from .copilot.router import router as copilot_router
from .config import settings
from .writing.router import router as writing_router
from .workflows.executor import workflow_run_manager
from .workflows.scheduler import workflow_scheduler
from .services.code_analysis.runner import code_analysis_run_manager
from .services.code_analysis.backfill import backfill_code_analysis_metadata
from .db import SessionLocal


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：启动 APScheduler 并加载定时工作流；退出时回收后台任务。"""
    workflow_scheduler.start()
    await workflow_scheduler.load_all()
    async with SessionLocal() as db:
        await backfill_code_analysis_metadata(db)
        await db.commit()
    yield
    workflow_scheduler.shutdown()
    await agent_run_manager.shutdown()
    await workflow_run_manager.shutdown()
    await code_analysis_run_manager.shutdown()

# 数据库 Schema 由 Alembic 迁移管理（容器入口/部署脚本执行 `alembic upgrade head`），
# 不再在启动时 create_all，避免与迁移漂移。

app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(code_analysis.router)
app.include_router(github_webhooks.router)
app.include_router(tasks.router)
app.include_router(notes.router)
app.include_router(docs.router)
app.include_router(team.router)
app.include_router(ai.router)
app.include_router(copilot_router)
app.include_router(writing_router)
app.include_router(agents.router)
app.include_router(param_templates.router)
app.include_router(knowledge.router)
app.include_router(notifications.router)
app.include_router(workflows.router)
app.include_router(wechat.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs"}
