"""LangGraph 检查点表：图状态持久化的落库形态。

**为什么不直接用官方 `langgraph-checkpoint-postgres`？**

两个理由，都是这个项目的硬约束逼出来的：

1. **「Alembic 是唯一建表来源」** —— 官方 saver 的建表方式是运行时调 `.setup()`，
   由它自己 `CREATE TABLE IF NOT EXISTS`。这等于在应用代码里开了第二处 DDL 来源，
   与项目的硬性不变量正面冲突。要用它就得写一条 Alembic 迁移把它的 DDL 抄一遍 ——
   那已经是「自己维护这套表结构」了，不如直接自己实现。
2. **测试跑 SQLite、生产跑 PostgreSQL** —— 官方 PG saver 在测试里用不了，
   只能退回 MemorySaver，于是「测试验的」和「线上跑的」是两套持久化路径。
   自研走 SQLAlchemy，两边同一份代码，测试真的在验生产路径。

代价是 `BaseCheckpointSaver` 的接口要自己实现（本模块 + checkpointer.py），
且要跟住 LangGraph 的 checkpoint 格式版本（`checkpoint["v"]`）。
换来的是：表结构、租户列、清理策略全部在自己手里。

**为什么 `thread_id` 不建到 workflow_runs 的外键？**

本平台里 thread_id 恒等于 workflow run id（见 `app/workflows/graph.py` 的 `thread_id_for`），
加外键确实能白拿级联删除。但那样「LangGraph 的存储」就被钉死在「工作流运行」这一个
语义上 —— 之后想给副驾多轮对话也开线程，就得改表。这里用 `tenant_id` 列做隔离与清理
锚点，删除工作流时由端点按 thread 显式清理（见 `app/llm/checkpointer.py` 的 `delete_threads`）。
"""

from sqlalchemy import Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class LangGraphCheckpoint(Base, TimestampMixin):
    """一次图状态快照。

    三元组 (thread_id, checkpoint_ns, checkpoint_id) 是主键：thread 是一条执行线程，
    ns 供子图使用（本平台全部为 ""），checkpoint_id 是单调递增的 uuid6。

    刻意**不额外建索引**：主键复合索引 (thread_id, checkpoint_ns, checkpoint_id)
    已经覆盖了 alist 的唯一查询形态（同 thread 同 ns 按 checkpoint_id 倒序取最近一条），
    反向扫描即可，再加一条同前缀的索引纯属写放大。

    checkpoint / metadata 存序列化后的二进制（`serde.dumps_typed` 的产物），
    用 LargeBinary 而不是 JSON 列 —— 状态里可以塞任意 Python 对象，
    msgpack 序列化结果不保证是合法 UTF-8，走 JSON 列会在入库时炸。
    """

    __tablename__ = "langgraph_checkpoints"

    thread_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(120), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(72), nullable=True)
    # 隔离锚点：在构造 saver 时注入（见 checkpointer.py 的构造函数）
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, default="default")
    # serde 的类型标记（"msgpack" / "json"），loads_typed 靠它挑反序列化器。
    # checkpoint 与 metadata 各存一份：dumps_typed 的返回值是 (类型, 字节) 二元组，
    # 同一对象在不同内容下可能选不同编码（jsonplus 对纯 JSON 用 "json"，
    # 遇到 bytes/set 之类退回 "msgpack"），共用一个类型列会在两者编码不同时解错。
    type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    checkpoint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    metadata_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    metadata_: Mapped[bytes] = mapped_column("metadata", LargeBinary, nullable=False)


class LangGraphWrite(Base, TimestampMixin):
    """挂起写入（pending writes）。

    一个 super-step 里各节点产生的状态更新先落这里，等该步 checkpoint 落定后才合并
    进主状态。中断恢复、并行分支的部分完成状态都靠它 —— 少了这张表，图跑到一半崩掉
    就无法知道「哪几个并行分支已经写完了」，只能整段重跑。
    """

    __tablename__ = "langgraph_checkpoint_writes"

    thread_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(120), primary_key=True, default="")
    checkpoint_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # 任务在子图里的路径（本平台不使用子图，恒为 ""）
    task_path: Mapped[str] = mapped_column(String(240), default="")
