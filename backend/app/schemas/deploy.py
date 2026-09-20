from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeployRunRead(BaseModel):
    """一次部署记录。刻意不含任何 token / 凭据字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    workflow: str
    repo_full_name: str
    github_run_id: str | None
    run_url: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
