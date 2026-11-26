"""Tests for detached RunSupervisor, multi-device snapshot sync, /stop unlock, and orphan reconciliation."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes import chat as chat_routes
from app.db.models import Conversation, CreditLedger, Message, MessageChunk, RunTelemetry, User
from app.services import chat_stream, chat_tickets, cross_chat_memory, realtime_bus, run_supervisor
from app.services.agent_client import AgentError
from tests.conftest import auth_header


async def _issue_ticket_headers(client, token: str, conv_id: str, action: str) -> dict[str, str]:
    nonce = uuid.uuid4().hex[:16]
    resp = await client.post(
        f"/api/conversations/{conv_id}/tickets",
        json={"action": action, "nonce": nonce},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    return {
        **auth_header(token),
        chat_tickets.TICKET_HEADER: resp.json()["ticket"],
        chat_tickets.NONCE_HEADER: nonce,
    }


def _parse_sse(raw: str) -> list[tuple[str | None, str, dict]]:
    out: list[tuple[str | None, str, dict]] = []
    cur_id: str | None = None
    cur_event = "message"
    data_lines: list[str] = []
    for line in raw.splitlines():
        line = line.rstrip("\r")
        if line == "":
            if data_lines:
                payload = "\n".join(data_lines)
                try:
                    parsed = json.loads(payload)
                except Exception:
                    parsed = {"raw": payload}
                out.append((cur_id, cur_event, parsed))
                cur_id = None
                cur_event = "message"
                data_lines = []
            continue
        if line.startswith("id:"):
            cur_id = line[3:].strip()
        elif line.startswith("event:"):
            cur_event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    return out


@pytest.mark.asyncio
async def test_client_disconnect_mid_stream_still_persists_and_settles_once(
    register, client, db, engine, monkeypatch
):
    """Detached RunSupervisor must survive client disconnect, persist full text, settle credits once, and index turn."""
    reg = await register(email="detach@test.local", display_name="DetachUser")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "detach@test.local"))).scalar_one()
    conv = (await client.post("/api/conversations", json={"title": "断线续跑测试"}, headers=headers)).json()
    conv_id = uuid.UUID(conv["id"])

    from app.services import embeddings as emb_svc

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    from app.services import rag_jobs

    monkeypatch.setattr(chat_stream, "SessionLocal", session_factory)
    monkeypatch.setattr(run_supervisor, "SessionLocal", session_factory)
    monkeypatch.setattr(cross_chat_memory, "SessionLocal", session_factory)
    monkeypatch.setattr(rag_jobs, "SessionLocal", session_factory)
    monkeypatch.setattr(emb_svc, "is_embedding_configured", lambda: False)

    gate = asyncio.Event()

    class SlowFakeAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            pass

        async def create_run(self, **kwargs) -> dict:
            return {"run_id": "run-detach-1"}

        async def stream_events_with_id(self, run_id: str, *, last_event_id: str | None = None, include_snapshot: bool = False):
            yield ("message.delta", {"text": "第一段：整体采用分层控制面与异步执行器架构；"}, "1-0")
            await gate.wait()
            yield ("message.delta", {"text": "第二段完整输出：支持多端断线重连与幂等结算。"}, "2-0")
            yield (
                "run.completed",
                {
                    "output": "第一段：整体采用分层控制面与异步执行器架构；第二段完整输出：支持多端断线重连与幂等结算。",
                    "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
                },
                "3-0",
            )

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(chat_stream, "AgentClient", SlowFakeAgent)
    monkeypatch.setattr(run_supervisor, "AgentClient", SlowFakeAgent)

    # Start streaming directly via chat_stream.stream_chat, read first delta, then forcibly close the generator (disconnect!)
    gen = chat_stream.stream_chat(
        conv_id,
        user.id,
        user.agent_namespace,
        user.agent_api_key,
        "请帮我写一段关于系统架构设计的完整技术回复说明",
        run_slot=None,
    )
    seen = []
    async for ev_dict in gen:
        seen.append(ev_dict)
        if ev_dict.get("event") == "message.delta":
            raw_d = ev_dict.get("data")
            parsed_d = json.loads(raw_d) if isinstance(raw_d, str) else (raw_d or {})
            if "第一段" in str(parsed_d.get("text") or ""):
                break
    await gen.aclose()  # Simulates abrupt browser refresh / tab close!

    # Now let the Agent emit remaining tokens & complete while NO client is connected
    gate.set()
    for _ in range(50):
        await asyncio.sleep(0.05)
        async with session_factory() as check_db:
            c = await check_db.get(Conversation, conv_id)
            if c and c.active_run_id is None:
                break

    async with session_factory() as check_db:
        c = await check_db.get(Conversation, conv_id)
        assert c is not None
        assert c.active_run_id is None
        assert c.active_run_status is None

        msgs = (
            await check_db.execute(
                select(Message)
                .where(Message.conversation_id == conv_id, Message.role == "assistant")
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
        assert len(msgs) == 1
        assert msgs[0].status == "completed"
        assert msgs[0].content == "第一段：整体采用分层控制面与异步执行器架构；第二段完整输出：支持多端断线重连与幂等结算。"

        # Credits settled strictly once
        ledger_count = await check_db.scalar(
            select(func.count()).select_from(CreditLedger).where(CreditLedger.user_id == user.id)
        )
        assert ledger_count == 1

        # Telemetry persisted strictly once
        telem_count = await check_db.scalar(
            select(func.count()).select_from(RunTelemetry).where(RunTelemetry.run_id == "run-detach-1")
        )
        assert telem_count == 1

        # Allow background message_chunks indexing task a brief moment to commit
        mc_count = 0
        for _ in range(40):
            async with session_factory() as mc_db:
                mc_count = int(
                    await mc_db.scalar(
                        select(func.count()).select_from(MessageChunk).where(MessageChunk.conversation_id == conv_id)
                    )
                    or 0
                )
            if mc_count >= 1:
                break
            await asyncio.sleep(0.05)
        assert mc_count >= 1


@pytest.mark.asyncio
async def test_multi_device_reconnect_receives_snapshot_without_duplication_or_double_billing(
    register, client, db, engine, monkeypatch
):
    """Device B attaching mid-run gets run.snapshot + tail deltas with zero text duplication & single billing."""
    reg = await register(email="sync@test.local", display_name="SyncUser")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "sync@test.local"))).scalar_one()
    conv = (await client.post("/api/conversations", json={"title": "多端同步测试"}, headers=headers)).json()
    conv_id = uuid.UUID(conv["id"])

    from app.services import embeddings as emb_svc

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    from app.services import rag_jobs

    monkeypatch.setattr(chat_stream, "SessionLocal", session_factory)
    monkeypatch.setattr(run_supervisor, "SessionLocal", session_factory)
    monkeypatch.setattr(cross_chat_memory, "SessionLocal", session_factory)
    monkeypatch.setattr(rag_jobs, "SessionLocal", session_factory)
    monkeypatch.setattr(emb_svc, "is_embedding_configured", lambda: False)

    first_chunk_emitted = asyncio.Event()
    release_tail = asyncio.Event()

    class MultiDeviceFakeAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            pass

        async def create_run(self, **kwargs) -> dict:
            return {"run_id": "run-sync-1"}

        async def stream_events_with_id(self, run_id: str, *, last_event_id: str | None = None, include_snapshot: bool = False):
            yield ("message.delta", {"text": "Alpha "}, "10-0")
            first_chunk_emitted.set()
            await release_tail.wait()
            yield ("message.delta", {"text": "Beta"}, "11-0")
            yield (
                "run.completed",
                {"output": "Alpha Beta", "usage": {"total_tokens": 150}},
                "12-0",
            )

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(chat_stream, "AgentClient", MultiDeviceFakeAgent)
    monkeypatch.setattr(run_supervisor, "AgentClient", MultiDeviceFakeAgent)

    # Device A starts streaming
    dev_a_events: list[dict] = []

    async def consume_a():
        async for ev_dict in chat_stream.stream_chat(
            conv_id,
            user.id,
            user.agent_namespace,
            user.agent_api_key,
            "hello sync",
            run_slot=None,
        ):
            dev_a_events.append(ev_dict)

    task_a = asyncio.create_task(consume_a())
    await asyncio.wait_for(first_chunk_emitted.wait(), timeout=5.0)
    # Give supervisor a beat to accumulate "Alpha " into its snapshot
    await asyncio.sleep(0.05)

    # Device B reconnects mid-run via stream_reconnect
    dev_b_events: list[tuple[str, dict]] = []

    async def consume_b():
        async for ev_dict in chat_stream.stream_reconnect(
            conv_id,
            user.agent_namespace,
            user.agent_api_key,
            "run-sync-1",
        ):
            raw_data = ev_dict.get("data")
            parsed = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
            dev_b_events.append((str(ev_dict.get("event") or ""), parsed))

    task_b = asyncio.create_task(consume_b())
    await asyncio.sleep(0.05)
    release_tail.set()

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=5.0)

    snapshot_ev = next((d for ev, d in dev_b_events if ev == "run.snapshot"), None)
    assert snapshot_ev is not None
    assert "Alpha " in (snapshot_ev.get("output") or "")

    # Reconstruct text as frontend does: replace on run.snapshot, append subsequent deltas
    reconstructed = snapshot_ev.get("output") or ""
    saw_snapshot = False
    for ev, d in dev_b_events:
        if ev == "run.snapshot":
            saw_snapshot = True
            reconstructed = d.get("output") or ""
        elif saw_snapshot and ev == "message.delta":
            reconstructed += d.get("text") or ""
    assert reconstructed == "Alpha Beta"

    # Single settlement verified
    async with session_factory() as check_db:
        ledger_count = await check_db.scalar(
            select(func.count()).select_from(CreditLedger).where(CreditLedger.user_id == user.id)
        )
        assert ledger_count == 1


@pytest.mark.asyncio
async def test_stop_unlocks_pending_and_agent_404_runs(register, client, db, monkeypatch):
    reg = await register(email="stopfix@test.local", display_name="StopUser")
    headers = auth_header(reg["access_token"])
    conv = (await client.post("/api/conversations", json={"title": "停止解锁测试"}, headers=headers)).json()
    conv_id = uuid.UUID(conv["id"])

    # Case 1: stuck in "pending"
    c = await db.get(Conversation, conv_id)
    assert c is not None
    c.active_run_id = "pending"
    c.active_run_status = "starting"
    await db.commit()

    stop_headers = await _issue_ticket_headers(client, reg["access_token"], str(conv_id), "stop")
    resp = await client.post(f"/api/conversations/{conv_id}/stop", headers=stop_headers)
    assert resp.status_code == 200, resp.text
    await db.refresh(c)
    assert c.active_run_id is None
    assert c.active_run_status is None

    # Case 2: agent returns 404 (run already expired/lost in agent)
    c.active_run_id = "run-missing-404"
    c.active_run_status = "running"
    await db.commit()

    class NotFoundAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            pass

        async def cancel_run(self, run_id: str) -> dict:
            raise AgentError(404, "Run not found")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(chat_routes, "AgentClient", NotFoundAgent)

    stop_headers2 = await _issue_ticket_headers(client, reg["access_token"], str(conv_id), "stop")
    resp2 = await client.post(f"/api/conversations/{conv_id}/stop", headers=stop_headers2)
    assert resp2.status_code == 200, resp2.text
    assert resp2.json().get("status") == "cancelled"
    await db.refresh(c)
    assert c.active_run_id is None
    assert c.active_run_status is None


@pytest.mark.asyncio
async def test_realtime_bus_delivers_user_sync_events():
    uid = uuid.uuid4()
    received: list[tuple[str, dict]] = []

    async def consumer():
        async for ev, data in realtime_bus.subscribe_user_events(uid):
            received.append((ev, data))
            if ev == "conversation.run_updated":
                break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    await realtime_bus.publish_user_event(
        uid,
        "conversation.run_updated",
        {"conversation_id": "conv-1", "active_run_id": "run-9", "active_run_status": "running"},
    )
    await asyncio.wait_for(task, timeout=3.0)
    assert len(received) == 1
    assert received[0][0] == "conversation.run_updated"
    assert received[0][1]["active_run_id"] == "run-9"


@pytest.mark.asyncio
async def test_reconcile_orphaned_runs_clears_stale_active_run(register, client, db, engine, monkeypatch):
    reg = await register(email="orphan@test.local", display_name="OrphanUser")
    headers = auth_header(reg["access_token"])
    conv = (await client.post("/api/conversations", json={"title": "孤儿恢复测试"}, headers=headers)).json()
    conv_id = uuid.UUID(conv["id"])

    c = await db.get(Conversation, conv_id)
    assert c is not None
    c.active_run_id = "run-orphan-1"
    c.active_run_status = "running"
    msg = Message(
        conversation_id=conv_id,
        role="assistant",
        content="",
        status="streaming",
        run_id="run-orphan-1",
    )
    db.add(msg)
    await db.commit()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(run_supervisor, "SessionLocal", session_factory)

    class TerminalAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            pass

        async def get_run(self, run_id: str) -> dict:
            return {"run_id": run_id, "status": "completed", "text": "恢复后的最终文本"}

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(run_supervisor, "AgentClient", TerminalAgent)

    cleaned = await run_supervisor.reconcile_orphaned_runs()
    assert cleaned >= 1

    async with session_factory() as check_db:
        c2 = await check_db.get(Conversation, conv_id)
        m2 = await check_db.get(Message, msg.id)
        assert c2 is not None and c2.active_run_id is None
        assert m2 is not None and m2.status == "completed" and m2.content == "恢复后的最终文本"
