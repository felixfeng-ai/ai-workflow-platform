"""分支条件：工作流画布上「这条边什么时候走」的判定。

**为什么是一门结构化 DSL，而不是一个 Python 表达式字符串？**

直觉做法是让用户在边上写 `"风险" in {{prev_output}}`，后端 eval 求值。这在
「AI 生成的编排 JSON + 多租户 SaaS」的组合下是不能接受的：`workflow.steps/edges`
由登录用户提交并原样落库，eval 一下等于把服务端任意代码执行权交出去，而这份 JSON
还会被定时调度器在无人值守时自动重放。同理，任何自研的「表达式解析器」也只是把
注入面从 eval 挪到自己写的 parser 上，收益不正比于成本。

结构化 DSL 把「能表达什么」事先钉死成一份 op 白名单：没有属性访问、没有函数调用、
没有下标，求值过程不碰 Python 运行时。代价是表达力受限（写不出 `a and (b or c)` 之外
的花活），而这类平台里条件本来就是「上一步输出里有没有 XX」这种量级的判断。

**为什么求值失败要抛错、而不是当成 False 跳过？**

条件写错（比如对一段散文用 `gt 100`）时，静默返回 False 会让流程悄悄走另一条分支 ——
用户看到的是「工作流成功了，但结果不对」，这比失败难查得多。定时任务在凌晨跑完，
更是没人盯着。所以：结构性错误（未知 op、缺字段）在**保存时**由 validate_condition 拦下，
运行时的类型不匹配一律抛 ConditionError 让整个 run 失败并留下 error 文本。
"""

from __future__ import annotations

from typing import Any

from .templates import resolve

# op 白名单：文本 / 空值 / 数值比较 / 布尔组合，共 4 组
_TEXT_OPS = {"contains", "not_contains", "starts_with", "ends_with"}
_EQUALITY_OPS = {"eq", "ne"}
_EMPTINESS_OPS = {"is_empty", "not_empty"}
_NUMERIC_OPS = {"gt", "gte", "lt", "lte"}
_LOGIC_OPS = {"all", "any", "not"}

ALL_OPS = _TEXT_OPS | _EQUALITY_OPS | _EMPTINESS_OPS | _NUMERIC_OPS | _LOGIC_OPS
# 需要 right 的 op（其余只用 left）；组合 op 用 of 而非 left/right
_BINARY_OPS = _TEXT_OPS | _EQUALITY_OPS
# 组合 op 最多嵌套的子条件数：防止用户（或 AI 生成的编排）塞一棵深树把求值拖爆
_MAX_DEPTH = 6


class ConditionError(ValueError):
    """条件结构非法或运行时无法求值。"""


def _check_depth(condition: dict, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise ConditionError(f"条件嵌套超过 {_MAX_DEPTH} 层")


def validate_condition(condition: Any, depth: int = 0) -> None:
    """保存时校验结构：op 在白名单内、必填字段齐全、子条件递归合法。

    保存端点调用它把「能拦的错误拦在最前面」——写错条件的人在界面上就能看到报错，
    而不是等到定时任务凌晨跑挂。
    """
    _check_depth(condition, depth)
    if not isinstance(condition, dict):
        raise ConditionError("条件必须是对象")
    op = condition.get("op")
    if op not in ALL_OPS:
        raise ConditionError(f"未知条件类型: {op!r}")

    if op in _LOGIC_OPS:
        if op == "not":
            sub = condition.get("of")
            if isinstance(sub, dict):
                sub = [sub]
            if not isinstance(sub, list) or len(sub) != 1:
                raise ConditionError("not 需要恰好一个子条件（of）")
            validate_condition(sub[0], depth + 1)
            return
        subs = condition.get("of")
        if not isinstance(subs, list) or not subs:
            raise ConditionError(f"{op} 需要非空的子条件列表（of）")
        for s in subs:
            validate_condition(s, depth + 1)
        return

    if "left" not in condition:
        raise ConditionError(f"{op} 缺少 left")
    if op in _BINARY_OPS and "right" not in condition:
        raise ConditionError(f"{op} 缺少 right")
    if not isinstance(condition.get("left"), str):
        raise ConditionError("left 必须是字符串模板（如 {{prev_output}}）")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ConditionError("布尔值不能参与文本比较")
    if isinstance(value, (int, float)):
        return str(value)
    # list/dict 等（比如上游步骤输出被渲染成了结构）—— 直接拒绝，避免 str() 出一坨
    raise ConditionError(f"不支持的类型参与条件比较: {type(value).__name__}")


def _as_number(value: Any, side: str) -> float:
    # bool 是 int 子类，先拦下：True > 0 静默成立会掩盖写错的参数
    if isinstance(value, bool):
        raise ConditionError(f"{side} 需要数字，收到布尔值")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            raise ConditionError(f"{side} 需要数字，收到 {value[:40]!r}") from None
    raise ConditionError(f"{side} 需要数字，收到 {type(value).__name__}")


def evaluate(condition: dict, results: list[dict]) -> bool:
    """对当前已完成的步骤结果求值。results 为 [{label, agent_key, output}, …]。"""
    op = (condition or {}).get("op")
    if op not in ALL_OPS:
        raise ConditionError(f"未知条件类型: {op!r}")

    if op == "all":
        return all(evaluate(c, results) for c in condition["of"])
    if op == "any":
        return any(evaluate(c, results) for c in condition["of"])
    if op == "not":
        sub = condition["of"]
        if isinstance(sub, dict):
            sub = [sub]
        return not evaluate(sub[0], results)

    left = resolve(condition.get("left"), results)

    if op in _EMPTINESS_OPS:
        empty = left is None or (isinstance(left, str) and left.strip() == "")
        return empty if op == "is_empty" else not empty

    if op in _NUMERIC_OPS:
        lv = _as_number(left, "left")
        rv = _as_number(condition.get("right"), "right")
        return {
            "gt": lv > rv,
            "gte": lv >= rv,
            "lt": lv < rv,
            "lte": lv <= rv,
        }[op]

    # 文本比较：right 一律按字面量处理（不做模板渲染）——右值写成模板容易与
    # 左值渲染结果混淆，且「拿上游输出当关键词」没有真实场景，留白比留坑好
    lt = _as_text(left)
    rt = _as_text(condition.get("right"))
    if op == "contains":
        return rt in lt
    if op == "not_contains":
        return rt not in lt
    if op == "starts_with":
        return lt.startswith(rt)
    if op == "ends_with":
        return lt.endswith(rt)
    if op == "eq":
        return lt == rt
    if op == "ne":
        return lt != rt
    raise ConditionError(f"未知条件类型: {op!r}")  # pragma: no cover - 白名单已穷尽
