from __future__ import annotations

import asyncio
import secrets
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.crypto import encrypt_secret
from ..db import get_db
from ..models import CodeAnalysisRun, Project, ProjectRepoConnection, User
from ..schemas.code_analysis import (
    CodeAnalysisConfigCreate,
    CodeAnalysisConfigCreated,
    CodeAnalysisConfigRead,
    CodeAnalysisManualRun,
    CodeAnalysisRunPage,
    CodeAnalysisRunRead,
    CodeAnalysisRunSummary,
)
from ..services.code_analysis.github import (
    GitHubClient,
    GitHubError,
    normalize_github_source_path,
    parse_github_source_path,
)
from ..services.code_analysis.docx_export import build_code_analysis_docx
from ..services.code_analysis.runner import code_analysis_run_manager
from ..services.deploy import parse_github_repo
from .deps import get_current_user, owner_only

router = APIRouter(
    prefix="/api/projects/{project_id}/code-analysis",
    tags=["code-analysis"],
)


async def _get_project(db: AsyncSession, user: User, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _webhook_path(connection_id: str) -> str:
    return f"/api/integrations/github/{connection_id}/webhook"


def _config_read(connection: ProjectRepoConnection) -> CodeAnalysisConfigRead:
    return CodeAnalysisConfigRead(
        id=connection.id,
        project_id=connection.project_id,
        provider=connection.provider,
        repo_full_name=connection.repo_full_name,
        source_path=connection.source_path,
        default_branch=connection.default_branch,
        branch_patterns=connection.branch_patterns or [],
        enabled=connection.enabled,
        webhook_path=_webhook_path(connection.id),
        last_verified_at=connection.last_verified_at,
        webhook_connected_at=connection.webhook_connected_at,
        webhook_last_event=connection.webhook_last_event,
        last_error=connection.last_error,
    )


@router.post(
    "/config",
    response_model=CodeAnalysisConfigCreated,
    status_code=status.HTTP_201_CREATED,
)
async def configure_code_analysis(
    project_id: str,
    payload: CodeAnalysisConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(owner_only),
) -> CodeAnalysisConfigCreated:
    project = await _get_project(db, user, project_id)
    parsed_repo = parse_github_repo(payload.repo_url)
    if parsed_repo is None:
        raise HTTPException(
            status_code=400,
            detail="请输入 GitHub 仓库地址，可直接粘贴目录、文件或提交页面链接",
        )
    repo_full_name = f"{parsed_repo[0]}/{parsed_repo[1]}"

    patterns = [item.strip() for item in payload.branch_patterns if item.strip()]
    if not patterns:
        raise HTTPException(status_code=400, detail="至少配置一条分支规则")

    client = GitHubClient(payload.access_token)
    try:
        repository = await client.get_repository(repo_full_name)
    except GitHubError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repository_id = repository.get("id")
    verified_full_name = repository.get("full_name") or repo_full_name
    default_branch = repository.get("default_branch") or "main"
    if not isinstance(repository_id, int):
        raise HTTPException(status_code=400, detail="GitHub 仓库元数据缺少 repository id")
    try:
        source_path = (
            normalize_github_source_path(payload.source_path)
            if payload.source_path and payload.source_path.strip()
            else parse_github_source_path(payload.repo_url, default_branch)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = (
        await db.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.project_id == project.id,
                ProjectRepoConnection.provider == "github",
            )
        )
    ).scalar_one_or_none()

    duplicate = (
        await db.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.tenant_id == user.tenant_id,
                ProjectRepoConnection.provider == "github",
                ProjectRepoConnection.repository_id == repository_id,
                ProjectRepoConnection.project_id != project.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="该仓库已绑定到当前团队的其他项目")

    webhook_secret = None
    if existing is None or payload.rotate_secret:
        webhook_secret = f"whsec_{secrets.token_urlsafe(32)}"
        assert webhook_secret is not None
    connection = existing or ProjectRepoConnection(
        tenant_id=user.tenant_id,
        project_id=project.id,
        provider="github",
        auth_type="pat",
        repository_id=repository_id,
        repo_full_name=verified_full_name,
        default_branch=default_branch,
        branch_patterns=patterns,
        webhook_secret_encrypted="",
        created_by=user.id,
    )
    connection.repository_id = repository_id
    connection.repo_full_name = verified_full_name
    connection.source_path = source_path
    connection.default_branch = default_branch
    connection.branch_patterns = patterns
    if webhook_secret:
        connection.webhook_secret_encrypted = encrypt_secret(webhook_secret)
    connection.access_token_encrypted = encrypt_secret(payload.access_token)
    connection.enabled = payload.enabled
    connection.last_verified_at = datetime.now(timezone.utc)
    connection.last_error = None
    if existing is None:
        db.add(connection)
    await db.commit()
    await db.refresh(connection)

    return CodeAnalysisConfigCreated(
        **_config_read(connection).model_dump(),
        webhook_secret=webhook_secret,
    )


