from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CodeAnalysisRun
from .report import build_search_text, risk_summary


async def backfill_code_analysis_metadata(db: AsyncSession) -> int:
    """回填旧报告的搜索文本和风险摘要。

    只在 search_text 为空时处理；正常新报告完成后已由 runner 写入。
    """
    result = await db.execute(
        select(CodeAnalysisRun).where(
            CodeAnalysisRun.report.is_not(None),
            CodeAnalysisRun.search_text == "",
        )
    )
    updated = 0
    for run in result.scalars().all():
        report = run.report
        if not isinstance(report, dict):
            continue
        run.search_text = build_search_text(report)
        run.max_severity, run.finding_count = risk_summary(report)
        updated += 1
    if updated:
        await db.flush()
    return updated
