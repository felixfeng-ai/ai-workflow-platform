import pytest

from app.workflows.executor import interpolate
from app.workflows.scheduler import workflow_scheduler


class _FakeEngine:
    """后台引擎替身：返回固定回答并记录查询。"""

    def __init__(self, answer: str = "工作流输出"):
        self.answer = answer
        self.queries: list[str] = []

    async def chat(self, query: str, user: str = "unknown") -> str:
        self.queries.append(query)
        return self.answer

    async def knowledge_query(self, query: str, user: str = "unknown") -> str:
        return self.answer


def _steps(*agent_keys: str) -> list[dict]:
    return [
        {"label": f"步骤{i + 1}", "agent_key": k, "params": {}}
        for i, k in enumerate(agent_keys)
    ]


def _graph_steps(*agent_keys: str) -> list[dict]:
    """带画布元数据的步骤（node_id + position），供可视化编排持久化测试。"""
    return [
        {
            "label": f"步骤{i + 1}",
            "agent_key": k,
            "params": {},
            "node_id": f"n{i}",
            "position": {"x": i * 240, "y": 0},
        }
        for i, k in enumerate(agent_keys)
    ]


# ---------- interpolate 纯函数 ----------


def test_interpolate():
    results = [
        {"label": "a", "agent_key": "x", "output": "第一步"},
        {"label": "b", "agent_key": "y", "output": "第二步"},
    ]
    assert interpolate("{{prev_output}}", results) == "第二步"
    assert interpolate("{{step.0.output}} 与 {{step.1.output}}", results) == "第一步 与 第二步"
    assert interpolate({"a": "{{prev_output}}", "b": ["{{step.0.output}}"]}, results) == {
        "a": "第二步",
        "b": ["第一步"],
    }
    assert interpolate(42, results) == 42
    assert interpolate("无模板", []) == "无模板"


# ---------- CRUD ----------


