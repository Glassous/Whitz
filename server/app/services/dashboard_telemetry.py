"""Aggregation service for Scheduled Tasks, Curl/HTTP/Sandbox tools, and Web Search dashboards."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    Message,
    RunTelemetry,
    ScheduledTask,
    ScheduledTaskPendingProposal,
    ScheduledTaskRun,
    User,
)
from app.services import schedule_calc

_CURL_CMD_RE = re.compile(r"(?:^|[\s;|&`(])(curl|wget|http)\b", re.IGNORECASE)
_JSON_OK_RE = re.compile(r'"ok"\s*:\s*(true|false)', re.IGNORECASE)
_JSON_STATUS_CODE_RE = re.compile(r'"status_code"\s*:\s*(\d{3})')
_JSON_PROVIDER_RE = re.compile(r'"provider"\s*:\s*"([^"]{1,40})"')
_JSON_FALLBACK_RE = re.compile(r'"fallback_from"\s*:\s*"([^"]{1,40})"')
_JSON_RESULT_COUNT_RE = re.compile(r'"result_count"\s*:\s*(\d+)')
_JSON_EXIT_CODE_RE = re.compile(r'"exit_code"\s*:\s*(-?\d+)')
_JSON_ERROR_RE = re.compile(r'"error"\s*:\s*"([^"]{1,300})"')
_JSON_BYTES_RE = re.compile(r'"bytes_read"\s*:\s*(\d+)')
_JSON_ELAPSED_RE = re.compile(r'"elapsed_ms"\s*:\s*(\d+)')


def _window_bounds(days: int) -> tuple[datetime, date, date, datetime]:
    clamped = max(1, min(int(days or 14), 90))
    now = datetime.now(timezone.utc)
    end_day = now.date()
    start_day = end_day - timedelta(days=clamped - 1)
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    return now, start_day, end_day, window_start


def _aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _day_iso(dt: datetime | None) -> str:
    aware = _aware_utc(dt)
    return aware.date().isoformat() if aware is not None else ""


def _rate_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def _avg_opt(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    pos = (len(ordered) - 1) * max(0.0, min(1.0, q))
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return round(ordered[lo], 1)
    frac = pos - lo
    return round(ordered[lo] * (1.0 - frac) + ordered[hi] * frac, 1)


def _sanitize_url(raw_url: str) -> tuple[str, str]:
    cleaned = (raw_url or "").strip()
    if not cleaned:
        return "unknown", ""
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return "invalid", cleaned[:200]
    host = (parsed.hostname or "unknown").lower()
    scheme = parsed.scheme or "https"
    port_part = f":{parsed.port}" if parsed.port else ""
    path_part = parsed.path or "/"
    safe_url = f"{scheme}://{host}{port_part}{path_part}"
    if len(safe_url) > 240:
        safe_url = safe_url[:237] + "..."
    return host, safe_url


def _unwrap_tool_text(text: str) -> str:
    raw = text.strip()
    if raw.startswith("<untrusted_tool_result"):
        end_tag = raw.find(">")
        if end_tag >= 0:
            raw = raw[end_tag + 1 :]
    suffix = "</untrusted_tool_result>"
    if raw.rstrip().endswith(suffix):
        raw = raw.rstrip()[: -len(suffix)]
    return raw.strip()


def _parse_json_obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    text = _unwrap_tool_text(raw)
    start = text.find("{")
    if start >= 0:
        candidate = text[start:]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    # Regex fallback for truncated JSON payloads (>24k chars)
    extracted: dict[str, Any] = {}
    if m := _JSON_OK_RE.search(text):
        extracted["ok"] = m.group(1).lower() == "true"
    if m := _JSON_STATUS_CODE_RE.search(text):
        extracted["status_code"] = int(m.group(1))
    if m := _JSON_PROVIDER_RE.search(text):
        extracted["provider"] = m.group(1)
    if m := _JSON_FALLBACK_RE.search(text):
        extracted["fallback_from"] = m.group(1)
    if m := _JSON_RESULT_COUNT_RE.search(text):
        extracted["result_count"] = int(m.group(1))
    if m := _JSON_EXIT_CODE_RE.search(text):
        extracted["exit_code"] = int(m.group(1))
    if m := _JSON_ERROR_RE.search(text):
        extracted["error"] = m.group(1)
    if m := _JSON_BYTES_RE.search(text):
        extracted["bytes_read"] = int(m.group(1))
    if m := _JSON_ELAPSED_RE.search(text):
        extracted["elapsed_ms"] = int(m.group(1))
    return extracted


def _extract_duration_ms(payload: dict[str, Any], parsed_result: dict[str, Any]) -> float | None:
    for raw_val in (payload.get("duration_ms"), payload.get("duration"), parsed_result.get("elapsed_ms")):
        if isinstance(raw_val, (int, float)) and raw_val >= 0:
            return float(raw_val)
    return None


def classify_http_request_outcome(
    msg_status: str,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> tuple[bool, bool, int | None, str | None]:
    """Return (is_running, is_ok, status_code, err_msg) for an http_request tool message."""
    err_msg = payload.get("error") or result.get("error")
    raw_sc = result.get("status_code")
    status_code = int(raw_sc) if isinstance(raw_sc, (int, float)) and not isinstance(raw_sc, bool) else None
    if msg_status == "running" and not err_msg and result.get("ok") is None:
        return True, False, status_code, None
    if result.get("ok") is True:
        is_ok = True
    elif result.get("ok") is False or err_msg or msg_status == "failed":
        is_ok = False
    elif status_code is not None:
        is_ok = 200 <= status_code < 400
    else:
        is_ok = msg_status == "completed"
    return False, is_ok, status_code, str(err_msg) if err_msg else None


def classify_web_search_outcome(
    msg_status: str,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> tuple[bool, bool, str, int, str | None]:
    """Return (is_running, is_ok, provider, result_count, err_msg) for a web_search tool message."""
    err_msg = payload.get("error") or result.get("error")
    provider = str(result.get("provider") or "unknown").strip().lower() or "unknown"
    if isinstance(result.get("result_count"), (int, float)) and not isinstance(result.get("result_count"), bool):
        result_count = max(0, int(result["result_count"]))
    elif isinstance(result.get("results"), list):
        result_count = len(result["results"])
    else:
        result_count = 0
    if msg_status == "running" and not err_msg and not result:
        return True, False, provider, result_count, None
    is_ok = (
        msg_status != "failed"
        and not err_msg
        and provider != "none"
        and result.get("ok") is not False
    )
    return False, is_ok, provider, result_count, str(err_msg) if err_msg else None


async def _fallback_tools_from_telemetry(
    db: AsyncSession,
    *,
    window_start: datetime,
    tool_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Read aggregate per-tool counts from RunTelemetry when Message(role='tool') rows are absent."""
    rows = (
        await db.execute(
            select(RunTelemetry.tools_summary, RunTelemetry.created_at).where(
                RunTelemetry.created_at >= window_start,
                RunTelemetry.tools_summary.is_not(None),
            )
        )
    ).all()
    target_set = set(tool_names)
    agg: dict[str, dict[str, Any]] = {}
    for summary_list, created_at in rows:
        if not isinstance(summary_list, list):
            continue
        day_str = _day_iso(created_at)
        for item in summary_list:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name not in target_set:
                continue
            calls = max(0, int(item.get("calls") or 0))
            errors = max(0, int(item.get("errors") or 0))
            dur = max(0, int(item.get("total_duration_ms") or 0))
            bucket = agg.setdefault(
                name,
                {"calls": 0, "errors": 0, "total_duration_ms": 0, "daily": {}},
            )
            bucket["calls"] += calls
            bucket["errors"] += errors
            bucket["total_duration_ms"] += dur
            if day_str:
                dbucket = bucket["daily"].setdefault(day_str, {"calls": 0, "errors": 0, "dur_ms": 0})
                dbucket["calls"] += calls
                dbucket["errors"] += errors
                dbucket["dur_ms"] += dur
    return agg


