from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# 部署 workflow 文件名：只允许单段文件名，必须以 .yml/.yaml 结尾。
# 这个值会被拼进带部署 PAT 的 GitHub URL，绝不能让 / 和 .. 进来 ——
# 允许路径段就等于允许把「部署本项目」改写成「用平台的 token 去部署任意仓库」。
# 这是入口防线（另一道在 services/deploy.py，schema 不是唯一防线）。
WORKFLOW_NAME_PATTERN = r"^[A-Za-z0-9._-]+\.ya?ml$"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    color: str | None = None
    repo_url: str | None = None
    deploy_url: str | None = None
    local_path: str | None = None
    # 留空 = 该项目不可远程部署（前端只显示「线上」外链）
    deploy_workflow: str | None = Field(default=None, max_length=120, pattern=WORKFLOW_NAME_PATTERN)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    color: str | None = None
    repo_url: str | None = None
    deploy_url: str | None = None
    local_path: str | None = None
    deploy_workflow: str | None = Field(default=None, max_length=120, pattern=WORKFLOW_NAME_PATTERN)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    status: str
    color: str | None
    repo_url: str | None
    deploy_url: str | None
    local_path: str | None
    deploy_workflow: str | None
    # 服务端计算的可部署性（不是数据库字段）：同时取决于「配了 workflow」+
    # 「repo_url 是可解析的 GitHub 地址」+「服务端配了 token」+「当前用户是 owner」。
    # 前端据此决定显示「部署」按钮还是「线上」外链 —— 让前端自己算会漏掉 token
    # 这一项（前端不知道服务端配没配），结果就是 owner 点了一个必 503 的按钮。
    can_deploy: bool = False
    created_at: datetime
    updated_at: datetime
