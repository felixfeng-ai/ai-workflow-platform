import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import uuid4

from docx import Document
from sqlalchemy import select

from app.core.security import hash_password
from app.core.crypto import decrypt_secret
from app.models import CodeAnalysisRun, ProjectRepoConnection, User


class FakeGitHubClient:
    """测试替身：验证配置只依赖 GitHub 仓库读取，不访问真实网络。"""

    def __init__(self, token: str, api_base: str | None = None):
        self.token = token
        self.api_base = api_base

    async def get_repository(self, repo_full_name: str) -> dict:
        return {
            "id": 424242,
            "full_name": repo_full_name,
            "default_branch": "main",
        }

    async def get_compare(self, repo_full_name: str, before: str, after: str) -> dict:
        return {
            "commits": [
                {
                    "sha": after,
                    "commit": {
                        "message": "feat(code-analysis): add webhook reporting",
                        "author": {"name": "林"},
                    },
                }
            ],
            "files": [
                {
                    "filename": "backend/app/code_analysis.py",
                    "status": "added",
                    "additions": 18,
                    "deletions": 0,
                    "patch": '@@ -0,0 +1,2 @@\n+API_KEY = "sk-live-1234567890123456"\n+print("report")',
                },
                {
                    "filename": "frontend/src/Old.tsx",
                    "previous_filename": "frontend/src/old.tsx",
                    "status": "renamed",
                    "additions": 2,
                    "deletions": 1,
                    "patch": "@@ -1 +1 @@\n-old\n+new",
                },
            ],
        }


async def _configure(client, headers: dict, project_id: str, patterns: list[str] | None = None):
    return await client.post(
        f"/api/projects/{project_id}/code-analysis/config",
        headers=headers,
        json={
            "repo_url": "https://github.com/acme/demo",
            "access_token": "github_pat_test",
            "branch_patterns": patterns or ["feature/*", "fix/*"],
            "enabled": True,
        },
    )


async def _wait_run(client, headers: dict, project_id: str, run_id: str, timeout: float = 20.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        r = await client.get(
            f"/api/projects/{project_id}/code-analysis/runs/{run_id}",
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()
        if data["status"] in {"succeeded", "partial", "failed"}:
            return data
        if loop.time() > deadline:
            raise AssertionError(f"code analysis run timed out: {data}")
        await asyncio.sleep(0.05)


def _signed_push(
    secret: str,
    *,
    delivery: str,
    before: str = "1" * 40,
    after: str = "2" * 40,
    branch: str = "feature/code-analysis",
) -> tuple[dict, str, dict[str, str]]:
    body = json.dumps(
        {
            "ref": f"refs/heads/{branch}",
            "before": before,
            "after": after,
            "repository": {"full_name": "acme/demo"},
            "pusher": {"name": "dev"},
            "head_commit": {"message": "feat: add report"},
            "commits": [{"id": after, "message": "feat: add report"}],
        }
    )
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": f"sha256={signature}",
        "Content-Type": "application/json",
    }
    return json.loads(body), body, headers


async def test_configure_repository_returns_secret_once_and_redacts_token(
    client, auth_headers, db_session, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)

    project = (
        await client.post(
            "/api/projects",
            headers=auth_headers,
            json={"name": "代码分析项目", "repo_url": "https://github.com/acme/demo"},
        )
    ).json()

    r = await _configure(client, auth_headers, project["id"])
    assert r.status_code == 201
    created = r.json()
    assert created["repo_full_name"] == "acme/demo"
    assert created["webhook_secret"].startswith("whsec_")
    assert "access_token" not in created
    assert created["webhook_path"].endswith("/webhook")

    r = await client.get(
        f"/api/projects/{project['id']}/code-analysis/config", headers=auth_headers
    )
    assert r.status_code == 200
    read = r.json()
    assert read["repo_full_name"] == "acme/demo"
    assert "access_token" not in read
    assert "webhook_secret" not in read

    connection = (
        await db_session.execute(
            select(ProjectRepoConnection).where(
                ProjectRepoConnection.project_id == project["id"]
            )
        )
    ).scalar_one()
    assert connection.access_token_encrypted != "github_pat_test"
    assert decrypt_secret(connection.access_token_encrypted or "") == "github_pat_test"
    assert decrypt_secret(connection.webhook_secret_encrypted) == created["webhook_secret"]


async def test_configure_public_repository_without_token(client, auth_headers, monkeypatch):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "公开仓库项目"})
    ).json()
    response = await client.post(
        f"/api/projects/{project['id']}/code-analysis/config",
        headers=auth_headers,
        json={
            "repo_url": "https://github.com/pypa/sampleproject",
            "access_token": "",
            "branch_patterns": ["main"],
            "enabled": True,
        },
    )
    assert response.status_code == 201
    assert response.json()["repo_full_name"] == "pypa/sampleproject"


