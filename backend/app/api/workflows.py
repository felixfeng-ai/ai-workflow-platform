from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.registry import AGENT_REGISTRY, ensure_registered
from ..ai import AiEngine, get_ai_engine
from ..ai.errors import AiEngineUnavailable
from ..config import settings
from ..core.ratelimit import rate_limit
from ..db import get_db
from ..llm.checkpointer import delete_threads
from ..models.custom_agent import CustomAgent
from ..models.project import Project
from ..models.user import User
from ..models.workflow import Workflow
from ..models.workflow_run import WorkflowRun
from ..schemas.agent import Paginated
from ..schemas.workflow import (
    WorkflowCreate,
    WorkflowDraft,
    WorkflowDraftRequest,
    WorkflowRead,
    WorkflowRunCreated,
    WorkflowRunRead,
    WorkflowUpdate,
)
from ..workflows.conditions import ConditionError
from ..workflows.drafter import CatalogAgent, DraftContext, DraftError, draft_workflow
from ..workflows.executor import workflow_run_manager
from ..workflows.graph import WorkflowGraphError, validate_graph
from ..workflows.scheduler import workflow_scheduler
from .deps import get_current_user, require_role

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# 限流依赖：按「来源 IP + workflow_run」滑动窗口计数，超限抛 429（工作流触发防误触）。
# 端点的 `_rl: None = Depends(...)` 参数不传值，只负责把依赖挂进请求链路，见 core/ratelimit.py
_run_limit = rate_limit(settings.ratelimit_run_per_min, 60, scope="workflow_run")

# 起草是纯 LLM 调用，和 /api/ai/chat 共用 llm 这个桶：限的是「这个 IP 每分钟花多少 token」，
# 不是「这个功能被点了几次」。分开计数的话，对话 + 起草各 20 次等于把预算翻倍。
_llm_limit = rate_limit(settings.ratelimit_llm_per_min, 60, scope="llm")


def _normalize_schedule(schedule) -> dict | None:
    """只保留显式设置的调度字段（cron 或 interval_minutes）。"""
    if schedule is None:
        return None
    return {k: v for k, v in schedule.model_dump().items() if v is not None}


