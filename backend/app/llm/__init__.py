"""LangChain / LangGraph 适配层。

这一层只做「把本项目已有抽象接到框架上」，不承载业务：
- `chat_model`  —— `AiEngine` → `BaseChatModel`（保住 Dify / OpenAI 兼容端点的可替换性）
- `checkpointer` —— LangGraph 状态持久化 → 本项目自己的表

业务侧的编排逻辑在 `app/workflows/graph.py`。
"""

from .chat_model import AiEngineChatModel
from .checkpointer import SqlAlchemyCheckpointer, delete_threads

__all__ = ["AiEngineChatModel", "SqlAlchemyCheckpointer", "delete_threads"]
