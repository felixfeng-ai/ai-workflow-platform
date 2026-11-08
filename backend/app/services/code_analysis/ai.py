from __future__ import annotations

import asyncio
import json
import re

from ...ai import get_ai_engine
from ...ai.errors import AiEngineUnavailable
from ...config import settings

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _compact_change_set(change_set: dict) -> str:
    parts = ["COMMITS:"]
    for commit in change_set["commits"]:
        parts.append(f"- {commit['sha'][:12]} {commit['message'][:500]}")
    parts.append("\nFILES AND PATCHES:")
    used = 0
    for file in change_set["files"]:
        block = (
            f"\n### {file['path']} ({file['status']}) +{file['additions']}/-{file['deletions']}\n"
            f"{file.get('patch') or '[no patch]'}"
        )
        if used + len(block) > settings.code_analysis_ai_max_chars:
            parts.append("\n[context truncated]")
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)


async def enrich_with_ai(
    *, change_set: dict, report: dict, user_id: str
) -> tuple[dict | None, str | None, str | None]:
    """AI 只补充解释性字段；失败时确定性报告仍可独立成立。"""
    if not settings.code_analysis_ai_enabled:
        return None, None, None
    prompt = f"""你是代码变更审查助手。请只根据给定 diff 输出一个 JSON 对象，不要 Markdown 代码围栏。

必须包含字段：
- summary: 字符串
- functional_points: 数组，元素含 title, description, files, confidence
- boundaries: 数组，元素含 module, boundary_type, description, evidence, confidence
- state_management: 数组，元素含 area, mechanism, risk, evidence, confidence
- impact: 对象，含 direct, indirect, external_contracts, test_gaps
- security_findings: 数组，元素含 severity, category, title, file, line, source, evidence, recommendation, confidence
- test_gaps: 字符串数组
- review_checklist: 字符串数组
- unknowns: 字符串数组

规则：
1. 不能编造不存在的文件或行为。
2. 证据不足时写入 unknowns，并降低 confidence。
3. AI 安全判断 source 必须为 ai。
4. 只输出 JSON。

确定性统计：
{json.dumps(report['change_scale'], ensure_ascii=False)}

变更：
{_compact_change_set(change_set)}
"""
    try:
        engine = get_ai_engine()
        raw = await asyncio.wait_for(
            engine.chat(prompt, user=user_id),
            timeout=settings.code_analysis_timeout,
        )
    except AiEngineUnavailable:
        return None, None, None
    except Exception:
        return None, None, None

    match = _JSON_RE.search(raw)
    if not match:
        return None, settings.ai_provider, None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, settings.ai_provider, None
    if not isinstance(data, dict):
        return None, settings.ai_provider, None
    model = settings.openai_compatible_model if settings.ai_provider == "openai_compatible" else None
    return data, settings.ai_provider, model


def merge_ai_report(report: dict, ai: dict) -> dict:
    merged = dict(report)
    for key in (
        "summary",
        "functional_points",
        "boundaries",
        "state_management",
        "test_gaps",
        "review_checklist",
        "unknowns",
    ):
        value = ai.get(key)
        if value:
            merged[key] = value

    impact = ai.get("impact")
    if isinstance(impact, dict):
        merged["impact"] = {**report["impact"], **impact}

    ai_findings = ai.get("security_findings")
    if isinstance(ai_findings, list):
        normalized = []
        for finding in ai_findings:
            if not isinstance(finding, dict):
                continue
            normalized.append(
                {
                    **finding,
                    "source": "ai",
                    "confidence": finding.get("confidence") or "low",
                }
            )
        merged["security_findings"] = report["security_findings"] + normalized
    return merged
