"""AI 起草工作流：接口与规整逻辑测试。

沿用 test_ai.py 的做法，用 dependency_overrides 把 get_ai_engine 换成回固定文本的假引擎。
这里要验的不是模型本身，而是「拿到模型输出之后怎么处理」—— 而这恰恰是这功能唯一的
风险面：模型会编不存在的助手、编 schema 里没有的参数、编不存在的项目 id。
"""

import json

import pytest

from app.ai import get_ai_engine
from app.ai.errors import AiEngineUnavailable
from app.main import app
from app.workflows.drafter import DraftError, normalize_draft, parse_draft


class _ScriptedEngine:
    """按脚本返回文本的假引擎；raw 为 None 时抛 unavailable（模拟未配置）。"""

    def __init__(self, raw: str | None) -> None:
        self.raw = raw
        self.last_query = ""

    async def chat(self, query: str, user: str = "unknown") -> str:
        self.last_query = query
        if self.raw is None:
            raise AiEngineUnavailable("AI 引擎未配置")
        return self.raw


def _use_engine(raw: str | None) -> _ScriptedEngine:
    engine = _ScriptedEngine(raw)
    app.dependency_overrides[get_ai_engine] = lambda: engine
    return engine


@pytest.fixture(autouse=True)
def _clean_override():
    yield
    app.dependency_overrides.pop(get_ai_engine, None)


def _draft(**over) -> str:
    payload = {
        "name": "竞品价格周报",
        "description": "每周抓竞品价格并出简报",
        "rationale": "按你说的三个竞品、周一一早、发群里拆成两步",
        "steps": [
            {
                "label": "抓取价格页",
                "agent_key": "competitor_research",
                "params": {"topic": "竞品价格", "urls": "https://a.com", "max_sources": 3},
            },
            {"label": "生成简报", "agent_key": "weekly_report", "params": {"period": "this_week"}},
        ],
    }
    payload.update(over)
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------- 端点


async def test_draft_requires_auth(client):
    r = await client.post("/api/workflows/draft", json={"intent": "做点什么"})
    assert r.status_code == 401