async def test_workflow_crud(client, auth_headers):
    payload = {
        "name": "每日巡检",
        "description": "周一自动巡检",
        "steps": _steps("inspection_report", "weekly_report"),
        "schedule": {"cron": "0 9 * * 1"},
    }
    r = await client.post("/api/workflows", json=payload, headers=auth_headers)
    assert r.status_code == 201
    wf = r.json()
    wf_id = wf["id"]
    assert wf["name"] == "每日巡检"
    assert wf["schedule"] == {"cron": "0 9 * * 1"}
    assert len(wf["steps"]) == 2
    assert wf["enabled"] is True

    r = await client.get("/api/workflows", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.get(f"/api/workflows/{wf_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == wf_id

    r = await client.patch(
        f"/api/workflows/{wf_id}",
        json={"name": "每日巡检 v2", "enabled": False},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "每日巡检 v2"
    assert r.json()["enabled"] is False

    r = await client.delete(f"/api/workflows/{wf_id}", headers=auth_headers)
    assert r.status_code == 204
    r = await client.get("/api/workflows", headers=auth_headers)
    assert r.json() == []


async def test_workflow_create_unknown_agent(client, auth_headers):
    r = await client.post(
        "/api/workflows",
        json={"name": "坏流程", "steps": _steps("no_such_agent")},
        headers=auth_headers,
    )
    assert r.status_code == 422


async def test_workflow_not_owned_404(client, auth_headers):
    r = await client.post(
        "/api/workflows", json={"name": "A 的流程", "steps": _steps("weekly_report")},
        headers=auth_headers,
    )
    wf_id = r.json()["id"]

    r = await client.post(
        "/api/auth/register",
        json={"email": "b@example.com", "password": "secret123", "name": "B"},
    )
    headers_b = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # B 的列表看不到 A 的工作流（租户隔离）
    assert (await client.get("/api/workflows", headers=headers_b)).json() == []
    assert (await client.get(f"/api/workflows/{wf_id}", headers=headers_b)).status_code == 404
    assert (
        await client.delete(f"/api/workflows/{wf_id}", headers=headers_b)
    ).status_code == 404
    # B 不能运行 A 的工作流（租户隔离）
    assert (
        await client.post(f"/api/workflows/{wf_id}/run", headers=headers_b)
    ).status_code == 404


# ---------- 手动运行 + 链式 ----------


async def test_manual_run_chains_outputs(client, auth_headers, monkeypatch, wait_run):
    fake = _FakeEngine("题库输出")
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)

    steps = [
        {"label": "出题", "agent_key": "interview_questions", "params": {"topic": "FastAPI"}},
        # 第二步主题引用第一步输出（模板在 executor 中 interpolate 后传入 Agent）
        {"label": "追加深挖", "agent_key": "interview_questions", "params": {"topic": "{{step.0.output}}"}},
    ]
    r = await client.post(
        "/api/workflows", json={"name": "押题流程", "steps": steps}, headers=auth_headers
    )
    wf_id = r.json()["id"]

    r = await client.post(f"/api/workflows/{wf_id}/run", headers=auth_headers)
    assert r.status_code == 202
    data = await wait_run(r.json()["run_id"], auth_headers)
    assert data["status"] == "succeeded"
    assert data["triggered_by"] == "manual"
    assert len(data["results"]) == 2
    assert data["results"][0]["agent_key"] == "interview_questions"
    assert data["results"][0]["output"] == "题库输出"
    # 第二步 query 里应出现第一步 output（验证 interpolate 生效）
    assert len(fake.queries) == 2
    assert "题库输出" in fake.queries[1]


async def test_manual_run_failure_records_error(client, auth_headers, monkeypatch, wait_run):
    class _RaisingEngine(_FakeEngine):
        async def chat(self, query: str, user: str = "unknown") -> str:
            raise RuntimeError("引擎挂了")

    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: _RaisingEngine())
    r = await client.post(
        "/api/workflows",
        json={
            "name": "会挂的流程",
            "steps": [
                {"label": "出题", "agent_key": "interview_questions", "params": {"topic": "FastAPI"}}
            ],
        },
        headers=auth_headers,
    )
    wf_id = r.json()["id"]
    r = await client.post(f"/api/workflows/{wf_id}/run", headers=auth_headers)
    data = await wait_run(r.json()["run_id"], auth_headers)
    assert data["status"] == "failed"
    assert "引擎挂了" in data["error"]


async def test_list_workflow_runs_paginated(client, auth_headers, monkeypatch, wait_run):
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: _FakeEngine())
    r = await client.post(
        "/api/workflows",
        json={"name": "跑三次", "steps": _steps("weekly_report")},
        headers=auth_headers,
    )
    wf_id = r.json()["id"]
    for _ in range(3):
        r = await client.post(f"/api/workflows/{wf_id}/run", headers=auth_headers)
        await wait_run(r.json()["run_id"], auth_headers)

    r = await client.get("/api/workflows/runs?page_size=2", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


# ---------- 定时路径 ----------


async def test_scheduled_trigger_runs_workflow(client, auth_headers, monkeypatch, wait_run):
    fake = _FakeEngine("定时报告")
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: fake)

    r = await client.post(
        "/api/workflows",
        json={
            "name": "定时周报",
            "steps": _steps("weekly_report"),
            "schedule": {"cron": "0 9 * * 1"},
        },
        headers=auth_headers,
    )
    wf_id = r.json()["id"]

    # 直接调用定时触发器（无需真实等待 cron）
    await workflow_scheduler._trigger(wf_id)

    r = await client.get("/api/workflows/runs", headers=auth_headers)
    runs = r.json()["items"]
    assert len(runs) == 1
    assert runs[0]["triggered_by"] == "scheduled"
    data = await wait_run(runs[0]["id"], auth_headers)
    assert data["status"] == "succeeded"
    assert data["results"][0]["output"] == "定时报告"


async def test_scheduled_trigger_ignores_disabled(client, auth_headers, monkeypatch):
    r = await client.post(
        "/api/workflows",
        json={
            "name": "已停用",
            "steps": _steps("weekly_report"),
            "schedule": {"interval_minutes": 60},
        },
        headers=auth_headers,
    )
    wf_id = r.json()["id"]
    await client.patch(f"/api/workflows/{wf_id}", json={"enabled": False}, headers=auth_headers)

    await workflow_scheduler._trigger(wf_id)
    r = await client.get("/api/workflows/runs", headers=auth_headers)
    assert r.json()["items"] == []


# ---------- 调度器 job 管理 ----------


