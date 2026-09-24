"""条件分支 / 并行扇出 / 汇聚 / 断点续跑的端到端测试。

走完整的 HTTP → 后台 asyncio 任务 → LangGraph 图 → 真库 checkpointer 链路，
不是对着内部函数打桩 —— 这几条正是「换了引擎之后还成立吗」最该验的东西。
"""

import asyncio

import pytest


class _ScriptedEngine:
    """按 prompt 里的关键词决定回答，可控制延迟与失败次数。

    关键词挂在 `interview_questions` 的 topic 上（会原样出现在 prompt 的「主题「X」」里），
    这样每个节点都能拿到可区分的输出，且不必给测试专门造 Agent。
    """

    def __init__(self, rules: list[tuple[str, str]], default: str = "默认输出"):
        self.rules = rules
        self.default = default
        self.queries: list[str] = []
        self.fail_times: dict[str, int] = {}
        self.delays: dict[str, float] = {}

    async def chat(self, query: str, user: str = "unknown") -> str:
        self.queries.append(query)
        for needle, answer in self.rules:
            if needle in query:
                if self.delays.get(needle):
                    # 用于把并行分支的完成顺序掰成「后发先至」
                    await asyncio.sleep(self.delays[needle])
                if self.fail_times.get(needle, 0) > 0:
                    self.fail_times[needle] -= 1
                    raise RuntimeError("引擎挂了")
                return answer
        return self.default

    async def knowledge_query(self, query: str, user: str = "unknown") -> str:
        return self.default

    def hits(self, needle: str) -> int:
        """某个节点实际被调用了几次 —— 续跑测试靠它证明「已完成步骤没重跑」。"""
        return sum(1 for q in self.queries if needle in q)


def _step(label: str, node_id: str, topic: str) -> dict:
    return {
        "label": label,
        "agent_key": "interview_questions",
        "params": {"topic": topic},
        "node_id": node_id,
    }


async def _create(client, headers, name: str, steps, edges=None) -> str:
    body: dict = {"name": name, "steps": steps}
    if edges is not None:
        body["edges"] = edges
    r = await client.post("/api/workflows", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _run(client, headers, wf_id: str) -> str:
    r = await client.post(f"/api/workflows/{wf_id}/run", headers=headers)
    assert r.status_code == 202
    return r.json()["run_id"]


# ---------------------------------------------------------------- 条件分支


async def test_conditional_branch_skips_other_path(client, auth_headers, monkeypatch, wait_run):
    """条件成立的那条分支跑，另一条整支跳过 —— 连 LLM 调用都不该发生。"""
    fake = _ScriptedEngine(
        [("T-ROOT", "存在重大风险"), ("T-RISK", "风险结论"), ("T-SAFE", "安全结论")]
    )
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)

    wf_id = await _create(
        client,
        auth_headers,
        "条件分支",
        [
            _step("判断", "a", "T-ROOT"),
            _step("有风险", "b", "T-RISK"),
            _step("无风险", "c", "T-SAFE"),
        ],
        [
            {
                "source": "a",
                "target": "b",
                "when": {"op": "contains", "left": "{{prev_output}}", "right": "风险"},
            },
            {
                "source": "a",
                "target": "c",
                "when": {"op": "not_contains", "left": "{{prev_output}}", "right": "风险"},
            },
        ],
    )
    data = await wait_run(await _run(client, auth_headers, wf_id), auth_headers)
    assert data["status"] == "succeeded", data.get("error")
    assert [r["node_id"] for r in data["results"]] == ["a", "b"]
    # 被跳过的分支一次模型调用都没发生（省钱，也是「跳过」的定义）
    assert fake.hits("T-SAFE") == 0
    assert fake.hits("T-RISK") == 1


async def test_dead_end_fails_run_instead_of_quiet_success(
    client, auth_headers, monkeypatch, wait_run
):
    """所有出边条件都不成立 → 明确失败。

    若静默结束，run 会被记成 succeeded 但只跑了一半，用户看到的是「成功了但结果不对」，
    这是最难排查的一类问题。
    """
    fake = _ScriptedEngine([("T-ROOT", "一切正常")])
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)

    wf_id = await _create(
        client,
        auth_headers,
        "死路",
        [_step("判断", "a", "T-ROOT"), _step("后续", "b", "T-NEXT")],
        [
            {
                "source": "a",
                "target": "b",
                "when": {"op": "contains", "left": "{{prev_output}}", "right": "绝不出现的词"},
            }
        ],
    )
    data = await wait_run(await _run(client, auth_headers, wf_id), auth_headers)
    assert data["status"] == "failed"
    assert "无路可走" in data["error"]
    assert fake.hits("T-NEXT") == 0


