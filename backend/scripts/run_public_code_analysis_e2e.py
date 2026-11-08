"""对本地运行的后端执行公开仓库代码分析全链路测试。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import tempfile
from pathlib import Path

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--repo", default="pypa/sampleproject")
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=90) as client:
        register = await client.post(
            f"{args.base_url}/api/auth/register",
            json={
                "email": "code-analysis-e2e@example.com",
                "password": "secret123",
                "name": "E2E",
            },
        )
        register.raise_for_status()
        headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

        project_response = await client.post(
            f"{args.base_url}/api/projects",
            headers=headers,
            json={
                "name": "公开仓库 E2E",
                "repo_url": f"https://github.com/{args.repo}",
            },
        )
        project_response.raise_for_status()
        project = project_response.json()

        config_response = await client.post(
            f"{args.base_url}/api/projects/{project['id']}/code-analysis/config",
            headers=headers,
            json={
                "repo_url": f"https://github.com/{args.repo}",
                "access_token": "",
                "branch_patterns": ["main"],
                "enabled": True,
            },
        )
        config_response.raise_for_status()
        config = config_response.json()

        commits_response = await client.get(
            f"https://api.github.com/repos/{args.repo}/commits",
            params={"sha": "main", "per_page": 2},
            headers={"Accept": "application/vnd.github+json", "User-Agent": "VeyaWork-E2E"},
        )
        commits_response.raise_for_status()
        commits = commits_response.json()
        if len(commits) < 2:
            raise RuntimeError("公开仓库至少需要两个提交")
        after = commits[0]["sha"]
        before = commits[1]["sha"]

        payload = {
            "ref": "refs/heads/main",
            "before": before,
            "after": after,
            "repository": {"full_name": args.repo},
            "pusher": {"name": "e2e"},
            "head_commit": {"message": commits[0]["commit"]["message"]},
        }
        body = json.dumps(payload, ensure_ascii=False)
        signature = hmac.new(
            config["webhook_secret"].encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        webhook = await client.post(
            f"{args.base_url}{config['webhook_path']}",
            content=body,
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": f"public-e2e-{after[:12]}",
                "X-Hub-Signature-256": f"sha256={signature}",
                "Content-Type": "application/json",
            },
        )
        webhook.raise_for_status()
        run_id = webhook.json()["run_id"]

        run = {}
        for _ in range(120):
            result = await client.get(
                f"{args.base_url}/api/projects/{project['id']}/code-analysis/runs/{run_id}",
                headers=headers,
            )
            result.raise_for_status()
            run = result.json()
            if run["status"] in {"succeeded", "partial", "failed"}:
                break
            await asyncio.sleep(1)
        if run.get("status") not in {"succeeded", "partial"}:
            raise RuntimeError(f"分析未成功: {run}")

        document = await client.get(
            f"{args.base_url}/api/projects/{project['id']}/code-analysis/runs/{run_id}/download.docx",
            headers=headers,
        )
        document.raise_for_status()
        if not document.content.startswith(b"PK"):
            raise RuntimeError("下载文件不是有效 DOCX")
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as output:
            output.write(document.content)
            output_path = Path(output.name)
        try:
            print(
                json.dumps(
                    {
                        "repo": args.repo,
                        "before": before,
                        "after": after,
                        "run_id": run_id,
                        "status": run["status"],
                        "files": run["change_stats"]["files"],
                        "finding_count": run["finding_count"],
                        "docx_bytes": len(document.content),
                        "docx_path": str(output_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