async def test_scheduler_registers_and_removes_job(client, auth_headers, monkeypatch):
    # 必须先启动调度器，POST 里的 reschedule 才会注册 job
    workflow_scheduler.start()
    try:
        sched = workflow_scheduler._get_scheduler()
        r = await client.post(
            "/api/workflows",
            json={
                "name": "带调度",
                "steps": _steps("weekly_report"),
                "schedule": {"cron": "0 9 * * 1"},
            },
            headers=auth_headers,
        )
        wf_id = r.json()["id"]
        assert sched.get_job(f"wf-{wf_id}") is not None

        # 停用后 job 被移除
        await client.patch(
            f"/api/workflows/{wf_id}", json={"enabled": False}, headers=auth_headers
        )
        assert sched.get_job(f"wf-{wf_id}") is None

        # 重新启用且改 interval 后 job 更新
        await client.patch(
            f"/api/workflows/{wf_id}",
            json={"enabled": True, "schedule": {"interval_minutes": 30}},
            headers=auth_headers,
        )
        assert sched.get_job(f"wf-{wf_id}") is not None
    finally:
        workflow_scheduler.shutdown()


# ---------- 可视化编排图元数据（node_id/position 透传） ----------


async def test_workflow_create_persists_graph_metadata(client, auth_headers):
    """创建时 steps 携带 node_id/position，落库后回读一致。"""
    r = await client.post(
        "/api/workflows",
        json={"name": "画布流程", "steps": _graph_steps("inspection_report", "weekly_report")},
        headers=auth_headers,
    )
    assert r.status_code == 201
    wf = r.json()
    assert len(wf["steps"]) == 2
    assert wf["steps"][0]["node_id"] == "n0"
    assert wf["steps"][0]["position"] == {"x": 0, "y": 0}
    assert wf["steps"][1]["node_id"] == "n1"

    r = await client.get(f"/api/workflows/{wf['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["steps"][1]["position"] == {"x": 240, "y": 0}


async def test_workflow_update_persists_graph_metadata(client, auth_headers):
    """旧式创建后 PATCH 为带图元数据的 steps，回读一致。"""
    r = await client.post(
        "/api/workflows", json={"name": "旧式", "steps": _steps("weekly_report")}, headers=auth_headers
    )
    wf_id = r.json()["id"]

    r = await client.patch(
        f"/api/workflows/{wf_id}",
        json={"steps": _graph_steps("weekly_report", "interview_questions")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert steps[0]["node_id"] == "n0"
    assert steps[1]["position"] == {"x": 240, "y": 0}


async def test_workflow_run_with_graph_metadata(client, auth_headers, monkeypatch, wait_run):
    """执行器不因多余字段受影响：results 顺序 = steps 顺序。

    用必填参数补齐的 agent（competitor_research 需 topic），避免空 params 触发校验失败。
    """
    monkeypatch.setattr("app.workflows.executor.get_ai_engine", lambda: _FakeEngine())
    steps = [
        {
            "label": "调研",
            "agent_key": "competitor_research",
            "params": {"topic": "AI 项目管理"},
            "node_id": "n0",
            "position": {"x": 0, "y": 0},
        },
        {
            "label": "周报",
            "agent_key": "weekly_report",
            "params": {},
            "node_id": "n1",
            "position": {"x": 240, "y": 0},
        },
    ]
    r = await client.post(
        "/api/workflows", json={"name": "画布执行", "steps": steps}, headers=auth_headers
    )
    wf_id = r.json()["id"]

    r = await client.post(f"/api/workflows/{wf_id}/run", headers=auth_headers)
    assert r.status_code == 202
    data = await wait_run(r.json()["run_id"], auth_headers)
    assert data["status"] == "succeeded"
    assert [x["agent_key"] for x in data["results"]] == ["competitor_research", "weekly_report"]


async def test_workflow_unknown_agent_with_graph_metadata(client, auth_headers):
    """图元数据不绕过 agent 校验：未知 agent_key 仍 422。"""
    r = await client.post(
        "/api/workflows",
        json={"name": "坏画布", "steps": _graph_steps("no_such_agent")},
        headers=auth_headers,
    )
    assert r.status_code == 422


async def test_workflow_legacy_steps_still_accepted(client, auth_headers):
    """无 node_id/position 的旧式 steps 仍可创建（兼容存量数据）。"""
    r = await client.post(
        "/api/workflows",
        json={"name": "存量流程", "steps": _steps("weekly_report")},
        headers=auth_headers,
    )
    assert r.status_code == 201
    step = r.json()["steps"][0]
    assert "node_id" not in step
    assert "position" not in step
