"""站内通知中心测试：用户级收件箱隔离、已读/删除、到期提醒幂等、Agent run 集成。

复用 conftest 的 client/auth_headers/db_session。造通知直接调 services 层
create_notification（SAVEPOINT 内写入，测试侧再 commit），保持与生产同一条写路径。
"""

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models.notification import Notification
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.notification import (
    create_notification,
    due_reminder_dedupe_key,
    scan_due_reminders,
)


class _RecordingEngine:
    """记录最近一次 prompt，返回「回答: <prompt>」。"""

    def __init__(self) -> None:
        self.last_query: str | None = None

    async def chat(self, query: str, user: str = "unknown") -> str:
        self.last_query = query
        return f"回答: {query}"

    async def knowledge_query(self, query: str, user: str = "unknown") -> str:
        return query


async def _wait_run(client, headers, run_id, timeout: float = 3.0) -> dict:
    """轮询 agent run 直到终止态。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        r = await client.get(f"/api/agents/runs/{run_id}", headers=headers)
        assert r.status_code == 200
        data = r.json()
        if data["status"] in ("succeeded", "failed"):
            return data
        if loop.time() > deadline:
            raise AssertionError(f"run {run_id} 未在 {timeout}s 内结束: status={data['status']}")
        await asyncio.sleep(0.05)


async def _user_id(client, headers, email: str) -> str:
    """按 email 从团队成员列表取 user id。"""
    r = await client.get("/api/team/members", headers=headers)
    assert r.status_code == 200
    return next(m["id"] for m in r.json() if m["email"] == email)


async def _register(client, email: str, name: str = "用户", invite_code: str | None = None) -> dict:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "secret123", "name": name, "invite_code": invite_code}
        if invite_code
        else {"email": email, "password": "secret123", "name": name},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- 基础：鉴权 / 空收件箱 / 用户隔离 ----------


async def test_notifications_require_auth(client):
    assert (await client.get("/api/notifications")).status_code == 401
    assert (await client.get("/api/notifications/unread-count")).status_code == 401
    assert (await client.post("/api/notifications/read-all")).status_code == 401


async def test_registered_user_has_empty_inbox(client, auth_headers):
    r = await client.get("/api/notifications", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []


async def test_notification_isolation_between_users(client, auth_headers, db_session):
    """用户 A 的通知对 B 完全不可见；B 读/删 A 的通知一律 404。"""
    me = await _user_id(client, auth_headers, "test@example.com")
    ok = await create_notification(db_session, user_id=me, type="team", title="A 专属", tenant_id="default")
    assert ok
    await db_session.commit()
    notif_id = (
        await db_session.execute(select(Notification).where(Notification.title == "A 专属"))
    ).scalar_one().id

    b = await _register(client, "other@example.com", "路人")
    r = await client.get("/api/notifications", headers=b)
    assert r.json()["total"] == 0

    assert (
        await client.post(f"/api/notifications/{notif_id}/read", headers=b)
    ).status_code == 404
    assert (await client.delete(f"/api/notifications/{notif_id}", headers=b)).status_code == 404


# ---------- 列表过滤 / 未读数 ----------


async def test_unread_count_and_filters(client, auth_headers, db_session):
    me = await _user_id(client, auth_headers, "test@example.com")
    # 2 条未读（team + due_reminder）+ 1 条已读（knowledge）
    for typ, title in (("team", "团队通知"), ("due_reminder", "到期通知"), ("knowledge", "入库通知")):
        await create_notification(db_session, user_id=me, type=typ, title=title, tenant_id="default")
    await db_session.commit()
    read_one = (
        await db_session.execute(select(Notification).where(Notification.title == "入库通知"))
    ).scalar_one()
    read_one.read_at = datetime.now(ZoneInfo(settings.scheduler_timezone))
    await db_session.commit()

    r = await client.get("/api/notifications/unread-count", headers=auth_headers)
    assert r.json()["count"] == 2

    # unread_only 过滤
    r = await client.get("/api/notifications?unread_only=true", headers=auth_headers)
    assert r.json()["total"] == 2
    assert all(n["read_at"] is None for n in r.json()["items"])

    # type 过滤
    r = await client.get("/api/notifications?type=due_reminder", headers=auth_headers)
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["type"] == "due_reminder"

    # 分页形状
    r = await client.get("/api/notifications?page=1&page_size=2", headers=auth_headers)
    assert r.json()["total"] == 3
    assert len(r.json()["items"]) == 2


# ---------- 已读 / 全部已读 / 删除 ----------


async def test_mark_read_and_idempotent(client, auth_headers, db_session):
    me = await _user_id(client, auth_headers, "test@example.com")
    await create_notification(db_session, user_id=me, type="team", title="单条", tenant_id="default")
    await db_session.commit()
    notif_id = (
        await db_session.execute(select(Notification).where(Notification.title == "单条"))
    ).scalar_one().id

    assert (
        await client.post(f"/api/notifications/{notif_id}/read", headers=auth_headers)
    ).status_code == 204
    assert (
        await client.get("/api/notifications/unread-count", headers=auth_headers)
    ).json()["count"] == 0
    # 重复标记幂等
    assert (
        await client.post(f"/api/notifications/{notif_id}/read", headers=auth_headers)
    ).status_code == 204


async def test_mark_all_read(client, auth_headers, db_session):
    me = await _user_id(client, auth_headers, "test@example.com")
    for i in range(3):
        await create_notification(db_session, user_id=me, type="team", title=f"批量{i}", tenant_id="default")
    await db_session.commit()

    r = await client.post("/api/notifications/read-all", headers=auth_headers)
    assert r.json()["updated"] == 3
    assert (
        await client.get("/api/notifications/unread-count", headers=auth_headers)
    ).json()["count"] == 0
    # 再次全部已读：0 行更新
    r = await client.post("/api/notifications/read-all", headers=auth_headers)
    assert r.json()["updated"] == 0


async def test_delete_notification(client, auth_headers, db_session):
    me = await _user_id(client, auth_headers, "test@example.com")
    await create_notification(db_session, user_id=me, type="team", title="待删除", tenant_id="default")
    await db_session.commit()
    notif_id = (
        await db_session.execute(select(Notification).where(Notification.title == "待删除"))
    ).scalar_one().id

    assert (
        await client.delete(f"/api/notifications/{notif_id}", headers=auth_headers)
    ).status_code == 204
    r = await client.get("/api/notifications", headers=auth_headers)
    assert r.json()["total"] == 0


# ---------- 角色：readonly 也能读自己的通知（不拦读权限） ----------


async def test_readonly_can_read_own_notifications(client, auth_headers, db_session):
    """readonly 成员的通知收件箱可用：通知端点不挂 require_role。"""
    r = await client.post(
        "/api/team/invites", json={"email": "viewer@example.com", "role": "readonly"}, headers=auth_headers
    )
    assert r.status_code == 201
    code = r.json()["code"]
    viewer = await _register(client, "viewer@example.com", "只读者", invite_code=code)
    viewer_id = await _user_id(client, viewer, "viewer@example.com")

    ok = await create_notification(
        db_session, user_id=viewer_id, type="due_reminder", title="只读可见", tenant_id="default"
    )
    assert ok
    await db_session.commit()

    r = await client.get("/api/notifications", headers=viewer)
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["title"] == "只读可见"


# ---------- 到期提醒：幂等 + done/未来不生成 ----------


def test_dedupe_key_fits_column_width():
    """幂等键必须放得进 notifications.dedupe_key 的列宽。

    SQLite 不校验 varchar 长度而 PG 会，溢出的表现是**只在线上的**写入失败：
    create_notification 吞掉异常返回 False，scan 静默算出 0 条，任务永远不提醒。
    所以这条断言必须在单测里挡住，不能只靠 PG 那条腿。
    """
    key = due_reminder_dedupe_key(
        "1e292549-ecf8-4eea-8476-a22e29eee6a6", "19efe1dc-f715-40da-ab04-149a1ed708a6", date(2026, 9, 28)
    )
    width = Notification.__table__.c.dedupe_key.type.length
    assert len(key) <= width, f"dedupe_key 长 {len(key)}，列宽只有 {width}"


async def _seed_task(db_session, tenant_id: str, *, title: str, status: str, due_date) -> Task:
    project = Project(tenant_id=tenant_id, name="到期测试项目")
    db_session.add(project)
    await db_session.flush()
    task = Task(tenant_id=tenant_id, project_id=project.id, title=title, status=status, due_date=due_date)
    db_session.add(task)
    await db_session.commit()
    return task


async def test_due_reminder_scan_idempotent(client, auth_headers, db_session):
    """今天到期任务 → scan 两次恰生成 1 条提醒；dedupe_key 含今天日期。"""
    me = await _user_id(client, auth_headers, "test@example.com")
    me_user = await db_session.get(User, me)
    today = datetime.now(ZoneInfo(settings.scheduler_timezone)).date()

    await _seed_task(db_session, me_user.tenant_id, title="今天到期", status="todo", due_date=today)

    factory = app.state.test_session_factory
    assert await scan_due_reminders(factory) == 1
    assert await scan_due_reminders(factory) == 0  # 幂等：第二次去重命中

    rows = (
        await db_session.execute(
            select(Notification).where(Notification.type == "due_reminder")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == me
    assert rows[0].dedupe_key == f"due:{me}:{rows[0].ref_id}:{today.isoformat()}"


async def test_due_reminder_skips_done_and_future(client, auth_headers, db_session):
    me = await _user_id(client, auth_headers, "test@example.com")
    me_user = await db_session.get(User, me)
    today = datetime.now(ZoneInfo(settings.scheduler_timezone)).date()

    await _seed_task(db_session, me_user.tenant_id, title="已完成", status="done", due_date=today)
    await _seed_task(
        db_session, me_user.tenant_id, title="未来到期", status="todo", due_date=today + timedelta(days=1)
    )
    await _seed_task(
        db_session, me_user.tenant_id, title="已逾期", status="todo", due_date=today - timedelta(days=1)
    )

    factory = app.state.test_session_factory
    # 只有「已逾期」应生成（done 与未来 due 均跳过）
    assert await scan_due_reminders(factory) == 1

    rows = (
        await db_session.execute(
            select(Notification).where(Notification.type == "due_reminder")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].ref_id is not None


# ---------- Agent run 集成：完成后生成 agent_run 通知 ----------


async def test_agent_run_generates_notification(client, auth_headers, monkeypatch):
    engine = _RecordingEngine()
    monkeypatch.setattr("app.agents.runner.get_ai_engine", lambda: engine)

    r = await client.post(
        "/api/agents/interview_questions/run",
        json={"params": {"topic": "FastAPI"}},
        headers=auth_headers,
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    data = await _wait_run(client, auth_headers, run_id)
    assert data["status"] == "succeeded"

    r = await client.get("/api/notifications?type=agent_run", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert any(n["ref_id"] == run_id for n in r.json()["items"])
