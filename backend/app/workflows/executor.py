"""工作流执行：把一张工作流图跑起来。

改造后执行主体是 LangGraph 编译出的图（见 graph.py），本模块负责的是「运行生命周期」：
建 run 记录、装 checkpointer、跑图、落结果、发通知。旧版那个手写 for 循环已经删掉，
但 `interpolate` 这个名字保留 re-export —— 存量测试与调用方按这个名字引用它。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai import get_ai_engine
from app.db import SessionLocal
from app.llm.checkpointer import SqlAlchemyCheckpointer
from app.models import User, Workflow, WorkflowRun
from app.services.notification import create_notification

from ..agents.registry import ensure_registered
from .graph import (
    build_workflow_graph,
    recursion_limit_for,
    sort_results,
    thread_id_for,
)
from .templates import render

# 兼容名：模板渲染原本叫 interpolate，现在实现搬到了 templates.render。
# 这里保留别名而不是让调用方改 import，是为了让「重构」与「换引擎」两件事分开 ——
# 前者不该在 diff 里制造噪音，也不该逼着外部调用点跟着动。
interpolate = render

__all__ = ["WorkflowRunManager", "workflow_run_manager", "interpolate"]


class WorkflowRunManager:
    """工作流执行管理：跑图，失败即终止并保留已完成步骤的结果。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self.session_factory = session_factory or SessionLocal
        self._tasks: set[asyncio.Task] = set()

    def submit(self, run_id: str, *, resume: bool = False) -> None:
        """把一个 run 丢进后台执行。resume=True 时同一 run 从断点续跑。"""
        task = asyncio.create_task(self._execute(run_id, resume=resume))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run_id: str, *, resume: bool = False) -> None:
        async with self.session_factory() as db:
            run = await db.get(WorkflowRun, run_id)
            if run is None:
                return
            run.status = "running"
            if not resume:
                # resumed_at 由 resume 端点写（那里才是用户点击的时刻）；这里只管首次运行。
                # status 两边都写是幂等的：resume 端点已置过 running，scheduler 路径没有
                run.started_at = datetime.now(timezone.utc)
            await db.commit()

            workflow = None  # finally 通知要用 workflow.name，提前绑定避免 NameError
            graph = None  # 失败分支要读图快照，同样提前绑定
            config: dict[str, Any] = {}
            try:
                workflow = await db.get(Workflow, run.workflow_id)
                if workflow is None:
                    raise ValueError(f"workflow {run.workflow_id} not found")
                user = await db.get(User, run.user_id)
                if user is None:
                    raise ValueError(f"user {run.user_id} not found")
                ensure_registered()

                # 关掉上面几条 SELECT 打开的读事务（见下）：图执行期间节点函数与
                # checkpointer 各自开会话读写，本会话若仍持着读事务，SQLite 上
                # 写者会被挡到锁超时。expire_on_commit=False 保证 commit 后
                # workflow/user 的属性仍可读，不会触发新的 SELECT 把事务又开回来。
                await db.commit()

                steps = workflow.steps or []
                if not steps:
                    # 空工作流：没图可编译，直接成功。与旧版 for 循环跑 0 次的行为一致
                    run.results = []
                    run.status = "succeeded"
                else:
                    graph = build_workflow_graph(
                        steps,
                        workflow.edges,
                        session_factory=self.session_factory,
                        user_id=run.user_id,
                        tenant_id=run.tenant_id,
                        # 传工厂函数而不是引擎实例：Agent 可能在不同的 super-step 里
                        # 拿到不同的引擎（配置热更新 / 测试替换），一次解析一次用
                        engine_factory=get_ai_engine,
                        checkpointer=SqlAlchemyCheckpointer(
                            self.session_factory, tenant_id=run.tenant_id
                        ),
                    )
                    config = {
                        "configurable": {"thread_id": thread_id_for(run.id)},
                        # 默认 25 步上限，长工作流会撞，见 graph.recursion_limit_for
                        "recursion_limit": recursion_limit_for(len(steps)),
                    }
                    # 首次运行喂初始状态；续跑传 None —— LangGraph 会从该线程最后一个
                    # checkpoint 接着跑，已完成的步骤不会重跑（LLM 花费不白花）
                    state = await graph.ainvoke(
                        None if resume else {"outputs": []}, config
                    )
                    run.results = sort_results((state or {}).get("outputs"))
                    run.status = "succeeded"
            except Exception as exc:  # noqa: BLE001 - 失败写 error，后台任务不崩溃
                run.status = "failed"
                run.error = str(exc)
                # 失败也把已完成步骤落库：前端要显示「跑到哪一步挂的」，用户要据此
                # 决定是修图重跑还是断点续跑。旧实现只在成功时写 results。
                run.results = await self._snapshot_results(graph, config)
            finally:
                run.finished_at = datetime.now(timezone.utc)
                # 运行结果通知：best-effort，失败不影响 run 状态落库
                trigger_label = "定时" if run.triggered_by == "scheduled" else "手动"
                if run.status == "succeeded":
                    await create_notification(
                        db,
                        user_id=run.user_id,
                        type="workflow_run",
                        title="工作流运行完成",
                        body=f"工作流「{workflow.name}」（{trigger_label}）已运行完成" if workflow else "工作流已运行完成",
                        ref_id=run.id,
                        tenant_id=run.tenant_id,
                    )
                else:
                    await create_notification(
                        db,
                        user_id=run.user_id,
                        type="workflow_run",
                        title="工作流运行失败",
                        body=f"工作流「{workflow.name}」（{trigger_label}）运行失败：{(run.error or '')[:200]}" if workflow else "工作流运行失败",
                        ref_id=run.id,
                        tenant_id=run.tenant_id,
                    )
                await db.commit()

    async def _snapshot_results(self, graph, config: dict) -> list[dict]:
        """从图的最后一份 checkpoint 里取已完成步骤的输出。

        读快照本身也可能失败（比如库连不上导致 checkpointer 写入就是失败原因），
        这里必须吞掉 —— 快照只是「让失败记录更好看」，不能盖掉真正的 error 文本。
        """
        if graph is None or not config:
            return []
        try:
            snapshot = await graph.aget_state(config)
            return sort_results(((snapshot.values if snapshot else {}) or {}).get("outputs"))
        except Exception:  # noqa: BLE001 - 见上
            return []

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


workflow_run_manager = WorkflowRunManager()