# ---------------------------------------------------------------- 并行扇出


async def test_parallel_fanout_sorts_results_by_step_order(
    client, auth_headers, monkeypatch, wait_run
):
    """两分支真并行；完成顺序是「后发先至」，但 results 必须按 steps 顺序收口。

    让第 2 步故意比第 3 步慢：如果结果按完成顺序追加，这里就会得到 [a, c, b]。
    """
    fake = _ScriptedEngine([("T-ROOT", "起点结论"), ("T-SLOW", "慢分支"), ("T-FAST", "快分支")])
    fake.delays = {"T-SLOW": 0.2}
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)

    wf_id = await _create(
        client,
        auth_headers,
        "并行",
        [_step("起点", "a", "T-ROOT"), _step("慢", "b", "T-SLOW"), _step("快", "c", "T-FAST")],
        # 两条无条件出边 = 并行扇出
        [{"source": "a", "target": "b"}, {"source": "a", "target": "c"}],
    )
    data = await wait_run(await _run(client, auth_headers, wf_id), auth_headers)
    assert data["status"] == "succeeded", data.get("error")
    assert [r["node_id"] for r in data["results"]] == ["a", "b", "c"]
    assert [r["output"] for r in data["results"]] == ["起点结论", "慢分支", "快分支"]


async def test_join_node_sees_both_branch_outputs(
    client, auth_headers, monkeypatch, wait_run
):
    """菱形汇聚：汇聚节点的 {{prev_output}} 是两条分支输出的拼接，而不是随便挑一个。"""
    fake = _ScriptedEngine(
        [("T-ROOT", "起点结论"), ("T-B", "B分支结论"), ("T-C", "C分支结论")]
    )
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)

    join_step = {
        "label": "汇总",
        "agent_key": "interview_questions",
        "params": {"topic": "{{prev_output}}"},
        "node_id": "d",
    }
    wf_id = await _create(
        client,
        auth_headers,
        "菱形",
        [_step("起点", "a", "T-ROOT"), _step("B", "b", "T-B"), _step("C", "c", "T-C"), join_step],
        [
            {"source": "a", "target": "b"},
            {"source": "a", "target": "c"},
            {"source": "b", "target": "d"},
            {"source": "c", "target": "d"},
        ],
    )
    data = await wait_run(await _run(client, auth_headers, wf_id), auth_headers)
    assert data["status"] == "succeeded", data.get("error")
    # 汇聚节点只跑一次（两分支同一步完成，写被合并）
    assert [r["node_id"] for r in data["results"]] == ["a", "b", "c", "d"]
    merged = [q for q in fake.queries if "B分支结论" in q and "C分支结论" in q]
    assert len(merged) == 1, "汇聚节点应当同时看到两条分支的输出"


# ---------------------------------------------------------------- 断点续跑


async def test_resume_after_failure_skips_completed_steps(
    client, auth_headers, monkeypatch, wait_run
):
    """失败后从断点续跑：已完成的步骤不重跑，LLM 花费不白花。"""
    fake = _ScriptedEngine([("T-0", "第一步输出"), ("T-1", "第二步输出"), ("T-2", "第三步输出")])
    fake.fail_times = {"T-1": 1}  # 第二步第一次必挂
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)

    wf_id = await _create(
        client,
        auth_headers,
        "会挂的链",
        [_step("一", "s0", "T-0"), _step("二", "s1", "T-1"), _step("三", "s2", "T-2")],
    )
    run_id = await _run(client, auth_headers, wf_id)
    failed = await wait_run(run_id, auth_headers)
    assert failed["status"] == "failed"
    assert "引擎挂了" in failed["error"]
    # 失败也要留下「跑到哪一步挂的」：旧实现只在成功时写 results，失败记录是空的
    assert [r["node_id"] for r in failed["results"]] == ["s0"]
    assert fake.hits("T-0") == 1

    r = await client.post(f"/api/workflows/runs/{run_id}/resume", headers=auth_headers)
    assert r.status_code == 202
    done = await wait_run(run_id, auth_headers)
    assert done["status"] == "succeeded", done.get("error")
    assert [r["node_id"] for r in done["results"]] == ["s0", "s1", "s2"]
    # 续跑不新建 run，同一条记录上记下续跑时间
    assert done["resumed_at"] is not None

    # 关键断言：第一步全程只被调用过一次 —— 续跑是从断点接上的，不是重跑一遍
    assert fake.hits("T-0") == 1
    assert fake.hits("T-1") == 2  # 失败那次 + 续跑重试那次
    assert fake.hits("T-2") == 1