async def test_non_owner_cannot_configure_code_analysis(
    client, auth_headers, db_session, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "Owner 项目"})
    ).json()
    owner = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()
    member = User(
        id=str(uuid4()),
        tenant_id=owner.tenant_id,
        email="member@example.com",
        name="成员",
        password_hash=hash_password("secret123"),
        role="member",
    )
    db_session.add(member)
    await db_session.commit()
    login = await client.post(
        "/api/auth/login",
        json={"email": "member@example.com", "password": "secret123"},
    )
    member_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await _configure(client, member_headers, project["id"])
    assert r.status_code == 403


async def test_code_analysis_project_is_tenant_isolated(client, auth_headers):
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "隔离项目"})
    ).json()
    other = await client.post(
        "/api/auth/register",
        json={"email": "other-code@example.com", "password": "secret123", "name": "外人"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert (
        await client.get(
            f"/api/projects/{project['id']}/code-analysis/config", headers=other_headers
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/projects/{project['id']}/code-analysis/runs", headers=other_headers
        )
    ).status_code == 404


async def test_webhook_rejects_invalid_signature(
    client, auth_headers, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "签名项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()

    _, body, headers = _signed_push(
        "wrong-secret", delivery="delivery-invalid", branch="feature/test"
    )
    r = await client.post(
        config["webhook_path"],
        content=body,
        headers=headers,
    )
    assert r.status_code == 401


async def test_ping_marks_webhook_as_connected(
    client, auth_headers, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "Ping 项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()
    body = json.dumps({"zen": "Keep it logically awesome."})
    signature = hmac.new(
        config["webhook_secret"].encode(), body.encode(), hashlib.sha256
    ).hexdigest()

    ping = await client.post(
        config["webhook_path"],
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "delivery-ping",
            "X-Hub-Signature-256": f"sha256={signature}",
            "Content-Type": "application/json",
        },
    )
    assert ping.status_code == 200

    read = await client.get(
        f"/api/projects/{project['id']}/code-analysis/config", headers=auth_headers
    )
    assert read.status_code == 200
    assert read.json()["webhook_connected_at"] is not None
    assert read.json()["webhook_last_event"] == "ping"


async def test_push_webhook_creates_report_and_notification(
    client, auth_headers, monkeypatch
):
    import app.api.code_analysis as code_analysis_api
    import app.services.code_analysis.runner as runner_module

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(runner_module, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "Webhook 项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()

    _, body, headers = _signed_push(
        config["webhook_secret"], delivery="delivery-valid", branch="feature/code-analysis"
    )
    r = await client.post(config["webhook_path"], content=body, headers=headers)
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    run = await _wait_run(client, auth_headers, project["id"], run_id)
    assert run["status"] == "succeeded"
    report = run["report"]
    assert report["change_scale"]["files"] == 2
    assert report["change_scale"]["commits"] == 1
    assert report["change_scale"]["additions"] == 20
    assert report["change_scale"]["deletions"] == 1
    assert any("重命名" in item for item in report["impact"]["direct"])
    assert report["commits"][0]["sha"] == "2" * 40
    assert any(f["source"] == "secret_scan" for f in report["security_findings"])
    assert run["max_severity"] == "high"
    assert run["finding_count"] >= 1
    connection_read = await client.get(
        f"/api/projects/{project['id']}/code-analysis/config", headers=auth_headers
    )
    assert connection_read.json()["webhook_last_event"] == "push"
    assert "summary" in report
    assert "functional_points" in report
    assert "state_management" in report

    notifications = await client.get(
        "/api/notifications?type=code_analysis", headers=auth_headers
    )
    assert notifications.status_code == 200
    assert notifications.json()["total"] >= 1

    download = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs/{run_id}/download.docx",
        headers=auth_headers,
    )
    assert download.status_code == 200
    assert (
        download.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment" in download.headers["content-disposition"]
    assert "filename*=UTF-8''" in download.headers["content-disposition"]
    assert download.content.startswith(b"PK")

    document = Document(BytesIO(download.content))
    paragraphs = "\n".join(paragraph.text for paragraph in document.paragraphs)
    table_text = "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )
    exported = f"{paragraphs}\n{table_text}"
    assert "代码分析报告" in exported
    assert "feature/code-analysis" in exported
    assert "变更概览" in exported
    assert "功能点" in exported
    assert "安全发现" in exported
    assert "疑似硬编码凭据" in exported


async def test_download_rejects_run_without_report(
    client, auth_headers, db_session, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "空报告项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()
    db_run = CodeAnalysisRun(
        tenant_id=project["id"],
        project_id=project["id"],
        connection_id=config["id"],
        repo_full_name="acme/demo",
        branch="feature/pending",
        before_sha="a" * 40,
        after_sha="b" * 40,
        status="running",
    )
    # tenant_id 必须来自真实用户，而不是项目 id；使用数据库反查修正。
    owner = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()
    db_run.tenant_id = owner.tenant_id
    db_session.add(db_run)
    await db_session.commit()
    await db_session.refresh(db_run)

    download = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs/{db_run.id}/download.docx",
        headers=auth_headers,
    )
    assert download.status_code == 409


async def test_duplicate_delivery_is_idempotent(
    client, auth_headers, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "幂等项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()
    _, body, headers = _signed_push(
        config["webhook_secret"], delivery="delivery-duplicate", branch="feature/test"
    )

    first = await client.post(config["webhook_path"], content=body, headers=headers)
    second = await client.post(config["webhook_path"], content=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 204

    runs = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs", headers=auth_headers
    )
    assert runs.status_code == 200
    assert runs.json()["total"] == 1
    assert len(runs.json()["items"]) == 1


async def test_branch_not_matching_pattern_is_ignored(
    client, auth_headers, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "分支项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"], patterns=["feature/*"])).json()
    _, body, headers = _signed_push(
        config["webhook_secret"], delivery="delivery-ignore", branch="docs/readme"
    )

    r = await client.post(config["webhook_path"], content=body, headers=headers)
    assert r.status_code == 204
    runs = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs", headers=auth_headers
    )
    assert runs.json()["total"] == 0
    assert runs.json()["items"] == []


async def test_history_pagination_keyword_and_filters(
    client, auth_headers, db_session, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "搜索项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()
    owner = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()

    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=1)).date().isoformat()
    date_to = (now + timedelta(days=1)).date().isoformat()
    rows = [
        CodeAnalysisRun(
            tenant_id=owner.tenant_id,
            project_id=project["id"],
            connection_id=config["id"],
            repo_full_name="acme/demo",
            branch="feature/auth",
            before_sha="1" * 40,
            after_sha="a" * 40,
            head_commit_message="feat: add OAuth callback",
            status="succeeded",
            search_text="OAuth callback backend/app/auth.py 登录安全",
            max_severity="high",
            finding_count=2,
            created_at=now,
        ),
        CodeAnalysisRun(
            tenant_id=owner.tenant_id,
            project_id=project["id"],
            connection_id=config["id"],
            repo_full_name="acme/demo",
            branch="fix/payment",
            before_sha="2" * 40,
            after_sha="b" * 40,
            head_commit_message="fix: payment retry",
            status="failed",
            search_text="payment retry backend/app/payment.py 状态管理",
            max_severity="medium",
            finding_count=1,
            created_at=now - timedelta(days=1),
        ),
        CodeAnalysisRun(
            tenant_id=owner.tenant_id,
            project_id=project["id"],
            connection_id=config["id"],
            repo_full_name="acme/demo",
            branch="docs/readme",
            before_sha="3" * 40,
            after_sha="c" * 40,
            head_commit_message="docs: update readme",
            status="succeeded",
            search_text="README documentation",
            max_severity="none",
            finding_count=0,
            created_at=now - timedelta(days=2),
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    page = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs?page=1&page_size=2",
        headers=auth_headers,
    )
    assert page.status_code == 200
    payload = page.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert len(payload["items"]) == 2

    keyword = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs?keyword=OAuth",
        headers=auth_headers,
    )
    assert keyword.status_code == 200
    assert keyword.json()["total"] == 1
    assert keyword.json()["items"][0]["branch"] == "feature/auth"
    assert keyword.json()["items"][0]["max_severity"] == "high"
    assert keyword.json()["items"][0]["finding_count"] == 2

    combined = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs"
        f"?status=failed&branch=fix/payment&severity=medium&date_from={date_from}&date_to={date_to}",
        headers=auth_headers,
    )
    assert combined.status_code == 200
    assert combined.json()["total"] == 1
    assert combined.json()["items"][0]["after_sha"] == "b" * 40


