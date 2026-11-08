from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CodeAnalysisConfigCreate(BaseModel):
    repo_url: str = Field(min_length=1, max_length=300)
    access_token: str = Field(default="", max_length=500)
    branch_patterns: list[str] = Field(default_factory=lambda: ["feature/*", "fix/*"])
    enabled: bool = True
    rotate_secret: bool = False


class CodeAnalysisConfigRead(BaseModel):
    id: str
    project_id: str
    provider: str
    repo_full_name: str
    default_branch: str
    branch_patterns: list[str]
    enabled: bool
    webhook_path: str
    last_verified_at: datetime | None
    webhook_connected_at: datetime | None
    webhook_last_event: str | None
    last_error: str | None

    model_config = ConfigDict(from_attributes=True)


class CodeAnalysisConfigCreated(CodeAnalysisConfigRead):
    """Webhook Secret 只在创建/轮换响应中出现一次。"""

    webhook_secret: str | None = None


class CodeAnalysisRunRead(BaseModel):
    id: str
    project_id: str
    connection_id: str
    trigger_type: str
    repo_full_name: str
    branch: str
    before_sha: str
    after_sha: str
    pusher_login: str | None
    head_commit_message: str | None
    status: str
    change_stats: dict | None
    report: dict | None
    report_markdown: str | None
    analysis_version: str
    max_severity: str
    finding_count: int
    ai_provider: str | None
    ai_model: str | None
    truncated: bool
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CodeAnalysisRunSummary(BaseModel):
    id: str
    project_id: str
    repo_full_name: str
    branch: str
    before_sha: str
    after_sha: str
    pusher_login: str | None
    head_commit_message: str | None
    status: str
    change_stats: dict | None
    max_severity: str
    finding_count: int
    truncated: bool
    error: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CodeAnalysisRunPage(BaseModel):
    items: list[CodeAnalysisRunSummary]
    total: int
    page: int
    page_size: int


class CodeAnalysisManualRun(BaseModel):
    branch: str | None = None
    after_sha: str | None = Field(default=None, min_length=7, max_length=40)