async def test_resume_rejected_unless_failed(client, auth_headers, monkeypatch, wait_run):
    """只有 failed 能续跑：running 再提交一次会让同一线程被两个协程同时推进。"""
    fake = _ScriptedEngine([("T-0", "输出")])
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)
    wf_id = await _create(client, auth_headers, "正常的链", [_step("一", "s0", "T-0")])
    run_id = await _run(client, auth_headers, wf_id)
    assert (await wait_run(run_id, auth_headers))["status"] == "succeeded"

    r = await client.post(f"/api/workflows/runs/{run_id}/resume", headers=auth_headers)
    assert r.status_code == 409
    assert "succeeded" in r.json()["detail"]


# ---------------------------------------------------------------- 保存时校验


@pytest.mark.parametrize(
    ("edges", "match"),
    [
        # 环
        ([{"source": "a", "target": "b"}, {"source": "b", "target": "a"}], "存在环"),
        # 两条互不相连的链 → 两个入口
        ([{"source": "a", "target": "b"}, {"source": "c", "target": "b"}], "多个起始步骤"),
        # 指向不存在的节点
        ([{"source": "a", "target": "ghost"}], "连线终点不存在"),
        # 条件结构非法
        (
            [{"source": "a", "target": "b", "when": {"op": "no_such_op"}}],
            "未知条件类型",
        ),
    ],
)
async def test_invalid_graph_rejected_at_save(client, auth_headers, edges, match):
    """非法结构在保存时就 422，而不是等定时任务凌晨跑挂。"""
    r = await client.post(
        "/api/workflows",
        json={
            "name": "坏图",
            "steps": [_step("一", "a", "T-0"), _step("二", "b", "T-1"), _step("三", "c", "T-2")],
            "edges": edges,
        },
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert match in r.json()["detail"]


async def test_edges_persist_and_null_means_linear(client, auth_headers, monkeypatch, wait_run):
    """不传 edges = 线性（存量形态）；传了就回读一致。"""
    fake = _ScriptedEngine([("T-0", "甲"), ("T-1", "乙")])
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)
    steps = [_step("一", "a", "T-0"), _step("二", "b", "T-1")]

    # 不传 edges：落库为 NULL，按 steps 顺序自动连成链
    linear_id = await _create(client, auth_headers, "线性", steps)
    r = await client.get(f"/api/workflows/{linear_id}", headers=auth_headers)
    assert r.json()["edges"] is None
    data = await wait_run(await _run(client, auth_headers, linear_id), auth_headers)
    assert [x["output"] for x in data["results"]] == ["甲", "乙"]

    # PATCH 只改 edges：校验要用「新 edges + 库里 steps」的组合形态
    r = await client.patch(
        f"/api/workflows/{linear_id}",
        json={"edges": [{"source": "a", "target": "b", "when": {"op": "not_empty", "left": "{{prev_output}}"}}]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["edges"][0]["source"] == "a"
    assert r.json()["edges"][0]["when"]["op"] == "not_empty"

    # 显式传 null = 退回线性
    r = await client.patch(f"/api/workflows/{linear_id}", json={"edges": None}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["edges"] is None


async def test_delete_workflow_cleans_checkpoints(client, auth_headers, monkeypatch, wait_run):
    """删除工作流要连带清掉图状态：检查点表上没有外键，级联帮不上忙。"""
    from sqlalchemy import func, select

    from app.main import app
    from app.models.checkpoint import LangGraphCheckpoint

    fake = _ScriptedEngine([("T-0", "输出")])
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)
    wf_id = await _create(client, auth_headers, "待删", [_step("一", "s0", "T-0")])
    run_id = await _run(client, auth_headers, wf_id)
    await wait_run(run_id, auth_headers)

    factory = app.state.test_session_factory
    async with factory() as db:
        before = (
            await db.execute(
                select(func.count()).select_from(LangGraphCheckpoint).where(
                    LangGraphCheckpoint.thread_id == run_id
                )
            )
        ).scalar_one()
    assert before > 0

    assert (await client.delete(f"/api/workflows/{wf_id}", headers=auth_headers)).status_code == 204
    async with factory() as db:
        after = (
            await db.execute(
                select(func.count()).select_from(LangGraphCheckpoint).where(
                    LangGraphCheckpoint.thread_id == run_id
                )
            )
        ).scalar_one()
    assert after == 0
