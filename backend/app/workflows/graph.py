"""工作流 → LangGraph 图。

steps 是画布上的节点，edges 是连线；本模块把两者编译成一张 `StateGraph` 并跑起来。
`edges` 为 NULL 的存量工作流按 steps 顺序自动连成一条链（normalize_edges），
行为与改造前的线性 for 循环逐字一致。

---

**为什么每步要自开一个 session，而不是共用 run 级会话？**

并行分支意味着两个节点函数会同时被 await。SQLAlchemy 的 AsyncSession 不是并发安全的
（一个 session 同一时刻只能有一个进行中的操作），两个协程共用会直接抛
「This session is provisioning a new connection」之类的错。所以节点的 session 是
「进节点开、出节点关」的短生命周期，run 级会话在整张图跑的过程中保持空闲。
这与项目「后台任务自开会话」的不变量同源。

**为什么节点名用 n0/n1… 而不是用户给的 node_id？**

LangGraph 把节点名当作通道名前缀（`branch:to:<name>`），带冒号/下划线的名字会被
当成子图命名空间解析。node_id 来自前端画布、是用户可提交的字符串，直接拿来当节点名
等于把内部命名规则暴露给外部输入。位置编号 n{i} 与用户输入彻底解耦，
node_id 只出现在 results 里（前端靠它把运行结果对回画布节点）。

**为什么汇聚节点要求各分支「等深」？**

这是本文件最反直觉的一处约束。LangGraph 里一条 `add_edge(src, target)` 写的是
`branch:to:target` 这个 `EphemeralValue` 通道，同一 super-step 内的多笔写会被合并，
**但跨 super-step 不会** —— 若 a→b→合并 与 a→c→d→合并 深度不同，合并节点会在
b 完成的那个 super-step 先跑一次，再在 d 完成时被触发跑第二次（LLM 白烧一遍）。
真正「等齐所有入边」的写法是 `add_edge([srcs...], target)` 的 NamedBarrierValue，
但那个语义是「所有前置都必须完成」—— 条件分支下被跳过的那条永远不会完成，
if/else 汇聚就直接死锁了。

两种语义都买不到「if/else 合并」+「并行汇聚」两个场景，所以这里选 EphemeralValue
（保住 if/else 合并这个高频用法），并**在保存时把不等深的汇聚直接判为非法**
（validate_graph）——让用户改图，而不是运行时悄悄多烧一次模型调用。
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import AgentContext
from app.agents.custom import resolve_agent
from app.ai.base import AiEngine
from app.models import User

from .conditions import evaluate, validate_condition
from .templates import render

# 多前置分支合并成 prev_output 时的分隔符：模型能明确看出这是多段拼接而非一段连续文本
MERGE_SEPARATOR = "\n\n---\n\n"

# LangGraph 默认 recursion_limit=25，即最多 25 个 super-step。线性 N 步要 N+1 步，
# 不改这个上限的话 24 步以上的工作流会抛 GraphRecursionError。给 2 倍步数 + 余量。
_MIN_RECURSION_LIMIT = 25


class WorkflowGraphError(RuntimeError):
    """工作流图结构非法（保存时）或运行时走进死路。"""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    when: dict | None = None


@dataclass(frozen=True)
class StepNode:
    index: int
    node_id: str
    label: str
    agent_key: str
    params: dict


class WorkflowState(TypedDict):
    """图状态：只放「已完成步骤的输出」。

    outputs 用 operator.add 归约 —— 并行分支各写各的、由 reducer 合并，节点之间不需要
    互相加锁。条目里带 index（步骤下标），收口时按 index 排序还原「steps 顺序」：
    并行下完成顺序不等于 steps 顺序，直接依赖追加顺序会让 results 顺序随机。
    """

    outputs: Annotated[list[dict], operator.add]


# ---------------------------------------------------------------- 结构归一


def collect_nodes(steps: list[dict] | None) -> list[StepNode]:
    """steps → 节点列表。node_id 缺省时按下标合成，与前端画布约定保持一致。"""
    nodes: list[StepNode] = []
    seen: set[str] = set()
    for i, step in enumerate(steps or []):
        node_id = step.get("node_id") or f"node-{i}"
        if node_id in seen:
            raise WorkflowGraphError(f"节点 id 重复: {node_id}")
        seen.add(node_id)
        agent_key = step.get("agent_key") or ""
        nodes.append(
            StepNode(
                index=i,
                node_id=node_id,
                label=step.get("label") or agent_key or f"步骤{i + 1}",
                agent_key=agent_key,
                params=step.get("params") or {},
            )
        )
    return nodes


def normalize_edges(nodes: list[StepNode], edges: list[dict] | None) -> list[Edge]:
    """edges 为 NULL/空 → 按 steps 顺序连成一条链；否则逐条解析。

    存量工作流（创建时还没有 edges 字段）走的就是前一条分支：不做事后回填，
    NULL 本身就是「线性」的合法表达。
    """
    if not edges:
        return [
            Edge(source=nodes[i].node_id, target=nodes[i + 1].node_id)
            for i in range(len(nodes) - 1)
        ]
    return [
        Edge(
            source=e.get("source") or "",
            target=e.get("target") or "",
            when=e.get("when") or None,
        )
        for e in edges
    ]


def _preds_and_out(nodes: list[StepNode], edges: list[Edge]) -> tuple[dict, dict]:
    preds: dict[str, list[str]] = {n.node_id: [] for n in nodes}
    out: dict[str, list[Edge]] = {n.node_id: [] for n in nodes}
    for e in edges:
        out[e.source].append(e)
        preds[e.target].append(e.source)
    return preds, out


def _topo_order(node_ids: list[str], preds: dict[str, list[str]], out: dict[str, list[Edge]]):
    """Kahn 拓扑排序。返回 (order, remaining)；remaining 非空即说明有环。"""
    indeg = {nid: len(preds[nid]) for nid in node_ids}
    ready = [nid for nid in node_ids if indeg[nid] == 0]
    order: list[str] = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for e in out[nid]:
            indeg[e.target] -= 1
            if indeg[e.target] == 0:
                ready.append(e.target)
    return order, [nid for nid in node_ids if nid not in set(order)]


def _entry_node(nodes: list[StepNode], preds: dict[str, list[str]]) -> str:
    """入口 = 唯一没有入边的节点。0 个（有环）或多个（不知道从哪开始）都是非法图。"""
    entries = [n.node_id for n in nodes if not preds[n.node_id]]
    if not entries:
        raise WorkflowGraphError("找不到起始步骤：每个节点都有上游，图里存在环")
    if len(entries) > 1:
        labels = "、".join(_label_of(nodes, nid) for nid in entries)
        raise WorkflowGraphError(f"存在多个起始步骤（{labels}），工作流只能有一个入口")
    return entries[0]


def _label_of(nodes: list[StepNode], node_id: str) -> str:
    for n in nodes:
        if n.node_id == node_id:
            return n.label
    return node_id


def validate_graph(steps: list[dict] | None, edges: list[dict] | None) -> None:
    """保存时校验整张图；非法直接抛 WorkflowGraphError（端点转 422）。

    把「能静态发现的错误」全部拦在保存这一步：定时任务凌晨无人值守地跑，
    一个走不通的分支结构在运行时才炸，用户第二天看到的只是一条失败的运行记录。
    """
    nodes = collect_nodes(steps)
    if not nodes:
        return
    node_ids = [n.node_id for n in nodes]
    known = set(node_ids)
    norm = normalize_edges(nodes, edges)

    for e in norm:
        if e.source not in known:
            raise WorkflowGraphError(f"连线起点不存在: {e.source}")
        if e.target not in known:
            raise WorkflowGraphError(f"连线终点不存在: {e.target}")
        if e.source == e.target:
            raise WorkflowGraphError(f"步骤「{_label_of(nodes, e.source)}」不能连到自己")
        if e.when is not None:
            validate_condition(e.when)

    preds, out = _preds_and_out(nodes, norm)
    order, remaining = _topo_order(node_ids, preds, out)
    if remaining:
        labels = "、".join(_label_of(nodes, nid) for nid in remaining)
        raise WorkflowGraphError(f"工作流存在环，无法执行: {labels}")

    _entry_node(nodes, preds)

    # 这里刻意没有单独的「可达性」校验：无环 + 唯一入口已经蕴含所有节点可达 ——
    # 从任一节点沿前驱回溯（无环保证不会绕圈）必然止于某个入度为 0 的节点，
    # 而那样的节点只有入口一个，所以孤立节点根本不可能通过上面的入口检查。
    # 写一段永远触发不了的校验只会让人以为这个场景被处理了。

    # 等深汇聚（原因见模块 docstring）：深度 = 从入口出发的最长路径边数
    depth: dict[str, int] = {}
    for nid in order:
        depth[nid] = max((depth[p] + 1 for p in preds[nid]), default=0)
    for nid in node_ids:
        if len(preds[nid]) < 2:
            continue
        levels = {depth[p] for p in preds[nid]}
        if len(levels) > 1:
            detail = "、".join(
                f"{_label_of(nodes, p)}(第{depth[p] + 1}层)" for p in preds[nid]
            )
            raise WorkflowGraphError(
                f"步骤「{_label_of(nodes, nid)}」的上游分支深度不一致（{detail}），"
                "会在先到的分支上被提前执行一次。请让各分支步数相同后再汇聚"
            )


# ---------------------------------------------------------------- 运行时


def sort_results(outputs: list[dict] | None) -> list[dict]:
    """按步骤下标收口并去重，输出前端消费的 results。

    去重保留**最后一次**：不等深汇聚会让同一节点跑两次（保存时已拦下，但历史数据
    或手改库仍可能触发），保留最新一次至少让结果可解释。
    """
    by_index: dict[int, dict] = {}
    for item in outputs or []:
        idx = item.get("index")
        if isinstance(idx, int):
            by_index[idx] = item
    return [
        {
            "label": by_index[k].get("label"),
            "agent_key": by_index[k].get("agent_key"),
            "output": by_index[k].get("output"),
            "node_id": by_index[k].get("node_id"),
        }
        for k in sorted(by_index)
    ]


def thread_id_for(run_id: str) -> str:
    """线程 id == run id。

    一个 run 就是一条执行线程，续跑复用同一个 run（因此也复用同一个 thread_id）
    才能接着最后一份 checkpoint 跑 —— 若续跑新建 run、新开线程，已完成步骤的
    LLM 花费就白花了，等于把「断点续跑」退化成「重跑一遍」。
    """
    return run_id


def recursion_limit_for(node_count: int) -> int:
    """图执行的最大 super-step 数：线性 N 步需要 N+1 步，留一倍余量给分支与循环检测。"""
    return max(_MIN_RECURSION_LIMIT, node_count * 2 + 10)


def _render_context(results: list[dict], predecessors: list[str]) -> list[dict]:
    """构造本步骤的模板渲染上下文，把 `{{prev_output}}` 指向**图上的前置节点**。

    改造前「上一步」= 结果列表的最后一条，等于「执行顺序上的上一步」。有了分支之后
    这个定义就崩了：并行分支的完成顺序不确定，「最后一条」可能是任何一个兄弟节点。
    所以改成按图拓扑解析 —— 前置节点必然在更早的 super-step 完成，结果是确定的。

    多前置（汇聚）时取各分支输出的拼接：两个分支都跑过才轮到汇聚，
    用户想要的显然是「看到两边的结论」而不是「随便挑一个」。
    """
    if not predecessors:
        return results
    wanted = set(predecessors)
    mine = [r for r in results if r.get("node_id") in wanted]
    if not mine:
        return results
    # 唯一前置恰好是结果里的最后一条：prev_output 本来就指向它，不必追加
    if len(mine) == 1 and results and mine[0].get("node_id") == results[-1].get("node_id"):
        return results
    merged = dict(mine[-1])
    merged["output"] = MERGE_SEPARATOR.join(r.get("output") or "" for r in mine)
    return [*results, merged]


def _make_node(
    step: StepNode,
    *,
    predecessors: list[str],
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    tenant_id: str,
    engine_factory: Callable[[], AiEngine],
):
    """把一步编译成图节点函数。"""

    async def run_step(state: WorkflowState) -> dict:
        results = sort_results(state.get("outputs"))
        params = render(step.params, _render_context(results, predecessors))
        async with session_factory() as db:
            user = await db.get(User, user_id)
            if user is None:
                raise WorkflowGraphError(f"user {user_id} not found")
            # 内置 + DB 自定义 Agent 统一解析（自定义步骤在定时调度里也能执行）
            agent = await resolve_agent(db, step.agent_key)
            if agent is None:
                raise WorkflowGraphError(f"unknown agent: {step.agent_key}")
            ctx = AgentContext(
                db=db, user=user, engine=engine_factory(), tenant_id=tenant_id
            )
            output = await agent.run(ctx, params)
        return {
            "outputs": [
                {
                    "index": step.index,
                    "node_id": step.node_id,
                    "label": step.label,
                    "agent_key": step.agent_key,
                    "output": output,
                }
            ]
        }

    return run_step


def _make_router(
    node: StepNode, out_edges: list[Edge], graph_name: dict[str, str]
):
    """出边路由：走所有条件成立的边；无条件边恒成立。

    多条边同时成立 = 并行扇出（LangGraph 返回列表即多目的地）。一条都不成立时抛错
    而不是静默结束 —— 静默结束会让 run 记成 succeeded，用户看到「成功了但只跑了一半」，
    这是最难查的一类问题。

    返回值必须是图上的节点名（n{i}）而不是 node_id，见模块 docstring 的命名说明。
    """

    def route(state: WorkflowState) -> list[str]:
        results = sort_results(state.get("outputs"))
        taken = [
            graph_name[e.target]
            for e in out_edges
            if e.when is None or evaluate(e.when, results)
        ]
        if not taken:
            raise WorkflowGraphError(
                f"步骤「{node.label}」的所有分支条件都不成立，流程无路可走"
            )
        return list(dict.fromkeys(taken))  # 同一目标的多条边只走一次

    return route


def build_workflow_graph(
    steps: list[dict] | None,
    edges: list[dict] | None,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    tenant_id: str,
    engine_factory: Callable[[], AiEngine],
    checkpointer: Any = None,
) -> CompiledStateGraph:
    """编译工作流图。每次运行都重新编译 —— 拓扑来自刚读到的 workflow，
    缓存一份图意味着改完工作流后旧图还在跑，代价（编译开销）远小于收益。"""
    nodes = collect_nodes(steps)
    if not nodes:
        raise WorkflowGraphError("工作流没有任何步骤")
    norm = normalize_edges(nodes, edges)
    preds, out = _preds_and_out(nodes, norm)
    graph_name = {n.node_id: f"n{n.index}" for n in nodes}

    builder = StateGraph(WorkflowState)
    for n in nodes:
        builder.add_node(
            graph_name[n.node_id],
            _make_node(
                n,
                predecessors=preds[n.node_id],
                session_factory=session_factory,
                user_id=user_id,
                tenant_id=tenant_id,
                engine_factory=engine_factory,
            ),
        )

    builder.add_edge(START, graph_name[_entry_node(nodes, preds)])
    for n in nodes:
        name = graph_name[n.node_id]
        if out[n.node_id]:
            builder.add_conditional_edges(
                name, _make_router(n, out[n.node_id], graph_name)
            )
        else:
            builder.add_edge(name, END)
    return builder.compile(checkpointer=checkpointer)