async def test_history_search_sha_and_file_path(
    client, auth_headers, db_session, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "路径项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()
    owner = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()
    db_session.add(
        CodeAnalysisRun(
            tenant_id=owner.tenant_id,
            project_id=project["id"],
            connection_id=config["id"],
            repo_full_name="acme/demo",
            branch="feature/parser",
            before_sha="4" * 40,
            after_sha="deadbeef" + "5" * 32,
            head_commit_message="refactor parser",
            status="succeeded",
            search_text="backend/app/parser.py 功能点 解析器安全",
            max_severity="low",
            finding_count=1,
        )
    )
    await db_session.commit()

    sha_result = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs?keyword=deadbeef",
        headers=auth_headers,
    )
    assert sha_result.status_code == 200
    assert sha_result.json()["total"] == 1

    path_result = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs?keyword=parser.py",
        headers=auth_headers,
    )
    assert path_result.status_code == 200
    assert path_result.json()["total"] == 1


async def test_backfill_old_report_metadata(
    client, auth_headers, db_session, monkeypatch
):
    import app.api.code_analysis as code_analysis_api
    from app.services.code_analysis.backfill import backfill_code_analysis_metadata

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "回填项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()
    owner = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()
    run = CodeAnalysisRun(
        tenant_id=owner.tenant_id,
        project_id=project["id"],
        connection_id=config["id"],
        repo_full_name="acme/demo",
        branch="feature/old",
        before_sha="7" * 40,
        after_sha="8" * 40,
        status="succeeded",
        report={
            "repo_full_name": "acme/demo",
            "branch": "feature/old",
            "summary": "历史报告",
            "commits": [{"sha": "8" * 40, "message": "feat: legacy"}],
            "functional_points": [
                {
                    "title": "旧功能点",
                    "description": "legacy search",
                    "files": ["backend/app/legacy.py"],
                }
            ],
            "security_findings": [
                {
                    "severity": "high",
                    "title": "旧安全风险",
                    "file": "backend/app/legacy.py",
                    "evidence": "unsafe",
                    "recommendation": "fix",
                    "source": "ai",
                }
            ],
        },
        search_text="",
        max_severity="none",
        finding_count=0,
    )
    db_session.add(run)
    await db_session.commit()

    updated = await backfill_code_analysis_metadata(db_session)
    await db_session.commit()
    await db_session.refresh(run)
    assert updated == 1
    assert "legacy.py" in run.search_text
    assert run.max_severity == "high"
    assert run.finding_count == 1


