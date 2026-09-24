"""把既有的 `AiEngine` Protocol 适配成 LangChain 的 `BaseChatModel`。

**为什么是适配器，而不是直接用 `langchain_openai.ChatOpenAI`？**

本项目最大的可替换性卖点是「AI 引擎可在 Dify / OpenAI 兼容端点之间平替」，这个选择
收敛在 `app/ai/` 一层（`get_ai_engine()` 按配置切换）。直接用 `ChatOpenAI` 会把
「走哪个后端」这件事泄漏到每一个 Agent 和每个工作流节点里，等于把已有的抽象层作废；
而且 Dify 的知识库检索、会话变量这些能力在 `ChatOpenAI` 里根本没有对应物。

所以这里做的是**反向适配**：LangChain 侧看到的是一个标准 `BaseChatModel`（于是能拿到
回调、token 流、未来可接 LangSmith / 结构化输出），底层仍然落到 `AiEngine` 上。
代价是放弃了 LangChain 生态里依赖 OpenAI 私有字段（tool_calls 协议、response_format
透传等）的那部分能力 —— 本项目用不到，值得换。

**为什么 `_generate`（同步）直接抛错？**

`AiEngine` 只有异步接口（Dify 与 OpenAI 兼容端点都是 httpx 异步客户端）。同步路径要
么另起线程池跑 event loop，要么再写一套同步客户端，两者都是为了「让用不到的路径看起来
能用」。图执行全程走 `ainvoke` / `astream`，同步路径干脆显式失败，比静默降级好排查。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

# LangChain 的 message.type → OpenAI 风格的 role。AiEngine.stream_chat / Dify 都吃 OpenAI 形状。
_ROLE_MAP = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def content_text(content: Any) -> str:
    """消息 content 可能是 str，也可能是内容块列表（多模态写法），统一取纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    return "" if content is None else str(content)


def to_engine_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """转成 AiEngine.stream_chat 期望的 [{"role","content"}, …]。"""
    return [
        {"role": _ROLE_MAP.get(m.type, "user"), "content": content_text(m.content)} for m in messages
    ]


def to_engine_query(messages: list[BaseMessage]) -> str:
    """转成 AiEngine.chat 期望的单个 query 字符串。

    单条消息直接取其内容 —— 这是存量 Agent 的唯一形态（一次 prompt 一次调用），
    必须与改造前 `engine.chat(prompt)` 逐字一致，否则提示词会多出前缀。
    多条消息（含 system）按出现顺序用空行拼接：`chat()` 这一层没有角色概念，
    与其自造一个「system: xxx」前缀格式（下游 Dify 未必认）不如老实平铺。
    """
    if not messages:
        return ""
    if len(messages) == 1:
        return content_text(messages[0].content)
    return "\n\n".join(content_text(m.content) for m in messages)


class AiEngineChatModel(BaseChatModel):
    """LangChain 侧的模型门面，实际调用落到 AiEngine。

    engine / user_id 用 Any 声明是为了绕开 pydantic 校验：AiEngine 是 Protocol，
    而本项目测试里注入的是鸭子类型的假引擎（见 tests/conftest.py 的 fake engine）。
    """

    engine: Any = None
    user_id: str = "unknown"

    @property
    def _llm_type(self) -> str:
        return "ai-engine"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("AiEngine 只有异步接口，请走 ainvoke / astream")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = await self.engine.chat(to_engine_query(messages), user=self.user_id)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        # 空串 chunk 直接丢掉：底层 SSE 会吐 keep-alive 空行，原样透传会让下游
        # 收到一堆空 token（前端表现为光标闪但不前进）。这层过滤在 HTTP 客户端里
        # 没有做，因为那是传输层语义，而「空增量算不算一次产出」是模型层语义。
        async for piece in self.engine.stream_chat(
            to_engine_messages(messages), user=self.user_id
        ):
            if piece:
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
