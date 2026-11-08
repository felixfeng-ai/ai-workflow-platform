from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.crypto import SecretDecryptionError, decrypt_secret
from ..db import get_db
from ..models import CodeAnalysisRun, ProjectRepoConnection
from ..services.code_analysis.runner import code_analysis_run_manager

router = APIRouter(prefix="/api/integrations/github", tags=["github-webhooks"])


def _verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


def _matches_branch(branch: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(branch, pattern) for pattern in patterns)


async def _mark_connected(
    db: AsyncSession, connection: ProjectRepoConnection, event: str
) -> None:
    now = datetime.now(timezone.utc)
    if connection.webhook_connected_at is None:
        connection.webhook_connected_at = now
    connection.webhook_last_event = event
    await db.commit()


@router.post("/{connection_id}/webhook")
async def github_webhook(
    connection_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    connection = await db.get(ProjectRepoConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="connection not found")
    body = await request.body()
    try:
        secret = decrypt_secret(connection.webhook_secret_encrypted)
    except SecretDecryptionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not _verify_signature(secret, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        await _mark_connected(db, connection, event)
        return Response(status_code=200)
    if event != "push":
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid JSON payload")

    repository = payload.get("repository") or {}
    if repository.get("full_name") != connection.repo_full_name:
        raise HTTPException(status_code=400, detail="repository does not match connection")
    if not connection.enabled:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await _mark_connected(db, connection, event)

    ref = str(payload.get("ref") or "")
    if not ref.startswith("refs/heads/"):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    branch = ref.removeprefix("refs/heads/")
    if not _matches_branch(branch, connection.branch_patterns or []):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    before = str(payload.get("before") or "")
    after = str(payload.get("after") or "")
    if not before or not after or set(after) == {"0"}:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    delivery_id = request.headers.get("X-GitHub-Delivery")
    if delivery_id:
        existing_delivery = (
            await db.execute(
                select(CodeAnalysisRun.id).where(
                    CodeAnalysisRun.connection_id == connection.id,
                    CodeAnalysisRun.delivery_id == delivery_id,
                )
            )
        ).scalar_one_or_none()
        if existing_delivery is not None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    existing_range = (
        await db.execute(
            select(CodeAnalysisRun.id).where(
                CodeAnalysisRun.connection_id == connection.id,
                CodeAnalysisRun.branch == branch,
                CodeAnalysisRun.before_sha == before,
                CodeAnalysisRun.after_sha == after,
            )
        )
    ).scalar_one_or_none()
    if existing_range is not None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    head_commit = payload.get("head_commit") or {}
    run = CodeAnalysisRun(
        tenant_id=connection.tenant_id,
        project_id=connection.project_id,
        connection_id=connection.id,
        trigger_type="webhook",
        delivery_id=delivery_id,
        repo_full_name=connection.repo_full_name,
        branch=branch,
        before_sha=before,
        after_sha=after,
        pusher_login=str((payload.get("pusher") or {}).get("name") or "") or None,
        head_commit_message=str(head_commit.get("message") or "") or None,
        status="pending",
    )
    db.add(run)
    try:
        await db.commit()
    except IntegrityError:
        # 并发投递可能同时穿过上面的预查；唯一约束是最后一道幂等闸。
        await db.rollback()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await db.refresh(run)
    code_analysis_run_manager.submit(run.id)
    return Response(
        content=json.dumps({"run_id": run.id, "status": run.status}),
        media_type="application/json",
        status_code=status.HTTP_202_ACCEPTED,
    )
