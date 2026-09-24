"""自研 SQLAlchemy Checkpointer：把 LangGraph 的图状态存进本项目自己的表。

表结构见 `app/models/checkpoint.py`（由 Alembic 迁移创建）。这里只负责读写，
不做任何 DDL —— 「Alembic 是唯一建表来源」是项目的硬性不变量。

**为什么每个方法各自开一个 session，而不是共用一个长会话？**

checkpointer 的调用点分布在 super-step 边界上，而节点执行期间另有自己的短会话。
共用一个长会话有两个问题：一是 SQLite 上长事务会挡住节点会话的写（见
app/workflows/graph.py 的并发说明），二是 LangGraph 内部会并发调用 aput_writes
（多个并行任务各写各的），而 AsyncSession 不是并发安全的。自开会话让每次调用
天然隔离，代价是连接开销 —— 相对一次 LLM 调用的耗时可以忽略。

**为什么按 checkpoint_id 倒序就是「最近一条」？**

LangGraph 的 checkpoint id 由 `get_next_version` 生成，形态是
`{递增计数:032}.{随机后缀:016}`（前导零定宽），所以字符串字典序 == 时间序。
这正是「同 thread 同 ns 取最近一条」可以直接 `ORDER BY checkpoint_id DESC LIMIT 1`
而不额外加时间列索引的原因（复合主键的反向扫描就够）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.base import WRITES_IDX_MAP
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.checkpoint import LangGraphCheckpoint, LangGraphWrite

DEFAULT_CHECKPOINT_NS = ""


def _configurable(config: dict) -> dict:
    return (config or {}).get("configurable") or {}


class SqlAlchemyCheckpointer(BaseCheckpointSaver[str]):
    """LangGraph 状态持久化，落 SQLite / PostgreSQL 均可。

    tenant_id 走构造函数而不是 config：config 在 LangGraph 内部流转时会被重建
    （aput 的返回值会成为下一次调用的基底），把租户挂在 config 上等于依赖一个
    不受本模块控制的传递链。每个 run 本来就是单租户的，构造时一次性绑定最稳。
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: str = "default",
        serde: Any = None,
    ) -> None:
        super().__init__(serde=serde)
        self.session_factory = session_factory
        self.tenant_id = tenant_id

    # ------------------------------------------------------------ 读

    async def aget_tuple(self, config: dict) -> CheckpointTuple | None:
        conf = _configurable(config)
        thread_id = conf.get("thread_id")
        if not thread_id:
            return None
        checkpoint_ns = conf.get("checkpoint_ns") or DEFAULT_CHECKPOINT_NS
        checkpoint_id = conf.get("checkpoint_id")

        async with self.session_factory() as db:
            if checkpoint_id:
                row = await db.get(
                    LangGraphCheckpoint, (thread_id, checkpoint_ns, checkpoint_id)
                )
            else:
                row = (
                    await db.execute(
                        select(LangGraphCheckpoint)
                        .where(
                            LangGraphCheckpoint.thread_id == thread_id,
                            LangGraphCheckpoint.checkpoint_ns == checkpoint_ns,
                        )
                        .order_by(LangGraphCheckpoint.checkpoint_id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if row is None:
                return None
            writes = await self._load_writes(db, thread_id, checkpoint_ns, [row.checkpoint_id])
        return self._to_tuple(row, writes.get(row.checkpoint_id, []))

    async def alist(
        self,
        config: dict | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """按 checkpoint_id 倒序遍历历史。config 为 None 时跨线程遍历（管理用途）。

        每页的 pending writes 用一条 IN 查询批量取回，避免逐条 checkpoint 查一次
        （历史回看是「一屏 N 条」的读放大场景）。
        """
        conf = _configurable(config)
        thread_id = conf.get("thread_id")
        checkpoint_ns = conf.get("checkpoint_ns") or DEFAULT_CHECKPOINT_NS
        before_id = _configurable(before).get("checkpoint_id") if before else None

        stmt = select(LangGraphCheckpoint)
        if thread_id:
            stmt = stmt.where(LangGraphCheckpoint.thread_id == thread_id)
        if config is not None and thread_id:
            stmt = stmt.where(LangGraphCheckpoint.checkpoint_ns == checkpoint_ns)
        if before_id:
            stmt = stmt.where(LangGraphCheckpoint.checkpoint_id < before_id)
        stmt = stmt.order_by(
            LangGraphCheckpoint.thread_id,
            LangGraphCheckpoint.checkpoint_ns,
            LangGraphCheckpoint.checkpoint_id.desc(),
        )
        # limit 只在无 filter 时下推到 SQL：filter 走 metadata 反序列化后才判定，
        # 下推会把「前 N 条里没有匹配的」错当成「没有匹配的」
        if limit and not filter:
            stmt = stmt.limit(limit)

        async with self.session_factory() as db:
            rows = list((await db.execute(stmt)).scalars().all())
            if filter:
                rows = [
                    r for r in rows if self._metadata_matches(self._meta_of(r), filter)
                ]
            if limit:
                rows = rows[:limit]
            # 跨线程时按 (thread, ns) 分组取 writes，同线程只用一次查询
            grouped: dict[tuple[str, str], list[str]] = {}
            for r in rows:
                grouped.setdefault((r.thread_id, r.checkpoint_ns), []).append(r.checkpoint_id)
            writes: dict[str, list] = {}
            for (tid, ns), ids in grouped.items():
                writes.update(await self._load_writes(db, tid, ns, ids))

        for row in rows:
            yield self._to_tuple(row, writes.get(row.checkpoint_id, []))

    # ------------------------------------------------------------ 写

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict:
        conf = _configurable(config)
        thread_id = conf["thread_id"]
        checkpoint_ns = conf.get("checkpoint_ns") or DEFAULT_CHECKPOINT_NS
        checkpoint_id = checkpoint["id"]
        ctype, cblob = self.serde.dumps_typed(checkpoint)
        # 官方 helper：把 config 里的 parent 链并进 metadata，alist 的 filter 依赖它
        mtype, mblob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        parent_id = conf.get("checkpoint_id")

        async with self.session_factory() as db:
            # 同 id 重放（恢复时 LangGraph 会重写同一 super-step）先删后插：
            # 不用 ON CONFLICT 是为了 SQLite / PG 同一份代码 —— 两边的 upsert 语法与
            # 冲突目标写法不同，为省一条 DELETE 引入方言分支不划算
            await db.execute(
                delete(LangGraphCheckpoint).where(
                    LangGraphCheckpoint.thread_id == thread_id,
                    LangGraphCheckpoint.checkpoint_ns == checkpoint_ns,
                    LangGraphCheckpoint.checkpoint_id == checkpoint_id,
                )
            )
            db.add(
                LangGraphCheckpoint(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_id,
                    tenant_id=self.tenant_id,
                    type=ctype,
                    checkpoint=cblob,
                    metadata_type=mtype,
                    metadata_=mblob,
                )
            )
            await db.commit()
        # 返回值会被 aupdate_state 链式使用；hot loop 里丢弃（见 pregel/_loop.py）。
        # 刻意不把 tenant_id 塞回去：它由构造函数持有，不依赖这条传递链。
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        conf = _configurable(config)
        thread_id = conf["thread_id"]
        checkpoint_ns = conf.get("checkpoint_ns") or DEFAULT_CHECKPOINT_NS
        checkpoint_id = conf["checkpoint_id"]

        async with self.session_factory() as db:
            for i, (channel, value) in enumerate(writes):
                # 特殊通道（__error__ / __interrupt__ / __resume__ …）用固定的负下标，
                # 这样同一任务重放时会覆盖同一条而不是堆积副本 —— 与官方实现一致
                idx = WRITES_IDX_MAP.get(channel, i)
                vtype, vblob = self.serde.dumps_typed(value)
                await db.execute(
                    delete(LangGraphWrite).where(
                        LangGraphWrite.thread_id == thread_id,
                        LangGraphWrite.checkpoint_ns == checkpoint_ns,
                        LangGraphWrite.checkpoint_id == checkpoint_id,
                        LangGraphWrite.task_id == task_id,
                        LangGraphWrite.idx == idx,
                    )
                )
                db.add(
                    LangGraphWrite(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        idx=idx,
                        channel=channel,
                        type=vtype,
                        value=vblob,
                        task_path=task_path,
                    )
                )
            await db.commit()

    async def adelete_thread(self, thread_id: str) -> None:
        """删掉一条线程的全部检查点与挂起写入。"""
        async with self.session_factory() as db:
            for model in (LangGraphWrite, LangGraphCheckpoint):
                await db.execute(delete(model).where(model.thread_id == thread_id))
            await db.commit()

    # ------------------------------------------------------------ 内部

    def _to_tuple(self, row: LangGraphCheckpoint, writes: list) -> CheckpointTuple:
        configurable = {
            "thread_id": row.thread_id,
            "checkpoint_ns": row.checkpoint_ns,
            "checkpoint_id": row.checkpoint_id,
        }
        parent = None
        if row.parent_checkpoint_id:
            parent = {
                "configurable": {
                    "thread_id": row.thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                }
            }
        return CheckpointTuple(
            config={"configurable": configurable},
            checkpoint=self.serde.loads_typed((row.type, row.checkpoint)),
            metadata=self.serde.loads_typed((row.metadata_type, row.metadata_)),
            parent_config=parent,
            pending_writes=writes,
        )

    def _meta_of(self, row: LangGraphCheckpoint) -> dict:
        try:
            return self.serde.loads_typed((row.metadata_type, row.metadata_)) or {}
        except Exception:  # noqa: BLE001 - 历史行的序列化格式可能已变，过滤时当作空 metadata
            return {}

    @staticmethod
    def _metadata_matches(metadata: dict, filter: dict[str, Any]) -> bool:
        return all(metadata.get(k) == v for k, v in filter.items())

    async def _load_writes(
        self, db: AsyncSession, thread_id: str, checkpoint_ns: str, checkpoint_ids: list[str]
    ) -> dict[str, list[tuple[str, str, Any]]]:
        """取回指定 checkpoint 的挂起写入，按 checkpoint_id 分组。

        返回官方约定的 PendingWrite 三元组 (task_id, channel, value) ——
        顺序不能错，LangGraph 直接按位置解包。
        """
        if not checkpoint_ids:
            return {}
        rows = (
            await db.execute(
                select(LangGraphWrite)
                .where(
                    LangGraphWrite.thread_id == thread_id,
                    LangGraphWrite.checkpoint_ns == checkpoint_ns,
                    LangGraphWrite.checkpoint_id.in_(checkpoint_ids),
                )
                .order_by(LangGraphWrite.task_id, LangGraphWrite.idx)
            )
        ).scalars().all()
        grouped: dict[str, list[tuple[str, str, Any]]] = {}
        for r in rows:
            grouped.setdefault(r.checkpoint_id, []).append(
                (r.task_id, r.channel, self.serde.loads_typed((r.type, r.value)))
            )
        return grouped


async def delete_threads(
    db: AsyncSession, thread_ids: Sequence[str]
) -> None:
    """按线程清理检查点（删除工作流时调用，避免孤儿数据无限堆积）。

    收口成模块级函数而不是 saver 方法：这里用的是**请求级会话**（删除端点本来就持有），
    而 saver 的方法总是自开会话。让调用方决定用哪个会话，比让 saver 猜更清楚。
    """
    ids = [t for t in thread_ids if t]
    if not ids:
        return
    for model in (LangGraphWrite, LangGraphCheckpoint):
        await db.execute(delete(model).where(model.thread_id.in_(ids)))
