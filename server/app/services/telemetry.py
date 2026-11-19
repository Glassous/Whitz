from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import record_run_metrics
from app.db.models import Message, RunTelemetry
from app.services import usage

logger = logging.getLogger(__name__)


def _int_or_zero(value: Any) -> int:
    return max(0, int(value)) if isinstance(value, (int, float)) else 0


def extract_token_breakdown(usage_dict: Any) -> tuple[int, int, int]:
    if not isinstance(usage_dict, dict):
        return 0, 0, 0
    prompt = _int_or_zero(usage_dict.get("prompt_tokens") or usage_dict.get("input_tokens"))
    completion = _int_or_zero(usage_dict.get("completion_tokens") or usage_dict.get("output_tokens"))
    total = _int_or_zero(usage_dict.get("total_tokens"))
    if total <= 0:
        total = prompt + completion
    return prompt, completion, total


def extract_tools_summary(tool_payload: dict[str, Any] | None) -> tuple[int, int, list[dict[str, Any]]]:
    if not isinstance(tool_payload, dict):
        return 0, 0, []
    reasoning = tool_payload.get("reasoning")
    if not isinstance(reasoning, list):
        return 0, 0, []

    stats: dict[str, dict[str, Any]] = {}
    total_calls = 0
    total_errors = 0
    for block in reasoning:
        if not isinstance(block, dict):
            continue
        tools = block.get("tools")
        if not isinstance(tools, list):
            continue
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("tool") or item.get("name") or "unknown").strip() or "unknown"
            status = str(item.get("status") or "").lower()
            is_error = status in ("error", "failed", "denied") or bool(item.get("error"))
            dur = item.get("duration_ms")
            if dur is None:
                dur = item.get("duration")
            dur_ms = int(dur) if isinstance(dur, (int, float)) and dur >= 0 else 0

            entry = stats.setdefault(name, {"name": name, "calls": 0, "errors": 0, "total_duration_ms": 0})
            entry["calls"] += 1
            if is_error:
                entry["errors"] += 1
                total_errors += 1
            entry["total_duration_ms"] += dur_ms
            total_calls += 1

    summary = sorted(stats.values(), key=lambda x: (-x["calls"], x["name"]))
    return total_calls, total_errors, summary


async def record_run_telemetry(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    assistant: Message,
    run_id: str | None,
    status: str | None = None,
    ttft_ms: int | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
) -> None:
    eff_run_id = (run_id or assistant.run_id or "").strip() or str(assistant.id)
    payload = assistant.tool_payload if isinstance(assistant.tool_payload, dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}

    route = str(runtime.get("route") or "auto").strip() or "auto"
    model_name = str(runtime.get("model") or "").strip()
    eff_status = (status or assistant.status or "completed").strip() or "completed"

    prompt_tokens, completion_tokens, total_tokens = extract_token_breakdown(payload.get("usage"))
    if total_tokens <= 0:
        total_tokens = usage.tokens_from_usage(payload.get("usage"))

    tool_calls_count, tool_errors_count, tools_summary = extract_tools_summary(payload)
    skills_raw = payload.get("skills")
    skills_used = [str(s) for s in skills_raw] if isinstance(skills_raw, list) else None

    if ttft_ms is None and isinstance(runtime.get("ttft_ms"), (int, float)):
        ttft_ms = max(0, int(runtime["ttft_ms"]))
    if duration_ms is None and isinstance(runtime.get("duration_ms"), (int, float)):
        duration_ms = max(0, int(runtime["duration_ms"]))

    record_run_metrics(
        route=route,
        status=eff_status,
        duration_ms=duration_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tools_summary=tools_summary,
    )

    try:
        stmt = (
            insert(RunTelemetry)
            .values(
                id=uuid.uuid4(),
                run_id=eff_run_id[:128],
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=assistant.id,
                model_route=route[:32],
                model_name=model_name[:120],
                status=eff_status[:24],
                ttft_ms=ttft_ms,
                duration_ms=duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=0.0,
                tool_calls_count=tool_calls_count,
                tool_errors_count=tool_errors_count,
                tools_summary=tools_summary or None,
                skills_used=skills_used,
                error_code=error_code[:80] if error_code else None,
            )
            .on_conflict_do_nothing(index_elements=[RunTelemetry.run_id])
        )
        await db.execute(stmt)
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to record run_telemetry run_id=%s: %s", eff_run_id, exc)
        await db.rollback()
