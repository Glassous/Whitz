"""Scheduled tasks CRUD, pending proposals, atomic due-task claiming, and background execution."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.metrics import SCHEDULED_TASK_RUNS_TOTAL
from app.db.models import (
    Conversation,
    Message,
    ScheduledTask,
    ScheduledTaskPendingProposal,
    ScheduledTaskRun,
    User,
)
from app.db.session import SessionLocal
from app.services import limits, membership, realtime_bus, schedule_calc, usage
from app.services.agent_client import AgentClient, AgentError
from app.services.cross_chat_memory import ensure_main_conversation, load_cursor_aligned_history

logger = logging.getLogger("whitz.scheduler")

TIER_SCHEDULE_QUOTAS: dict[str, dict[str, int]] = {
    "free": {"max_active_tasks": 3, "min_interval_minutes": 60},
    "plus": {"max_active_tasks": 10, "min_interval_minutes": 15},
    "pro": {"max_active_tasks": 30, "min_interval_minutes": 5},
}

VALID_TARGET_MODES = frozenset({"dedicated", "main", "conversation"})
VALID_MODEL_ROUTES = frozenset({"auto", "default", "fast", "reasoning"})

_SCHEDULER_TASK: asyncio.Task[Any] | None = None
_BACKGROUND_RUN_TASKS: set[asyncio.Task[Any]] = set()


class ScheduleServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def quota_for_user(user: User) -> dict[str, Any]:
    tier = membership.effective_tier(user)
    cfg = TIER_SCHEDULE_QUOTAS.get(tier, TIER_SCHEDULE_QUOTAS["free"])
    return {
        "tier": tier,
        "max_active_tasks": cfg["max_active_tasks"],
        "min_interval_minutes": cfg["min_interval_minutes"],
    }


def _normalize_target_mode(raw: str | None) -> str:
    mode = (raw or "dedicated").strip().lower()
    if mode not in VALID_TARGET_MODES:
        raise ScheduleServiceError(422, f"无效的投递目标模式: {mode}")
    return mode


def _normalize_model_route(raw: str | None) -> str:
    route = (raw or "auto").strip().lower()
    if route not in VALID_MODEL_ROUTES:
        return "auto"
    return route


def _normalize_skills(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = str(item or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
        if len(out) >= 10:
            break
    return out


def serialize_task(task: ScheduledTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "conversation_id": task.conversation_id,
        "target_mode": task.target_mode,
        "name": task.name,
        "prompt": task.prompt,
        "schedule_type": task.schedule_type,
        "schedule_config": dict(task.schedule_config or {}),
        "schedule_description": schedule_calc.describe_schedule(
            task.schedule_type, task.schedule_config, task.timezone
        ),
        "timezone": task.timezone,
        "model_route": task.model_route,
        "skill_names": list(task.skill_names or []),
        "enabled": bool(task.enabled),
        "status": task.status,
        "next_run_at": task.next_run_at,
        "last_run_at": task.last_run_at,
        "last_run_status": task.last_run_status,
        "last_error": task.last_error,
        "run_count": int(task.run_count or 0),
        "consecutive_failures": int(task.consecutive_failures or 0),
        "max_runs": task.max_runs,
        "source": task.source,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def serialize_task_run(run: ScheduledTaskRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "conversation_id": run.conversation_id,
        "assistant_message_id": run.assistant_message_id,
        "run_id": run.run_id,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "scheduled_for": run.scheduled_for,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "summary": run.summary,
        "error": run.error,
        "tokens_used": int(run.tokens_used or 0),
    }


def serialize_pending_proposal(row: ScheduledTaskPendingProposal) -> dict[str, Any]:
    payload = dict(row.payload or {})
    schedule_type = str(payload.get("schedule_type") or "")
    schedule_config = payload.get("schedule_config") if isinstance(payload.get("schedule_config"), dict) else {}
    tz_name = str(payload.get("timezone") or "Asia/Shanghai")
    schedule_desc = ""
    if schedule_type:
        try:
            schedule_desc = schedule_calc.describe_schedule(schedule_type, schedule_config, tz_name)
        except Exception:
            schedule_desc = schedule_type
    return {
        "id": str(row.id),
        "target_task_id": str(row.target_task_id) if row.target_task_id else None,
        "conversation_id": row.conversation_id,
        "action": row.action,
        "payload": payload,
        "schedule_description": schedule_desc,
        "reason": row.reason,
        "status": row.status,
        "created_at": row.created_at,
    }


async def _count_active_tasks(db: AsyncSession, user_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None) -> int:
    stmt = select(func.count(ScheduledTask.id)).where(
        ScheduledTask.user_id == user_id,
        ScheduledTask.enabled.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(ScheduledTask.id != exclude_id)
    return int(await db.scalar(stmt) or 0)


async def _validate_target_conversation(
    db: AsyncSession,
    user: User,
    target_mode: str,
    conversation_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if target_mode == "main":
        main_conv = await ensure_main_conversation(db, user)
        return main_conv.id
    if target_mode == "conversation":
        if conversation_id is None:
            raise ScheduleServiceError(422, "指定会话投递模式必须提供 conversation_id")
        conv = await db.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user.id:
            raise ScheduleServiceError(404, "指定的目标会话不存在或无权访问")
        return conv.id
    # dedicated mode: either reuse existing owned side conversation or leave None until created
    if conversation_id is not None:
        conv = await db.get(Conversation, conversation_id)
        if conv is not None and conv.user_id == user.id and conv.kind == "side":
            return conv.id
    return None


async def list_pending(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ScheduledTaskPendingProposal)
            .where(
                ScheduledTaskPendingProposal.user_id == user_id,
                ScheduledTaskPendingProposal.status == "pending",
            )
            .order_by(ScheduledTaskPendingProposal.created_at.asc())
        )
    ).scalars().all()
    return [serialize_pending_proposal(r) for r in rows]


async def list_overview(db: AsyncSession, user: User) -> dict[str, Any]:
    quota = quota_for_user(user)
    rows = (
        await db.execute(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == user.id)
            .order_by(ScheduledTask.enabled.desc(), ScheduledTask.created_at.desc())
        )
    ).scalars().all()
    pending = await list_pending(db, user.id)
    active_count = sum(1 for r in rows if r.enabled)
    return {
        "tasks": [serialize_task(r) for r in rows],
        "pending": pending,
        "quota": {
            **quota,
            "active_count": active_count,
        },
    }


async def get_task_detail(
    db: AsyncSession,
    user: User,
    task_id: uuid.UUID,
    *,
    runs_limit: int = 20,
) -> dict[str, Any]:
    task = await db.get(ScheduledTask, task_id)
    if task is None or task.user_id != user.id:
        raise ScheduleServiceError(404, "定时任务不存在")
    runs = (
        await db.execute(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.task_id == task.id, ScheduledTaskRun.user_id == user.id)
            .order_by(ScheduledTaskRun.started_at.desc())
            .limit(max(1, min(runs_limit, 100)))
        )
    ).scalars().all()
    out = serialize_task(task)
    out["runs"] = [serialize_task_run(r) for r in runs]
    return out


async def create_task(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    prompt: str,
    schedule_type: str,
    schedule_config: dict[str, Any],
    timezone_name: str | None = None,
    target_mode: str = "dedicated",
    conversation_id: uuid.UUID | None = None,
    model_route: str = "auto",
    skill_names: list[str] | None = None,
    enabled: bool = True,
    max_runs: int | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    cleaned_name = (name or "").strip()
    cleaned_prompt = (prompt or "").strip()
    if not cleaned_name:
        raise ScheduleServiceError(422, "任务名称不能为空")
    if not cleaned_prompt:
        raise ScheduleServiceError(422, "执行提示词不能为空")

    quota = quota_for_user(user)
    if enabled:
        active_cnt = await _count_active_tasks(db, user.id)
        if active_cnt >= quota["max_active_tasks"]:
            raise ScheduleServiceError(
                400,
                f"当前 {quota['tier'].upper()} 档位最多启用 {quota['max_active_tasks']} 个定时任务",
            )

    tz_val = (timezone_name or "").strip() or (user.timezone or "Asia/Shanghai")
    try:
        stype, norm_cfg, tz_norm, next_run = schedule_calc.validate_and_normalize_schedule(
            schedule_type,
            schedule_config,
            tz_val,
            min_interval_minutes=quota["min_interval_minutes"],
        )
    except schedule_calc.ScheduleValidationError as exc:
        raise ScheduleServiceError(422, str(exc)) from exc

    tmode = _normalize_target_mode(target_mode)
    resolved_conv_id = await _validate_target_conversation(db, user, tmode, conversation_id)

    effective_max_runs = 1 if stype == "once" else max_runs
    task = ScheduledTask(
        user_id=user.id,
        conversation_id=resolved_conv_id,
        target_mode=tmode,
        name=cleaned_name[:120],
        prompt=cleaned_prompt,
        schedule_type=stype,
        schedule_config=norm_cfg,
        timezone=tz_norm,
        model_route=_normalize_model_route(model_route),
        skill_names=_normalize_skills(skill_names),
        enabled=bool(enabled),
        status="active" if enabled else "paused",
        next_run_at=next_run if enabled else None,
        max_runs=effective_max_runs,
        source=source or "manual",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    data = serialize_task(task)
    await realtime_bus.publish_user_event(
        user.id,
        "schedule.updated",
        {"action": "created", "task": data},
    )
    return data


async def update_task(
    db: AsyncSession,
    user: User,
    task_id: uuid.UUID,
    *,
    name: str | None = None,
    prompt: str | None = None,
    schedule_type: str | None = None,
    schedule_config: dict[str, Any] | None = None,
    timezone_name: str | None = None,
    target_mode: str | None = None,
    conversation_id: uuid.UUID | None = None,
    model_route: str | None = None,
    skill_names: list[str] | None = None,
    enabled: bool | None = None,
    max_runs: int | None = None,
) -> dict[str, Any]:
    task = await db.get(ScheduledTask, task_id)
    if task is None or task.user_id != user.id:
        raise ScheduleServiceError(404, "定时任务不存在")

    quota = quota_for_user(user)
    next_enabled = task.enabled if enabled is None else bool(enabled)
    if next_enabled and not task.enabled:
        active_cnt = await _count_active_tasks(db, user.id, exclude_id=task.id)
        if active_cnt >= quota["max_active_tasks"]:
            raise ScheduleServiceError(
                400,
                f"当前 {quota['tier'].upper()} 档位最多启用 {quota['max_active_tasks']} 个定时任务",
            )

    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise ScheduleServiceError(422, "任务名称不能为空")
        task.name = cleaned[:120]

    if prompt is not None:
        cleaned = prompt.strip()
        if not cleaned:
            raise ScheduleServiceError(422, "执行提示词不能为空")
        task.prompt = cleaned

    if model_route is not None:
        task.model_route = _normalize_model_route(model_route)

    if skill_names is not None:
        task.skill_names = _normalize_skills(skill_names)

    if target_mode is not None or conversation_id is not None:
        tmode = _normalize_target_mode(target_mode if target_mode is not None else task.target_mode)
        conv_candidate = conversation_id if conversation_id is not None else task.conversation_id
        task.target_mode = tmode
        task.conversation_id = await _validate_target_conversation(db, user, tmode, conv_candidate)

    schedule_changed = (
        schedule_type is not None or schedule_config is not None or timezone_name is not None
    )
    stype_in = schedule_type if schedule_type is not None else task.schedule_type
    scfg_in = schedule_config if schedule_config is not None else dict(task.schedule_config or {})
    tz_in = timezone_name if timezone_name is not None else task.timezone

    if schedule_changed or (next_enabled and not task.enabled):
        try:
            stype, norm_cfg, tz_norm, next_run = schedule_calc.validate_and_normalize_schedule(
                stype_in,
                scfg_in,
                tz_in,
                min_interval_minutes=quota["min_interval_minutes"],
            )
        except schedule_calc.ScheduleValidationError as exc:
            raise ScheduleServiceError(422, str(exc)) from exc
        task.schedule_type = stype
        task.schedule_config = norm_cfg
        task.timezone = tz_norm
        if next_enabled:
            task.next_run_at = next_run

    if max_runs is not None:
        task.max_runs = 1 if task.schedule_type == "once" else max_runs

    task.enabled = next_enabled
    if next_enabled:
        task.status = "active"
        task.consecutive_failures = 0
        task.last_error = None
        if task.next_run_at is None:
            task.next_run_at = schedule_calc.compute_next_run_at(
                task.schedule_type, task.schedule_config, task.timezone
            )
    else:
        task.status = "paused"
        task.next_run_at = None

    await db.commit()
    await db.refresh(task)
    data = serialize_task(task)
    await realtime_bus.publish_user_event(
        user.id,
        "schedule.updated",
        {"action": "updated", "task": data},
    )
    return data


async def delete_task(db: AsyncSession, user: User, task_id: uuid.UUID) -> None:
    task = await db.get(ScheduledTask, task_id)
    if task is None or task.user_id != user.id:
        raise ScheduleServiceError(404, "定时任务不存在")
    tid = str(task.id)
    await db.delete(task)
    await db.commit()
    await realtime_bus.publish_user_event(
        user.id,
        "schedule.updated",
        {"action": "deleted", "task_id": tid},
    )


async def create_proposal(
    db: AsyncSession,
    user: User,
    *,
    action: str,
    payload: dict[str, Any],
    target_task_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    act = (action or "create").strip().lower()
    if act not in ("create", "update", "pause", "resume", "delete"):
        raise ScheduleServiceError(422, f"不支持的定时任务操作: {act}")

    quota = quota_for_user(user)
    clean_payload = dict(payload or {})

    if act == "create":
        name = str(clean_payload.get("name") or "").strip()
        prompt = str(clean_payload.get("prompt") or "").strip()
        if not name or not prompt:
            raise ScheduleServiceError(422, "创建定时任务必须提供 name 与 prompt")
        active_cnt = await _count_active_tasks(db, user.id)
        if active_cnt >= quota["max_active_tasks"]:
            raise ScheduleServiceError(
                400,
                f"当前 {quota['tier'].upper()} 档位最多启用 {quota['max_active_tasks']} 个定时任务",
            )
        tz_val = str(clean_payload.get("timezone") or "").strip() or (user.timezone or "Asia/Shanghai")
        try:
            stype, norm_cfg, tz_norm, _ = schedule_calc.validate_and_normalize_schedule(
                str(clean_payload.get("schedule_type") or ""),
                clean_payload.get("schedule_config") if isinstance(clean_payload.get("schedule_config"), dict) else {},
                tz_val,
                min_interval_minutes=quota["min_interval_minutes"],
            )
        except schedule_calc.ScheduleValidationError as exc:
            raise ScheduleServiceError(422, str(exc)) from exc
        clean_payload["name"] = name[:120]
        clean_payload["prompt"] = prompt
        clean_payload["schedule_type"] = stype
        clean_payload["schedule_config"] = norm_cfg
        clean_payload["timezone"] = tz_norm
        clean_payload["target_mode"] = _normalize_target_mode(clean_payload.get("target_mode"))
        clean_payload["model_route"] = _normalize_model_route(clean_payload.get("model_route"))
    else:
        if target_task_id is None:
            raise ScheduleServiceError(422, "修改、启停或删除定时任务必须提供 task_id")
        task = await db.get(ScheduledTask, target_task_id)
        if task is None or task.user_id != user.id:
            raise ScheduleServiceError(404, "定时任务不存在")
        clean_payload.setdefault("name", task.name)
        clean_payload.setdefault("schedule_type", task.schedule_type)
        clean_payload.setdefault("schedule_config", dict(task.schedule_config or {}))
        clean_payload.setdefault("timezone", task.timezone)
        if act == "update" and ("schedule_type" in payload or "schedule_config" in payload or "timezone" in payload):
            try:
                stype, norm_cfg, tz_norm, _ = schedule_calc.validate_and_normalize_schedule(
                    str(clean_payload.get("schedule_type") or task.schedule_type),
                    clean_payload.get("schedule_config") if isinstance(clean_payload.get("schedule_config"), dict) else {},
                    str(clean_payload.get("timezone") or task.timezone),
                    min_interval_minutes=quota["min_interval_minutes"],
                )
            except schedule_calc.ScheduleValidationError as exc:
                raise ScheduleServiceError(422, str(exc)) from exc
            clean_payload["schedule_type"] = stype
            clean_payload["schedule_config"] = norm_cfg
            clean_payload["timezone"] = tz_norm

    row = ScheduledTaskPendingProposal(
        user_id=user.id,
        conversation_id=conversation_id,
        target_task_id=target_task_id,
        action=act,
        payload=clean_payload,
        reason=(reason or "").strip()[:500] or None,
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    serialized = serialize_pending_proposal(row)
    await realtime_bus.publish_user_event(
        user.id,
        "schedule.pending_updated",
        {"action": "created", "proposal": serialized},
    )
    return serialized


async def resolve_proposal(
    db: AsyncSession,
    user: User,
    proposal_id: uuid.UUID,
    decision: str,
) -> dict[str, Any]:
    row = await db.get(ScheduledTaskPendingProposal, proposal_id)
    if row is None or row.user_id != user.id:
        raise ScheduleServiceError(404, "待确认定时任务提案不存在")
    if row.status != "pending":
        raise ScheduleServiceError(409, "该提案已被处理")

    act = (decision or "").strip().lower()
    if act not in ("approve", "reject"):
        raise ScheduleServiceError(422, "仅支持 approve 或 reject")

    if act == "reject":
        row.status = "rejected"
        await db.commit()
        await realtime_bus.publish_user_event(
            user.id,
            "schedule.pending_updated",
            {"action": "rejected", "proposal_id": str(row.id)},
        )
        return {"status": "rejected", "proposal_id": str(row.id), "task": None}

    p = dict(row.payload or {})
    task_out: dict[str, Any] | None = None
    if row.action == "create":
        conv_uuid: uuid.UUID | None = None
        if p.get("conversation_id"):
            try:
                conv_uuid = uuid.UUID(str(p["conversation_id"]))
            except ValueError:
                conv_uuid = None
        task_out = await create_task(
            db,
            user,
            name=str(p.get("name") or "定时任务"),
            prompt=str(p.get("prompt") or ""),
            schedule_type=str(p.get("schedule_type") or "daily"),
            schedule_config=p.get("schedule_config") if isinstance(p.get("schedule_config"), dict) else {},
            timezone_name=p.get("timezone"),
            target_mode=str(p.get("target_mode") or "dedicated"),
            conversation_id=conv_uuid,
            model_route=str(p.get("model_route") or "auto"),
            skill_names=p.get("skill_names") if isinstance(p.get("skill_names"), list) else None,
            max_runs=p.get("max_runs") if isinstance(p.get("max_runs"), int) else None,
            enabled=True,
            source="agent",
        )
    elif row.action in ("update", "pause", "resume"):
        if row.target_task_id is None:
            raise ScheduleServiceError(404, "关联定时任务不存在")
        enabled_override = p.get("enabled")
        if row.action == "pause":
            enabled_override = False
        elif row.action == "resume":
            enabled_override = True
        conv_uuid_upd: uuid.UUID | None = None
        if p.get("conversation_id"):
            try:
                conv_uuid_upd = uuid.UUID(str(p["conversation_id"]))
            except ValueError:
                conv_uuid_upd = None
        task_out = await update_task(
            db,
            user,
            row.target_task_id,
            name=p.get("name") if "name" in p else None,
            prompt=p.get("prompt") if "prompt" in p else None,
            schedule_type=p.get("schedule_type") if "schedule_type" in p else None,
            schedule_config=p.get("schedule_config") if isinstance(p.get("schedule_config"), dict) else None,
            timezone_name=p.get("timezone") if "timezone" in p else None,
            target_mode=p.get("target_mode") if "target_mode" in p else None,
            conversation_id=conv_uuid_upd,
            model_route=p.get("model_route") if "model_route" in p else None,
            skill_names=p.get("skill_names") if isinstance(p.get("skill_names"), list) else None,
            max_runs=p.get("max_runs") if isinstance(p.get("max_runs"), int) else None,
            enabled=enabled_override if enabled_override is not None else None,
        )
    elif row.action == "delete":
        if row.target_task_id is None:
            raise ScheduleServiceError(404, "关联定时任务不存在")
        await delete_task(db, user, row.target_task_id)

    row.status = "approved"
    await db.commit()
    await realtime_bus.publish_user_event(
        user.id,
        "schedule.pending_updated",
        {"action": "approved", "proposal_id": str(row.id)},
    )
    return {"status": "approved", "proposal_id": str(row.id), "task": task_out}


async def _resolve_or_create_target_conversation(
    db: AsyncSession,
    user: User,
    task: ScheduledTask,
) -> Conversation:
    mode = (task.target_mode or "dedicated").lower()
    if mode == "main":
        return await ensure_main_conversation(db, user)

    if task.conversation_id is not None:
        conv = await db.get(Conversation, task.conversation_id)
        if conv is not None and conv.user_id == user.id:
            if mode == "conversation" or conv.kind == "side":
                return conv

    conv = Conversation(
        user_id=user.id,
        kind="side",
        title=f"[定时] {task.name}"[:200],
        is_scheduled=True,
        thread_id=str(uuid.uuid4()),
    )
    db.add(conv)
    await db.flush()
    task.conversation_id = conv.id
    await db.commit()
    await db.refresh(conv)
    await realtime_bus.publish_user_event(
        user.id,
        "conversation.updated",
        {
            "action": "created",
            "conversation_id": str(conv.id),
            "title": conv.title,
            "kind": conv.kind,
            "is_scheduled": True,
        },
    )
    return conv


async def _mark_run_skipped(
    db: AsyncSession,
    task: ScheduledTask,
    task_run: ScheduledTaskRun,
    reason: str,
) -> None:
    now = datetime.now(timezone.utc)
    task_run.status = "skipped"
    task_run.finished_at = now
    task_run.error = reason[:500]
    task.last_run_status = "skipped"
    task.last_error = reason[:500]
    await db.commit()
    await db.refresh(task_run)
    await db.refresh(task)
    SCHEDULED_TASK_RUNS_TOTAL.labels(trigger=task_run.trigger_type, status="skipped").inc()
    await realtime_bus.publish_user_event(
        task.user_id,
        "schedule.run_updated",
        {"task_id": str(task.id), "run": serialize_task_run(task_run), "task": serialize_task(task)},
    )


async def _execute_claimed_task_run(
    session_factory: Callable[[], Any],
    task_run_id: uuid.UUID,
) -> None:
    from app.services import chat_stream

    run_slot: str | None = None
    user_id_for_slot: uuid.UUID | None = None
    handed_off = False
    conv_claimed = False
    conv_id_claimed: uuid.UUID | None = None

    try:
        async with session_factory() as db:
            task_run = await db.get(ScheduledTaskRun, task_run_id)
            if task_run is None:
                return
            task = await db.get(ScheduledTask, task_run.task_id)
            user = await db.get(User, task_run.user_id)
            if task is None or user is None:
                return
            user_id_for_slot = user.id

            if not user.is_active:
                await _mark_run_skipped(db, task, task_run, "用户账号已停用")
                return

            credits = await membership.status(db, user)
            if credits["remaining"] <= 0:
                await _mark_run_skipped(db, task, task_run, "积分已用尽，本次定时执行已跳过")
                return

            plan = membership.plan_for(membership.effective_tier(user))
            run_slot = await limits.acquire_run(user.id, plan.max_runs_per_user)
            if run_slot is None:
                await _mark_run_skipped(db, task, task_run, "当前任务并发已满，本次定时执行已跳过")
                return

            conv = await _resolve_or_create_target_conversation(db, user, task)
            now = datetime.now(timezone.utc)
            claimed = await db.execute(
                update(Conversation)
                .where(Conversation.id == conv.id, Conversation.active_run_id.is_(None))
                .values(
                    active_run_id="pending",
                    active_run_status="starting",
                    pending_control=None,
                    last_message_at=now,
                )
            )
            await db.commit()
            if not claimed.rowcount:
                # Target conversation is busy: retry in 60s for scheduled runs instead of losing the execution
                if task_run.trigger_type == "scheduled" and task.enabled and task.status == "active":
                    retry_at = now + timedelta(seconds=60)
                    if task.next_run_at is None or task.next_run_at > retry_at:
                        task.next_run_at = retry_at
                await _mark_run_skipped(db, task, task_run, "目标会话正在执行其他任务，将于 60 秒后重试")
                return

            conv_claimed = True
            conv_id_claimed = conv.id
            await db.refresh(conv)
            if not conv.thread_id:
                conv.thread_id = str(uuid.uuid4())
                await db.commit()

            client = AgentClient(user.agent_namespace, user.agent_api_key)
            prompt_display = f"[定时任务 · {task.name}]\n{task.prompt}"
            history = await load_cursor_aligned_history(db, conv)
            turn_ctx = await chat_stream._prepare_turn_context(
                db,
                user,
                conv,
                file_ids=None,
                skill_names=list(task.skill_names or []),
                query_text=task.prompt,
            )
            user_payload = dict(turn_ctx.get("user_payload") or {})
            user_payload["scheduled_task"] = {
                "task_id": str(task.id),
                "name": task.name,
                "schedule_run_id": str(task_run.id),
                "trigger_type": task_run.trigger_type,
            }

            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=prompt_display,
                tool_payload=user_payload,
                status="completed",
                created_at=now,
            )
            assistant = Message(
                conversation_id=conv.id,
                role="assistant",
                content="",
                status="streaming",
                created_at=now.replace(microsecond=min(999000, now.microsecond + 1000)),
            )
            db.add_all([user_msg, assistant])
            conv.plan = None
            conv.last_message_at = now
            await db.commit()
            await usage.record_message(db, user.id)

            task_run.conversation_id = conv.id
            task_run.assistant_message_id = assistant.id
            task_run.status = "running"
            task.run_count = int(task.run_count or 0) + 1
            task.last_run_at = now
            task.last_run_status = "running"
            await db.commit()

            try:
                _sup, _q, run_id = await chat_stream._launch_supervised_turn(
                    db,
                    client,
                    conv,
                    user,
                    assistant,
                    user_msg.id,
                    task.prompt,
                    turn_ctx,
                    conversation_history=history or None,
                    model_route=task.model_route or "auto",
                    max_seconds=plan.run_max_seconds,
                    max_tool_iterations=plan.max_tool_iterations,
                    run_slot=run_slot,
                    idempotency_key=f"sched-{task_run.id}",
                    allow_hitl=False,
                    scheduled_run_id=task_run.id,
                )
                handed_off = True
                task_run.run_id = run_id
                await db.commit()
                await db.refresh(task_run)
                await db.refresh(task)
                await realtime_bus.publish_user_event(
                    user.id,
                    "schedule.run_updated",
                    {"task_id": str(task.id), "run": serialize_task_run(task_run), "task": serialize_task(task)},
                )
            except (AgentError, Exception) as exc:
                assistant.status = "failed"
                await db.execute(
                    update(Conversation)
                    .where(Conversation.id == conv.id, Conversation.active_run_id == "pending")
                    .values(active_run_id=None, active_run_status=None, pending_control=None)
                )
                conv_claimed = False
                await db.commit()
                await client.aclose()
                await finalize_scheduled_run(
                    db,
                    scheduled_run_id=task_run.id,
                    status="failed",
                    output="",
                    error=str(exc),
                    tokens_used=0,
                )
    except Exception as exc:
        logger.exception("Scheduled run %s dispatch failed", task_run_id)
        try:
            async with session_factory() as err_db:
                if conv_claimed and conv_id_claimed is not None:
                    await err_db.execute(
                        update(Conversation)
                        .where(Conversation.id == conv_id_claimed, Conversation.active_run_id == "pending")
                        .values(active_run_id=None, active_run_status=None, pending_control=None)
                    )
                await finalize_scheduled_run(
                    err_db,
                    scheduled_run_id=task_run_id,
                    status="failed",
                    output="",
                    error=str(exc),
                    tokens_used=0,
                )
        except Exception:
            logger.debug("Failed to record scheduled run failure", exc_info=True)
    finally:
        if run_slot and user_id_for_slot is not None and not handed_off:
            await limits.release_run(user_id_for_slot, run_slot)


async def finalize_scheduled_run(
    db: AsyncSession,
    *,
    scheduled_run_id: uuid.UUID,
    status: str,
    output: str = "",
    error: str | None = None,
    tokens_used: int = 0,
) -> None:
    task_run = await db.get(ScheduledTaskRun, scheduled_run_id)
    if task_run is None:
        return
    if task_run.status in ("completed", "failed", "cancelled", "skipped"):
        return

    now = datetime.now(timezone.utc)
    norm_status = status if status in ("completed", "failed", "cancelled", "skipped") else "failed"
    task_run.status = norm_status
    task_run.finished_at = now
    if output:
        collapsed = " ".join(output.split())
        task_run.summary = (collapsed[:397] + "…") if len(collapsed) > 400 else collapsed
    if error:
        task_run.error = str(error)[:500]
    task_run.tokens_used = max(0, int(tokens_used or 0))

    task = await db.get(ScheduledTask, task_run.task_id)
    if task is not None:
        task.last_run_at = now
        task.last_run_status = norm_status
        if norm_status == "completed":
            task.consecutive_failures = 0
            task.last_error = None
            reached_cap = task.max_runs is not None and int(task.run_count or 0) >= int(task.max_runs)
            if task.schedule_type == "once" or reached_cap:
                task.enabled = False
                task.status = "completed"
                task.next_run_at = None
        elif norm_status == "failed":
            task.consecutive_failures = int(task.consecutive_failures or 0) + 1
            task.last_error = task_run.error or "执行失败"
            max_fail = max(1, int(get_settings().scheduler_max_consecutive_failures))
            if task.consecutive_failures >= max_fail:
                task.enabled = False
                task.status = "error"
                task.next_run_at = None
        elif norm_status == "cancelled":
            task.last_error = "任务被取消"

    await db.commit()
    await db.refresh(task_run)
    if task is not None:
        await db.refresh(task)
    SCHEDULED_TASK_RUNS_TOTAL.labels(trigger=task_run.trigger_type, status=norm_status).inc()
    if task is not None:
        await realtime_bus.publish_user_event(
            task.user_id,
            "schedule.run_updated",
            {"task_id": str(task.id), "run": serialize_task_run(task_run), "task": serialize_task(task)},
        )


def _track_background_task(coro: Any, *, name: str) -> asyncio.Task[Any]:
    t = asyncio.create_task(coro, name=name)
    _BACKGROUND_RUN_TASKS.add(t)
    t.add_done_callback(_BACKGROUND_RUN_TASKS.discard)
    return t


async def trigger_task_now(
    db: AsyncSession,
    user: User,
    task_id: uuid.UUID,
    *,
    session_factory: Callable[[], Any] | None = None,
    dispatch_async: bool = True,
) -> dict[str, Any]:
    task = await db.get(ScheduledTask, task_id)
    if task is None or task.user_id != user.id:
        raise ScheduleServiceError(404, "定时任务不存在")

    now = datetime.now(timezone.utc)
    task_run = ScheduledTaskRun(
        task_id=task.id,
        user_id=user.id,
        conversation_id=task.conversation_id,
        trigger_type="manual",
        status="queued",
        scheduled_for=now,
        started_at=now,
    )
    db.add(task_run)
    task.last_run_at = now
    task.last_run_status = "running"
    await db.commit()
    await db.refresh(task_run)
    await db.refresh(task)

    factory = session_factory or SessionLocal
    if dispatch_async:
        _track_background_task(
            _execute_claimed_task_run(factory, task_run.id),
            name=f"sched-manual-{task_run.id}",
        )
    else:
        await _execute_claimed_task_run(factory, task_run.id)
        await db.refresh(task_run)
    return serialize_task_run(task_run)


async def dispatch_due_tasks(
    *,
    session_factory: Callable[[], Any] | None = None,
    now: datetime | None = None,
    batch_size: int | None = None,
    execute_inline: bool = False,
) -> int:
    """Atomically claim due scheduled tasks with SKIP LOCKED and dispatch executions."""
    factory = session_factory or SessionLocal
    settings = get_settings()
    limit_n = max(1, int(batch_size or settings.scheduler_batch_size))
    current = now or datetime.now(timezone.utc)
    claimed_run_ids: list[uuid.UUID] = []

    async with factory() as db:
        stmt = (
            select(ScheduledTask)
            .where(
                ScheduledTask.enabled.is_(True),
                ScheduledTask.status == "active",
                ScheduledTask.next_run_at.is_not(None),
                ScheduledTask.next_run_at <= current,
            )
            .order_by(ScheduledTask.next_run_at.asc())
            .limit(limit_n)
            .with_for_update(skip_locked=True)
        )
        due_tasks = list((await db.execute(stmt)).scalars().all())
        for task in due_tasks:
            scheduled_for = task.next_run_at or current
            task.last_run_at = current
            task.last_run_status = "running"

            if task.schedule_type == "once":
                # Keep enabled=True until execution completes, but clear next_run_at so it isn't double-claimed
                task.next_run_at = None
            else:
                try:
                    task.next_run_at = schedule_calc.compute_next_run_at(
                        task.schedule_type,
                        task.schedule_config or {},
                        task.timezone,
                        after_dt=current,
                    )
                except schedule_calc.ScheduleValidationError as exc:
                    task.enabled = False
                    task.status = "error"
                    task.next_run_at = None
                    task.last_error = str(exc)[:500]
                if task.next_run_at is None and task.status == "active":
                    task.enabled = False
                    task.status = "completed"

            run_row = ScheduledTaskRun(
                task_id=task.id,
                user_id=task.user_id,
                conversation_id=task.conversation_id,
                trigger_type="scheduled",
                status="queued",
                scheduled_for=scheduled_for,
                started_at=current,
            )
            db.add(run_row)
            await db.flush()
            claimed_run_ids.append(run_row.id)

        if claimed_run_ids:
            await db.commit()

    if execute_inline:
        for rid in claimed_run_ids:
            await _execute_claimed_task_run(factory, rid)
    else:
        for rid in claimed_run_ids:
            _track_background_task(
                _execute_claimed_task_run(factory, rid),
                name=f"sched-due-{rid}",
            )
    return len(claimed_run_ids)


async def cancel_task_run(
    db: AsyncSession,
    user: User,
    task_id: uuid.UUID,
    task_run_id: uuid.UUID,
) -> dict[str, Any]:
    """Cancel a queued or running scheduled task execution."""
    task = await db.get(ScheduledTask, task_id)
    if task is None or task.user_id != user.id:
        raise ScheduleServiceError(404, "定时任务不存在")
    task_run = await db.get(ScheduledTaskRun, task_run_id)
    if task_run is None or task_run.task_id != task.id or task_run.user_id != user.id:
        raise ScheduleServiceError(404, "执行记录不存在")
    if task_run.status in ("completed", "failed", "cancelled", "skipped"):
        return serialize_task_run(task_run)

    if task_run.run_id:
        from app.services import run_supervisor

        await run_supervisor.cancel_local_supervisor(task_run.run_id)
        client = AgentClient(user.agent_namespace, user.agent_api_key)
        try:
            await client.cancel_run(task_run.run_id)
        except Exception:
            pass
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    await finalize_scheduled_run(
        db,
        scheduled_run_id=task_run.id,
        status="cancelled",
        error="用户手动取消执行",
    )
    await db.refresh(task_run)
    return serialize_task_run(task_run)


async def recover_stale_scheduled_runs(
    *,
    session_factory: Callable[[], Any] | None = None,
) -> int:
    """Recover queued/running ScheduledTaskRun rows orphaned by a server crash."""
    factory = session_factory or SessionLocal
    stale_seconds = max(600, int(get_settings().run_max_seconds or 1200) + 300)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    recovered = 0
    try:
        async with factory() as db:
            rows = list(
                (
                    await db.execute(
                        select(ScheduledTaskRun).where(
                            ScheduledTaskRun.status.in_(("queued", "running")),
                            ScheduledTaskRun.started_at < cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for run in rows:
                await finalize_scheduled_run(
                    db,
                    scheduled_run_id=run.id,
                    status="failed",
                    error="执行超时或服务重启导致中断，已自动恢复",
                )
                recovered += 1
    except Exception as exc:
        logger.debug("Stale scheduled run recovery skipped: %s", exc)
    return recovered


async def _scheduler_loop() -> None:
    await asyncio.sleep(4.0)
    await recover_stale_scheduled_runs()
    while True:
        settings = get_settings()
        if settings.scheduler_enabled:
            try:
                await dispatch_due_tasks()
            except Exception as exc:
                logger.warning("Scheduler tick failed: %s", exc)
        await asyncio.sleep(max(2.0, float(settings.scheduler_poll_interval_seconds)))


def start_scheduler() -> None:
    global _SCHEDULER_TASK
    if not get_settings().scheduler_enabled:
        return
    if _SCHEDULER_TASK is None or _SCHEDULER_TASK.done():
        _SCHEDULER_TASK = asyncio.create_task(_scheduler_loop(), name="scheduled-tasks-dispatcher")


async def stop_scheduler() -> None:
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK is not None:
        _SCHEDULER_TASK.cancel()
        try:
            await _SCHEDULER_TASK
        except (asyncio.CancelledError, Exception):
            pass
        _SCHEDULER_TASK = None
    if _BACKGROUND_RUN_TASKS:
        await asyncio.wait(list(_BACKGROUND_RUN_TASKS), timeout=3.0)
