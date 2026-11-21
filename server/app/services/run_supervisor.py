from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.models import Conversation, Message, User
from app.db.session import SessionLocal
from app.services import (
    cross_chat_memory,
    limits,
    membership,
    memory_service,
    reactions,
    realtime_bus,
    skills_service,
    telemetry,
    usage,
)
from app.services.agent_client import AgentClient, AgentError

logger = logging.getLogger("whitz.run_supervisor")

_ACTIVE_SUPERVISORS: dict[str, "SupervisedRun"] = {}
_RECONCILER_TASK: asyncio.Task[Any] | None = None
_SETTLED_LOCAL: set[str] = set()


async def _claim_settlement_once(run_id: str | None, assistant_id: uuid.UUID) -> bool:
    """Guarantee UsageDaily, CreditLedger, and Prometheus run metrics settle strictly once per run."""
    key_id = run_id or str(assistant_id)
    if key_id in _SETTLED_LOCAL:
        return False
    try:
        r = get_redis()
        claimed = await r.set(f"srv:settled:{key_id}", "1", ex=86400, nx=True)
        if not claimed:
            _SETTLED_LOCAL.add(key_id)
            return False
    except Exception:
        pass
    _SETTLED_LOCAL.add(key_id)
    if len(_SETTLED_LOCAL) > 4096:
        _SETTLED_LOCAL.clear()
    return True


async def settle_usage_once(db: AsyncSession, user_id: uuid.UUID, assistant: Message) -> None:
    """Exactly-once billing, usage_daily recording, and run telemetry settlement."""
    if not await _claim_settlement_once(assistant.run_id, assistant.id):
        return
    tokens = usage.tokens_from_usage((assistant.tool_payload or {}).get("usage"))
    if tokens > 0:
        await usage.record_tokens(db, user_id, tokens)
        await membership.settle(
            db,
            user_id,
            tokens,
            message_id=assistant.id,
            conversation_id=assistant.conversation_id,
        )
    elif assistant.status == "completed":
        logger.warning("run completed without token usage message=%s", assistant.id)
    await telemetry.record_run_telemetry(
        db,
        user_id=user_id,
        conversation_id=assistant.conversation_id,
        assistant=assistant,
        run_id=assistant.run_id,
    )


