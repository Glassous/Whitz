import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    Conversation,
    CreditLedger,
    Message,
    ScheduledTask,
    ScheduledTaskPendingProposal,
    ScheduledTaskRun,
    User,
)
from app.services import chat_stream, mcp_schedules, schedule_calc, scheduler_service
from tests.conftest import auth_header


def test_schedule_calc_presets_and_cron():
    base = datetime(2026, 6, 1, 0, 30, tzinfo=timezone.utc)  # 08:30 Asia/Shanghai

    # Daily before 09:00 -> same day 09:00 Shanghai = 01:00 UTC
    nxt_daily = schedule_calc.compute_next_run_at("daily", {"hour": 9, "minute": 0}, "Asia/Shanghai", after_dt=base)
    assert nxt_daily == datetime(2026, 6, 1, 1, 0, tzinfo=timezone.utc)

    # Weekly Mon/Wed/Fri
    nxt_weekly = schedule_calc.compute_next_run_at(
        "weekly", {"weekdays": [3, 5], "hour": 8, "minute": 0}, "Asia/Shanghai", after_dt=base
    )
    # 2026-06-01 is Monday; next Wednesday is 2026-06-03 08:00 CST = 00:00 UTC
    assert nxt_weekly == datetime(2026, 6, 3, 0, 0, tzinfo=timezone.utc)

    # Monthly clamping (31st in February)
    feb_base = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    nxt_feb = schedule_calc.compute_next_run_at(
        "monthly", {"day": 31, "hour": 10, "minute": 0}, "Asia/Shanghai", after_dt=feb_base
    )
    assert nxt_feb == datetime(2026, 2, 28, 2, 0, tzinfo=timezone.utc)

    # Cron 0 9 * * 1-5
    desc, runs = schedule_calc.preview_next_runs(
        "cron", {"expr": "0 9 * * 1-5"}, "Asia/Shanghai", count=5, min_interval_minutes=5, now=base
    )
    assert "Cron" in desc
    assert len(runs) == 5
    assert runs[0] == datetime(2026, 6, 1, 1, 0, tzinfo=timezone.utc)

    # Min interval guard rejects every-minute cron on 60m quota
    with pytest.raises(schedule_calc.ScheduleValidationError):
        schedule_calc.validate_and_normalize_schedule(
            "cron", {"expr": "* * * * *"}, "Asia/Shanghai", min_interval_minutes=60, now=base
        )


