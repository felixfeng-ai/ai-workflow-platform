"""远程触发 GitHub Actions 部署。

平台不构建任何东西 —— 构建在 GitHub 侧跑，这里只负责「按下按钮」：
调 workflow_dispatch API 触发仓库里既有的 workflow，再把 run 状态回查回来展示。

两个必须知道的 GitHub API 特性（决定了本模块的结构）：

1. **workflow_dispatch 返回 204，不回传 run id。** 也就是说触发成功之后我们
   并不知道刚创建的是哪一次 run。只能拿着 workflow 去查「最近一次 run」再认领，
   见 `sync_deploy_run`。这也是 DeployRun 表存在的原因。

2. **不是所有 workflow 都能被远程触发。** 仓库的 workflow 文件里必须有
   `on: workflow_dispatch:`，否则 API 返回 422。这是最常见的失败原因，所以
   422 单独映射成一句能直接照做的提示。

安全约束：本模块的调用方（API 端点）必须用 owner_only 依赖。token 能触发
本组织仓库的部署，绝不能让 member（含访客租户）碰到。
"""

from __future__ import annotations

import re
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.deploy_run import DeployRun
from ..models.project import Project
from ..models.user import User

# 单次 GitHub API 调用的超时（秒）。触发和回查都是轻量请求，不该慢
GITHUB_TIMEOUT = 15.0
# 部署哪个分支。workflow_dispatch 必传 ref；部署 main 是唯一合理的默认值。
# 若日后要支持选分支，这里改成 Project 上的字段即可
DEFAULT_DEPLOY_REF = "main"
# 已经是终态的 run 不再回查（省 GitHub 配额，也避免把历史结论覆盖掉）。
# unknown 也算终态：它表示「回查窗口内没能在 GitHub 上找到这次 run」，
# 若不算终态，前端每次轮询都会重新打 GitHub，永远查不到也永远不罢休。
TERMINAL_STATUSES = frozenset({"success", "failure", "cancelled", "unknown"})
# 触发后「认领」这次 run 的时限。workflow_dispatch 只回 204 不给 run id，
# 我们靠回查该 workflow 的最近一次 run 来认领。超过这个时间还认领不到，
# 基本可判定这次触发没有真的产生 run（workflow 没声明 workflow_dispatch
# 却没被 GitHub 拦成 422、或触发被静默丢弃），此时继续回查纯属白烧配额。
# 只对「还没认领到」的 run 生效；已认领的 in_progress run 会自然跑完，不设上限
SYNC_STALE_AFTER = timedelta(minutes=30)
# 回查「最近一次 run」时允许的时间倒推量：本机与 GitHub 的时钟有偏差，
# 且 run 创建时刻可能略早于我们收到 204 的时刻。部署是低频手动操作，
# 放宽窗口比精确匹配更实用（宁可认领到刚好并发的那一次，也不要永远认领不到）
SYNC_SKEW = timedelta(minutes=2)

# 与 DeployRun.repo_full_name 的列宽一致。repo_url 上限 300 字符，解析出的
# owner/repo 理论上可能超出列宽；与其让 PostgreSQL 在 insert 时抛 DataError
# 变成 500，不如在可部署性判断里先拦下来
MAX_REPO_FULL_NAME = 200

# 只认 https://github.com/<owner>/<repo> 形式（可带 .git 后缀与结尾斜杠）。
# 刻意不解析其它 Git 托管：触发逻辑用的是 GitHub 专有 API。
#
# 字符集刻意收紧到 GitHub 实际允许的范围，而不是宽松的 [^/\s]：owner 和 repo
# 都会被拼进带部署 PAT 的上游 URL，放开就有 ? # % 这类字符混进来改写路径/查询。
# owner 必须以字母数字开头，这一条同时排除了 "." 和 ".."。
_GITHUB_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)

# workflow 文件名只允许单段（见 schemas/project.py 的同名约束，两处必须一致）。
# 服务层再校验一次是刻意的：schema 只挡 API 入口，数据库里可能已存在脏数据，
# 而这里是真正拼 URL 的地方
_WORKFLOW_RE = re.compile(r"^[A-Za-z0-9._-]+\.ya?ml$")


def parse_github_repo(repo_url: str | None) -> tuple[str, str] | None:
    """从 repo_url 解析出 (owner, repo)；不是 GitHub 地址则返回 None。"""
    if not repo_url:
        return None
    match = _GITHUB_REPO_RE.match(repo_url.strip())
    if match is None:
        return None
    owner, repo = match.group(1), match.group(2)
    # 点段会被 httpx 在发送前归一化掉（/repos/o/../x 变成 /repos/x），
    # 从而改写上游路径。owner 侧已由正则排除，repo 侧这里显式挡一次
    if owner in {".", ".."} or repo in {".", ".."}:
        return None
    return owner, repo


