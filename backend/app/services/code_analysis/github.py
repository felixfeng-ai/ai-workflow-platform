from __future__ import annotations

from urllib.parse import unquote, urlsplit

import httpx

from ...config import settings
from ..deploy import parse_github_repo

GITHUB_TIMEOUT = 20.0


class GitHubError(RuntimeError):
    pass


def normalize_github_source_path(value: str | None) -> str | None:
    """把用户填写的目录归一成仓库内 Posix 相对路径。"""
    if not value or not value.strip():
        return None
    decoded = unquote(value.strip()).replace("\\", "/")
    parts = [part for part in decoded.strip("/").split("/") if part not in {"", "."}]
    if any(part == ".." or "\x00" in part for part in parts):
        raise ValueError("代码目录不能包含 .. 或空字符")
    return "/".join(parts) or None


def parse_github_source_path(repo_url: str, default_branch: str) -> str | None:
    """从 GitHub tree/blob 页面链接提取仓库内代码目录。

    GitHub 链接不显式区分分支名和目录名；优先匹配仓库默认分支，
    非默认分支的普通单段名称则按第一段处理。含斜杠的非默认分支可在
    表单中显式填写目录，避免歧义。
    """
    parsed = urlsplit(repo_url.strip())
    if (parsed.hostname or "").lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 4 or parts[2] not in {"tree", "blob"}:
        return None

    remainder = parts[3:]
    branch_parts = [part for part in default_branch.strip("/").split("/") if part]
    if branch_parts and remainder[: len(branch_parts)] == branch_parts:
        remainder = remainder[len(branch_parts) :]
    else:
        remainder = remainder[1:]
    if parts[2] == "blob" and remainder:
        remainder = remainder[:-1]
    return normalize_github_source_path("/".join(remainder))


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