class SupervisedRun:
    """Detached single-writer run supervisor that survives HTTP SSE disconnects and fans out to N devices."""

    def __init__(
        self,
        *,
        run_id: str,
        conv_id: uuid.UUID,
        user_id: uuid.UUID,
        assistant_id: uuid.UUID,
        user_msg_id: uuid.UUID | None,
        user_content: str,
        client: AgentClient,
        session_factory: Callable[[], Any],
        started_at: float,
        max_seconds: int | None,
        run_slot: str | None,
        initial_mem_ids: set[str],
        initial_skill_ids: set[str],
        seed_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.run_id = run_id
        self.conv_id = conv_id
        self.user_id = user_id
        self.assistant_id = assistant_id
        self.user_msg_id = user_msg_id
        self.user_content = user_content
        self.client = client
        self.session_factory = session_factory
        self.started_at = started_at
        self.max_seconds = max_seconds
        self.run_slot = run_slot
        self.initial_mem_ids = initial_mem_ids
        self.initial_skill_ids = initial_skill_ids

        self.subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self.done = False
        self.last_event_id: str = "0-0"
        self.pipeline: Any = None
        self.live_status: str = "running"
        self.live_pending_control: dict[str, Any] | None = None
        self.live_tools: list[dict[str, Any]] = []
        self._seed_events = list(seed_events or [])
        self.task: asyncio.Task[Any] | None = None

    def add_subscriber(self, *, replay_seed: bool = False) -> asyncio.Queue[dict[str, Any] | None]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=512)
        if replay_seed:
            for ev in self._seed_events:
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    break
        self.subscribers.add(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        self.subscribers.discard(q)

    def broadcast(self, ev: dict[str, Any] | None) -> None:
        if ev is not None and ev.get("id"):
            self.last_event_id = str(ev["id"])
        for q in list(self.subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                # Drop oldest delta if a slow client falls behind; supervisor never blocks on slow clients
                try:
                    q.get_nowait()
                    q.put_nowait(ev)
                except Exception:
                    pass

    def build_snapshot_event(self) -> dict[str, Any]:
        p = self.pipeline
        content = "".join(p.buffer) if p is not None else ""
        reasoning = list(p.reasoning) if p is not None else []
        plan = p.plan if p is not None else None
        artifacts = list(p.artifacts) if p is not None else []
        payload = {
            "run_id": self.run_id,
            "conversation_id": str(self.conv_id),
            "assistant_message_id": str(self.assistant_id),
            "status": self.live_status,
            "output": content,
            "reasoning": reasoning,
            "plan": plan,
            "artifacts": artifacts,
            "tool_events": list(self.live_tools),
            "pending_control": self.live_pending_control,
            "last_event_id": self.last_event_id,
        }
        ev: dict[str, Any] = {"event": "run.snapshot", "data": json.dumps(payload, ensure_ascii=False)}
        if self.last_event_id and self.last_event_id != "0-0":
            ev["id"] = self.last_event_id
        return ev

    async def run(self) -> None:
        # Local import avoids circular module dependency with chat_stream
        from app.services import chat_stream

        lease_key = f"srv:run_writer:{self.run_id}"
        try:
            await get_redis().set(lease_key, "1", ex=max(120, (self.max_seconds or 1200) + 60))
        except Exception:
            pass

        try:
            async with self.session_factory() as db:
                conv = await db.get(Conversation, self.conv_id)
                assistant = await db.get(Message, self.assistant_id)
                if conv is None or assistant is None:
                    self.broadcast(chat_stream.sse("error", {"code": "not_found"}))
                    return

                pipeline = chat_stream.ChatPipeline(
                    db,
                    self.client,
                    conv,
                    assistant,
                    self.run_id,
                    started_at=self.started_at,
                    max_seconds=self.max_seconds,
                )
                self.pipeline = pipeline
                if assistant.content:
                    pipeline.buffer = [assistant.content]
                await pipeline.prepare()
                # Release any read transaction immediately before awaiting the long-lived SSE stream
                await db.commit()

                await realtime_bus.publish_user_event(
                    self.user_id,
                    "conversation.run_updated",
                    {
                        "conversation_id": str(self.conv_id),
                        "active_run_id": self.run_id,
                        "active_run_status": "running",
                        "assistant_message_id": str(self.assistant_id),
                        "pending_control": None,
                    },
                )

                async for ev in pipeline.pump():
                    ev_name = str(ev.get("event") or "")
                    if ev_name in ("approval.request", "clarify.request"):
                        try:
                            ctl = json.loads(ev.get("data") or "{}")
                            ctl["kind"] = "approval" if ev_name == "approval.request" else "clarify"
                            self.live_pending_control = ctl
                            self.live_status = (
                                "waiting_for_approval" if ev_name == "approval.request" else "waiting_for_clarify"
                            )
                        except Exception:
                            pass
                        await realtime_bus.publish_user_event(
                            self.user_id,
                            "conversation.run_updated",
                            {
                                "conversation_id": str(self.conv_id),
                                "active_run_id": self.run_id,
                                "active_run_status": self.live_status,
                                "pending_control": self.live_pending_control,
                            },
                        )
                    elif ev_name in ("control.resolved", "run.resumed"):
                        self.live_pending_control = None
                        self.live_status = "running"
                        await realtime_bus.publish_user_event(
                            self.user_id,
                            "control.resolved",
                            {"conversation_id": str(self.conv_id), "run_id": self.run_id},
                        )
                    elif ev_name == "message.reaction":
                        try:
                            rd = json.loads(ev.get("data") or "{}")
                            reaction_val = reactions.validate_reaction(
                                author_type="assistant",
                                reaction=str(rd.get("reaction") or ""),
                            )
                            if self.user_msg_id is not None:
                                user_msg = await db.get(Message, self.user_msg_id)
                                if user_msg is not None and user_msg.role == "user":
                                    row = await reactions.upsert_reaction(
                                        db,
                                        message=user_msg,
                                        user_id=self.user_id,
                                        author_type="assistant",
                                        reaction=reaction_val,
                                        comment=str(rd.get("note") or "")[:500] or None,
                                    )
                                    items = await reactions.list_message_reactions(db, user_msg.id)
                                    ev = chat_stream.sse(
                                        "message.reaction",
                                        {
                                            "conversation_id": str(self.conv_id),
                                            "message_id": str(user_msg.id),
                                            "reaction": reactions.serialize_reaction(row),
                                            "reactions": items,
                                        },
                                    )
                                    await realtime_bus.publish_user_event(
                                        self.user_id,
                                        "message.reaction_updated",
                                        {
                                            "conversation_id": str(self.conv_id),
                                            "message_id": str(user_msg.id),
                                            "reactions": items,
                                        },
                                    )
                        except Exception:
                            logger.debug("Ignored invalid assistant message.reaction event", exc_info=True)
                            continue
                    elif ev_name == "tool.started":
                        try:
                            td = json.loads(ev.get("data") or "{}")
                            self.live_tools.append({**td, "status": "running"})
                        except Exception:
                            pass
                    elif ev_name == "tool.completed":
                        try:
                            td = json.loads(ev.get("data") or "{}")
                            cid = td.get("call_id")
                            mid = td.get("message_id")
                            matched = False
                            for i, item in enumerate(self.live_tools):
                                if (cid and item.get("call_id") == cid) or (mid and item.get("message_id") == mid):
                                    self.live_tools[i] = {**item, **td, "status": "failed" if td.get("error") else "completed"}
                                    matched = True
                                    break
                            if not matched:
                                self.live_tools.append({**td, "status": "failed" if td.get("error") else "completed"})
                        except Exception:
                            pass
                    self.broadcast(ev)

                if pipeline.terminal:
                    self.live_status = assistant.status or "completed"
                    self.live_pending_control = None
                    await settle_usage_once(db, self.user_id, assistant)

                    if assistant.status == "completed":
                        if conv.kind == "side":
                            cross_chat_memory.schedule_side_chat_digest_refresh(conv.id, self.user_id)
                        elif conv.kind == "main":
                            cross_chat_memory.schedule_main_compaction_check(conv.id)
                        # Episodic turn vectorization into message_chunks
                        if self.user_content or assistant.content:
                            cross_chat_memory.schedule_turn_chunk_indexing(
                                user_id=self.user_id,
                                conversation_id=conv.id,
                                conversation_kind=conv.kind or "side",
                                conversation_title=conv.title or "",
                                user_msg_id=self.user_msg_id,
                                assistant_msg_id=assistant.id,
                                user_content=self.user_content,
                                assistant_content=assistant.content or "",
                            )

                    for ev in await chat_stream._pending_events_since(
                        db, self.user_id, self.initial_mem_ids, self.initial_skill_ids
                    ):
                        self.broadcast(ev)

                    async for ev in chat_stream._auto_title_events(db, conv, assistant):
                        self.broadcast(ev)
                        if ev.get("event") == "conversation.title_updated":
                            try:
                                td = json.loads(ev.get("data") or "{}")
                                await realtime_bus.publish_user_event(
                                    self.user_id,
                                    "conversation.updated",
                                    {"conversation_id": str(conv.id), "title": td.get("title")},
                                )
                            except Exception:
                                pass

                    await realtime_bus.publish_user_event(
                        self.user_id,
                        "conversation.run_updated",
                        {
                            "conversation_id": str(self.conv_id),
                            "active_run_id": None,
                            "active_run_status": None,
                            "last_status": assistant.status,
                            "assistant_message_id": str(self.assistant_id),
                            "pending_control": None,
                        },
                    )
        except AgentError as exc:
            logger.warning("Supervised run %s agent error: %s", self.run_id, exc)
            await self._mark_failed_in_db()
            self.broadcast(
                chat_stream.sse("error", {"code": "agent_error", "status": exc.status_code, "detail": exc.detail})
            )
        except Exception as exc:
            logger.exception("Supervised run %s failed unexpectedly", self.run_id)
            await self._mark_failed_in_db()
            self.broadcast(chat_stream.sse("error", {"code": "internal_error", "detail": str(exc)}))
        finally:
            self.done = True
            self.broadcast(None)
            _ACTIVE_SUPERVISORS.pop(self.run_id, None)
            if self.run_slot:
                await limits.release_run(self.user_id, self.run_slot)
            try:
                await get_redis().delete(lease_key)
            except Exception:
                pass
            await self.client.aclose()

    async def _mark_failed_in_db(self) -> None:
        try:
            async with self.session_factory() as db:
                conv = await db.get(Conversation, self.conv_id)
                assistant = await db.get(Message, self.assistant_id)
                if assistant is not None and assistant.status in ("streaming", "waiting"):
                    assistant.status = "failed"
                if conv is not None and conv.active_run_id == self.run_id:
                    conv.active_run_id = None
                    conv.active_run_status = None
                    conv.pending_control = None
                await db.commit()
            await realtime_bus.publish_user_event(
                self.user_id,
                "conversation.run_updated",
                {
                    "conversation_id": str(self.conv_id),
                    "active_run_id": None,
                    "active_run_status": None,
                    "last_status": "failed",
                    "pending_control": None,
                },
            )
        except Exception:
            logger.debug("Failed to persist failure state for run=%s", self.run_id, exc_info=True)


def get_supervisor(run_id: str) -> SupervisedRun | None:
    sup = _ACTIVE_SUPERVISORS.get(run_id)
    if sup is not None and not sup.done:
        return sup
    return None


def start_supervised_run(
    *,
    run_id: str,
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    assistant_id: uuid.UUID,
    user_msg_id: uuid.UUID | None,
    user_content: str,
    client: AgentClient,
    session_factory: Callable[[], Any] | None = None,
    started_at: float | None = None,
    max_seconds: int | None = None,
    run_slot: str | None = None,
    initial_mem_ids: set[str] | None = None,
    initial_skill_ids: set[str] | None = None,
    seed_events: list[dict[str, Any]] | None = None,
) -> tuple[SupervisedRun, asyncio.Queue[dict[str, Any] | None]]:
    existing = get_supervisor(run_id)
    if existing is not None:
        return existing, existing.add_subscriber(replay_seed=False)

    sup = SupervisedRun(
        run_id=run_id,
        conv_id=conv_id,
        user_id=user_id,
        assistant_id=assistant_id,
        user_msg_id=user_msg_id,
        user_content=user_content,
        client=client,
        session_factory=session_factory or SessionLocal,
        started_at=started_at if started_at is not None else time.time(),
        max_seconds=max_seconds,
        run_slot=run_slot,
        initial_mem_ids=initial_mem_ids or set(),
        initial_skill_ids=initial_skill_ids or set(),
        seed_events=seed_events,
    )
    q = sup.add_subscriber(replay_seed=True)
    _ACTIVE_SUPERVISORS[run_id] = sup
    sup.task = asyncio.create_task(sup.run(), name=f"run-supervisor-{run_id}")
    return sup, q


async def iter_subscriber_queue(
    sup: SupervisedRun,
    q: asyncio.Queue[dict[str, Any] | None],
) -> AsyncIterator[dict[str, Any]]:
    """Read-only SSE fan-out consumer. Cancelling this generator NEVER affects the SupervisedRun."""
    try:
        while True:
            item = await q.get()
            if item is None:
                return
            yield item
    finally:
        sup.remove_subscriber(q)


async def reconcile_orphaned_runs() -> int:
    """Detect conversations stuck with active_run_id after server/worker restart and recover or unlock them."""
    reconciled = 0
    try:
        async with SessionLocal() as db:
            rows = list(
                (
                    await db.execute(
                        select(Conversation).where(Conversation.active_run_id.is_not(None))
                    )
                )
                .scalars()
                .all()
            )
            now = datetime.now(timezone.utc)
            for conv in rows:
                run_id = conv.active_run_id
                if not run_id or run_id in _ACTIVE_SUPERVISORS:
                    continue

                # 1. Stuck "pending" claim older than 45s (client disconnected before agent create_run)
                if run_id == "pending":
                    ref_dt = conv.updated_at or conv.last_message_at or conv.created_at
                    if ref_dt and (now - ref_dt).total_seconds() > 45:
                        conv.active_run_id = None
                        conv.active_run_status = None
                        conv.pending_control = None
                        await db.commit()
                        reconciled += 1
                    continue

                # Skip if another server instance currently holds the writer lease
                try:
                    if await get_redis().exists(f"srv:run_writer:{run_id}"):
                        continue
                except Exception:
                    pass

                user = await db.get(User, conv.user_id)
                if user is None:
                    continue
                assistant = (
                    await db.execute(
                        select(Message).where(
                            Message.conversation_id == conv.id,
                            Message.run_id == run_id,
                            Message.role == "assistant",
                        )
                    )
                ).scalars().first()

                client = AgentClient(user.agent_namespace, user.agent_api_key)
                try:
                    run_info = await client.get_run(run_id)
                except AgentError as exc:
                    if exc.status_code == 404:
                        if assistant is not None and assistant.status in ("streaming", "waiting"):
                            assistant.status = "failed"
                        conv.active_run_id = None
                        conv.active_run_status = None
                        conv.pending_control = None
                        await db.commit()
                        reconciled += 1
                    continue

                status_str = str(run_info.get("status") or "")
                if status_str in ("completed", "failed", "cancelled", "interrupted"):
                    if assistant is not None:
                        final_out = run_info.get("output") or run_info.get("text")
                        if final_out:
                            assistant.content = str(final_out)
                        assistant.status = "completed" if status_str == "completed" else (
                            "failed" if status_str == "failed" else "cancelled"
                        )
                        extra = dict(assistant.tool_payload or {})
                        if run_info.get("usage"):
                            extra["usage"] = run_info["usage"]
                        if run_info.get("plan"):
                            extra["plan"] = run_info["plan"]
                            conv.plan = run_info["plan"]
                        if run_info.get("reasoning"):
                            extra["reasoning"] = run_info["reasoning"]
                        assistant.tool_payload = extra
                    conv.active_run_id = None
                    conv.active_run_status = None
                    conv.pending_control = None
                    await db.commit()
                    if assistant is not None:
                        await settle_usage_once(db, conv.user_id, assistant)
                    await realtime_bus.publish_user_event(
                        conv.user_id,
                        "conversation.run_updated",
                        {
                            "conversation_id": str(conv.id),
                            "active_run_id": None,
                            "active_run_status": None,
                            "last_status": status_str,
                            "pending_control": None,
                        },
                    )
                    reconciled += 1
                elif assistant is not None:
                    # Run is still live on agent-worker -> re-attach a background RunSupervisor!
                    logger.info("Re-attaching RunSupervisor to orphaned active run=%s conv=%s", run_id, conv.id)
                    start_supervised_run(
                        run_id=run_id,
                        conv_id=conv.id,
                        user_id=conv.user_id,
                        assistant_id=assistant.id,
                        user_msg_id=None,
                        user_content="",
                        client=client,
                        session_factory=SessionLocal,
                        started_at=assistant.created_at.timestamp() if assistant.created_at else time.time(),
                        max_seconds=get_settings().run_max_seconds,
                    )
                    reconciled += 1
    except Exception as exc:
        logger.debug("Orphan run reconciler skipped: %s", exc)
    return reconciled


async def _reconciler_loop() -> None:
    await asyncio.sleep(3.0)
    while True:
        await reconcile_orphaned_runs()
        await asyncio.sleep(30.0)


def start_reconciler() -> None:
    global _RECONCILER_TASK
    if _RECONCILER_TASK is None or _RECONCILER_TASK.done():
        _RECONCILER_TASK = asyncio.create_task(_reconciler_loop(), name="orphan-run-reconciler")


async def stop_reconciler_and_supervisors() -> None:
    global _RECONCILER_TASK
    if _RECONCILER_TASK is not None:
        _RECONCILER_TASK.cancel()
        try:
            await _RECONCILER_TASK
        except (asyncio.CancelledError, Exception):
            pass
        _RECONCILER_TASK = None
    # Give active supervisors up to 5s to flush current DB state on graceful server shutdown
    tasks = [s.task for s in list(_ACTIVE_SUPERVISORS.values()) if s.task is not None and not s.task.done()]
    if tasks:
        await asyncio.wait(tasks, timeout=5.0)