async def test_history_date_filter_uses_shanghai_timezone(
    client, auth_headers, db_session, monkeypatch
):
    import app.api.code_analysis as code_analysis_api

    monkeypatch.setattr(code_analysis_api, "GitHubClient", FakeGitHubClient)
    project = (
        await client.post("/api/projects", headers=auth_headers, json={"name": "时区项目"})
    ).json()
    config = (await _configure(client, auth_headers, project["id"])).json()
    owner = (
        await db_session.execute(select(User).where(User.email == "test@example.com"))
    ).scalar_one()
    db_session.add(
        CodeAnalysisRun(
            tenant_id=owner.tenant_id,
            project_id=project["id"],
            connection_id=config["id"],
            repo_full_name="acme/demo",
            branch="feature/timezone",
            before_sha="9" * 40,
            after_sha="a" * 40,
            head_commit_message="feat: timezone",
            status="succeeded",
            search_text="timezone",
            max_severity="none",
            finding_count=0,
            created_at=datetime(2026, 11, 9, 16, 30, tzinfo=timezone.utc),
        )
    )
    await db_session.commit()

    result = await client.get(
        f"/api/projects/{project['id']}/code-analysis/runs"
        "?date_from=2026-11-10&date_to=2026-11-10",
        headers=auth_headers,
    )
    assert result.status_code == 200
    assert result.json()["total"] == 1


async def test_github_client_omits_empty_authorization():
    from app.services.code_analysis.github import GitHubClient

    headers = GitHubClient("")._headers()
    assert "Authorization" not in headers


