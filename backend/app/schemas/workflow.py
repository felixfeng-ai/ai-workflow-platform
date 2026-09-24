from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStep(BaseModel):
    """工作流步骤：一个 Agent 调用及其参数模板。

    node_id/position 为前端画布编排预留：可选字段，缺省兼容存量无坐标数据。
    执行器只读 label/agent_key/params，多余字段透传落库、运行时不参与。
    """

    label: str
    agent_key: str
    params: dict = Field(default_factory=dict)
    node_id: str | None = None
    position: dict[str, float] | None = None  # {"x": float, "y": float} 画布坐标


class WorkflowEdge(BaseModel):
    """画布连线：source/target 为 steps 的 node_id。

    when 为空 = 无条件边（恒走）；有 when 则仅在条件成立时走。
    多条出边同时成立 = 并行扇出。条件结构由 app/workflows/conditions.py 校验，
    这里只声明成 dict —— 用嵌套模型反而会把「哪个 op 需要哪些字段」的规则
    写两遍（schema 一遍、DSL 一遍），两处迟早不一致。
    """

    source: str
    target: str
    when: dict | None = None


class Schedule(BaseModel):
    """定时调度：cron（如 "0 9 * * 1"）或 interval_minutes 二选一。"""

    cron: str | None = None
    interval_minutes: int | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    steps: list[WorkflowStep] = Field(default_factory=list)
    # 不传 = 线性工作流（按 steps 顺序串联），与升级前的存量形态一致
    edges: list[WorkflowEdge] | None = None
    schedule: Schedule | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[WorkflowStep] | None = None
    # 显式传 null = 退回线性（清空分支），与「不传 = 不改动」区分开
    edges: list[WorkflowEdge] | None = None
    schedule: Schedule | None = None
    enabled: bool | None = None


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    description: str | None
    steps: list[dict]
    edges: list[dict] | None
    schedule: dict | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class WorkflowRunCreated(BaseModel):
    run_id: str
    status: str


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    status: str
    results: list[dict] | None
    error: str | None
    triggered_by: str
    started_at: datetime | None
    finished_at: datetime | None
    # 非空 = 这条记录失败过、并从断点续跑过（续跑复用同一个 run，不新建记录）
    resumed_at: datetime | None
    created_at: datetime


class WorkflowDraftRequest(BaseModel):
    """一句话起草请求。intent 是用户原话，长度上限防的是「整篇文档粘进来」把提示词撑爆。"""

    intent: str = Field(min_length=1, max_length=500)


class WorkflowDraft(BaseModel):
    """AI 起草结果：形状与 WorkflowCreate 对齐，前端可直接喂给画布。

    edges 为 None = 线性链（与存量工作流的表达一致）。
    rationale 不给用户看保存路径 —— 它是「AI 为什么这么拆」的一句话，
    展示在草稿成功后的提示条上，让用户能判断要不要采纳。
    """

    name: str
    description: str = ""
    rationale: str = ""
    steps: list[dict]
    edges: list[dict] | None = None
