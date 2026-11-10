from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...config import settings
from ...core.crypto import SecretDecryptionError, decrypt_secret
from ...db import SessionLocal
from ...models import CodeAnalysisRun, ProjectRepoConnection
from ...services.notification import create_notification
from .ai import enrich_with_ai, merge_ai_report
from .github import GitHubClient, GitHubError
from .report import (
    build_report,
    build_search_text,
    normalize_change_set,
    render_markdown,
    risk_summary,
)
from .scanner import run_semgrep


class CodeAnalysisRunManager:
    """进程内后台分析执行器。

    与现有 Agent/Workflow 运行模式一致：Webhook 只落 pending 并立即返回，
    分析在独立会话中完成。生产多实例部署前需要替换为持久队列。
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self.session_factory = session_factory or SessionLocal
        self._tasks: set[asyncio.Task] = set()

    def submit(self, run_id: str) -> None:
        task = asyncio.create_task(self._execute(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run_id: str) -> None:
        async with self.session_factory() as db:
            run = await db.get(CodeAnalysisRun, run_id)
            if run is None:
                return
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            await db.commit()

            connection: ProjectRepoConnection | None = None
            try:
                connection = await db.get(ProjectRepoConnection, run.connection_id)
                if connection is None or not connection.enabled:
                    raise ValueError("仓库连接不存在或已停用")
                if not connection.access_token_encrypted:
                    raise ValueError("仓库连接未配置访问 Token")
                token = decrypt_secret(connection.access_token_encrypted)
                client = GitHubClient(token)

                base = run.before_sha
                if not base or set(base) == {"0"}:
                    base = connection.default_branch
                try:
                    payload = await client.get_compare(
                        connection.repo_full_name, base, run.after_sha
                    )
                except GitHubError:
                    if base != connection.default_branch:
                        payload = await client.get_compare(
                            connection.repo_full_name,
                            connection.default_branch,
                            run.after_sha,
                        )
                    else:
                        raise

                change_set, truncated = normalize_change_set(
                    payload,
                    max_files=settings.code_analysis_max_files,
                    max_patch_chars=settings.code_analysis_max_patch_chars,
                    source_path=connection.source_path,
                )
                semgrep_findings, semgrep_status = await run_semgrep(change_set["files"])
                report = build_report(
                    change_set,
                    branch=run.branch,
                    before_sha=run.before_sha,
                    after_sha=run.after_sha,
                    repo_full_name=run.repo_full_name,
                    semgrep_findings=semgrep_findings,
                    semgrep_status=semgrep_status,
                    source_path=connection.source_path,
                )

                ai, provider, model = await enrich_with_ai(
                    change_set=change_set,
                    report=report,
                    user_id=connection.created_by,
                )
                if ai:
                    report = merge_ai_report(report, ai)

                run.change_stats = report["change_scale"]
                run.report = report
                run.report_markdown = render_markdown(report)
                run.search_text = build_search_text(report)
                run.max_severity, run.finding_count = risk_summary(report)
                run.truncated = truncated
                run.ai_provider = provider
                run.ai_model = model
                run.status = "partial" if truncated else "succeeded"
                run.error = None
            except SecretDecryptionError as exc:
                run.status = "failed"
                run.error = str(exc)
            except Exception as exc:  # noqa: BLE001 - 后台任务必须把错误落库
                run.status = "failed"
                run.error = f"{exc.__class__.__name__}: {exc}"
            finally:
                run.finished_at = datetime.now(timezone.utc)
                if connection is not None:
                    title = "代码分析完成" if run.status != "failed" else "代码分析失败"
                    body = (
                        f"{run.repo_full_name} · {run.branch} · {run.after_sha[:8]} "
                        f"已完成提交分析"
                        if run.status != "failed"
                        else f"{run.repo_full_name} · {run.branch} 分析失败：{(run.error or '')[:160]}"
                    )
                    await create_notification(
                        db,
                        user_id=connection.created_by,
                        type="code_analysis",
                        title=title,
                        body=body,
                        ref_id=run.id,
                        tenant_id=run.tenant_id,
                    )
                await db.commit()

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


code_analysis_run_manager = CodeAnalysisRunManager()
