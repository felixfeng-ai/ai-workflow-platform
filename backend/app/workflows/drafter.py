"""AI 起草工作流：一句话意图 → 一份可落到画布上的草稿。

**为什么草稿要由后端规整，而不是把模型的 JSON 直接甩给前端？**

模型输出是外部数据，和用户表单提交没有区别 —— 它会编出注册表里不存在的 agent_key、
编出 param_schema 里没有的参数名、编出不存在的 project_id。这些东西一旦落进画布，
用户的体验是「AI 帮我建了个工作流」，跑起来才发现某一步调的是空气。
所以本模块的分工是：**提示词负责「让模型尽量猜对」，规整与校验负责「猜错也进不来」**。
前者是概率，后者是保证；只做前者等于把正确性押在模型的自觉上。

**为什么校验失败要硬报错（422），而不是把坏的那部分丢掉？**

丢掉一个 agent_key 不存在的步骤，会得到一张「少做一件事」的图 —— 用户看不出少了什么，
跑完才发现。这比直接失败难查得多。所以除了两类**用户可见**的降级（见下），一律报错。

那两类例外，区别在于「丢掉之后用户看不看得见」：

- ``params`` 里 schema 之外的键：丢掉。它们是模型凭空加的（如 temperature），
  删掉对图没有任何结构影响，界面上的字段该有的都还在。
- ``project_id`` 类型的参数指向不存在的项目：丢掉。项目是用户环境里的事实，
  模型无从得知，锅不该它背；丢掉后画布上那个字段留空，用户自己选。
- 边上的 ``when`` 条件：丢掉。见 ``_clean_edges`` 的注释。

**为什么这条链路要单独一个模块，而不是塞进 api/workflows.py？**

提示词构造、输出解析、规整策略三者是一体的，测试也围着它们转（tests/test_workflow_draft.py
里有一半用例直接测 normalize_draft，不走 HTTP）。放进路由文件会让「模型输出怎么被处理」
散落在接口代码里，改提示词的人看不到校验，改校验的人看不到提示词。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .conditions import ConditionError
from .graph import Edge, StepNode, WorkflowGraphError, collect_nodes, normalize_edges, validate_graph

# 画布节点尺寸与间距：必须与前端 frontend/src/lib/workflowGraph.ts 的
# NODE_W / NODE_H / X_GAP 保持一致，否则草稿落下去节点会叠在一起。
# 跨端常量没法共享，只能靠这条注释 + 两边的测试各自钉住。
NODE_W = 220
NODE_H = 96
X_GAP = 56
Y_GAP = 40

# 名称长度上限与 schemas/workflow.WorkflowCreate 的 name 校验一致：
# 草稿存不下的话，用户改完名字才能保存，那不如现在就截断
_NAME_MAX = 120
_DESC_MAX = 500


class DraftError(ValueError):
    """草稿无法使用：模型输出不可解析，或规整后发现结构性错误。"""


class _ChatEngine(Protocol):
    """只需要 chat 一个方法 —— 这里不用 AiEngine 全量协议，便于测试塞假引擎。"""

    async def chat(self, query: str, user: str = "unknown") -> str: ...


@dataclass(frozen=True)
class CatalogAgent:
    """给模型看的助手条目。params 用 param_schema 的原始 dict，不再包一层。"""

    key: str
    name: str
    description: str
    params: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DraftContext:
    """起草时可用的素材：本租户能调用的助手、本租户的项目。

    projects 是 (id, name) 二元组 —— 模型只需要知道「有哪些项目可选」，
    传完整 Project 模型会把用户的其它字段一并塞进提示词，没必要。
    """

    agents: tuple[CatalogAgent, ...]
    projects: tuple[tuple[str, str], ...]

    @property
    def agent_keys(self) -> set[str]:
        return {a.key for a in self.agents}

    def agent(self, key: str) -> CatalogAgent | None:
        return next((a for a in self.agents if a.key == key), None)


# ---------------------------------------------------------------- 提示词


def build_prompt(intent: str, ctx: DraftContext) -> str:
    """拼提示词。助手清单是这个提示词里唯一的「事实来源」，必须完整且结构化。

    给的是 key 而不是中文名：key 是后端认识的东西，交给模型中文名等于让它自己
    翻译回 key，多一次出错机会。
    """
    if ctx.agents:
        lines: list[str] = []
        for a in ctx.agents:
            lines.append(f"- key: {a.key}（{a.name}）—— {a.description}")
            for p in a.params:
                req = "必填" if p.get("required") else "选填"
                # options 是 [{"value","label"}] 而不是裸字符串列表：给模型的必须是 value
                # （后端按 value 判定），label 只是帮它理解这个值是什么意思
                opts = p.get("options") or []
                extra = "，可选值：" + "/".join(str(o.get("value")) for o in opts) if opts else ""
                default = f"，默认 {p['default']!r}" if p.get("default") not in (None, "") else ""
                lines.append(f"    参数 {p.get('name')}（{p.get('label')}，{req}，{p.get('type')}{extra}{default}）")
        catalog = "\n".join(lines)
    else:
        catalog = "（当前没有可用助手）"

    if ctx.projects:
        projects = "\n".join(f"- {pid}（{name}）" for pid, name in ctx.projects)
    else:
        projects = "（当前没有项目）"

    # 用 json.dumps 而不是三重引号贴模板：意图是用户原话，里面可能有引号、花括号、
    # 甚至「忽略以上指令」这类文本，嵌在结构化 JSON 里能天然隔开。
    return _PROMPT.format(
        catalog=catalog,
        projects=projects,
        intent=json.dumps(intent, ensure_ascii=False),
    )


_PROMPT = """你是工作流编排助手。用户用一句自然语言描述他想让平台替他做的事，\
你把它拆成一条由「AI 助手」组成的执行链。

