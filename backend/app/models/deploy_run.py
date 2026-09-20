from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class DeployRun(Base, TimestampMixin):
    """一次远程部署的记录（对应 GitHub Actions 的一次 workflow run）。

    为什么要自己存一张表，而不是每次直接问 GitHub：
    - GitHub 的 workflow_dispatch 只返回 204，**不给 run id**。必须先落一条本地记录，
      再回查「该 workflow 最近一次 run」把 id 补上（见 services/deploy.py）。
    - 列表页要按租户隔离展示「谁在什么时候部署了什么」，这是 GitHub 侧没有的视角。
    - GitHub API 有速率限制，列表接口不应每次穿透到上游。

    status 取值与 GitHub 的 run status/conclusion 对齐：
      queued → in_progress → success | failure | cancelled
      unknown = 回查超时或上游返回了没见过的状态，前端按「未知」处理而不是当失败
    """

    __tablename__ = "deploy_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default="default", index=True)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # 触发者。留痕用：部署是 owner 级操作，出问题要能定位到人
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # 触发的是哪个 workflow 文件（冗余存一份：项目上的配置日后可能被改，
    # 历史记录应反映当时实际触发的那条）
    workflow: Mapped[str] = mapped_column(String(120))
    # owner/repo，同样冗余：项目换仓库后旧记录仍应指向当时那个仓库
    repo_full_name: Mapped[str] = mapped_column(String(200))
    # GitHub 侧 run id；workflow_dispatch 不回传，靠回查补上，补到之前为 None
    github_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    run_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # 失败原因（触发失败 / 上游报错），只给运维看，不回传 token 等敏感信息
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
