"""通过真实 GitHub Webhook 执行代码分析全链路测试，并自动清理远端资源。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import httpx


def run(cmd: list[str], *, cwd: Path, input_text: str | None = None, check: bool = True):
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=check,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    branch = f"feature/e2e-webhook-{int(time.time())}"
    worktree = Path(tempfile.mkdtemp(prefix="veyawork-webhook-e2e-"))
    hook_id: str | None = None
    remote_branch_created = False
    result: dict = {}

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            register = await client.post(
                f"{args.base_url}/api/auth/register",
                json={
                    "email": "webhook-e2e@example.com",
                    "password": "secret123",
                    "name": "Webhook E2E",
                },
            )
            register.raise_for_status()
            headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

            project = (
                await client.post(
                    f"{args.base_url}/api/projects",
                    headers=headers,
                    json={
                        "name": "真实 Webhook E2E",
                        "repo_url": f"https://github.com/{args.repo}",
                    },
                )
            ).json()
            config_response = await client.post(
                f"{args.base_url}/api/projects/{project['id']}/code-analysis/config",
                headers=headers,
                json={
                    "repo_url": f"https://github.com/{args.repo}",
                    "access_token": "",
                    "branch_patterns": ["feature/*"],
                    "enabled": True,
                },
            )
            config_response.raise_for_status()
            config = config_response.json()

            webhook_url = f"{args.public_url.rstrip('/')}{config['webhook_path']}"
            hook_body = {
                "name": "web",
                "active": True,
                "events": ["push"],
                "config": {
                    "url": webhook_url,
                    "content_type": "json",
                    "secret": config["webhook_secret"],
                    "insecure_ssl": "0",
                },
            }
            hook = run(
                [
                    "gh",
                    "api",
                    f"repos/{args.repo}/hooks",
                    "--method",
                    "POST",
                    "--input",
                    "-",
                ],
                cwd=repo_root,
                input_text=json.dumps(hook_body),
            )
            hook_id = str(json.loads(hook.stdout)["id"])

            run(
                ["git", "worktree", "add", "--detach", str(worktree), "origin/main"],
                cwd=repo_root,
            )
            run(["git", "switch", "-c", branch], cwd=worktree)
            run(
                [
                    "git",
                    "-c",
                    "user.name=VeyaWork E2E",
                    "-c",
                    "user.email=e2e@veyawork.local",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "test: verify github code analysis webhook",
                ],
                cwd=worktree,
            )
            run(["git", "push", "origin", branch], cwd=worktree)
            remote_branch_created = True

            run_data = None
            for _ in range(150):
                runs_response = await client.get(
                    f"{args.base_url}/api/projects/{project['id']}/code-analysis/runs",
                    headers=headers,
                    params={"keyword": branch, "page_size": 10},
                )
                runs_response.raise_for_status()
                runs = runs_response.json()["items"]
                if runs:
                    run_id = runs[0]["id"]
                    detail = await client.get(
                        f"{args.base_url}/api/projects/{project['id']}/code-analysis/runs/{run_id}",
                        headers=headers,
                    )
                    detail.raise_for_status()
                    run_data = detail.json()
                    if run_data["status"] in {"succeeded", "partial", "failed"}:
                        break
                await asyncio.sleep(1)

            if not run_data or run_data["status"] not in {"succeeded", "partial"}:
                raise RuntimeError(f"Webhook 分析未成功: {run_data}")

            document = await client.get(
                f"{args.base_url}/api/projects/{project['id']}/code-analysis/runs/{run_data['id']}/download.docx",
                headers=headers,
            )
            document.raise_for_status()
            if not document.content.startswith(b"PK"):
                raise RuntimeError("DOCX 下载内容无效")

            result = {
                "repo": args.repo,
                "branch": branch,
                "webhook_id": hook_id,
                "run_id": run_data["id"],
                "status": run_data["status"],
                "files": run_data["change_stats"]["files"],
                "findings": run_data["finding_count"],
                "docx_bytes": len(document.content),
            }
    finally:
        if remote_branch_created:
            run(["git", "push", "origin", "--delete", branch], cwd=repo_root, check=False)
        run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=repo_root,
            check=False,
        )
        shutil.rmtree(worktree, ignore_errors=True)
        if hook_id:
            run(
                [
                    "gh",
                    "api",
                    f"repos/{args.repo}/hooks/{hook_id}",
                    "--method",
                    "DELETE",
                ],
                cwd=repo_root,
                check=False,
            )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