async def _validate_steps(db: AsyncSession, user: User, steps: list[dict]) -> None:
    """校验步骤引用的 Agent：内置注册表优先，其次当前租户的自定义 Agent。"""
    ensure_registered()
    for step in steps:
        key = step.get("agent_key")
        if AGENT_REGISTRY.get(key) is not None:
            continue
        # 自定义 Agent 按租户校验（与 list_agents 可见范围一致）
        result = await db.execute(
            select(CustomAgent).where(
                CustomAgent.key == key, CustomAgent.tenant_id == user.tenant_id
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=422, detail=f"unknown agent: {key}")


def _clean(items: list[dict] | None) -> list[dict] | None:
    """剔除值为 None 的键：旧式步骤/无边工作流不落 null 噪音，保持存量数据干净。"""
    if not items:
        return None
    return [{k: v for k, v in item.items() if v is not None} for item in items]


def _validate_graph_or_422(steps: list[dict] | None, edges: list[dict] | None) -> None:
    """图结构静态校验（环 / 多入口 / 孤立节点 / 等深汇聚 / 条件合法性）。

    放在保存时而不是运行时的理由：定时调度凌晨无人值守地跑，一个走不通的结构在
    运行时才炸，用户第二天看到的只是一条失败记录，而界面上当时完全存得进去。
    422 而不是 400：与 unknown agent 的报错形态保持一致，前端一处处理。

    这里要接两种异常，因为错误来自两层：WorkflowGraphError 是图结构层（环、多入口），
    ConditionError 是条件 DSL 层（op 不在白名单）。下面不合并成一种，是为了让两个
    校验函数各自只关心自己那层；跨层的类型转换放在 API 边界做，正是边界该干的事。
    """
    try:
        validate_graph(steps, edges)
    except (WorkflowGraphError, ConditionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Workflow]:
    # 数据隔离 R17：列表按租户可见（团队共享模型，与 agents.py list_agents 一致）
    result = await db.execute(
        select(Workflow)
        .where(Workflow.tenant_id == user.tenant_id)
        .order_by(Workflow.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner", "member")),
) -> Workflow:
    # exclude_none: 无 node_id/position 的旧式步骤不落 null 噪音，保持存量数据干净
    steps = [s.model_dump(exclude_none=True) for s in payload.steps]
    edges = _clean([e.model_dump(exclude_none=True) for e in payload.edges or []])
    await _validate_steps(db, user, steps)
    _validate_graph_or_422(steps, edges)
    wf = Workflow(
        user_id=user.id,
        tenant_id=user.tenant_id,
        name=payload.name,
        description=payload.description,
        steps=steps,
        edges=edges,
        schedule=_normalize_schedule(payload.schedule),
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    workflow_scheduler.reschedule(wf)
    return wf


async def _build_catalog(db: AsyncSession, user: User) -> DraftContext:
    """组装起草素材：本租户可用的助手（内置 + 自定义）+ 本租户的项目。

    可见范围必须与 list_agents / 步骤校验一致 —— 提示词里给出别租户的 agent_key，
    模型照抄之后会在 _validate_steps 那一关被拒，用户看到的是一份用不了的草稿。
    自定义助手按 tenant_id 过滤（和 list_agents 一样是租户级，不是 user_id 级）。
    """
    ensure_registered()
    result = await db.execute(
        select(CustomAgent).where(CustomAgent.tenant_id == user.tenant_id)
    )
    custom = [
        CatalogAgent(
            key=a.key,
            name=a.name,
            description=a.description or "",
            params=tuple(a.param_schema or ()),
        )
        for a in result.scalars().all()
    ]
    builtin = [
        CatalogAgent(
            key=a.key,
            name=a.name,
            description=a.description,
            params=tuple(asdict(p) for p in a.param_schema),
        )
        for a in AGENT_REGISTRY.list()
    ]
    projects = await db.execute(
        select(Project.id, Project.name).where(Project.tenant_id == user.tenant_id)
    )
    return DraftContext(
        agents=tuple(builtin + custom),
        projects=tuple((pid, name) for pid, name in projects.all()),
    )


@router.post("/draft", response_model=WorkflowDraft)
async def draft_workflow_endpoint(
    payload: WorkflowDraftRequest,
    _rl: None = Depends(_llm_limit),
    db: AsyncSession = Depends(get_db),
    engine: AiEngine = Depends(get_ai_engine),
    user: User = Depends(require_role("owner", "member")),
) -> WorkflowDraft:
    """一句话 → 一份工作流草稿。**只起草，不落库。**

    刻意不做「起草即创建」：草稿是模型的猜测，必须让用户在画布上看一眼再决定。
    直接落库的话，用错的草稿会变成一份带定时任务的、没人看过的真实工作流 ——
    到了钟点它会自己跑，还会调真的 AI。

    这里只调 draft_workflow，不重复做 validate_graph —— 草稿在 normalize_draft 里
    已经用同一把尺子量过了，量两遍不会更安全，只会让「草稿不合法」这句话有两个来源。
    """
    if not payload.intent.strip():
        raise HTTPException(status_code=422, detail="请先说说你想让 AI 做什么")
    ctx = await _build_catalog(db, user)
    if not ctx.agents:
        raise HTTPException(status_code=422, detail="当前没有可用的 AI 助手，先创建一个再起草")
    try:
        draft = await draft_workflow(engine, user.id, payload.intent.strip(), ctx)
    except DraftError as exc:
        # 草稿不合格是模型的问题，不是用户的输入错误，但 422 是唯一能带出可读原因的码；
        # 500 会让前端把它当成「平台挂了」，用户只会重试同一句话
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AiEngineUnavailable as exc:
        # 与 /api/ai/chat 一致：引擎没配好是服务端能力问题，不是这次请求的问题
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return WorkflowDraft(**draft)


@router.get("/runs", response_model=Paginated[WorkflowRunRead])
async def list_workflow_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Paginated[WorkflowRunRead]:
    # 数据隔离 R17：运行记录按租户可见（团队共享模型）
    where = [WorkflowRun.tenant_id == user.tenant_id]
    total = (
        await db.execute(select(func.count()).select_from(WorkflowRun).where(*where))
    ).scalar_one()
    result = await db.execute(
        select(WorkflowRun)
        .where(*where)
        .order_by(WorkflowRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Paginated(
        items=list(result.scalars().all()), total=total, page=page, page_size=page_size
    )


@router.get("/runs/{run_id}", response_model=WorkflowRunRead)
async def get_workflow_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowRun:
    run = await db.get(WorkflowRun, run_id)
    if run is None or run.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post(
    "/runs/{run_id}/resume",
    response_model=WorkflowRunCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_workflow_run(
    run_id: str,
    _rl: None = Depends(_run_limit),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner", "member")),
) -> WorkflowRunCreated:
    """从断点续跑一次失败的运行。

    复用同一个 run（因此也复用同一个 LangGraph thread_id）：已完成步骤的输出还在
    checkpoint 里，续跑只重跑失败的那一步及其下游，不重烧前面的 LLM 花费。

    只允许 failed → 续跑：running 的再提交一次等于同一条线程被两个协程同时推进，
    LangGraph 与数据库都挡不住这种重复执行（真正要拦它得上分布式锁，见 scheduler
    的单例说明）。succeeded 的没有可续的断点，返回 409 让前端别显示这个按钮。

    **状态必须在返回前改掉，不能留给后台任务改**：`submit` 只是 create_task，
    真正开始跑要等事件循环调度。若这里不落库，从用户点「续跑」到任务启动之间
    读到的仍是 failed —— 前端据此继续显示续跑按钮，用户连点两下就有两个协程
    推进同一条 thread，而上面那条「只有 failed 能续跑」的规则此时形同虚设。
    """
    run = await db.get(WorkflowRun, run_id)
    if run is None or run.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "failed":
        raise HTTPException(
            status_code=409, detail=f"只有失败的工作流运行可以续跑（当前状态：{run.status}）"
        )
    # 先落 running 再 submit：这个 commit 同时把「读到的 failed」改掉，使重复提交
    # 撞上上面的 409。resumed_at 记在这里（而不是后台任务里），时间才是用户点击的时刻
    run.status = "running"
    run.resumed_at = datetime.now(timezone.utc)
    await db.commit()
    workflow_run_manager.submit(run.id, resume=True)
    return WorkflowRunCreated(run_id=run.id, status=run.status)


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Workflow:
    # 数据隔离 R17：查看按租户共享（团队共享模型）
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="workflow not found")
    return wf


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner", "member")),
) -> Workflow:
    # 数据隔离 R17：编辑仅创建者本人（与 agents.py update_custom_agent 一致）
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="workflow not found")

    data = payload.model_dump(exclude_unset=True)
    if "steps" in data:
        await _validate_steps(db, user, data["steps"])
        # 与 create 一致：无 node_id/position 的旧式步骤不落 null 噪音
        data["steps"] = _clean(data["steps"]) or []
    if "edges" in data:
        # 显式传 null = 退回线性。_clean 对空列表也返回 None，两者语义一致
        data["edges"] = _clean(data["edges"])
    if "steps" in data or "edges" in data:
        # 校验「改完之后」的形态：只改 steps 时沿用库里的 edges，反之亦然 ——
        # 否则「先改步骤再改连线」这个正常操作会被中间态误判为非法图
        _validate_graph_or_422(
            data.get("steps", wf.steps), data.get("edges", wf.edges)
        )
    if "schedule" in data:
        sched = data["schedule"]
        data["schedule"] = (
            {k: v for k, v in sched.items() if v is not None} if sched else None
        )
    for field, value in data.items():
        setattr(wf, field, value)
    await db.commit()
    await db.refresh(wf)
    workflow_scheduler.reschedule(wf)
    return wf


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner", "member")),
) -> None:
    # 数据隔离 R17：删除仅创建者本人
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="workflow not found")
    workflow_scheduler.remove(wf.id)
    # 检查点表刻意没有指向 workflow_runs 的外键（那里解释了原因），所以级联删除
    # 帮不上忙：删除工作流时必须显式按线程清掉图状态，否则这些行会一直堆积。
    run_ids = list(
        (
            await db.execute(select(WorkflowRun.id).where(WorkflowRun.workflow_id == wf.id))
        )
        .scalars()
        .all()
    )
    await delete_threads(db, run_ids)
    await db.delete(wf)
    await db.commit()


@router.post(
    "/{workflow_id}/run",
    response_model=WorkflowRunCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_workflow(
    workflow_id: str,
    _rl: None = Depends(_run_limit),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner", "member")),
) -> WorkflowRunCreated:
    # 数据隔离 R17：运行按租户共享（同租户可触发，与 agents.py run_agent 一致）
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="workflow not found")
    run = WorkflowRun(
        tenant_id=wf.tenant_id,
        workflow_id=wf.id,
        user_id=user.id,
        status="pending",
        triggered_by="manual",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    workflow_run_manager.submit(run.id)
    return WorkflowRunCreated(run_id=run.id, status=run.status)
