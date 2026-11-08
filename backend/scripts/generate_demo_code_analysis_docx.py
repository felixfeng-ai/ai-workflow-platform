"""生成前端演示模式使用的代码分析报告样例。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.code_analysis.docx_export import build_code_analysis_docx


REPORT = {
    "schema_version": "1.0",
    "repo_full_name": "Drir1203/ai-workflow-platform",
    "branch": "feature/code-analysis",
    "before_sha": "1111111111111111111111111111111111111111",
    "after_sha": "2222222222222222222222222222222222222222",
    "summary": "本次推送新增代码分析后台链路、GitHub Webhook 验签、结构化报告生成与项目页入口。",
    "change_scale": {
        "commits": 2,
        "files": 9,
        "additions": 286,
        "deletions": 34,
        "languages": {"Python": 5, "TypeScript": 3, "YAML": 1},
        "statuses": {"added": 3, "modified": 5, "renamed": 1},
        "truncated": False,
    },
    "commits": [
        {
            "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "message": "feat: add code analysis background runner",
            "author": "林",
        },
        {
            "sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "message": "feat: show structured report in project page",
            "author": "林",
        },
    ],
    "functional_points": [
        {
            "title": "新增代码分析后台任务",
            "description": "接收 push 范围，拉取 GitHub Compare API，并生成结构化分析报告。",
            "files": ["backend/app/services/code_analysis/runner.py"],
            "confidence": "high",
        },
        {
            "title": "项目页代码分析入口",
            "description": "展示仓库连接状态、历史报告列表和报告详情。",
            "files": ["frontend/src/pages/CodeAnalysisTab.tsx"],
            "confidence": "high",
        },
    ],
    "modules": ["backend/app/api", "backend/app/services", "frontend/src/pages"],
    "boundaries": [
        {
            "module": "backend/app/api",
            "boundary_type": "api",
            "description": "Webhook 使用独立公开入口、HMAC 验签和 Delivery 去重。",
            "evidence": ["backend/app/api/github_webhooks.py"],
            "confidence": "high",
        },
        {
            "module": "backend/app/services",
            "boundary_type": "service",
            "description": "GitHub 拉取、报告分析和 Word 导出拆分为独立服务。",
            "evidence": ["backend/app/services/code_analysis"],
            "confidence": "high",
        },
    ],
    "state_management": [
        {
            "area": "code_analysis_runs",
            "mechanism": "数据库状态机",
            "risk": "服务重启可能留下 running 任务，需要恢复扫描。",
            "evidence": ["backend/app/models/code_analysis.py"],
            "confidence": "high",
        }
    ],
    "data_structures": ["project_repo_connections", "code_analysis_runs"],
    "impact": {
        "direct": ["新增 3 个文件", "修改 5 个文件", "重命名 1 个文件"],
        "indirect": ["通知类型新增 code_analysis", "项目页增加代码分析 Tab"],
        "external_contracts": ["GitHub push Webhook"],
        "test_gaps": ["还需要真实 GitHub 私有仓库联调。"],
    },
    "security_scans": {"secret_scan": "completed", "semgrep": "completed"},
    "security_findings": [
        {
            "severity": "medium",
            "category": "sast",
            "title": "Webhook 日志可能包含敏感请求数据",
            "file": "backend/app/api/github_webhooks.py",
            "line": 42,
            "source": "semgrep",
            "evidence": "logger.info(request.body)",
            "recommendation": "只记录 Delivery ID 和事件类型，不记录原始 body。",
            "confidence": "high",
        }
    ],
    "test_gaps": ["Force Push 和新分支 before 为空尚未覆盖真实仓库。"],
    "review_checklist": [
        "核对 Webhook 签名和 Delivery 去重。",
        "验证跨租户无法读取连接和报告。",
        "确认失败通知不会影响报告落库。",
    ],
    "unknowns": ["尚未验证超大仓库的 Compare API 截断行为。"],
    "limitations": ["V1 未建立完整调用图，影响范围部分为启发式结果。"],
}


def main() -> None:
    output = ROOT / "frontend" / "public" / "demo" / "code-analysis-sample.docx"
    output.parent.mkdir(parents=True, exist_ok=True)
    content = build_code_analysis_docx(
        REPORT,
        project_name="雅秩 平台",
        status="succeeded",
        created_at=datetime(2026, 11, 9, 9, 24),
    )
    output.write_bytes(content)
    print(output)


if __name__ == "__main__":
    main()
