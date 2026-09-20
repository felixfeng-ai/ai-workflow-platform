from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.ratelimit import rate_limit
from ..db import get_db
from ..models.deploy_run import DeployRun
from ..models.doc import Doc
from ..models.project import Project
from ..models.user import User
from ..schemas.deploy import DeployRunRead
from ..schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from ..services import deploy as deploy_service
from .deps import get_current_user, owner_only, require_role

router = APIRouter(prefix="/api/projects", tags=["projects"])

# 部署触发限流：按 IP 计数，防误触与脚本刷。部署是低频重操作（每次要跑几分钟）
_deploy_limit = rate_limit(settings.ratelimit_run_per_min, 60, scope="deploy")
# 部署状态回查限流：单独一个 scope，比触发宽松 —— 前端在部署进行中会按秒级轮询，
# 用触发的额度会把自己的轮询卡死。这道限流防的是「拿一个永远不结束的 run 疯狂轮询，
# 借服务端的 token 去烧 GitHub 配额」（每次回查都会真的打一次 GitHub）。
_deploy_sync_limit = rate_limit(settings.ratelimit_run_per_min * 6, 60, scope="deploy_sync")

# 只有 owner 能改的字段：这两个值决定服务端拿部署 token 去调哪个仓库、哪个 workflow，
# member 能改就等于能间接指挥一次特权上游调用（confused deputy）。
_OWNER_ONLY_FIELDS = frozenset({"repo_url", "deploy_workflow"})


async def _get_owned_project(db: AsyncSession, user: User, project_id: str) -> Project:
    """取当前租户下的项目；不存在或归属他租户一律 404，不泄露存在性（IDOR 防护）。"""
    project = await db.get(Project, project_id)
    if project is None or project.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _project_read(project: Project, user: User) -> ProjectRead:
    """序列化项目，并注入服务端计算的 can_deploy。

    can_deploy 不是数据库字段，无法由 from_attributes 自动带出，必须在这里塞进去。
    它按「当前用户」而变（member 恒为 False），所以不能缓存成项目自身的属性。
    """
    return ProjectRead.model_validate(project).model_copy(
        update={"can_deploy": deploy_service.can_deploy(project, user)}
    )


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ProjectRead]:
    # 数据隔离 R17：仅返回当前用户租户下的项目，杜绝跨用户串读
    result = await db.execute(
        select(Project).where(Project.tenant_id == user.tenant_id).order_by(Project.created_at.desc())
    )
    return [_project_read(p, user) for p in result.scalars().all()]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("owner", "member"))
) -> ProjectRead:
    # 归属：租户随创建者注入，避免落到默认 "default" 租户导致隔离失效
    project = Project(**payload.model_dump(), tenant_id=user.tenant_id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _project_read(project, user)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> ProjectRead:
    return _project_read(await _get_owned_project(db, user, project_id), user)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("owner", "member")),
) -> ProjectRead:
    project = await _get_owned_project(db, user, project_id)
    changes = payload.model_dump(exclude_unset=True)
    # 见 _OWNER_ONLY_FIELDS 的说明：member 可以改名字/描述，但不能改仓库与部署配置
    if user.role != "owner" and (_OWNER_ONLY_FIELDS & changes.keys()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅租户 owner 可修改仓库地址与部署配置",
        )
    for field, value in changes.items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return _project_read(project, user)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("owner", "member"))
) -> None:
    project = await _get_owned_project(db, user, project_id)
    # SQLite 不强制外键级联，应用层显式清理文档，防孤儿数据（tasks/notes 级联后做）
    await db.execute(delete(Doc).where(Doc.project_id == project_id))
    await db.delete(project)
    await db.commit()


# ── 远程部署（触发 GitHub Actions）─────────────────────────────
# 权限刻意收紧到 owner_only：访客租户的角色是 member，member 绝不能碰到
# 部署端点 —— token 能触发真实生产发布，让访客点得到等于把发布权公开。
# 前端也不会给 member 显示按钮（can_deploy 恒 False），此处是第二道防线。


@router.post(
    "/{project_id}/deploy",
    response_model=DeployRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def deploy_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(owner_only),
    _rl: None = Depends(_deploy_limit),
) -> DeployRun:
    """触发一次部署。202 = 已受理，不代表部署成功，状态需轮询 deployments/{run_id}。"""
    project = await _get_owned_project(db, user, project_id)

    # owner_only 依赖已经挡住了角色问题，所以这里剩余的 reason 只可能是配置问题：
    # token 没配属服务端未启用（503），项目没配 workflow 属请求不合法（400）
    reason = deploy_service.deploy_blocked_reason(project, user)
    if reason:
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if not settings.github_deploy_token
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=reason)

    return await deploy_service.trigger_deploy(db, project, user)


@router.get("/{project_id}/deployments", response_model=list[DeployRunRead])
async def list_deployments(
    project_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DeployRun]:
    """部署历史。读操作不限角色 —— 租户内成员都能看到本项目部署过什么。

    只读本地表，不穿透 GitHub：列表页会频繁刷新，逐条回查会打爆 API 配额。
    需要最新状态时由前端对「进行中的那一条」单独调 deployments/{run_id}。
    """
    await _get_owned_project(db, user, project_id)
    result = await db.execute(
        select(DeployRun)
        .where(DeployRun.project_id == project_id, DeployRun.tenant_id == user.tenant_id)
        .order_by(DeployRun.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{project_id}/deployments/{run_id}", response_model=DeployRunRead)
async def get_deployment(
    project_id: str,
    run_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _rl: None = Depends(_deploy_sync_limit),
) -> DeployRun:
    """单条部署详情。读取时会向 GitHub 同步一次状态，供前端轮询进行中的部署。

    限流比触发宽松但不是没有：这个端点每次都会真的打一次 GitHub，
    不加限制就能被拿来烧 token 的配额。终态 run 会跳过回查（见 services/deploy.py），
    所以正常情况下一个 run 只会被穿几次，不会因为前端轮询而持续消耗。
    """
    await _get_owned_project(db, user, project_id)
    run = await db.get(DeployRun, run_id)
    if run is None or run.project_id != project_id or run.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="deploy run not found")
    return await deploy_service.sync_deploy_run(db, run)