async def collect_schedules_dashboard(db: AsyncSession, *, days: int = 14) -> dict[str, Any]:
    now, start_day, _end_day, window_start = _window_bounds(days)

    task_rows = (
        await db.execute(
            select(ScheduledTask, User.email)
            .join(User, ScheduledTask.user_id == User.id)
            .order_by(ScheduledTask.created_at.desc())
        )
    ).all()

    pending_proposals = int(
        await db.scalar(
            select(func.count(ScheduledTaskPendingProposal.id)).where(
                ScheduledTaskPendingProposal.status == "pending"
            )
        )
        or 0
    )

    tasks_by_id: dict[str, tuple[ScheduledTask, str]] = {}
    enabled_cnt = 0
    active_cnt = 0
    paused_cnt = 0
    error_cnt = 0
    completed_task_cnt = 0
    type_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}

    for task, email in task_rows:
        tasks_by_id[str(task.id)] = (task, email)
        if task.enabled:
            enabled_cnt += 1
        if task.status == "active" and task.enabled:
            active_cnt += 1
        elif task.status == "error":
            error_cnt += 1
        elif task.status == "completed":
            completed_task_cnt += 1
        else:
            paused_cnt += 1
        stype = str(task.schedule_type or "unknown")
        type_counts[stype] = type_counts.get(stype, 0) + 1
        tmode = str(task.target_mode or "dedicated")
        mode_counts[tmode] = mode_counts.get(tmode, 0) + 1

    run_rows = (
        await db.execute(
            select(ScheduledTaskRun, ScheduledTask.name, User.email)
            .join(ScheduledTask, ScheduledTaskRun.task_id == ScheduledTask.id)
            .join(User, ScheduledTaskRun.user_id == User.id)
            .where(ScheduledTaskRun.started_at >= window_start)
            .order_by(ScheduledTaskRun.started_at.desc())
        )
    ).all()

    daily_map: dict[str, dict[str, int]] = {}
    for offset in range(days):
        d = (start_day + timedelta(days=offset)).isoformat()
        daily_map[d] = {"total": 0, "completed": 0, "failed": 0, "cancelled": 0, "skipped": 0, "tokens": 0}

    trigger_stats: dict[str, dict[str, int]] = {
        "scheduled": {"total": 0, "completed": 0, "failed": 0},
        "manual": {"total": 0, "completed": 0, "failed": 0},
    }
    task_window_stats: dict[str, dict[str, Any]] = {}
    durations_ms: list[float] = []
    dispatch_delays_ms: list[float] = []
    on_time_cnt = 0
    scheduled_delay_samples = 0
    total_tokens = 0
    r_completed = 0
    r_failed = 0
    r_cancelled = 0
    r_skipped = 0
    r_in_progress = 0
    recent_failures: list[dict[str, Any]] = []

    for run, task_name, email in run_rows:
        st = str(run.status or "queued")
        trig = "manual" if run.trigger_type == "manual" else "scheduled"
        tokens = int(run.tokens_used or 0)
        total_tokens += tokens

        started_at = _aware_utc(run.started_at)
        finished_at = _aware_utc(run.finished_at)
        sched_for = _aware_utc(run.scheduled_for)
        dur_ms: float | None = None
        if started_at and finished_at and finished_at >= started_at:
            dur_ms = round((finished_at - started_at).total_seconds() * 1000.0, 1)
            durations_ms.append(dur_ms)

        if trig == "scheduled" and started_at and sched_for:
            delay_ms = max(0.0, (started_at - sched_for).total_seconds() * 1000.0)
            dispatch_delays_ms.append(delay_ms)
            scheduled_delay_samples += 1
            if delay_ms <= 60_000.0:
                on_time_cnt += 1

        if st == "completed":
            r_completed += 1
        elif st == "failed":
            r_failed += 1
        elif st == "cancelled":
            r_cancelled += 1
        elif st == "skipped":
            r_skipped += 1
        else:
            r_in_progress += 1

        trig_entry = trigger_stats.setdefault(trig, {"total": 0, "completed": 0, "failed": 0})
        trig_entry["total"] += 1
        if st == "completed":
            trig_entry["completed"] += 1
        elif st == "failed":
            trig_entry["failed"] += 1

        day_key = _day_iso(started_at)
        if day_key in daily_map:
            drow = daily_map[day_key]
            drow["total"] += 1
            drow["tokens"] += tokens
            if st in ("completed", "failed", "cancelled", "skipped"):
                drow[st] += 1

        tid = str(run.task_id)
        tstat = task_window_stats.setdefault(
            tid,
            {"runs": 0, "completed": 0, "failed": 0, "durations": [], "tokens_used": 0},
        )
        tstat["runs"] += 1
        tstat["tokens_used"] += tokens
        if st == "completed":
            tstat["completed"] += 1
        elif st == "failed":
            tstat["failed"] += 1
        if dur_ms is not None:
            tstat["durations"].append(dur_ms)

        if st == "failed" and len(recent_failures) < 20:
            recent_failures.append(
                {
                    "id": str(run.id),
                    "task_id": tid,
                    "task_name": task_name,
                    "user_email": email,
                    "trigger_type": trig,
                    "status": st,
                    "error": run.error or "执行失败",
                    "started_at": started_at.isoformat() if started_at else None,
                    "finished_at": finished_at.isoformat() if finished_at else None,
                    "duration_ms": dur_ms,
                }
            )

    daily = []
    for d in sorted(daily_map.keys()):
        drow = daily_map[d]
        resolved = drow["completed"] + drow["failed"]
        daily.append(
            {
                "day": d,
                **drow,
                "success_rate_pct": _rate_pct(drow["completed"], resolved),
            }
        )

    top_tasks: list[dict[str, Any]] = []
    for tid, (task, email) in tasks_by_id.items():
        ws = task_window_stats.get(tid, {"runs": 0, "completed": 0, "failed": 0, "durations": [], "tokens_used": 0})
        resolved = ws["completed"] + ws["failed"]
        try:
            sched_desc = schedule_calc.describe_schedule(
                task.schedule_type, task.schedule_config or {}, task.timezone
            )
        except Exception:
            sched_desc = task.schedule_type
        top_tasks.append(
            {
                "task_id": tid,
                "name": task.name,
                "user_email": email,
                "schedule_type": task.schedule_type,
                "schedule_description": sched_desc,
                "target_mode": task.target_mode,
                "enabled": bool(task.enabled),
                "status": task.status,
                "consecutive_failures": int(task.consecutive_failures or 0),
                "runs": ws["runs"],
                "completed": ws["completed"],
                "failed": ws["failed"],
                "success_rate_pct": _rate_pct(ws["completed"], resolved),
                "avg_duration_ms": _avg_opt(ws["durations"]),
                "tokens_used": ws["tokens_used"],
                "last_run_at": _aware_utc(task.last_run_at).isoformat() if task.last_run_at else None,
                "last_run_status": task.last_run_status,
                "last_error": task.last_error,
            }
        )
    top_tasks.sort(key=lambda item: (-item["runs"], -item["failed"], -item["consecutive_failures"], item["name"]))

    resolved_total = r_completed + r_failed
    return {
        "window_days": days,
        "tasks_summary": {
            "total": len(tasks_by_id),
            "enabled": enabled_cnt,
            "active": active_cnt,
            "paused": paused_cnt,
            "error": error_cnt,
            "completed": completed_task_cnt,
            "pending_proposals": pending_proposals,
            "by_schedule_type": [
                {"type": k, "count": v}
                for k, v in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "by_target_mode": [
                {"mode": k, "count": v}
                for k, v in sorted(mode_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        },
        "runs_summary": {
            "total": len(run_rows),
            "completed": r_completed,
            "failed": r_failed,
            "cancelled": r_cancelled,
            "skipped": r_skipped,
            "in_progress": r_in_progress,
            "success_rate_pct": _rate_pct(r_completed, resolved_total),
            "avg_duration_ms": _avg_opt(durations_ms),
            "p95_duration_ms": _percentile(durations_ms, 0.95),
            "avg_dispatch_delay_ms": _avg_opt(dispatch_delays_ms),
            "on_time_rate_pct": _rate_pct(on_time_cnt, scheduled_delay_samples),
            "total_tokens": total_tokens,
        },
        "by_trigger": [
            {
                "trigger_type": trig,
                "total": st["total"],
                "completed": st["completed"],
                "failed": st["failed"],
                "success_rate_pct": _rate_pct(st["completed"], st["completed"] + st["failed"]),
            }
            for trig, st in trigger_stats.items()
        ],
        "daily": daily,
        "top_tasks": top_tasks[:25],
        "recent_failures": recent_failures,
        "generated_at": now.isoformat(),
    }


async def collect_http_tools_dashboard(db: AsyncSession, *, days: int = 14) -> dict[str, Any]:
    now, start_day, _end_day, window_start = _window_bounds(days)
    target_tools = ("http_request", "web_extract", "execute_code")

    rows = (
        await db.execute(
            select(Message, User.email)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(User, Conversation.user_id == User.id)
            .where(
                Message.role == "tool",
                Message.tool_name.in_(target_tools),
                Message.created_at >= window_start,
            )
            .order_by(Message.created_at.desc())
        )
    ).all()

    day_keys = [(start_day + timedelta(days=offset)).isoformat() for offset in range(days)]

    # --- http_request accumulators ---
    http_total = 0
    http_ok = 0
    http_fail = 0
    http_running = 0
    http_2xx = 0
    http_3xx = 0
    http_4xx = 0
    http_5xx = 0
    http_net_err = 0
    http_bytes = 0
    http_durs: list[float] = []
    http_methods: dict[str, dict[str, Any]] = {}
    http_hosts: dict[str, dict[str, Any]] = {}
    http_daily = {d: {"total": 0, "succeeded": 0, "failed": 0, "durs": []} for d in day_keys}
    http_failures: list[dict[str, Any]] = []

    # --- web_extract accumulators ---
    ext_total = 0
    ext_ok = 0
    ext_fail = 0
    ext_fallback = 0
    ext_durs: list[float] = []
    ext_providers: dict[str, dict[str, Any]] = {}
    ext_daily = {d: {"total": 0, "succeeded": 0, "failed": 0} for d in day_keys}

    # --- execute_code accumulators ---
    code_total = 0
    code_ok = 0
    code_fail = 0
    code_denied = 0
    code_curl_cmds = 0
    code_durs: list[float] = []
    code_langs: dict[str, dict[str, Any]] = {}
    code_daily = {d: {"total": 0, "succeeded": 0, "failed": 0, "denied": 0} for d in day_keys}
    code_failures: list[dict[str, Any]] = []

    for msg, email in rows:
        tname = str(msg.tool_name or "")
        payload = msg.tool_payload if isinstance(msg.tool_payload, dict) else {}
        args = _parse_json_obj(payload.get("args"))
        result = _parse_json_obj(payload.get("result"))
        dur_ms = _extract_duration_ms(payload, result)
        err_msg = payload.get("error") or result.get("error")
        day_key = _day_iso(msg.created_at)

        if tname == "http_request":
            http_total += 1
            method = str(args.get("method") or "GET").strip().upper() or "GET"
            raw_url = str(result.get("url") or args.get("url") or "").strip()
            host, safe_url = _sanitize_url(raw_url)
            http_bytes += max(0, int(result.get("bytes_read") or 0))
            if dur_ms is not None:
                http_durs.append(dur_ms)

            is_running, is_ok, status_code, err_str = classify_http_request_outcome(
                msg.status, payload, result
            )
            if is_running:
                http_running += 1
                continue

            if is_ok:
                http_ok += 1
            else:
                http_fail += 1

            if status_code is not None:
                if 200 <= status_code < 300:
                    http_2xx += 1
                elif 300 <= status_code < 400:
                    http_3xx += 1
                elif 400 <= status_code < 500:
                    http_4xx += 1
                elif 500 <= status_code < 600:
                    http_5xx += 1
                else:
                    http_net_err += 1
            elif not is_ok:
                http_net_err += 1

            m_entry = http_methods.setdefault(method, {"total": 0, "succeeded": 0, "failed": 0, "durs": []})
            m_entry["total"] += 1
            m_entry["succeeded" if is_ok else "failed"] += 1
            if dur_ms is not None:
                m_entry["durs"].append(dur_ms)

            h_entry = http_hosts.setdefault(host, {"total": 0, "succeeded": 0, "failed": 0, "durs": []})
            h_entry["total"] += 1
            h_entry["succeeded" if is_ok else "failed"] += 1
            if dur_ms is not None:
                h_entry["durs"].append(dur_ms)

            if day_key in http_daily:
                hd = http_daily[day_key]
                hd["total"] += 1
                hd["succeeded" if is_ok else "failed"] += 1
                if dur_ms is not None:
                    hd["durs"].append(dur_ms)

            if not is_ok and len(http_failures) < 20:
                http_failures.append(
                    {
                        "id": str(msg.id),
                        "created_at": _aware_utc(msg.created_at).isoformat(),
                        "user_email": email,
                        "method": method,
                        "url": safe_url,
                        "host": host,
                        "status_code": status_code,
                        "error": str(
                            err_msg
                            or (f"HTTP {status_code}" if status_code is not None else "请求失败")
                        )[:300],
                        "duration_ms": dur_ms,
                    }
                )

        elif tname == "web_extract":
            ext_total += 1
            if dur_ms is not None:
                ext_durs.append(dur_ms)
            provider = str(result.get("provider") or "unknown").strip().lower() or "unknown"
            if result.get("fallback_from"):
                ext_fallback += 1
            is_ok = (
                msg.status != "failed"
                and not err_msg
                and result.get("ok") is not False
            )
            if msg.status == "running" and not err_msg and result.get("ok") is None:
                continue
            if is_ok:
                ext_ok += 1
            else:
                ext_fail += 1

            p_entry = ext_providers.setdefault(provider, {"total": 0, "succeeded": 0, "failed": 0, "durs": []})
            p_entry["total"] += 1
            p_entry["succeeded" if is_ok else "failed"] += 1
            if dur_ms is not None:
                p_entry["durs"].append(dur_ms)

            if day_key in ext_daily:
                ed = ext_daily[day_key]
                ed["total"] += 1
                ed["succeeded" if is_ok else "failed"] += 1

        elif tname == "execute_code":
            code_total += 1
            if dur_ms is not None:
                code_durs.append(dur_ms)
            language = str(args.get("language") or result.get("language") or "python").strip().lower() or "python"
            code_text = str(args.get("code") or "")
            if language in ("sh", "bash", "shell") and _CURL_CMD_RE.search(code_text):
                code_curl_cmds += 1

            if msg.status == "running" and not err_msg and not result:
                continue

            is_denied = result.get("status") == "denied"
            raw_ec = result.get("exit_code")
            exit_code = int(raw_ec) if isinstance(raw_ec, (int, float)) and not isinstance(raw_ec, bool) else None
            is_ok = (
                not is_denied
                and msg.status != "failed"
                and not err_msg
                and (exit_code is None or exit_code == 0)
            )
            if is_denied:
                code_denied += 1
                outcome_key = "denied"
            elif is_ok:
                code_ok += 1
                outcome_key = "succeeded"
            else:
                code_fail += 1
                outcome_key = "failed"

            l_entry = code_langs.setdefault(
                language, {"total": 0, "succeeded": 0, "failed": 0, "denied": 0, "durs": []}
            )
            l_entry["total"] += 1
            l_entry[outcome_key] += 1
            if dur_ms is not None:
                l_entry["durs"].append(dur_ms)

            if day_key in code_daily:
                cd = code_daily[day_key]
                cd["total"] += 1
                cd[outcome_key] += 1

            if not is_ok and len(code_failures) < 15:
                code_failures.append(
                    {
                        "id": str(msg.id),
                        "created_at": _aware_utc(msg.created_at).isoformat(),
                        "user_email": email,
                        "language": language,
                        "status": "denied" if is_denied else "failed",
                        "exit_code": exit_code,
                        "error": str(
                            err_msg
                            or result.get("message")
                            or result.get("stderr")
                            or (f"exit_code={exit_code}" if exit_code is not None else "执行失败")
                        )[:300],
                        "duration_ms": dur_ms,
                    }
                )

    # Supplement from RunTelemetry.tools_summary only when Message(role='tool') has 0 rows for a tool
    missing = tuple(
        name
        for name, cnt in (("http_request", http_total), ("web_extract", ext_total), ("execute_code", code_total))
        if cnt == 0
    )
    if missing:
        tel_fallback = await _fallback_tools_from_telemetry(db, window_start=window_start, tool_names=missing)
        if "http_request" in tel_fallback:
            fb = tel_fallback["http_request"]
            http_total = fb["calls"]
            http_fail = fb["errors"]
            http_ok = max(0, http_total - http_fail)
            if http_total > 0 and fb["total_duration_ms"] > 0:
                http_durs = [fb["total_duration_ms"] / http_total]
            for d, dbk in fb["daily"].items():
                if d in http_daily:
                    http_daily[d]["total"] += dbk["calls"]
                    http_daily[d]["failed"] += dbk["errors"]
                    http_daily[d]["succeeded"] += max(0, dbk["calls"] - dbk["errors"])
        if "web_extract" in tel_fallback:
            fb = tel_fallback["web_extract"]
            ext_total = fb["calls"]
            ext_fail = fb["errors"]
            ext_ok = max(0, ext_total - ext_fail)
            if ext_total > 0 and fb["total_duration_ms"] > 0:
                ext_durs = [fb["total_duration_ms"] / ext_total]
        if "execute_code" in tel_fallback:
            fb = tel_fallback["execute_code"]
            code_total = fb["calls"]
            code_fail = fb["errors"]
            code_ok = max(0, code_total - code_fail)
            if code_total > 0 and fb["total_duration_ms"] > 0:
                code_durs = [fb["total_duration_ms"] / code_total]

    http_resolved = http_ok + http_fail
    ext_resolved = ext_ok + ext_fail
    code_resolved = code_ok + code_fail + code_denied

    return {
        "window_days": days,
        "http_request": {
            "summary": {
                "total": http_total,
                "succeeded": http_ok,
                "failed": http_fail,
                "in_progress": http_running,
                "success_rate_pct": _rate_pct(http_ok, http_resolved),
                "avg_duration_ms": _avg_opt(http_durs),
                "p95_duration_ms": _percentile(http_durs, 0.95),
                "total_bytes_read": http_bytes,
                "http_2xx": http_2xx,
                "http_3xx": http_3xx,
                "http_4xx": http_4xx,
                "http_5xx": http_5xx,
                "network_errors": http_net_err,
            },
            "by_method": [
                {
                    "method": m,
                    "total": st["total"],
                    "succeeded": st["succeeded"],
                    "failed": st["failed"],
                    "success_rate_pct": _rate_pct(st["succeeded"], st["succeeded"] + st["failed"]),
                    "avg_duration_ms": _avg_opt(st["durs"]),
                }
                for m, st in sorted(http_methods.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
            ],
            "by_status_bucket": [
                {"bucket": "2xx", "count": http_2xx},
                {"bucket": "3xx", "count": http_3xx},
                {"bucket": "4xx", "count": http_4xx},
                {"bucket": "5xx", "count": http_5xx},
                {"bucket": "network_error", "count": http_net_err},
            ],
            "top_hosts": [
                {
                    "host": h,
                    "total": st["total"],
                    "succeeded": st["succeeded"],
                    "failed": st["failed"],
                    "success_rate_pct": _rate_pct(st["succeeded"], st["succeeded"] + st["failed"]),
                    "avg_duration_ms": _avg_opt(st["durs"]),
                }
                for h, st in sorted(http_hosts.items(), key=lambda kv: (-kv[1]["total"], kv[0]))[:15]
            ],
            "daily": [
                {
                    "day": d,
                    "total": http_daily[d]["total"],
                    "succeeded": http_daily[d]["succeeded"],
                    "failed": http_daily[d]["failed"],
                    "success_rate_pct": _rate_pct(
                        http_daily[d]["succeeded"],
                        http_daily[d]["succeeded"] + http_daily[d]["failed"],
                    ),
                    "avg_duration_ms": _avg_opt(http_daily[d]["durs"]),
                }
                for d in day_keys
            ],
            "recent_failures": http_failures,
        },
        "web_extract": {
            "summary": {
                "total": ext_total,
                "succeeded": ext_ok,
                "failed": ext_fail,
                "success_rate_pct": _rate_pct(ext_ok, ext_resolved),
                "avg_duration_ms": _avg_opt(ext_durs),
                "fallback_count": ext_fallback,
            },
            "by_provider": [
                {
                    "provider": p,
                    "total": st["total"],
                    "succeeded": st["succeeded"],
                    "failed": st["failed"],
                    "success_rate_pct": _rate_pct(st["succeeded"], st["succeeded"] + st["failed"]),
                    "avg_duration_ms": _avg_opt(st["durs"]),
                }
                for p, st in sorted(ext_providers.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
            ],
            "daily": [
                {
                    "day": d,
                    "total": ext_daily[d]["total"],
                    "succeeded": ext_daily[d]["succeeded"],
                    "failed": ext_daily[d]["failed"],
                    "success_rate_pct": _rate_pct(
                        ext_daily[d]["succeeded"],
                        ext_daily[d]["succeeded"] + ext_daily[d]["failed"],
                    ),
                }
                for d in day_keys
            ],
        },
        "execute_code": {
            "summary": {
                "total": code_total,
                "succeeded": code_ok,
                "failed": code_fail,
                "denied": code_denied,
                "success_rate_pct": _rate_pct(code_ok, code_resolved),
                "avg_duration_ms": _avg_opt(code_durs),
                "curl_command_count": code_curl_cmds,
            },
            "by_language": [
                {
                    "language": lang,
                    "total": st["total"],
                    "succeeded": st["succeeded"],
                    "failed": st["failed"],
                    "denied": st["denied"],
                    "success_rate_pct": _rate_pct(st["succeeded"], st["total"]),
                    "avg_duration_ms": _avg_opt(st["durs"]),
                }
                for lang, st in sorted(code_langs.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
            ],
            "daily": [
                {
                    "day": d,
                    "total": code_daily[d]["total"],
                    "succeeded": code_daily[d]["succeeded"],
                    "failed": code_daily[d]["failed"],
                    "denied": code_daily[d]["denied"],
                    "success_rate_pct": _rate_pct(code_daily[d]["succeeded"], code_daily[d]["total"]),
                }
                for d in day_keys
            ],
            "recent_failures": code_failures,
        },
        "generated_at": now.isoformat(),
    }


async def collect_web_search_dashboard(db: AsyncSession, *, days: int = 14) -> dict[str, Any]:
    now, start_day, _end_day, window_start = _window_bounds(days)
    rows = (
        await db.execute(
            select(Message, User.email)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(User, Conversation.user_id == User.id)
            .where(
                Message.role == "tool",
                Message.tool_name == "web_search",
                Message.created_at >= window_start,
            )
            .order_by(Message.created_at.desc())
        )
    ).all()

    day_keys = [(start_day + timedelta(days=offset)).isoformat() for offset in range(days)]
    daily_map = {
        d: {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "fallback_count": 0,
            "with_results": 0,
            "durs": [],
        }
        for d in day_keys
    }
    providers: dict[str, dict[str, Any]] = {}
    durs: list[float] = []
    total = 0
    succeeded = 0
    failed = 0
    in_progress = 0
    with_results = 0
    empty_results = 0
    fallback_count = 0
    total_results_returned = 0
    recent_searches: list[dict[str, Any]] = []
    recent_failures: list[dict[str, Any]] = []

    for msg, email in rows:
        total += 1
        payload = msg.tool_payload if isinstance(msg.tool_payload, dict) else {}
        args = _parse_json_obj(payload.get("args"))
        result = _parse_json_obj(payload.get("result"))
        dur_ms = _extract_duration_ms(payload, result)
        if dur_ms is not None:
            durs.append(dur_ms)

        query = str(args.get("query") or "").strip()[:160]
        fallback_from = result.get("fallback_from")
        is_running, is_ok, provider, result_count, err_msg = classify_web_search_outcome(
            msg.status, payload, result
        )
        if is_running:
            in_progress += 1
            continue
        is_fallback = bool(fallback_from)
        if is_fallback:
            fallback_count += 1

        if is_ok:
            succeeded += 1
            total_results_returned += result_count
            if result_count > 0:
                with_results += 1
            else:
                empty_results += 1
        else:
            failed += 1

        p_entry = providers.setdefault(
            provider,
            {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "with_results": 0,
                "empty_results": 0,
                "fallback_count": 0,
                "durs": [],
            },
        )
        p_entry["total"] += 1
        p_entry["succeeded" if is_ok else "failed"] += 1
        if is_fallback:
            p_entry["fallback_count"] += 1
        if is_ok:
            p_entry["with_results" if result_count > 0 else "empty_results"] += 1
        if dur_ms is not None:
            p_entry["durs"].append(dur_ms)

        day_key = _day_iso(msg.created_at)
        if day_key in daily_map:
            dm = daily_map[day_key]
            dm["total"] += 1
            dm["succeeded" if is_ok else "failed"] += 1
            if is_fallback:
                dm["fallback_count"] += 1
            if is_ok and result_count > 0:
                dm["with_results"] += 1
            if dur_ms is not None:
                dm["durs"].append(dur_ms)

        record = {
            "id": str(msg.id),
            "created_at": _aware_utc(msg.created_at).isoformat(),
            "user_email": email,
            "query": query or "—",
            "provider": provider,
            "fallback_from": str(fallback_from) if fallback_from else None,
            "result_count": result_count,
            "status": "completed" if is_ok else "failed",
            "error": str(err_msg)[:300] if err_msg else None,
            "duration_ms": dur_ms,
        }
        if len(recent_searches) < 20:
            recent_searches.append(record)
        if (not is_ok or result_count == 0) and len(recent_failures) < 20:
            recent_failures.append(record)

    if total == 0:
        tel_fallback = await _fallback_tools_from_telemetry(
            db, window_start=window_start, tool_names=("web_search",)
        )
        if "web_search" in tel_fallback:
            fb = tel_fallback["web_search"]
            total = fb["calls"]
            failed = fb["errors"]
            succeeded = max(0, total - failed)
            if total > 0 and fb["total_duration_ms"] > 0:
                durs = [fb["total_duration_ms"] / total]
            for d, dbk in fb["daily"].items():
                if d in daily_map:
                    daily_map[d]["total"] += dbk["calls"]
                    daily_map[d]["failed"] += dbk["errors"]
                    daily_map[d]["succeeded"] += max(0, dbk["calls"] - dbk["errors"])

    resolved = succeeded + failed
    return {
        "window_days": days,
        "summary": {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "in_progress": in_progress,
            "success_rate_pct": _rate_pct(succeeded, resolved),
            "with_results": with_results,
            "empty_results": empty_results,
            "hit_rate_pct": _rate_pct(with_results, succeeded),
            "fallback_count": fallback_count,
            "avg_results_per_search": round(total_results_returned / succeeded, 1) if succeeded > 0 else 0.0,
            "avg_duration_ms": _avg_opt(durs),
            "p95_duration_ms": _percentile(durs, 0.95),
        },
        "by_provider": [
            {
                "provider": p,
                "total": st["total"],
                "succeeded": st["succeeded"],
                "failed": st["failed"],
                "with_results": st["with_results"],
                "empty_results": st["empty_results"],
                "fallback_count": st["fallback_count"],
                "success_rate_pct": _rate_pct(st["succeeded"], st["succeeded"] + st["failed"]),
                "avg_duration_ms": _avg_opt(st["durs"]),
            }
            for p, st in sorted(providers.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
        ],
        "daily": [
            {
                "day": d,
                "total": daily_map[d]["total"],
                "succeeded": daily_map[d]["succeeded"],
                "failed": daily_map[d]["failed"],
                "fallback_count": daily_map[d]["fallback_count"],
                "with_results": daily_map[d]["with_results"],
                "success_rate_pct": _rate_pct(
                    daily_map[d]["succeeded"],
                    daily_map[d]["succeeded"] + daily_map[d]["failed"],
                ),
                "avg_duration_ms": _avg_opt(daily_map[d]["durs"]),
            }
            for d in day_keys
        ],
        "recent_searches": recent_searches,
        "recent_failures": recent_failures,
        "generated_at": now.isoformat(),
    }