@router.post(
    "/config/rotate-secret",
    response_model=CodeAnalysisConfigCreated,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_code_analysis_secret(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(owner_only),
) -> CodeAnalysisConfigCreated:
    project = await _get_project(db, user, project_id)
    connection = (
        await db.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.project_id == project.id,
                ProjectRepoConnection.provider == "github",
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="尚未配置仓库连接")
    webhook_secret = f"whsec_{secrets.token_urlsafe(32)}"
    connection.webhook_secret_encrypted = encrypt_secret(webhook_secret)
    connection.webhook_connected_at = None
    connection.webhook_last_event = None
    await db.commit()
    await db.refresh(connection)
    return CodeAnalysisConfigCreated(
        **_config_read(connection).model_dump(),
        webhook_secret=webhook_secret,
    )


@router.get("/config", response_model=CodeAnalysisConfigRead | None)
async def get_code_analysis_config(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CodeAnalysisConfigRead | None:
    project = await _get_project(db, user, project_id)
    connection = (
        await db.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.project_id == project.id,
                ProjectRepoConnection.provider == "github",
            )
        )
    ).scalar_one_or_none()
    return _config_read(connection) if connection else None


@router.delete("/config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_code_analysis_config(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(owner_only),
) -> None:
    project = await _get_project(db, user, project_id)
    connection = (
        await db.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.project_id == project.id,
                ProjectRepoConnection.provider == "github",
            )
        )
    ).scalar_one_or_none()
    if connection is not None:
        await db.delete(connection)
        await db.commit()


@router.post("/verify", response_model=CodeAnalysisConfigRead)
async def verify_code_analysis_config(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(owner_only),
) -> CodeAnalysisConfigRead:
    project = await _get_project(db, user, project_id)
    connection = (
        await db.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.project_id == project.id,
                ProjectRepoConnection.provider == "github",
            )
        )
    ).scalar_one_or_none()
    if connection is None or not connection.access_token_encrypted:
        raise HTTPException(status_code=404, detail="尚未配置仓库连接")
    from ..core.crypto import decrypt_secret

    try:
        repository = await GitHubClient(decrypt_secret(connection.access_token_encrypted)).get_repository(
            connection.repo_full_name
        )
    except (GitHubError, ValueError) as exc:
        connection.last_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    connection.last_verified_at = datetime.now(timezone.utc)
    connection.last_error = None
    connection.default_branch = repository.get("default_branch") or connection.default_branch
    await db.commit()
    await db.refresh(connection)
    return _config_read(connection)