def test_ai_report_merge_preserves_deterministic_findings():
    from app.services.code_analysis.ai import merge_ai_report
    from app.services.code_analysis.report import build_report, normalize_change_set

    payload = {
        "commits": [{"sha": "a" * 40, "commit": {"message": "feat: test"}}],
        "files": [
            {
                "filename": "backend/app/demo.py",
                "status": "modified",
                "additions": 2,
                "deletions": 1,
                "patch": '@@ -1 +1,2 @@\n-old\n+API_KEY = "sk-live-1234567890123456"\n+new',
            }
        ],
    }
    changes, truncated = normalize_change_set(
        payload, max_files=10, max_patch_chars=10_000
    )
    report = build_report(
        changes,
        branch="feature/test",
        before_sha="b" * 40,
        after_sha="a" * 40,
        repo_full_name="acme/demo",
    )
    assert truncated is False
    merged = merge_ai_report(
        report,
        {
            "summary": "AI 摘要",
            "functional_points": [
                {
                    "title": "AI 功能点",
                    "description": "补充解释",
                    "files": ["backend/app/demo.py"],
                    "confidence": "medium",
                }
            ],
            "security_findings": [
                {
                    "severity": "medium",
                    "category": "logic",
                    "title": "AI 风险",
                    "file": "backend/app/demo.py",
                    "line": 1,
                    "evidence": "risk",
                    "recommendation": "review",
                }
            ],
        },
    )
    assert merged["summary"] == "AI 摘要"
    assert merged["functional_points"][0]["title"] == "AI 功能点"
    assert any(item["source"] == "secret_scan" for item in merged["security_findings"])
    assert any(item["source"] == "ai" for item in merged["security_findings"])


async def test_semgrep_scanner_maps_findings_to_changed_code():
    from app.services.code_analysis.scanner import run_semgrep

    findings, status = await run_semgrep(
        [
            {
                "path": "backend/app/danger.py",
                "patch": "@@ -10,0 +11 @@\n+subprocess.run(command, shell=True)",
            }
        ]
    )
    assert status in {"completed", "unavailable"}
    if status == "completed":
        assert any(item["source"] == "semgrep" for item in findings)
        assert all(item["file"] == "backend/app/danger.py" for item in findings)
        assert all(item["line"] == 11 for item in findings)


async def test_ai_enrichment_parses_structured_json(monkeypatch):
    import app.services.code_analysis.ai as ai_module
    from app.config import settings
    from app.services.code_analysis.report import build_report, normalize_change_set

    changes, _ = normalize_change_set(
        {
            "commits": [{"sha": "c" * 40, "commit": {"message": "feat: AI report"}}],
            "files": [],
        },
        max_files=10,
        max_patch_chars=1000,
    )
    report = build_report(
        changes,
        branch="feature/ai",
        before_sha="b" * 40,
        after_sha="c" * 40,
        repo_full_name="acme/demo",
    )

    class FakeEngine:
        async def chat(self, query: str, user: str) -> str:
            assert "COMMITS:" in query
            assert user == "user-1"
            return '{"summary":"AI 结构化摘要","functional_points":[],"security_findings":[]}'

    monkeypatch.setattr(settings, "code_analysis_ai_enabled", True)
    monkeypatch.setattr(ai_module, "get_ai_engine", lambda: FakeEngine())
    ai, provider, _model = await ai_module.enrich_with_ai(
        change_set=changes,
        report=report,
        user_id="user-1",
    )
    assert ai is not None
    assert ai["summary"] == "AI 结构化摘要"
    assert provider == settings.ai_provider


async def test_semgrep_scanner_degrades_when_binary_missing(monkeypatch):
    import app.services.code_analysis.scanner as scanner_module

    monkeypatch.setattr(scanner_module.shutil, "which", lambda _command: None)
    findings, status = await scanner_module.run_semgrep(
        [{"path": "a.py", "patch": "@@ -0,0 +1 @@\n+print(1)"}]
    )
    assert findings == []
    assert status == "unavailable"


async def test_github_client_reads_repository_compare_and_branch(monkeypatch):
    import app.services.code_analysis.github as github_module

    class FakeResponse:
        def __init__(self, payload: dict):
            self.status_code = 200
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.calls: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, headers: dict, params=None):
            self.calls.append(url)
            if "/compare/" in url:
                return FakeResponse({"commits": [], "files": []})
            if "/branches/" in url:
                return FakeResponse({"commit": {"sha": "d" * 40}})
            return FakeResponse({"id": 1, "full_name": "acme/demo", "default_branch": "main"})

    monkeypatch.setattr(github_module.httpx, "AsyncClient", FakeAsyncClient)
    client = github_module.GitHubClient("token", "https://api.github.test")
    repo = await client.get_repository("acme/demo")
    compare = await client.get_compare("acme/demo", "a" * 40, "b" * 40)
    head = await client.get_branch_head("acme/demo", "main")
    assert repo["full_name"] == "acme/demo"
    assert compare["files"] == []
    assert head == "d" * 40
    assert client.parse_repo_url("https://github.com/acme/demo") == "acme/demo"