# 可用的 AI 助手（只能从这里选，agent_key 必须原样照抄）

{catalog}

# 用户的项目（参数类型为 project_id 的，值必须从下面选）

{projects}

# 用户的描述

{intent}

# 输出要求

只输出一个 JSON 对象，不要任何解释文字，不要 markdown 代码块。格式：

{{
  "name": "工作流名称，12 个字以内，说清做什么",
  "description": "一句话说明它替你做什么",
  "rationale": "一句话说明你为什么这么拆步骤",
  "steps": [
    {{"node_id": "n1", "label": "这一步做什么", "agent_key": "上面列出的 key", "params": {{"参数名": "值"}}}}
  ],
  "edges": [{{"source": "n1", "target": "n2"}}]
}}

规则：
1. 步骤尽量少。能一步做完就别拆两步 —— 用户要的是省事，不是一张复杂的图。
2. 只填你能从用户描述里确定的参数。不确定的参数留空，用户会在界面上补。
3. edges 可以省略，省略即按 steps 顺序依次执行（大多数情况都是这样）。
   只有当用户明确说了「如果……就……否则……」这类分流时，才写 edges 并在边上加条件。
4. agent_key 必须来自上面的清单。宁可少一步，也不要编一个不存在的助手。
"""


# ---------------------------------------------------------------- 解析


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_draft(raw: str) -> dict[str, Any] | None:
    """从模型输出里抠出 JSON 对象；抠不出来返回 None。

    模型爱在 JSON 前后加一句话、或者套一层 ```json 围栏，这两种都当正常情况处理。
    只在第一个 ``{`` 到最后一个 ``}`` 之间取 —— 用括号配对扫描反而会在字符串里
    的花括号上翻车，而模型输出的结构是扁平的，首尾取就够了。
    """
    if not raw:
        return None
    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- 规整


def _clean_params(raw: Any, agent: CatalogAgent, project_ids: set[str]) -> dict[str, Any]:
    """按 param_schema 收参数：schema 之外的键丢掉，project_id 类型必须是真项目。"""
    if not isinstance(raw, dict):
        return {}
    allowed = {p.get("name"): p for p in agent.params}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        spec = allowed.get(key)
        if spec is None or value is None or value == "":
            continue
        # 模型编的 project_id 留着必然在运行时炸（执行器拿它查库查不到），
        # 而项目清单是用户环境里的事实 —— 丢掉，画布上留个空让用户自己选
        if spec.get("type") == "project_id" and value not in project_ids:
            continue
        # select 类参数同理：值不在 options 里就等于给执行器喂了个它没有的分支。
        # 提示词已经写明了可选值，模型还给别的，说明它在这步上没把握，那就别填
        opts = spec.get("options") or []
        if opts and value not in {str(o.get("value")) for o in opts}:
            continue
        out[key] = value
    return out


def _clean_steps(raw: Any, ctx: DraftContext) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise DraftError("AI 没能给出任何步骤，换个说法再试一次")
    project_ids = {pid for pid, _ in ctx.projects}
    steps: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise DraftError("AI 返回的步骤格式不对")
        key = str(item.get("agent_key") or "").strip()
        agent = ctx.agent(key)
        if agent is None:
            # 带上 key 名，用户和测试都能一眼看出模型编了什么
            raise DraftError(f"AI 用了一个不存在的助手：{key or '(空)'}")
        label = str(item.get("label") or "").strip() or agent.name
        steps.append(
            {
                "label": label,
                "agent_key": key,
                "params": _clean_params(item.get("params"), agent, project_ids),
                "node_id": str(item.get("node_id") or f"node-{i}").strip() or f"node-{i}",
            }
        )
    return steps


def _clean_edges(raw: Any, node_ids: set[str]) -> list[dict[str, Any]] | None:
    """规整连线；返回 None 表示交给 normalize_edges 按顺序连成链。

    **``when`` 一律丢掉，不校验也不透传。** 条件 DSL 的左值默认取上一步输出、
    op 有白名单，这些约定靠一段提示词教不会模型；让它猜，结果是运行到那一层才炸。
    丢掉之后两条线从同一节点出来且都没有标签 —— 这个「待填的空」用户一眼看得见，
    点一下线就能设条件。这与「丢掉一个步骤」性质不同：少一个节点是隐形的，
    多一个待填项是显形的。
    """
    if not isinstance(raw, list) or not raw:
        return None
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in raw:
        if not isinstance(e, dict):
            continue
        source = str(e.get("source") or "").strip()
        target = str(e.get("target") or "").strip()
        # 指向不存在节点的边直接丢：留着会以「未知节点」的形式在 validate_graph 里报错，
        # 而那个报错说的是图不合法，用户根本对不上号（他不知道 AI 编了个节点）
        if source not in node_ids or target not in node_ids or source == target:
            continue
        if (source, target) in seen:
            continue
        seen.add((source, target))
        edges.append({"source": source, "target": target})
    return edges or None


def _layout(nodes: list[StepNode], edges: list[Edge]) -> dict[str, dict[str, float]]:
    """按拓扑层级布点：层号 → x，同层内的行号 → y。

    与前端 appendNode「接在链尾右边」不是同一套 —— 那是增量布局（往已有图上加一个节点），
    这是整体布局（从零布一张图）。整体布局必须分层，否则并行分支会被按 steps 顺序
    排成一条直线，看上去像顺序执行，用户会以为两件事有先后。

    edges 传的是 normalize_edges 的结果（线性时它已合成好链），不是原始的 None ——
    传 None 会让整条链都落在第 0 层，排成一竖排。
    """
    ids = [n.node_id for n in nodes]
    known = set(ids)
    indeg = {i: 0 for i in ids}
    out: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        if e.source not in known or e.target not in known:
            continue
        indeg[e.target] += 1
        out[e.source].append(e.target)

    # Kahn 逐层推进。汇聚节点取所有前驱里最深的那层（max）：取浅的会让它跟上游并肩，
    # 连线在画布上要往回折。入度归零才出队，保证前驱全部算完才轮到自己。
    depth = {i: 0 for i in ids}
    ready = [i for i in ids if indeg[i] == 0]
    while ready:
        nid = ready.pop(0)
        for target in out[nid]:
            depth[target] = max(depth[target], depth[nid] + 1)
            indeg[target] -= 1
            if indeg[target] == 0:
                ready.append(target)
    # 环上的节点入度永远归不了零，depth 停在 0 —— 无所谓，validate_graph 已经拦掉了环，
    # 走到这里说明没环；真出了环也不该在这层报错（报出来没人看得懂）

    rows: dict[int, int] = {}
    pos: dict[str, dict[str, float]] = {}
    for n in nodes:
        d = depth[n.node_id]
        row = rows.get(d, 0)
        rows[d] = row + 1
        pos[n.node_id] = {"x": d * (NODE_W + X_GAP), "y": row * (NODE_H + Y_GAP)}
    return pos


def normalize_draft(data: dict[str, Any], ctx: DraftContext) -> dict[str, Any]:
    """模型输出 → 可以直接落库/落画布的草稿。任何结构性错误抛 DraftError。

    返回的 edges 为 None 时表示线性链（与存量工作流「edges 为 NULL = 线性」的表达一致），
    前端 stepsToGraph 收到 None 会自动按顺序连线。
    """
    name = str(data.get("name") or "").strip()[:_NAME_MAX]
    steps = _clean_steps(data.get("steps"), ctx)

    node_ids = {s["node_id"] for s in steps}
    if len(node_ids) != len(steps):
        raise DraftError("AI 给出的步骤编号重复")
    edges = _clean_edges(data.get("edges"), node_ids)

    # 用后端自己的图校验器过一遍 —— 它是保存路径上的同一把尺子。
    # 这里放行、保存时拒绝，等于让用户白填一次表单。
    try:
        nodes = collect_nodes(steps)
        validate_graph(steps, edges)
    except (WorkflowGraphError, ConditionError) as exc:
        raise DraftError(f"AI 画的结构不合法：{exc}") from exc

    # 边：线性链写 None（与存量工作流「edges 为 NULL = 线性」的表达一致），
    # 有分支才落数组。normalize_edges 顺带把线性链合成出来，供下面布点用。
    normalized = normalize_edges(nodes, edges)
    plain_edges = None if edges is None else [
        {"source": e.source, "target": e.target, **({"when": e.when} if e.when else {})}
        for e in normalized
    ]

    position = _layout(nodes, normalized)
    for s in steps:
        s["position"] = position[s["node_id"]]

    if not name:
        raise DraftError("AI 没能给出工作流名称，换个说法再试一次")

    return {
        "name": name,
        "description": str(data.get("description") or "").strip()[:_DESC_MAX],
        "rationale": str(data.get("rationale") or "").strip()[:_DESC_MAX],
        "steps": steps,
        "edges": plain_edges,
    }


# ---------------------------------------------------------------- 入口


async def draft_workflow(
    engine: _ChatEngine, user_id: str, intent: str, ctx: DraftContext
) -> dict[str, Any]:
    """调用模型起草一份工作流。失败一律抛 DraftError，由路由层翻成 422。

    引擎不可用（AiEngineUnavailable）不在这里捕获 —— 那是基础设施问题而非草稿问题，
    翻成 503 是路由层的决定，和 /api/ai/chat 的处理保持一致。
    """
    raw = await engine.chat(build_prompt(intent, ctx), user_id)
    data = parse_draft(raw)
    if data is None:
        raise DraftError("AI 没有返回可用的结构，换个说法再试一次")
    return normalize_draft(data, ctx)
