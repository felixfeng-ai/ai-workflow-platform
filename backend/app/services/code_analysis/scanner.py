from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from ...config import settings
from .report import _iter_added_lines

SEMGREP_RULES = Path(__file__).with_name("semgrep_rules.yml")


async def run_semgrep(files: list[dict]) -> tuple[list[dict], str]:
    """扫描 diff 中新增的文本行。

    V1 没有完整仓库快照，因此只把新增行写入临时文件做本地规则扫描。
    这比伪造“全仓扫描”更诚实，也足以发现高危模式。Semgrep 未安装时返回 unavailable。
    """
    executable = shutil.which(settings.semgrep_command)
    if not executable:
        return [], "unavailable"

    with tempfile.TemporaryDirectory(prefix="veyawork-semgrep-") as tmp:
        root = Path(tmp)
        scanned = 0
        line_maps: dict[str, list[int]] = {}
        for file in files:
            patch = file.get("patch")
            if not patch:
                continue
            added = list(_iter_added_lines(patch))
            if not added:
                continue
            target = root / file["path"]
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("\n".join(text for _, text in added), encoding="utf-8")
            except OSError:
                continue
            line_maps[file["path"]] = [line_no for line_no, _ in added]
            scanned += 1
        if scanned == 0:
            return [], "completed"

        proc = await asyncio.create_subprocess_exec(
            executable,
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
            "--config",
            str(SEMGREP_RULES),
            str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                proc.communicate(), timeout=min(settings.code_analysis_timeout, 90)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return [], "timeout"

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        return [], "error"

    findings = []
    for result in payload.get("results") or []:
        relative = str(result.get("path") or "").replace(str(Path(tmp)), "").lstrip("/\\")
        relative = relative.replace("\\", "/")
        start = int((result.get("start") or {}).get("line") or 1)
        mapped = line_maps.get(relative)
        if mapped and 1 <= start <= len(mapped):
            start = mapped[start - 1]
        extra = result.get("extra") or {}
        findings.append(
            {
                "severity": str(extra.get("severity") or "warning").lower(),
                "category": "sast",
                "title": str(extra.get("message") or result.get("check_id") or "Semgrep finding"),
                "file": relative,
                "line": start,
                "source": "semgrep",
                "evidence": str(extra.get("lines") or "").strip()[:240],
                "recommendation": str(extra.get("message") or "请结合上下文复核该风险。"),
                "confidence": "high",
                "rule_id": result.get("check_id"),
            }
        )
    return findings, "completed"