async def test_schedules_api_crud_preview_and_quotas(register, client, db):
    reg = await register(email="sched1@test.local", display_name="Sched1")
    headers = auth_header(reg["access_token"])

    # Preview endpoint
    prev_ok = await client.post(
        "/api/schedules/preview",
        json={"schedule_type": "daily", "schedule_config": {"hour": 9, "minute": 30}, "count": 3},
        headers=headers,
    )
    assert prev_ok.status_code == 200
    assert prev_ok.json()["valid"] is True
    assert len(prev_ok.json()["next_runs"]) == 3

    prev_bad = await client.post(
        "/api/schedules/preview",
        json={"schedule_type": "interval", "schedule_config": {"every_minutes": 5}},
        headers=headers,
    )
    assert prev_bad.status_code == 200
    assert prev_bad.json()["valid"] is False
    assert "60 分钟" in (prev_bad.json()["error"] or "")

    # Free tier allows up to 3 active tasks
    created_ids = []
    for i in range(3):
        resp = await client.post(
            "/api/schedules",
            json={
                "name": f"日报-{i}",
                "prompt": "汇总今日要点",
                "schedule_type": "daily",
                "schedule_config": {"hour": 9 + i, "minute": 0},
                "target_mode": "dedicated",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        created_ids.append(resp.json()["id"])

    # 4th active task hits free quota
    fourth = await client.post(
        "/api/schedules",
        json={
            "name": "超额任务",
            "prompt": "测试超额",
            "schedule_type": "daily",
            "schedule_config": {"hour": 14, "minute": 0},
        },
        headers=headers,
    )
    assert fourth.status_code == 400

    # Pause one task, update another, then delete
    paused = await client.patch(
        f"/api/schedules/{created_ids[0]}",
        json={"enabled": False},
        headers=headers,
    )
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False
    assert paused.json()["status"] == "paused"

    detail = await client.get(f"/api/schedules/{created_ids[0]}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "日报-0"

    deleted = await client.delete(f"/api/schedules/{created_ids[0]}", headers=headers)
    assert deleted.status_code == 204


async def test_mcp_schedules_proposal_and_resolution(register, client, db):
    reg = await register(email="schedmcp@test.local", display_name="SchedMcp")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "schedmcp@test.local"))).scalar_one()

    # Create proposal via MCP tool
    res = await mcp_schedules.call_tool(
        db,
        user,
        "create_scheduled_task",
        {
            "name": "科技新闻早报",
            "prompt": "搜索今天最重要的 3 条 AI 新闻",
            "schedule_type": "daily",
            "schedule_config": {"hour": 8, "minute": 30},
            "target_mode": "main",
            "reason": "用户请求每天早上 8:30 推送早报",
        },
    )
    assert res["isError"] is False

    pending_resp = await client.get("/api/schedules/pending", headers=headers)
    assert pending_resp.status_code == 200
    pending_items = pending_resp.json()
    assert len(pending_items) == 1
    pid = pending_items[0]["id"]

    # Approve proposal
    approved = await client.post(
        f"/api/schedules/pending/{pid}",
        json={"action": "approve"},
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    task = approved.json()["task"]
    assert task["name"] == "科技新闻早报"
    assert task["target_mode"] == "main"
    assert task["source"] == "agent"

    # List via MCP tool
    listed = await mcp_schedules.call_tool(db, user, "list_scheduled_tasks", {})
    assert listed["isError"] is False
    assert "科技新闻早报" in listed["content"][0]["text"]


async def test_dispatch_due_tasks_executes_without_hitl_and_handles_once(register, engine, db, monkeypatch):
    reg = await register(email="schedrun@test.local", display_name="SchedRun")
    user = (await db.execute(select(User).where(User.email == "schedrun@test.local"))).scalar_one()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    created_calls: list[dict] = []

    class FakeRunClient:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            self.namespace = namespace
            self.api_key = api_key

        async def health(self) -> bool:
            return True

        async def create_run(self, **kwargs):
            created_calls.append(kwargs)
            return {"run_id": f"fake-run-{uuid.uuid4().hex[:8]}", "status": "queued"}

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(scheduler_service, "AgentClient", FakeRunClient)
    monkeypatch.setattr(chat_stream, "SessionLocal", session_factory)

    launched: list[dict] = []

    def fake_start_supervised_run(**kwargs):
        launched.append(kwargs)
        return None, None

    monkeypatch.setattr(chat_stream.run_supervisor, "start_supervised_run", fake_start_supervised_run)

    past_due = datetime.now(timezone.utc) - timedelta(minutes=2)
    task = ScheduledTask(
        user_id=user.id,
        target_mode="dedicated",
        name="一次性提醒",
        prompt="检查系统状态并汇报",
        schedule_type="once",
        schedule_config={"run_at": past_due.isoformat()},
        timezone="Asia/Shanghai",
        enabled=True,
        status="active",
        next_run_at=past_due,
        max_runs=1,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    dispatched = await scheduler_service.dispatch_due_tasks(
        session_factory=session_factory,
        execute_inline=True,
    )
    assert dispatched == 1
    assert len(created_calls) == 1
    assert created_calls[0]["allow_hitl"] is False
    assert len(launched) == 1
    assert launched[0]["scheduled_run_id"] is not None

    # Second tick must not re-fire
    dispatched_again = await scheduler_service.dispatch_due_tasks(
        session_factory=session_factory,
        execute_inline=True,
    )
    assert dispatched_again == 0

    await db.refresh(task)
    assert task.enabled is False
    assert task.status == "completed"
    assert task.run_count == 1
    assert task.conversation_id is not None

    # Check created messages in dedicated conversation
    msgs = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == task.conversation_id)
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(msgs) == 2
    assert "[定时任务 · 一次性提醒]" in msgs[0].content

    # Simulate supervisor terminal finalization
    await scheduler_service.finalize_scheduled_run(
        db,
        scheduled_run_id=launched[0]["scheduled_run_id"],
        status="completed",
        output="系统运行正常，所有服务健康。",
        tokens_used=128,
    )
    run_row = (
        await db.execute(select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task.id))
    ).scalar_one()
    assert run_row.status == "completed"
    assert run_row.tokens_used == 128
    assert "系统运行正常" in (run_row.summary or "")


async def test_dispatch_skips_when_credits_exhausted(register, engine, db):
    reg = await register(email="schedskip@test.local", display_name="SchedSkip")
    user = (await db.execute(select(User).where(User.email == "schedskip@test.local"))).scalar_one()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Exhaust user's credits via ledger entry
    db.add(CreditLedger(user_id=user.id, tokens=-10_000_000, kind="consume", note="exhaust"))
    past_due = datetime.now(timezone.utc) - timedelta(minutes=1)
    task = ScheduledTask(
        user_id=user.id,
        target_mode="main",
        name="每日汇报",
        prompt="生成总结",
        schedule_type="daily",
        schedule_config={"hour": 9, "minute": 0},
        timezone="Asia/Shanghai",
        enabled=True,
        status="active",
        next_run_at=past_due,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    dispatched = await scheduler_service.dispatch_due_tasks(
        session_factory=session_factory,
        execute_inline=True,
    )
    assert dispatched == 1

    await db.refresh(task)
    assert task.last_run_status == "skipped"
    assert "积分" in (task.last_error or "")
    run_row = (
        await db.execute(select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task.id))
    ).scalar_one()
    assert run_row.status == "skipped"