def parse_workflow_name(workflow: str | None) -> str | None:
    """校验部署 workflow 文件名；不合法（含路径段、非 .yml/.yaml）返回 None。"""
    if not workflow:
        return None
    name = workflow.strip()
    return name if _WORKFLOW_RE.match(name) else None


def deploy_blocked_reason(project: Project, user: User) -> str | None:
    """返回不能部署的原因；可部署时返回 None。

    抽成独立函数是给两处共用：ProjectRead.can_deploy 算布尔值，触发端点
    要拿具体原因回 400/403/503 —— 两边共用一份判断，避免日后改一边漏一边。
    """
    if not settings.github_deploy_token:
        return "服务端未配置部署 token，部署功能未启用"
    if user.role != "owner":
        return "仅租户 owner 可触发部署"
    if not project.deploy_workflow:
        return "该项目未配置部署 workflow"
    if parse_workflow_name(project.deploy_workflow) is None:
        return "部署 workflow 文件名不合法（只允许单段文件名，如 deploy.yml）"
    repo = parse_github_repo(project.repo_url)
    if repo is None:
        return "项目仓库地址不是可识别的 GitHub 地址"
    if len(f"{repo[0]}/{repo[1]}") > MAX_REPO_FULL_NAME:
        return "项目仓库地址过长"
    return None


def can_deploy(project: Project, user: User) -> bool:
    return deploy_blocked_reason(project, user) is None


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_deploy_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _map_status(status: str | None, conclusion: str | None) -> str:
    """把 GitHub 的 (status, conclusion) 归一成本项目的 status。

    GitHub 用两个字段表达状态：status 是阶段（queued/in_progress/completed），
    conclusion 只在 completed 后才有值（success/failure/cancelled/…）。
    """
    if status != "completed":
        # requested/waiting/pending 都归到 queued：对用户而言都是「还没开始跑」
        return "in_progress" if status == "in_progress" else "queued"
    if conclusion == "success":
        return "success"
    if conclusion == "cancelled":
        return "cancelled"
    # timed_out / action_required / startup_failure / stale / neutral 等
    # 一律归为 failure：对用户来说都是「这次部署没成功」
    return "failure"


def _extract_error(resp: httpx.Response) -> str:
    """从 GitHub 错误响应里提取一句人话。不回显请求头，避免 token 泄漏进日志/DB。"""
    if resp.status_code == 401:
        return "GitHub token 无效或已过期"
    if resp.status_code == 403:
        return "GitHub token 权限不足（需 Actions: write）或触发了速率限制"
    if resp.status_code == 404:
        return "仓库或 workflow 不存在，或 token 未授权该仓库"
    if resp.status_code == 422:
        return "该 workflow 不支持远程触发（需在 workflow 文件中声明 on: workflow_dispatch）"
    return f"GitHub API 返回 {resp.status_code}"


