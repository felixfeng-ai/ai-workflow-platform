"""远程部署测试：权限收紧、GitHub API 交互、run 认领、失败留痕。

不真连 GitHub —— 用假的 httpx.AsyncClient 替换 app.services.deploy 里的 httpx，
记录请求并按预设脚本返回响应。真实 API 的行为（204 不回 run id、422 表示
workflow 不可远程触发）在假客户端里按同样语义模拟。
"""

from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.core.ratelimit import reset_limiter
from app.services import deploy as deploy_service

TOKEN = "ghp_test_token"
REPO = "https://github.com/acme/widget"
WORKFLOW = "deploy.yml"


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeGitHub:
    """假的 httpx.AsyncClient。可配置各接口的返回，并记录收到的请求。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.dispatch_status = 204
        self.runs_status = 200
        self.runs_payload: dict = {"workflow_runs": []}
        self.detail_status = 200
        self.detail_payload: dict = {}
        self.post_error: Exception | None = None

    def client(self, **_kwargs) -> "FakeGitHub":
        # 冒充 httpx.AsyncClient(**kwargs)：服务层写的是
        # `async with httpx.AsyncClient(timeout=…) as client`，故需支持构造 + 上下文管理
        return self

    async def __aenter__(self) -> "FakeGitHub":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def post(self, url: str, headers=None, json=None) -> _Resp:
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers})
        if self.post_error is not None:
            raise self.post_error
        return _Resp(self.dispatch_status)

    async def get(self, url: str, headers=None, params=None) -> _Resp:
        self.calls.append({"method": "GET", "url": url, "params": params})
        # 详情 URL 形如 …/actions/runs/<id>；列表 URL 形如 …/actions/workflows/<file>/runs
        if "/actions/runs/" in url:
            return _Resp(self.detail_status, self.detail_payload)
        return _Resp(self.runs_status, self.runs_payload)

    @property
    def posted(self) -> list[dict]:
        return [c for c in self.calls if c["method"] == "POST"]

    @property
    def gets(self) -> list[dict]:
        return [c for c in self.calls if c["method"] == "GET"]


@pytest.fixture
def gh(monkeypatch) -> FakeGitHub:
    """装上假 GitHub，并默认配好 token。"""
    fake = FakeGitHub()
    monkeypatch.setattr(
        deploy_service,
        "httpx",
        SimpleNamespace(AsyncClient=fake.client, HTTPError=httpx.HTTPError),
    )
    monkeypatch.setattr(settings, "github_deploy_token", TOKEN)
    return fake


async def _project(client, headers, **overrides) -> str:
    payload = {
        "name": "Widget",
        "repo_url": REPO,
        "deploy_workflow": WORKFLOW,
        **overrides,
    }
    r = await client.post("/api/projects", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _member_headers(client, owner_headers, email: str = "mate@example.com") -> dict:
    """造一个同租户的 member（走真实邀请链路，而非直接改库）。"""
    r = await client.post(
        "/api/team/invites", json={"email": email, "role": "member"}, headers=owner_headers
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "name": "队友", "invite_code": r.json()["code"]},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── 权限与配置门禁 ───────────────────────────────────────────


async def test_deploy_requires_auth(client):
    r = await client.post("/api/projects/whatever/deploy")
    assert r.status_code == 401


async def test_deploy_disabled_without_server_token(client, auth_headers, monkeypatch, gh):
    """服务端没配 token → 503（功能未启用），而不是 500 或静默成功。"""
    monkeypatch.setattr(settings, "github_deploy_token", "")
    pid = await _project(client, auth_headers)

    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    assert r.status_code == 503
    assert "token" in r.json()["detail"]
    assert gh.posted == []  # 未配置就不该发出任何请求


async def test_deploy_forbidden_for_member(client, auth_headers, gh):
    """member（含访客租户）不能触发部署 —— token 能发真实生产发布。"""
    pid = await _project(client, auth_headers)
    member = await _member_headers(client, auth_headers)

    r = await client.post(f"/api/projects/{pid}/deploy", headers=member)
    assert r.status_code == 403
    assert gh.posted == []


async def test_deploy_requires_workflow_configured(client, auth_headers, gh):
    pid = await _project(client, auth_headers, deploy_workflow=None)
    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    assert r.status_code == 400
    assert "workflow" in r.json()["detail"]


async def test_deploy_rejects_non_github_repo(client, auth_headers, gh):
    pid = await _project(client, auth_headers, repo_url="https://gitlab.com/acme/widget")
    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    assert r.status_code == 400
    assert "GitHub" in r.json()["detail"]


async def test_deploy_rate_limited(client, auth_headers, monkeypatch, gh):
    """触发限流：超过 ratelimit_run_per_min 后 429（部署是重操作，防脚本刷）。"""
    monkeypatch.setattr(settings, "ratelimit_enabled", True)
    reset_limiter()
    try:
        pid = await _project(client, auth_headers)
        codes = [
            (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).status_code
            for _ in range(settings.ratelimit_run_per_min + 1)
        ]
        assert codes[-1] == 429
        assert all(c == 202 for c in codes[:-1])
    finally:
        reset_limiter()


# ── 触发成功 ────────────────────────────────────────────────


async def test_deploy_triggers_workflow(client, auth_headers, gh):
    """happy path：POST 到正确的 dispatch 端点、带 ref、落一条 queued 记录。"""
    pid = await _project(client, auth_headers)

    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["workflow"] == WORKFLOW
    assert body["repo_full_name"] == "acme/widget"
    # workflow_dispatch 不回传 run id，此刻必须为空，等 sync 阶段认领
    assert body["github_run_id"] is None
    assert body["error"] is None

    assert len(gh.posted) == 1
    assert gh.posted[0]["url"] == (
        f"{settings.github_api_base}/repos/acme/widget/actions/workflows/{WORKFLOW}/dispatches"
    )
    assert gh.posted[0]["json"] == {"ref": "main"}
    assert gh.posted[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"


async def test_deploy_422_reports_workflow_dispatch_hint(client, auth_headers, gh):
    """422 = workflow 没有 on: workflow_dispatch，是最常见的失败，提示要能照做。"""
    gh.dispatch_status = 422
    pid = await _project(client, auth_headers)

    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    # 触发失败仍返回 202（请求已受理，这次部署失败了）—— 失败体现在记录状态上
    assert r.status_code == 202
    assert r.json()["status"] == "failure"
    assert "workflow_dispatch" in r.json()["error"]


async def test_deploy_network_error_recorded_not_500(client, auth_headers, gh):
    """网络层异常要落成一条 failed 记录，而不是抛 500 让它消失在日志里。"""
    gh.post_error = httpx.ConnectError("boom")
    pid = await _project(client, auth_headers)

    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["status"] == "failure"
    assert "ConnectError" in r.json()["error"]


async def test_deploy_401_reported(client, auth_headers, gh):
    """token 失效要给出可照做的提示，而不是笼统的失败。"""
    gh.dispatch_status = 401
    pid = await _project(client, auth_headers)
    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    assert r.json()["status"] == "failure"
    assert "无效或已过期" in r.json()["error"]


# ── 状态回查（run 认领）──────────────────────────────────────


async def test_sync_claims_recent_run_and_maps_conclusion(client, auth_headers, gh):
    """github_run_id 为空时认领最近一次 run，并把 conclusion 映射成成功。"""
    pid = await _project(client, auth_headers)
    run_id = (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).json()["id"]

    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    gh.runs_payload = {
        "workflow_runs": [
            {
                "id": 987654,
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/acme/widget/actions/runs/987654",
                "created_at": now_iso,
            }
        ]
    }

    r = await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["github_run_id"] == "987654"
    assert body["status"] == "success"
    assert body["run_url"].endswith("/runs/987654")


async def test_sync_maps_failure_conclusion(client, auth_headers, gh):
    from datetime import datetime, timezone

    pid = await _project(client, auth_headers)
    run_id = (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).json()["id"]

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    gh.runs_payload = {
        "workflow_runs": [
            {"id": 5, "status": "completed", "conclusion": "timed_out", "created_at": now_iso}
        ]
    }
    body = (
        await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)
    ).json()
    # timed_out 归为 failure：对用户而言就是「这次没成功」
    assert body["status"] == "failure"
    assert body["error"]


async def test_sync_leaves_queued_when_run_not_yet_visible(client, auth_headers, gh):
    """刚触发、GitHub 还没建好 run → 保持 queued，等下次轮询，不能报错。"""
    pid = await _project(client, auth_headers)
    run_id = (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).json()["id"]

    gh.runs_payload = {"workflow_runs": []}
    body = (
        await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)
    ).json()
    assert body["status"] == "queued"
    assert body["github_run_id"] is None
    assert body["error"] is None


async def test_sync_does_not_claim_stale_run(client, auth_headers, gh):
    """最近一次 run 远早于本次触发 → 不能认领，否则会把上一次的结论安到这次头上。"""
    pid = await _project(client, auth_headers)
    run_id = (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).json()["id"]

    gh.runs_payload = {
        "workflow_runs": [
            {
                "id": 111,
                "status": "completed",
                "conclusion": "success",
                "created_at": "2020-01-01T00:00:00Z",
            }
        ]
    }
    body = (
        await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)
    ).json()
    assert body["github_run_id"] is None
    assert body["status"] == "queued"


async def test_sync_skips_github_for_terminal_run(client, auth_headers, gh):
    """已到终态的 run 不再回查 —— 列表轮询不该反复打 GitHub 配额。"""
    pid = await _project(client, auth_headers)
    run_id = (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).json()["id"]

    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    gh.runs_payload = {
        "workflow_runs": [{"id": 42, "status": "completed", "conclusion": "success", "created_at": now_iso}]
    }
    await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)
    gets_after_first = len(gh.gets)

    # 再查两次，都不应产生新的 GitHub 请求
    await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)
    await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)
    assert len(gh.gets) == gets_after_first


# ── can_deploy 与历史 ───────────────────────────────────────


async def test_can_deploy_flag_differs_by_role(client, auth_headers, gh):
    """can_deploy 由服务端算：owner 为 true，member 恒为 false（前端据此隐藏按钮）。"""
    pid = await _project(client, auth_headers)
    member = await _member_headers(client, auth_headers)

    mine = (await client.get(f"/api/projects/{pid}", headers=auth_headers)).json()
    assert mine["can_deploy"] is True

    theirs = (await client.get(f"/api/projects/{pid}", headers=member)).json()
    assert theirs["can_deploy"] is False


async def test_can_deploy_false_without_workflow_or_token(client, auth_headers, monkeypatch, gh):
    no_wf = await _project(client, auth_headers, name="无 workflow", deploy_workflow=None)
    assert (await client.get(f"/api/projects/{no_wf}", headers=auth_headers)).json()["can_deploy"] is False

    monkeypatch.setattr(settings, "github_deploy_token", "")
    with_wf = await _project(client, auth_headers, name="有 workflow")
    assert (await client.get(f"/api/projects/{with_wf}", headers=auth_headers)).json()["can_deploy"] is False


async def test_deployments_list_and_isolation(client, auth_headers, gh):
    """部署历史按租户隔离：他人的项目一律 404，不泄露存在性。"""
    pid = await _project(client, auth_headers)
    await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)

    r = await client.get(f"/api/projects/{pid}/deployments", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # 另一个租户的用户：列表与详情都 404
    r = await client.post(
        "/api/auth/register",
        json={"email": "outsider@example.com", "password": "secret123", "name": "外人"},
    )
    outsider = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"/api/projects/{pid}/deployments", headers=outsider)).status_code == 404

    run_id = (await client.get(f"/api/projects/{pid}/deployments", headers=auth_headers)).json()[0]["id"]
    assert (
        await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=outsider)
    ).status_code == 404


async def test_deployment_detail_404_for_unknown_run(client, auth_headers, gh):
    pid = await _project(client, auth_headers)
    r = await client.get(f"/api/projects/{pid}/deployments/nope", headers=auth_headers)
    assert r.status_code == 404


# ── 注入防护：deploy_workflow 会被拼进带 PAT 的上游 URL ──────


async def test_workflow_creation_rejects_path_segments(client, auth_headers):
    """workflow 名含路径段一律 422。

    这不是格式洁癖：该值被拼进 `.../actions/workflows/{workflow}/dispatches`，
    允许 '/' 和 '..' 就能把「部署本项目」改写成「用平台 token 部署任意仓库」。
    """
    for evil in (
        "../../../../repos/other/repo/actions/workflows/pwn.yml",
        "sub/dir/deploy.yml",
        "deploy.yml/../../x.yml",
        "deploy.yaml?ref=evil",
        "deploy.txt",
        "..",
    ):
        r = await client.post(
            "/api/projects",
            json={"name": "x", "repo_url": REPO, "deploy_workflow": evil},
            headers=auth_headers,
        )
        assert r.status_code == 422, f"{evil!r} 应当被拒绝，实际 {r.status_code}"


async def test_workflow_update_rejects_path_segments(client, auth_headers, gh):
    pid = await _project(client, auth_headers)
    r = await client.patch(
        f"/api/projects/{pid}",
        json={"deploy_workflow": "../../../../repos/T/R/actions/workflows/pwn.yml"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_parse_workflow_name_accepts_only_single_yaml_file():
    assert deploy_service.parse_workflow_name("deploy.yml") == "deploy.yml"
    assert deploy_service.parse_workflow_name(" release.yaml ") == "release.yaml"
    assert deploy_service.parse_workflow_name("ci-1.2_x.yml") == "ci-1.2_x.yml"
    for bad in ("", None, "../x.yml", "a/b.yml", "x.txt", "..", ".yml"):
        assert deploy_service.parse_workflow_name(bad) is None, bad


def test_parse_github_repo_rejects_dot_segments():
    """点段会被 httpx 在发送前归一化，从而改写上游路径 —— 必须挡住。"""
    assert deploy_service.parse_github_repo("https://github.com/acme/widget") == ("acme", "widget")
    assert deploy_service.parse_github_repo("https://github.com/acme/widget.git") == ("acme", "widget")
    for bad in (
        "https://github.com/../../x/y",
        "https://github.com/acme/..",
        "https://github.com/../widget",
        "https://github.com/acme/widget?tab=readme",
        "https://evil.com/acme/widget",
        "https://github.com.evil.com/acme/widget",
        None,
        "",
    ):
        assert deploy_service.parse_github_repo(bad) is None, bad


async def test_legacy_bad_workflow_in_db_is_not_deployable(client, auth_headers, gh, db_session):
    """库里已有脏数据（绕过 schema 写进来的）→ can_deploy 为 false 且端点 400。

    服务层必须独立校验一次：schema 只挡 API 入口，挡不住直接写库的旧数据。
    """
    from app.models.project import Project

    pid = await _project(client, auth_headers)
    project = await db_session.get(Project, pid)
    project.deploy_workflow = "../../../../repos/T/R/actions/workflows/pwn.yml"
    await db_session.commit()

    assert (await client.get(f"/api/projects/{pid}", headers=auth_headers)).json()["can_deploy"] is False
    r = await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)
    assert r.status_code == 400
    assert gh.posted == []  # 绝不带着 token 发出这个请求


# ── PATCH 权限：仓库与部署配置只有 owner 能改 ────────────────


async def test_member_cannot_change_deploy_fields(client, auth_headers, gh):
    """member 能改项目名，但不能改 repo_url / deploy_workflow。

    这两个字段决定服务端拿部署 token 去调哪个仓库，让 member 改等于
    让他能间接指挥一次特权上游调用。
    """
    pid = await _project(client, auth_headers)
    member = await _member_headers(client, auth_headers)

    r = await client.patch(f"/api/projects/{pid}", json={"name": "改名可以"}, headers=member)
    assert r.status_code == 200
    assert r.json()["name"] == "改名可以"

    for patch in ({"deploy_workflow": "other.yml"}, {"repo_url": "https://github.com/evil/x"}):
        r = await client.patch(f"/api/projects/{pid}", json=patch, headers=member)
        assert r.status_code == 403, patch

    # owner 自己可以改
    r = await client.patch(f"/api/projects/{pid}", json={"deploy_workflow": "other.yml"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["deploy_workflow"] == "other.yml"


# ── 回查边界：查不到就不能无限查下去 ────────────────────────


async def test_never_claimed_run_becomes_unknown_after_deadline(client, auth_headers, gh, db_session):
    """触发后长时间认领不到 run → 落 unknown 并停止回查。

    否则一个永远停在 queued 的 run 会被前端一直轮询，每次轮询都真的打一次
    GitHub，等于拿平台的 token 烧配额。unknown 而非 failure：
    我们确实不知道结果。
    """
    from datetime import datetime, timedelta, timezone

    from app.models.deploy_run import DeployRun

    pid = await _project(client, auth_headers)
    created = (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).json()

    # 把创建时间推到认领时限之外
    run = await db_session.get(DeployRun, created["id"])
    run.created_at = datetime.now(timezone.utc) - deploy_service.SYNC_STALE_AFTER - timedelta(minutes=1)
    await db_session.commit()

    gets_before = len(gh.gets)
    r = await client.get(f"/api/projects/{pid}/deployments/{created['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "unknown"
    assert len(gh.gets) == gets_before  # 过期后不再打 GitHub

    # 已终态，后续查询也不回查
    r = await client.get(f"/api/projects/{pid}/deployments/{created['id']}", headers=auth_headers)
    assert r.json()["status"] == "unknown"
    assert len(gh.gets) == gets_before


async def test_sync_endpoint_rate_limited(client, auth_headers, monkeypatch, gh):
    """回查端点单独限流：它每次都会真的打 GitHub，不能无限刷。"""
    monkeypatch.setattr(settings, "ratelimit_enabled", True)
    reset_limiter()
    try:
        pid = await _project(client, auth_headers)
        run_id = (await client.post(f"/api/projects/{pid}/deploy", headers=auth_headers)).json()["id"]
        limit = settings.ratelimit_run_per_min * 6
        codes = [
            (await client.get(f"/api/projects/{pid}/deployments/{run_id}", headers=auth_headers)).status_code
            for _ in range(limit + 1)
        ]
        assert codes[-1] == 429
        assert all(c == 200 for c in codes[:-1])
    finally:
        reset_limiter()
