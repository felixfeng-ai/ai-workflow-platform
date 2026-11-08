import os

import pytest

from app.services.code_analysis.github import GitHubClient


@pytest.mark.skipif(
    not os.environ.get("GITHUB_TEST_REPO"),
    reason="设置 GITHUB_TEST_REPO 和可选 GITHUB_TEST_TOKEN 后执行真实 GitHub 联调",
)
async def test_live_github_repository_contract():
    repo = os.environ["GITHUB_TEST_REPO"]
    client = GitHubClient(os.environ.get("GITHUB_TEST_TOKEN", ""))
    repository = await client.get_repository(repo)
    assert repository.get("full_name") == repo
    branch = repository.get("default_branch") or "main"
    head = await client.get_branch_head(repo, branch)
    compare = await client.get_compare(repo, head, head)
    assert isinstance(compare, dict)