async def trigger_deploy(db: AsyncSession, project: Project, user: User) -> DeployRun:
    """触发一次部署并落库。调用方须已通过 owner_only 与 deploy_blocked_reason 校验。

    触发成功后 run 状态是 queued 且 github_run_id 仍为空 —— run id 要等
    前端轮询 GET 时由 sync_deploy_run 补上。
    """
    parsed = parse_github_repo(project.repo_url)
    if parsed is None:  # pragma: no cover - 调用方已校验，此处仅防御
        raise ValueError("project repo_url is not a parsable GitHub repo")
    owner, repo = parsed
    repo_full_name = f"{owner}/{repo}"
    # 同样再校验一次：这是真正把值拼进带 PAT 的 URL 的地方，不能只信入口校验
    workflow = parse_workflow_name(project.deploy_workflow)
    if workflow is None:  # pragma: no cover - 调用方已校验，此处仅防御
        raise ValueError("invalid deploy workflow name")

    run = DeployRun(
        tenant_id=project.tenant_id,
        project_id=project.id,
        user_id=user.id,
        status="queued",
        workflow=workflow,
        repo_full_name=repo_full_name,
    )

    url = (
        f"{settings.github_api_base}/repos/{repo_full_name}"
        f"/actions/workflows/{workflow}/dispatches"
    )
    try:
        async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT) as client:
            resp = await client.post(
                url, headers=_headers(), json={"ref": DEFAULT_DEPLOY_REF}
            )
    except (httpx.HTTPError, ValueError) as exc:
        # 网络层失败：记一条 failed 记录而不是抛 500 —— 用户需要看到「这次没发出去」，
        # 而不是一个消失在日志里的异常。
        # 连带捕获 ValueError 是因为 httpx.InvalidURL 继承自它（不是 HTTPError）：
        # github_api_base 配错或 URL 畸形时会走到这里，同样不该变成 500
        run.status = "failure"
        run.error = f"调用 GitHub 失败：{exc.__class__.__name__}"
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run

    if resp.status_code not in (201, 204):
        run.status = "failure"
        run.error = _extract_error(resp)
    else:
        # 202/204 都表示已受理。run_url 暂时给仓库的 Actions 页面，
        # 等 sync 拿到 run id 后替换成精确链接
        run.run_url = f"https://github.com/{repo_full_name}/actions"

    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def sync_deploy_run(db: AsyncSession, run: DeployRun) -> DeployRun:
    """把一次部署的最新状态从 GitHub 同步回来。

    两种情况：
    - run 已在终态 → 直接返回，不打 GitHub（列表轮询不该反复穿透上游）
    - github_run_id 还是空 → 先「认领」最近一次 run（见模块开头第 1 点），再查它的状态

    认领失败（run 还没出现在列表里）不算错误：保持 queued，等下次轮询再试。
    """
    if run.status in TERMINAL_STATUSES:
        return run

    # 认领超时：见 SYNC_STALE_AFTER 的说明。这里落 unknown 而不是 failure ——
    # 我们确实不知道它是成功还是失败，「没能确认」才是事实
    if run.github_run_id is None and _is_past_deadline(run.created_at, SYNC_STALE_AFTER):
        run.status = "unknown"
        run.error = "未能在 GitHub 上找到这次部署对应的运行记录，无法确认结果"
        await db.commit()
        await db.refresh(run)
        return run

    base = f"{settings.github_api_base}/repos/{run.repo_full_name}/actions"

    try:
        async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT) as client:
            if run.github_run_id is None:
                listed = await client.get(
                    f"{base}/workflows/{run.workflow}/runs",
                    headers=_headers(),
                    params={"per_page": 1},
                )
                if listed.status_code != 200:
                    run.error = _extract_error(listed)
                    await db.commit()
                    await db.refresh(run)
                    return run
                runs = listed.json().get("workflow_runs") or []
                if not runs:
                    # 刚触发、GitHub 侧还没建好 run。保持 queued 等下次
                    return run
                candidate = runs[0]
                created_at = candidate.get("created_at")
                if created_at and not _is_recent(created_at, run.created_at):
                    # 最近一次 run 早于本次触发太多 —— 说明我们这条还没出现，
                    # 不能认领（否则会把上一次的结论安到这一次头上）
                    return run
                run.github_run_id = str(candidate["id"])
                _apply(run, candidate)
            else:
                detail = await client.get(
                    f"{base}/runs/{run.github_run_id}", headers=_headers()
                )
                if detail.status_code != 200:
                    run.error = _extract_error(detail)
                    await db.commit()
                    await db.refresh(run)
                    return run
                _apply(run, detail.json())
    except (httpx.HTTPError, ValueError) as exc:
        # ValueError 同时覆盖 httpx.InvalidURL 与响应体不是 JSON 时的
        # json.JSONDecodeError（上游返回 HTML 错误页就会触发）
        run.error = f"同步 GitHub 状态失败：{exc.__class__.__name__}"
        await db.commit()
        await db.refresh(run)
        return run

    await db.commit()
    await db.refresh(run)
    return run


def _is_past_deadline(created_at, span: timedelta) -> bool:
    """created_at 是否已经早于「现在 - span」。

    两个时间都要带时区才能比较：SQLite 取回的是 naive datetime，
    而 SQLAlchemy 的 DateTime(timezone=True) 在 PostgreSQL 下是 aware，
    这里统一补成 UTC 再比，避免 TypeError。
    """
    from datetime import datetime, timezone

    reference = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - reference > span


def _is_recent(created_at_iso: str, reference) -> bool:
    """GitHub 返回的 created_at 是否落在本次触发附近（允许时钟偏差）。"""
    from datetime import datetime, timezone

    try:
        created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return created >= reference - SYNC_SKEW


def _apply(run: DeployRun, payload: dict) -> None:
    """把 GitHub 的一次 run 结果写进本地记录。"""
    run.status = _map_status(payload.get("status"), payload.get("conclusion"))
    if payload.get("html_url"):
        run.run_url = payload["html_url"]
    if run.status == "failure" and not run.error:
        run.error = f"部署未成功（{payload.get('conclusion') or 'unknown'}）"
