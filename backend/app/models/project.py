from uuid import uuid4

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), default="default", index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # L1 真实项目连接（线 B）：仓库/部署/本地路径
    repo_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    deploy_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # 要触发的 GitHub Actions workflow 文件名（如 "deploy.yml"）。
    # 为 None = 该项目不可远程部署，前端只显示「线上」外链而不显示「部署」按钮。
    # 之所以要显式指定而不是默认取某个文件名：仓库里可能有多条 workflow
    # （ci / deploy / release），猜错等于触发错的东西。
    deploy_workflow: Mapped[str | None] = mapped_column(String(120), nullable=True)