@router.post("/runs", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
async def create_manual_code_analysis_run(
    project_id: str,
    payload: CodeAnalysisManualRun,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = await _get_project(db, user, project_id)
    connection = (
        await db.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.project_id == project.id,
                ProjectRepoConnection.provider == "github",
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="尚未配置仓库连接")
    if not payload.after_sha:
        raise HTTPException(status_code=400, detail="V1 手动分析需要提供 after_sha")
    run = CodeAnalysisRun(
        tenant_id=user.tenant_id,
        project_id=project.id,
        connection_id=connection.id,
        trigger_type="manual",
        repo_full_name=connection.repo_full_name,
        branch=payload.branch or connection.default_branch,
        before_sha="0" * 40,
        after_sha=payload.after_sha,
        status="pending",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    code_analysis_run_manager.submit(run.id)
    return {"run_id": run.id, "status": run.status}


@router.get("/runs", response_model=CodeAnalysisRunPage)
async def list_code_analysis_runs(
    project_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    branch: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    severity: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CodeAnalysisRunPage:
    project = await _get_project(db, user, project_id)
    conditions = [
        CodeAnalysisRun.project_id == project.id,
        CodeAnalysisRun.tenant_id == user.tenant_id,
    ]
    if keyword and (term := keyword.strip()):
        pattern = f"%{term}%"
        conditions.append(
            or_(
                CodeAnalysisRun.branch.ilike(pattern),
                CodeAnalysisRun.before_sha.ilike(pattern),
                CodeAnalysisRun.after_sha.ilike(pattern),
                CodeAnalysisRun.head_commit_message.ilike(pattern),
                CodeAnalysisRun.search_text.ilike(pattern),
            )
        )
    if status_filter:
        conditions.append(CodeAnalysisRun.status == status_filter)
    if branch:
        conditions.append(CodeAnalysisRun.branch == branch.strip())
    if date_from:
        local_tz = ZoneInfo(settings.scheduler_timezone)
        conditions.append(
            CodeAnalysisRun.created_at
            >= datetime.combine(date_from, time.min, tzinfo=local_tz).astimezone(
                timezone.utc
            )
        )
    if date_to:
        local_tz = ZoneInfo(settings.scheduler_timezone)
        conditions.append(
            CodeAnalysisRun.created_at
            < datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=local_tz
            ).astimezone(timezone.utc)
        )
    if severity:
        rank = case(
            (CodeAnalysisRun.max_severity == "critical", 5),
            (CodeAnalysisRun.max_severity == "high", 4),
            (CodeAnalysisRun.max_severity == "medium", 3),
            (CodeAnalysisRun.max_severity == "low", 2),
            (CodeAnalysisRun.max_severity == "info", 1),
            else_=0,
        )
        threshold = {
            "critical": 5,
            "high": 4,
            "medium": 3,
            "low": 2,
            "info": 1,
        }.get(str(severity).lower())
        if threshold is None:
            raise HTTPException(status_code=400, detail="无效的风险等级")
        conditions.append(rank >= threshold)

    total = (
        await db.execute(
            select(func.count()).select_from(CodeAnalysisRun).where(*conditions)
        )
    ).scalar_one()
    result = await db.execute(
        select(CodeAnalysisRun)
        .where(*conditions)
        .order_by(CodeAnalysisRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return CodeAnalysisRunPage(
        items=[CodeAnalysisRunSummary.model_validate(item) for item in result.scalars().all()],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get("/runs/{run_id}", response_model=CodeAnalysisRunRead)
async def get_code_analysis_run(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CodeAnalysisRun:
    project = await _get_project(db, user, project_id)
    run = await db.get(CodeAnalysisRun, run_id)
    if (
        run is None
        or run.project_id != project.id
        or run.tenant_id != user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="code analysis run not found")
    return run


@router.get("/runs/{run_id}/download.docx")
async def download_code_analysis_run(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    project = await _get_project(db, user, project_id)
    run = await db.get(CodeAnalysisRun, run_id)
    if (
        run is None
        or run.project_id != project.id
        or run.tenant_id != user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="code analysis run not found")
    if not run.report:
        raise HTTPException(status_code=409, detail="报告尚未生成，暂不能下载")

    content = await asyncio.to_thread(
        build_code_analysis_docx,
        run.report,
        project_name=project.name,
        status=run.status,
        created_at=run.created_at,
    )
    sha = run.after_sha[:8]
    filename = f"{project.name}-代码分析-{sha}.docx"
    disposition = (
        f"attachment; filename=\"code-analysis-{sha}.docx\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
        },
    )
