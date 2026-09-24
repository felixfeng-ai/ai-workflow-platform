"""步骤模板渲染：把 `{{prev_output}}` / `{{step.N.output}}` 替换成上游步骤的真实输出。

独立成模块（而不是留在 executor 里）是为了让依赖方向单向：
    templates ← conditions ← graph ← executor
条件求值也要读上游输出，若把渲染留在 executor，conditions 就得反向 import executor 成环。
executor 仍 re-export `interpolate`，存量测试与调用方不受影响。
"""

from __future__ import annotations

import re
from typing import Any

# 占位符语法：{{ prev_output }} / {{ step.0.output }}
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(prev_output|step\.(\d+)\.output)\s*\}\}")


def _lookup(token: str, index: int | None, results: list[dict]) -> str | None:
    """单个占位符取值；无对应上游步骤时返回 None（与「空串」区分，见 resolve）。"""
    if token == "prev_output":
        return results[-1].get("output") if results else None
    if index is None:
        return None
    if 0 <= index < len(results):
        return results[index].get("output")
    return None


def render(value: Any, results: list[dict]) -> Any:
    """递归替换字符串模板，dict/list 逐层下钻。

    历史行为（与重构前逐字一致）：占位符解析不到时替换为空串，而不是保留原样 ——
    保留原样会把 `{{prev_output}}` 字面量喂给大模型，比空串更容易诱导出胡编内容。
    """
    if isinstance(value, str):
        return _PLACEHOLDER_RE.sub(lambda m: _lookup(m.group(1), _idx(m), results) or "", value)
    if isinstance(value, dict):
        return {k: render(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, results) for v in value]
    return value


def _idx(match: re.Match[str]) -> int | None:
    return int(match.group(2)) if match.group(2) is not None else None


def resolve(value: Any, results: list[dict]) -> Any:
    """取值语义的渲染：整个字符串就是一个占位符时返回**原始值**，否则返回渲染后的字符串。

    条件求值必须走这条路径：`{{step.0.output}}` 如果先被渲染成 str，下游再想按数字比较
    就只剩字符串了；而 `resolve` 保留原类型，`gt` / `lt` 才能拿到真正的 number。
    非字符串输入原样返回（条件右值允许直接写字面量数字）。
    """
    if isinstance(value, str):
        match = _PLACEHOLDER_RE.fullmatch(value.strip())
        if match:
            return _lookup(match.group(1), _idx(match), results)
        return render(value, results)
    return value


def run_context(results: list[dict]) -> dict[str, Any]:
    """条件求值上下文：暴露给「为什么这个分支没走」的可观测性，也是条件 DSL 的取值来源。"""
    return {"prev_output": results[-1].get("output") if results else None, "steps": results}
