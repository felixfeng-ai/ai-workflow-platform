from __future__ import annotations

import httpx

from ...config import settings
from ..deploy import parse_github_repo

GITHUB_TIMEOUT = 20.0


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    """只读 GitHub API 客户端：仓库元数据与 compare，不触发任何写操作。"""

    def __init__(self, token: str, api_base: str | None = None):
        self.token = token
        self.api_base = (api_base or settings.github_api_base).rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT) as client:
                resp = await client.get(
                    f"{self.api_base}{path}", headers=self._headers(), params=params
                )
        except (httpx.HTTPError, ValueError) as exc:
            raise GitHubError(f"GitHub 请求失败：{exc.__class__.__name__}") from exc

        if resp.status_code == 401:
            raise GitHubError("GitHub Token 无效或已过期")
        if resp.status_code == 403:
            raise GitHubError("GitHub Token 权限不足或触发速率限制")
        if resp.status_code == 404:
            raise GitHubError("GitHub 仓库、分支或提交不存在，或 Token 未授权")
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub API 返回 {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise GitHubError("GitHub 返回了非 JSON 响应") from exc
        if not isinstance(data, dict):
            raise GitHubError("GitHub 返回结构不合法")
        return data

    async def get_repository(self, repo_full_name: str) -> dict:
        return await self._get(f"/repos/{repo_full_name}")

    async def get_compare(
        self, repo_full_name: str, before: str, after: str
    ) -> dict:
        return await self._get(f"/repos/{repo_full_name}/compare/{before}...{after}")

    async def get_branch_head(self, repo_full_name: str, branch: str) -> str:
        data = await self._get(f"/repos/{repo_full_name}/branches/{branch}")
        sha = ((data.get("commit") or {}).get("sha")) or ""
        if not sha:
            raise GitHubError("无法读取分支最新提交")
        return str(sha)

    @staticmethod
    def parse_repo_url(repo_url: str) -> str | None:
        parsed = parse_github_repo(repo_url)
        return f"{parsed[0]}/{parsed[1]}" if parsed else None
