"""验证真实 GitHub 仓库元数据、默认分支和 Compare API。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.code_analysis.github import GitHubClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TEST_TOKEN", ""),
        help="私有仓库需要 Contents: read 和 Metadata: read",
    )
    args = parser.parse_args()

    client = GitHubClient(args.token)
    repository = await client.get_repository(args.repo)
    branch = str(repository.get("default_branch") or "main")
    head = await client.get_branch_head(args.repo, branch)
    compare = await client.get_compare(args.repo, head, head)
    print(
        json.dumps(
            {
                "repository": repository.get("full_name"),
                "default_branch": branch,
                "head": head,
                "compare_status": compare.get("status", "identical"),
                "commits": len(compare.get("commits") or []),
                "files": len(compare.get("files") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
