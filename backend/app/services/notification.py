"""通知服务：跨模块复用的通知写入 + 到期提醒扫描。

create_notification 是 best-effort 写入：通知失败绝不能影响调用方主流程
（run 完成 commit、成员迁移 commit 等），因此只在 SAVEPOINT 内 add+flush，
出错仅回滚本通知并吞异常记日志；提交交给调用方既有的 commit 边界。
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.notification import Notification
from ..models.task import Task
from ..models.user import User

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    *,
    user_id: str,
    type: str,
    title: str,
    body: str | None = None,
    ref_id: str | None = None,
    tenant_id: str = "default",
    dedupe_key: str | None = None,
) -> bool:
    """写一条站内通知。返回是否真正插入（幂等去重命中返回 False）。"""
    try:
        if dedupe_key:
            # 幂等预查：同 key 已存在直接跳过（唯一索引兜底并发冲突）
            hit = await db.execute(
                select(Notification.id).where(Notification.dedupe_key == dedupe_key)
            )
            if hit.first():
                return False
        async with db.begin_nested():  # SAVEPOINT：隔离本通知写入，失败不拖累外层事务
            db.add(
                Notification(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    type=type,
                    title=title,
                    body=body,
                    ref_id=ref_id,
                    dedupe_key=dedupe_key,
                )
            )
            await db.flush()
        return True
    except Exception:  # noqa: BLE001 - 通知失败仅记日志，不冒泡到主流程
        logger.exception("create_notification 失败: type=%s user=%s", type, user_id)
        return False


def due_reminder_dedupe_key(user_id: str, task_id: str, day: date) -> str:
    """到期提醒的幂等键：同 user+task+日历天 只落一条。

    单独抽出来是因为它有长度约束：两个 UUID + 日期共 88 字符，必须放得进
    notifications.dedupe_key 的列宽。SQLite 不校验 varchar 长度而 PG 会硬拒，
    溢出的后果是提醒在线上静默写不进去 —— 所以 tests 里有一条对列宽的断言盯着它。
    """
    return f"due:{user_id}:{task_id}:{day.isoformat()}"


async def scan_due_reminders(session_factory) -> int:
    """扫描今天到期或已逾期的未完成任务，为租户内每个成员各生成一条提醒。

    幂等：dedupe_key 见 due_reminder_dedupe_key，create_notification 预查
    + 唯一索引兜底，同 user+task+day 只落一条；逾期任务次日会再提醒。
    返回本次实际插入条数。
    """
    today = datetime.now(ZoneInfo(settings.scheduler_timezone)).date()
    count = 0
    async with session_factory() as db:
        tasks = (
            await db.execute(
                select(Task).where(
                    Task.status != "done",
                    Task.due_date.is_not(None),
                    Task.due_date <= today,
                )
            )
        ).scalars().all()
        for task in tasks:
            # 任务按租户共享（Task 无负责人字段，见 models/task.py），提醒发给租户全体成员
            user_ids = (
                await db.execute(select(User.id).where(User.tenant_id == task.tenant_id))
            ).scalars().all()
            for uid in user_ids:
                ok = await create_notification(
                    db,
                    user_id=uid,
                    type="due_reminder",
                    title="任务到期提醒",
                    body=f"任务「{task.title}」已于 {task.due_date} 到期，请及时处理",
                    ref_id=task.id,
                    tenant_id=task.tenant_id,
                    dedupe_key=due_reminder_dedupe_key(uid, task.id, today),
                )
                if ok:
                    count += 1
        await db.commit()
    return count
