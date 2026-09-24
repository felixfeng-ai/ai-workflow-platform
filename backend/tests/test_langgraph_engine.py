"""LangGraph 改造的单元层测试：图结构、条件 DSL、checkpointer、模型门面。

端到端（分支/并行/续跑走完整 API）在 test_workflow_branching.py。
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.llm.chat_model import AiEngineChatModel, content_text, to_engine_query
from app.llm.checkpointer import SqlAlchemyCheckpointer, delete_threads
from app.main import app
from app.workflows.conditions import ConditionError, evaluate, validate_condition
from app.workflows.graph import (
    WorkflowGraphError,
    collect_nodes,
    normalize_edges,
    recursion_limit_for,
    sort_results,
    thread_id_for,
    validate_graph,
)
from app.workflows.templates import render, resolve


class _FakeEngine:
    """鸭子类型的引擎替身：记录 query，按脚本吐答案。"""

    def __init__(self, answer: str = "输出", chunks: list[str] | None = None):
        self.answer = answer
        self.chunks = chunks or ["a", "b"]
        self.queries: list[str] = []
        self.streamed: list[list[dict]] = []

    async def chat(self, query: str, user: str = "unknown") -> str:
        self.queries.append(query)
        return self.answer

    async def knowledge_query(self, query: str, user: str = "unknown") -> str:
        return self.answer

    async def stream_chat(self, messages: list[dict], user: str = "unknown"):
        self.streamed.append(messages)
        for c in self.chunks:
            yield c


def _steps(*node_ids: str) -> list[dict]:
    return [
        {"label": f"步骤{i}", "agent_key": "weekly_report", "params": {}, "node_id": nid}
        for i, nid in enumerate(node_ids)
    ]


# ---------------------------------------------------------------- 结构归一


def test_normalize_edges_linear_when_null():
    """edges 为 NULL/空 = 存量线性工作流，按 steps 顺序自动连成一条链。"""
    nodes = collect_nodes(_steps("a", "b", "c"))
    edges = normalize_edges(nodes, None)
    assert [(e.source, e.target) for e in edges] == [("a", "b"), ("b", "c")]
    assert all(e.when is None for e in edges)
    assert normalize_edges(nodes, []) == edges


def test_collect_nodes_synthesizes_missing_node_id():
    """旧式 steps 没有 node_id，按下标合成 —— 与前端画布的缺省 id 规则一致。"""
    nodes = collect_nodes([{"label": "第一步", "agent_key": "weekly_report", "params": {}}])
    assert nodes[0].node_id == "node-0"
    assert nodes[0].label == "第一步"


def test_collect_nodes_rejects_duplicate_node_id():
    with pytest.raises(WorkflowGraphError, match="节点 id 重复"):
        collect_nodes(_steps("dup", "dup"))


# ---------------------------------------------------------------- 图校验


def test_validate_linear_and_diamond_ok():
    validate_graph(_steps("a", "b"), None)
    # 菱形：a 并行扇出 b/c，再汇聚到 d。两分支等深，合法
    validate_graph(
        _steps("a", "b", "c", "d"),
        [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "c"},
            {"source": "b", "target": "d"},
            {"source": "c", "target": "d"},
        ],
    )


def test_validate_rejects_cycle():
    with pytest.raises(WorkflowGraphError, match="存在环"):
        validate_graph(
            _steps("a", "b"),
            [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
        )


def test_validate_rejects_self_loop():
    with pytest.raises(WorkflowGraphError, match="不能连到自己"):
        validate_graph(_steps("a"), [{"source": "a", "target": "a"}])


def test_validate_rejects_two_entries():
    """两个无入边节点 = 不知道从哪开始，必须拒绝而不是随便挑一个。"""
    with pytest.raises(WorkflowGraphError, match="多个起始步骤"):
        validate_graph(
            _steps("a", "b", "c"),
            [{"source": "a", "target": "c"}, {"source": "b", "target": "c"}],
        )


def test_validate_rejects_disconnected_node():
    """游离节点（两条互不相连的链）会撞上「多个起始步骤」而不是静默不执行。

    无环 + 唯一入口已蕴含全部可达，所以不需要（也不该有）单独的可达性校验。
    """
    with pytest.raises(WorkflowGraphError, match="多个起始步骤"):
        validate_graph(
            _steps("a", "b", "c"),
            [{"source": "a", "target": "b"}, {"source": "c", "target": "b"}],
        )


def test_validate_rejects_unknown_endpoint():
    with pytest.raises(WorkflowGraphError, match="连线终点不存在"):
        validate_graph(_steps("a"), [{"source": "a", "target": "ghost"}])


def test_validate_rejects_uneven_join():
    """不等深汇聚必须拦在保存时：否则先到的分支会让汇聚节点多跑一次（白烧一次 LLM）。

    拓扑：a → b → c ┐
          a → d ────┴→ e   （c 在第 3 层、d 在第 2 层，e 会被触发两次）
    """
    with pytest.raises(WorkflowGraphError, match="深度不一致"):
        validate_graph(
            _steps("a", "b", "c", "d", "e"),
            [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "c"},
                {"source": "a", "target": "d"},
                {"source": "c", "target": "e"},
                {"source": "d", "target": "e"},
            ],
        )


def test_validate_rejects_bad_condition():
    with pytest.raises(ConditionError, match="未知条件类型"):
        validate_graph(
            _steps("a", "b"),
            [{"source": "a", "target": "b", "when": {"op": "evil_call"}}],
        )


def test_validate_allows_empty_workflow():
    """空工作流仍然合法（存量行为：跑 0 步算成功），由执行器短路处理。"""
    validate_graph([], None)


# ---------------------------------------------------------------- 结果收口


def test_sort_results_orders_by_step_index():
    """并行下完成顺序 ≠ steps 顺序，收口必须按下标排序。"""
    out = sort_results(
        [
            {"index": 2, "label": "c", "agent_key": "k", "output": "C", "node_id": "n2"},
            {"index": 0, "label": "a", "agent_key": "k", "output": "A", "node_id": "n0"},
        ]
    )
    assert [r["output"] for r in out] == ["A", "C"]


def test_sort_results_dedupes_keeping_last():
    """同一节点跑两次时保留最后一次（不等深汇聚的兜底，保存时已拦）。"""
    out = sort_results(
        [
            {"index": 0, "output": "旧", "label": "a", "agent_key": "k", "node_id": "n0"},
            {"index": 0, "output": "新", "label": "a", "agent_key": "k", "node_id": "n0"},
        ]
    )
    assert [r["output"] for r in out] == ["新"]


def test_recursion_limit_scales_with_steps():
    """默认 25 步上限会让 24 步以上的线性工作流抛 GraphRecursionError。"""
    assert recursion_limit_for(1) == 25
    assert recursion_limit_for(50) > 50
    assert thread_id_for("run-1") == "run-1"


# ---------------------------------------------------------------- 条件 DSL


def _results(*outputs: str) -> list[dict]:
    return [
        {"label": f"s{i}", "agent_key": "k", "output": o, "node_id": f"n{i}"}
        for i, o in enumerate(outputs)
    ]


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"op": "contains", "left": "{{prev_output}}", "right": "风险"}, True),
        ({"op": "not_contains", "left": "{{prev_output}}", "right": "风险"}, False),
        ({"op": "starts_with", "left": "{{prev_output}}", "right": "重大"}, True),
        ({"op": "ends_with", "left": "{{prev_output}}", "right": "。"}, True),
        ({"op": "eq", "left": "{{prev_output}}", "right": "重大风险。"}, True),
        ({"op": "ne", "left": "{{prev_output}}", "right": "无关"}, True),
        ({"op": "is_empty", "left": "{{step.9.output}}", "right": None}, True),
        ({"op": "not_empty", "left": "{{prev_output}}", "right": None}, True),
        ({"op": "all", "of": [
            {"op": "contains", "left": "{{prev_output}}", "right": "重大"},
            {"op": "contains", "left": "{{prev_output}}", "right": "风险"},
        ]}, True),
        ({"op": "any", "of": [
            {"op": "contains", "left": "{{prev_output}}", "right": "没有这个词"},
            {"op": "contains", "left": "{{prev_output}}", "right": "风险"},
        ]}, True),
        ({"op": "not", "of": {"op": "contains", "left": "{{prev_output}}", "right": "没有"}}, True),
    ],
)
def test_condition_ops(condition, expected):
    assert evaluate(condition, _results("重大风险。")) is expected


def test_condition_numeric_keeps_type_via_resolve():
    """resolve 保留原始类型，gt 才能拿到真数字；先渲染成 str 就只剩字符串比较。"""
    results = [{"label": "s", "agent_key": "k", "output": "42", "node_id": "n0"}]
    assert evaluate({"op": "gt", "left": "{{step.0.output}}", "right": 10}, results) is True
    assert resolve("{{step.0.output}}", results) == "42"  # 保留原值，不套额外引号


def test_condition_type_mismatch_raises_not_false():
    """静默返回 False 会让流程悄悄走另一条路（「成功但结果不对」），必须抛。"""
    with pytest.raises(ConditionError, match="需要数字"):
        evaluate({"op": "gt", "left": "{{prev_output}}", "right": 100}, _results("一段散文"))
    with pytest.raises(ConditionError, match="布尔值"):
        evaluate({"op": "gt", "left": "{{prev_output}}", "right": 1}, [{"output": True}])


def test_validate_condition_rejects_deep_nesting():
    cond: dict = {"op": "not", "of": {"op": "not_empty", "left": "{{prev_output}}"}}
    for _ in range(8):
        cond = {"op": "all", "of": [cond]}
    with pytest.raises(ConditionError, match="嵌套超过"):
        validate_condition(cond)


def test_render_still_replaces_missing_with_empty():
    """历史行为：解析不到的占位符替换为空串，不保留字面量（保留会诱导模型胡编）。"""
    assert render("前缀 {{step.9.output}} 后缀", []) == "前缀  后缀"
    validate_condition({"op": "not_empty", "left": "{{prev_output}}"})


# ---------------------------------------------------------------- 模型门面


async def test_chat_model_delegates_to_engine():
    fake = _FakeEngine("回答文本")
    model = AiEngineChatModel(engine=fake, user_id="u1")
    msg = await model.ainvoke([HumanMessage(content="你好")])
    assert isinstance(msg, AIMessage)
    assert msg.content == "回答文本"
    # 单条消息必须逐字透传，不能加角色前缀 —— 否则提示词与改造前不一致
    assert fake.queries == ["你好"]


async def test_chat_model_streams_engine_chunks():
    fake = _FakeEngine(chunks=["你", "", "好"])
    model = AiEngineChatModel(engine=fake, user_id="u1")
    chunks = [c async for c in model.astream("你好")]
    # 末尾那条空 chunk 是 LangChain 加的流终止标记（chunk_position="last"），
    # 属于框架契约：消费方靠它判定「流结束了，可以把前面合并成完整消息」。
    assert [c.content for c in chunks[:-1]] == ["你", "好"]
    assert chunks[-1].chunk_position == "last"
    # 引擎吐的空串（SSE keep-alive 空行）在中途被丢弃，不会变成空 token
    assert fake.streamed == [[{"role": "user", "content": "你好"}]]


def test_chat_model_sync_path_fails_loudly():
    """AiEngine 只有异步接口。同步路径显式报错，好过静默降级成别的东西。"""
    with pytest.raises(NotImplementedError):
        AiEngineChatModel(engine=_FakeEngine()).invoke("你好")


def test_to_engine_query_joins_multi_message():
    assert to_engine_query([SystemMessage(content="你是助手"), HumanMessage(content="问题")]) == (
        "你是助手\n\n问题"
    )
    assert content_text([{"text": "a"}, {"text": "b"}]) == "ab"


# ---------------------------------------------------------------- checkpointer


def _checkpoint(cid: str, outputs: list) -> dict:
    return {
        "v": 4,
        "id": cid,
        "ts": "2026-09-23T00:00:00+00:00",
        "channel_values": {"outputs": outputs},
        "channel_versions": {"outputs": "1"},
        "versions_seen": {},
    }


async def test_checkpointer_roundtrip(client):
    """自研 saver 的读写闭环：落库 → 按 thread 取最近一条 → 取挂起写入 → 删线程。"""
    saver = SqlAlchemyCheckpointer(app.state.test_session_factory, tenant_id="t1")
    cfg = {"configurable": {"thread_id": "run-1", "checkpoint_ns": ""}}

    saved = await saver.aput(cfg, _checkpoint("0001.0001", ["A"]), {"source": "loop", "step": 0}, {})
    assert saved["configurable"]["checkpoint_id"] == "0001.0001"

    # 不给 checkpoint_id 时取最近一条；id 前导零定宽，字典序 == 时间序
    await saver.aput(cfg, _checkpoint("0002.0001", ["A", "B"]), {"source": "loop", "step": 1}, {})
    latest = await saver.aget_tuple({"configurable": {"thread_id": "run-1"}})
    assert latest is not None
    assert latest.checkpoint["channel_values"]["outputs"] == ["A", "B"]
    assert latest.metadata["step"] == 1
    assert latest.parent_config is None  # 本次没带 checkpoint_id，故无父链

    # 指定 checkpoint_id 时精确取那一条，并串上父链
    older = await saver.aget_tuple(
        {"configurable": {"thread_id": "run-1", "checkpoint_id": "0001.0001"}}
    )
    assert older is not None and older.checkpoint["id"] == "0001.0001"

    # 挂起写入：返回值是官方约定的 (task_id, channel, value) 三元组，顺序不能错
    await saver.aput_writes(
        {"configurable": {"thread_id": "run-1", "checkpoint_id": "0002.0001"}},
        [("outputs", [{"index": 1, "output": "B"}])],
        "task-1",
    )
    with_writes = await saver.aget_tuple({"configurable": {"thread_id": "run-1"}})
    assert with_writes.pending_writes == [("task-1", "outputs", [{"index": 1, "output": "B"}])]

    # 历史列表：倒序 + limit
    history = [t async for t in saver.alist({"configurable": {"thread_id": "run-1"}})]
    assert [t.checkpoint["id"] for t in history] == ["0002.0001", "0001.0001"]
    assert len([t async for t in saver.alist({"configurable": {"thread_id": "run-1"}}, limit=1)]) == 1

    # 未知线程取不到东西，不抛异常
    assert await saver.aget_tuple({"configurable": {"thread_id": "nope"}}) is None

    await saver.adelete_thread("run-1")
    assert await saver.aget_tuple({"configurable": {"thread_id": "run-1"}}) is None


async def test_delete_threads_helper(client):
    """批量清理：删除工作流时按 run id 清检查点（表上没有外键，级联帮不上忙）。"""
    from app.db import get_db  # noqa: F401 - 仅为说明这里用的是请求级会话

    factory = app.state.test_session_factory
    saver = SqlAlchemyCheckpointer(factory, tenant_id="t1")
    for rid in ("r1", "r2"):
        await saver.aput(
            {"configurable": {"thread_id": rid, "checkpoint_ns": ""}},
            _checkpoint("0001.0001", []),
            {"source": "input", "step": -1},
            {},
        )
    async with factory() as db:
        await delete_threads(db, ["r1", "r2", ""])
        await db.commit()
    for rid in ("r1", "r2"):
        assert await saver.aget_tuple({"configurable": {"thread_id": rid}}) is None
