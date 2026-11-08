from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath

LANGUAGE_BY_EXT = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".rs": "Rust",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".css": "CSS",
    ".scss": "SCSS",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".sql": "SQL",
}

IGNORED_FILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
}
IGNORED_PREFIXES = (
    "dist/",
    "build/",
    "coverage/",
    "node_modules/",
    ".next/",
    ".venv/",
)

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*[\"'][^\"']{12,}[\"']"
    ),
)


def language_for(path: str) -> str | None:
    return LANGUAGE_BY_EXT.get(PurePosixPath(path).suffix.lower())


def should_ignore(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in IGNORED_FILE_NAMES or path.startswith(IGNORED_PREFIXES)


def _iter_added_lines(patch: str | None):
    """从 unified diff 提取新增行及新文件行号。"""
    if not patch:
        return
    new_line = 0
    for raw in patch.splitlines():
        match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if match:
            new_line = int(match.group(1))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            yield new_line, raw[1:]
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        else:
            new_line += 1


def normalize_change_set(
    payload: dict,
    *,
    max_files: int,
    max_patch_chars: int,
) -> tuple[dict, bool]:
    """把 GitHub compare 响应归一化为内部 ChangeSet。"""
    commits = []
    for item in payload.get("commits") or []:
        commit = item.get("commit") or {}
        commits.append(
            {
                "sha": str(item.get("sha") or ""),
                "message": str(commit.get("message") or item.get("message") or "").strip(),
                "author": str((commit.get("author") or {}).get("name") or ""),
            }
        )

    files = []
    truncated = False
    used_patch_chars = 0
    for item in payload.get("files") or []:
        path = str(item.get("filename") or "")
        if not path or should_ignore(path):
            continue
        if len(files) >= max_files or used_patch_chars >= max_patch_chars:
            truncated = True
            break
        patch = item.get("patch")
        if patch:
            remaining = max(0, max_patch_chars - used_patch_chars)
            if len(patch) > remaining:
                patch = patch[:remaining]
                truncated = True
            used_patch_chars += len(patch)
        files.append(
            {
                "path": path,
                "previous_path": item.get("previous_filename"),
                "status": str(item.get("status") or "modified"),
                "additions": int(item.get("additions") or 0),
                "deletions": int(item.get("deletions") or 0),
                "changes": int(item.get("changes") or 0),
                "language": language_for(path),
                "patch": patch,
                "is_binary": bool(item.get("binary")),
            }
        )

    languages = Counter(f["language"] for f in files if f["language"])
    statuses = Counter(f["status"] for f in files)
    stats = {
        "commits": len(commits),
        "files": len(files),
        "additions": sum(f["additions"] for f in files),
        "deletions": sum(f["deletions"] for f in files),
        "languages": dict(languages),
        "statuses": dict(statuses),
        "truncated": truncated,
    }
    return {"commits": commits, "files": files, "stats": stats}, truncated


def scan_secrets(files: list[dict]) -> list[dict]:
    findings: list[dict] = []
    for file in files:
        for line_no, text in _iter_added_lines(file.get("patch")):
            if not any(pattern.search(text) for pattern in SECRET_PATTERNS):
                continue
            findings.append(
                {
                    "severity": "high",
                    "category": "secret",
                    "title": "疑似硬编码凭据",
                    "file": file["path"],
                    "line": line_no,
                    "source": "secret_scan",
                    "evidence": text.strip()[:240],
                    "recommendation": "移除硬编码凭据，改用环境变量或密钥管理，并轮换已暴露凭据。",
                    "confidence": "high",
                }
            )
    return findings


def _module_of(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) >= 3 and parts[0] in {"backend", "frontend", "miniapp"}:
        return "/".join(parts[:3])
    return parts[0] if parts else "root"


def _commit_title(message: str) -> str:
    return message.splitlines()[0].strip() if message else "未提供提交说明"


def build_report(
    change_set: dict,
    *,
    branch: str,
    before_sha: str,
    after_sha: str,
    repo_full_name: str,
    semgrep_findings: list[dict] | None = None,
    semgrep_status: str = "unavailable",
) -> dict:
    commits = change_set["commits"]
    files = change_set["files"]
    stats = change_set["stats"]
    modules = sorted({_module_of(f["path"]) for f in files})

    functional_points = [
        {
            "title": _commit_title(commit["message"]),
            "description": commit["message"] or "无提交说明",
            "files": [],
            "confidence": "medium",
            "evidence": [commit["sha"][:12]] if commit["sha"] else [],
        }
        for commit in commits
    ]

    boundaries = []
    state_files = []
    data_files = []
    for file in files:
        path = file["path"].lower()
        if any(token in path for token in ("/api/", "/router", "/schema", "/contract")):
            boundaries.append(
                {
                    "module": _module_of(file["path"]),
                    "boundary_type": "api",
                    "description": f"接口或契约文件发生 {file['status']} 变更",
                    "evidence": [file["path"]],
                    "confidence": "medium",
                }
            )
        if any(token in path for token in ("state", "store", "hooks", "models/", "migration")):
            state_files.append(file["path"])
        if any(token in path for token in ("schema", "model", "types.ts", "migration")):
            data_files.append(file["path"])

    source_files = [
        f["path"]
        for f in files
        if f["language"]
        and f["status"] != "removed"
        and "/test" not in f["path"].lower()
        and ".test." not in f["path"].lower()
        and ".spec." not in f["path"].lower()
    ]
    test_files = [
        f["path"]
        for f in files
        if "/test" in f["path"].lower()
        or ".test." in f["path"].lower()
        or ".spec." in f["path"].lower()
    ]

    direct_impact = []
    for status, label in (
        ("added", "新增"),
        ("modified", "修改"),
        ("removed", "删除"),
        ("renamed", "重命名"),
    ):
        paths = [f["path"] for f in files if f["status"] == status]
        if paths:
            direct_impact.append(f"{label} {len(paths)} 个文件：{', '.join(paths)}")

    security_findings = scan_secrets(files)
    security_findings.extend(semgrep_findings or [])

    test_gaps = []
    if source_files and not test_files:
        test_gaps.append("本次修改了业务源码，但没有同步修改测试文件。")
    if any("migration" in path.lower() for path in source_files):
        test_gaps.append("包含数据库迁移，需要验证 SQLite 与 PostgreSQL 双路径。")

    state_management = [
        {
            "area": path,
            "mechanism": "状态、模型或迁移相关变更",
            "risk": "需要确认状态转换、持久化和并发行为。",
            "evidence": [path],
            "confidence": "medium",
        }
        for path in state_files
    ]

    report = {
        "schema_version": "1.0",
        "repo_full_name": repo_full_name,
        "branch": branch,
        "before_sha": before_sha,
        "after_sha": after_sha,
        "summary": (
            f"本次推送包含 {stats['commits']} 个提交、{stats['files']} 个文件，"
            f"新增 {stats['additions']} 行、删除 {stats['deletions']} 行。"
        ),
        "change_scale": stats,
        "commits": commits,
        "functional_points": functional_points,
        "modules": modules,
        "boundaries": boundaries,
        "state_management": state_management,
        "data_structures": data_files,
        "impact": {
            "direct": direct_impact,
            "indirect": [],
            "external_contracts": [
                p for p in source_files if any(t in p.lower() for t in ("api/", "client", "contract"))
            ],
            "test_gaps": test_gaps,
        },
        "security_scans": {
            "secret_scan": "completed",
            "semgrep": semgrep_status,
        },
        "security_findings": security_findings,
        "test_gaps": test_gaps,
        "review_checklist": [
            "核对报告中的功能点是否与提交意图一致。",
            "检查接口、状态和数据库迁移的兼容性。",
            "确认安全发现均有处置结论。",
            "确认业务源码变更是否有对应测试。",
        ],
        "unknowns": [],
        "limitations": [
            "V1 以 diff 和提交信息为主要上下文，未建立完整调用图。",
            "Semgrep 不可用时安全结论仅包含 Secret 扫描和启发式规则。",
        ],
    }
    return report


def _severity_name(value: str | None) -> str:
    normalized = str(value or "none").lower()
    if normalized in {"critical"}:
        return "critical"
    if normalized in {"high", "error"}:
        return "high"
    if normalized in {"medium", "warning"}:
        return "medium"
    if normalized in {"low"}:
        return "low"
    return "info"


def risk_summary(report: dict) -> tuple[str, int]:
    rankings = {
        "critical": 5,
        "high": 4,
        "medium": 3,
        "low": 2,
        "info": 1,
        "none": 0,
    }
    findings = report.get("security_findings") or []
    if not findings:
        return "none", 0
    max_name = max(
        (_severity_name(item.get("severity")) for item in findings),
        key=lambda item: rankings[item],
    )
    return max_name, len(findings)


def build_search_text(report: dict) -> str:
    """把可搜索字段压成一段文本，避免列表查询解析 report JSON。"""
    parts: list[str] = [
        str(report.get("repo_full_name") or ""),
        str(report.get("branch") or ""),
        str(report.get("before_sha") or ""),
        str(report.get("after_sha") or ""),
        str(report.get("summary") or ""),
    ]
    for commit in report.get("commits") or []:
        parts.extend(
            [
                str(commit.get("sha") or ""),
                str(commit.get("message") or ""),
                str(commit.get("author") or ""),
            ]
        )
    for point in report.get("functional_points") or []:
        parts.extend(
            [
                str(point.get("title") or ""),
                str(point.get("description") or ""),
                *map(str, point.get("files") or []),
            ]
        )
    for boundary in report.get("boundaries") or []:
        parts.extend(
            [
                str(boundary.get("module") or ""),
                str(boundary.get("boundary_type") or ""),
                str(boundary.get("description") or ""),
                *map(str, boundary.get("evidence") or []),
            ]
        )
    for state in report.get("state_management") or []:
        parts.extend(
            [
                str(state.get("area") or ""),
                str(state.get("mechanism") or ""),
                str(state.get("risk") or ""),
                *map(str, state.get("evidence") or []),
            ]
        )
    parts.extend(map(str, report.get("modules") or []))
    parts.extend(map(str, report.get("data_structures") or []))
    impact = report.get("impact") or {}
    for key in ("direct", "indirect", "external_contracts", "test_gaps"):
        parts.extend(map(str, impact.get(key) or []))
    for finding in report.get("security_findings") or []:
        parts.extend(
            [
                str(finding.get("title") or ""),
                str(finding.get("file") or ""),
                str(finding.get("evidence") or ""),
                str(finding.get("recommendation") or ""),
                str(finding.get("source") or ""),
            ]
        )
    parts.extend(map(str, report.get("test_gaps") or []))
    parts.extend(map(str, report.get("review_checklist") or []))
    return "\n".join(part for part in parts if part).strip()


def render_markdown(report: dict) -> str:
    scale = report["change_scale"]
    lines = [
        f"# 代码分析报告 · {report['branch']}",
        "",
        report["summary"],
        "",
        "## 变更概览",
        "",
        f"- 提交：{scale['commits']}",
        f"- 文件：{scale['files']}",
        f"- 新增：{scale['additions']} 行",
        f"- 删除：{scale['deletions']} 行",
        f"- 语言：{', '.join(f'{k} {v}' for k, v in (scale.get('languages') or {}).items()) or '未识别'}",
        "",
        "## 功能点",
        "",
    ]
    for item in report["functional_points"]:
        lines.append(f"- **{item['title']}**：{item['description']}")
    lines.extend(["", "## 影响范围", ""])
    for item in report["impact"]["direct"]:
        lines.append(f"- {item}")
    lines.extend(["", "## 安全发现", ""])
    if report["security_findings"]:
        for finding in report["security_findings"]:
            lines.append(
                f"- **{finding['severity']} · {finding['title']}** "
                f"`{finding.get('file')}:{finding.get('line')}`"
            )
    else:
        lines.append("- 未发现确定性命中项；这不代表代码绝对安全。")
    lines.extend(["", "## 测试缺口", ""])
    for item in report["test_gaps"]:
        lines.append(f"- {item}")
    if not report["test_gaps"]:
        lines.append("- 未检测到明显测试缺口。")
    lines.extend(["", "## 人工复核清单", ""])
    for item in report["review_checklist"]:
        lines.append(f"- {item}")
    return "\n".join(lines)