async def test_draft_returns_steps(client, auth_headers):
    _use_engine(_draft())
    r = await client.post(
        "/api/workflows/draft", json={"intent": "每周一抓竞品价格出简报"}, headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "竞品价格周报"
    assert [s["agent_key"] for s in body["steps"]] == ["competitor_research", "weekly_report"]
    # 每个步骤都要有 node_id：画布靠它建节点、靠它把运行结果对回来
    assert all(s["node_id"] for s in body["steps"])
    # 节点要有坐标，否则落到画布上全叠在原点
    assert all(isinstance(s["position"]["x"], (int, float)) for s in body["steps"])
    # 没给 edges = 线性：不落 edges 字段，与存量工作流的表达一致
    assert body["edges"] is None


async def test_draft_rejects_unknown_agent(client, auth_headers):
    """模型编了一个不存在的助手：整份草稿作废，而不是悄悄丢掉那一步。

    丢掉那一步会得到一张「少做一件事」的图，用户看不出少了什么，跑完才发现。
    """
    bad = json.loads(_draft())
    bad["steps"][1]["agent_key"] = "数据分析助手"
    _use_engine(json.dumps(bad, ensure_ascii=False))
    r = await client.post("/api/workflows/draft", json={"intent": "x"}, headers=auth_headers)
    assert r.status_code == 422
    assert "数据分析助手" in r.json()["detail"]


async def test_draft_rejects_non_json(client, auth_headers):
    _use_engine("好的，我来帮你规划一下。首先你需要……")
    r = await client.post("/api/workflows/draft", json={"intent": "x"}, headers=auth_headers)
    assert r.status_code == 422


async def test_draft_rejects_empty_steps(client, auth_headers):
    _use_engine(_draft(steps=[]))
    r = await client.post("/api/workflows/draft", json={"intent": "x"}, headers=auth_headers)
    assert r.status_code == 422


async def test_draft_rejects_broken_graph(client, auth_headers):
    """模型给的分支结构过不了 validate_graph：报 422 并带上原因。

    不退回线性 —— 那等于把「AI 画错了」伪装成「AI 就是想这么画」。
    """
    steps = json.loads(_draft())["steps"]
    steps[0]["node_id"] = "a"
    steps[1]["node_id"] = "b"
    _use_engine(_draft(steps=steps, edges=[{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]))
    r = await client.post("/api/workflows/draft", json={"intent": "x"}, headers=auth_headers)
    assert r.status_code == 422
    assert "环" in r.json()["detail"]


async def test_draft_empty_intent_rejected(client, auth_headers):
    _use_engine(_draft())
    r = await client.post("/api/workflows/draft", json={"intent": "   "}, headers=auth_headers)
    assert r.status_code == 422


async def test_draft_engine_unavailable(client, auth_headers):
    _use_engine(None)
    r = await client.post("/api/workflows/draft", json={"intent": "x"}, headers=auth_headers)
    assert r.status_code == 503


async def test_draft_prompt_lists_registered_agents(client, auth_headers):
    """提示词里必须带上注册表里的助手 key —— 这是模型唯一的信息来源。"""
    engine = _use_engine(_draft())
    await client.post("/api/workflows/draft", json={"intent": "做个巡检"}, headers=auth_headers)
    assert "inspection_report" in engine.last_query
    assert "competitor_research" in engine.last_query
    # 用户原话要原样进提示词，否则起草的是别的东西
    assert "做个巡检" in engine.last_query


# ---------------------------------------------------------------- 解析与规整


def test_parse_draft_strips_markdown_fence():
    text = '```json\n{"name": "x", "steps": []}\n```'
    assert parse_draft(text) == {"name": "x", "steps": []}


def test_parse_draft_tolerates_leading_prose():
    """模型常在 JSON 前后加一句话；只取第一个完整对象，不要因为它多说一句就整体失败。"""
    text = '按你的要求整理如下：\n{"name": "x", "steps": []}\n希望有帮助！'
    assert parse_draft(text) == {"name": "x", "steps": []}


def test_parse_draft_returns_none_on_garbage():
    assert parse_draft("完全不是 JSON") is None


def test_normalize_drops_params_outside_schema():
    """schema 之外的参数一律丢弃：模型编的参数传到执行器里只会变成噪音。

    与 custom.validate_params 的宽松透传**刻意不同** —— 那条路是用户手填的，
    多带的键是他自己知道的上下文；这条路的键是模型猜的，留着就是幻觉。
    """
    from app.workflows.drafter import CatalogAgent, DraftContext

    ctx = DraftContext(
        agents=(
            CatalogAgent(
                key="competitor_research",
                name="竞品调研",
                description="",
                params=({"name": "topic", "type": "text", "required": True},),
            ),
        ),
        projects=(),
    )
    out = normalize_draft(
        {
            "name": "n",
            "steps": [
                {
                    "label": "调研",
                    "agent_key": "competitor_research",
                    "params": {"topic": "AI 工具", "temperature": 0.7, "memory": True},
                }
            ],
        },
        ctx,
    )
    assert out["steps"][0]["params"] == {"topic": "AI 工具"}


def test_normalize_drops_hallucinated_project_id():
    """project_id 类参数必须命中真实项目：模型编的 uuid 留着必然在运行时炸。

    丢掉而不是报错 —— 项目是用户环境里的事实，模型无从得知，不该由它负责。
    画布上那个字段留空，用户自己选。
    """
    from app.workflows.drafter import CatalogAgent, DraftContext

    ctx = DraftContext(
        agents=(
            CatalogAgent(
                key="inspection_report",
                name="巡检报告",
                description="",
                params=({"name": "project_id", "type": "project_id", "required": True},),
            ),
        ),
        projects=(("p-real", "雅秩官网"),),
    )
    out = normalize_draft(
        {
            "name": "n",
            "steps": [
                {"label": "巡检", "agent_key": "inspection_report", "params": {"project_id": "p-编的"}}
            ],
        },
        ctx,
    )
    assert out["steps"][0]["params"] == {}


def test_normalize_keeps_real_project_id():
    from app.workflows.drafter import CatalogAgent, DraftContext

    ctx = DraftContext(
        agents=(
            CatalogAgent(
                key="inspection_report",
                name="巡检报告",
                description="",
                params=({"name": "project_id", "type": "project_id", "required": True},),
            ),
        ),
        projects=(("p-real", "雅秩官网"),),
    )
    out = normalize_draft(
        {"name": "n", "steps": [{"label": "巡检", "agent_key": "inspection_report", "params": {"project_id": "p-real"}}]},
        ctx,
    )
    assert out["steps"][0]["params"] == {"project_id": "p-real"}


def test_normalize_requires_name_and_steps():
    from app.workflows.drafter import CatalogAgent, DraftContext

    ctx = DraftContext(agents=(), projects=())
    with pytest.raises(DraftError):
        normalize_draft({"steps": []}, ctx)
    with pytest.raises(DraftError):
        normalize_draft({"name": "只有名字"}, ctx)
