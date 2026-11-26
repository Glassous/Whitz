"""Pure-Python timezone-aware schedule validation, description, and next-run calculation."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VALID_SCHEDULE_TYPES = frozenset({"once", "interval", "daily", "weekly", "monthly", "cron"})
_WEEKDAY_NAMES_ZH = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "日",
}
_MONTH_ALIASES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DOW_ALIASES = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}


class ScheduleValidationError(ValueError):
    """Raised when a schedule type, config, cron expression, or timezone is invalid."""


def validate_timezone(tz_name: str | None) -> str:
    cleaned = (tz_name or "").strip() or "Asia/Shanghai"
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleValidationError(f"无效的时区: {cleaned}") from exc
    return cleaned


def _get_zone(tz_name: str) -> ZoneInfo:
    return ZoneInfo(validate_timezone(tz_name))


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_int(value: Any, *, field: str, min_val: int, max_val: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleValidationError(f"{field} 必须是整数") from exc
    if num < min_val or num > max_val:
        raise ScheduleValidationError(f"{field} 必须在 {min_val} 到 {max_val} 之间")
    return num


def _parse_cron_token(
    token: str,
    min_val: int,
    max_val: int,
    *,
    aliases: dict[str, int] | None = None,
    wrap_seven_to_zero: bool = False,
) -> set[int]:
    """Parse a single comma-separated cron sub-expression."""
    raw = token.strip().lower()
    if not raw:
        raise ScheduleValidationError("Cron 字段不能为空")

    if aliases:
        for k, v in aliases.items():
            raw = re.sub(rf"\b{k}\b", str(v), raw)

    step = 1
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) != 2 or not parts[1].isdigit():
            raise ScheduleValidationError(f"无效的 Cron 步长语法: {token}")
        step = int(parts[1])
        if step <= 0:
            raise ScheduleValidationError(f"Cron 步长必须大于 0: {token}")
        raw = parts[0]

    if raw == "*":
        start, end = min_val, max_val
    elif "-" in raw:
        bounds = raw.split("-")
        if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
            raise ScheduleValidationError(f"无效的 Cron 范围语法: {token}")
        start, end = int(bounds[0]), int(bounds[1])
        if wrap_seven_to_zero and end == 7 and start < 7:
            # Allow 1-7 or 5-7 where 7 represents Sunday (0)
            values = set(range(start, 7, step))
            if (7 - start) % step == 0:
                values.add(0)
            if start < min_val or end > 7:
                raise ScheduleValidationError(f"Cron 范围越界: {token}")
            return values
        if start > end:
            raise ScheduleValidationError(f"Cron 范围起始值不能大于结束值: {token}")
    else:
        if not raw.isdigit():
            raise ScheduleValidationError(f"无效的 Cron 数值: {token}")
        val = int(raw)
        if wrap_seven_to_zero and val == 7:
            val = 0
        if val < min_val or val > max_val:
            raise ScheduleValidationError(f"Cron 数值越界 ({min_val}-{max_val}): {token}")
        if "/" in token:
            start, end = val, max_val
        else:
            return {val}

    max_allowed = 7 if wrap_seven_to_zero else max_val
    if start < min_val or end > max_allowed:
        raise ScheduleValidationError(f"Cron 范围越界 ({min_val}-{max_allowed}): {token}")

    out: set[int] = set()
    for v in range(start, end + 1, step):
        out.add(0 if (wrap_seven_to_zero and v == 7) else v)
    return out


@dataclass(frozen=True)
class ParsedCron:
    expr: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0=Sun..6=Sat (cron convention)
    dom_wildcard: bool
    dow_wildcard: bool

    def matches_local(self, dt_local: datetime) -> bool:
        if dt_local.minute not in self.minutes:
            return False
        if dt_local.hour not in self.hours:
            return False
        if dt_local.month not in self.months:
            return False

        # Python weekday(): Mon=0..Sun=6 -> Cron: Sun=0, Mon=1..Sat=6
        cron_dow = (dt_local.weekday() + 1) % 7
        dom_match = dt_local.day in self.days
        dow_match = cron_dow in self.weekdays
        if not self.dom_wildcard and not self.dow_wildcard:
            return dom_match or dow_match
        return dom_match and dow_match


def parse_cron(expr: str) -> ParsedCron:
    cleaned = re.sub(r"\s+", " ", (expr or "").strip())
    parts = cleaned.split(" ")
    if len(parts) != 5:
        raise ScheduleValidationError("Cron 表达式必须包含 5 个字段：分 时 日 月 周")

    min_f, hour_f, dom_f, month_f, dow_f = parts
    minutes: set[int] = set()
    for tok in min_f.split(","):
        minutes |= _parse_cron_token(tok, 0, 59)
    hours: set[int] = set()
    for tok in hour_f.split(","):
        hours |= _parse_cron_token(tok, 0, 23)
    days: set[int] = set()
    for tok in dom_f.split(","):
        days |= _parse_cron_token(tok, 1, 31)
    months: set[int] = set()
    for tok in month_f.split(","):
        months |= _parse_cron_token(tok, 1, 12, aliases=_MONTH_ALIASES)
    weekdays: set[int] = set()
    for tok in dow_f.split(","):
        weekdays |= _parse_cron_token(tok, 0, 6, aliases=_DOW_ALIASES, wrap_seven_to_zero=True)

    return ParsedCron(
        expr=cleaned,
        minutes=frozenset(minutes),
        hours=frozenset(hours),
        days=frozenset(days),
        months=frozenset(months),
        weekdays=frozenset(weekdays),
        dom_wildcard=(dom_f.strip() == "*"),
        dow_wildcard=(dow_f.strip() == "*"),
    )


def _cron_next(parsed: ParsedCron, after_utc: datetime, tz: ZoneInfo) -> datetime:
    """Find next UTC datetime strictly after ``after_utc`` matching ``parsed`` in ``tz``."""
    base_utc = _ensure_utc(after_utc)
    start_local = base_utc.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    candidate_local = start_local
    limit_dt = start_local + timedelta(days=366 * 4)

    sorted_hours = sorted(parsed.hours)
    sorted_minutes = sorted(parsed.minutes)

    while candidate_local <= limit_dt:
        if candidate_local.month not in parsed.months:
            year = candidate_local.year + (1 if candidate_local.month == 12 else 0)
            month = 1 if candidate_local.month == 12 else candidate_local.month + 1
            candidate_local = datetime(year, month, 1, 0, 0, tzinfo=tz)
            continue

        cron_dow = (candidate_local.weekday() + 1) % 7
        dom_match = candidate_local.day in parsed.days
        dow_match = cron_dow in parsed.weekdays
        day_ok = (dom_match or dow_match) if (not parsed.dom_wildcard and not parsed.dow_wildcard) else (dom_match and dow_match)
        if not day_ok:
            next_day = candidate_local.date() + timedelta(days=1)
            candidate_local = datetime(next_day.year, next_day.month, next_day.day, 0, 0, tzinfo=tz)
            continue

        if candidate_local.hour not in parsed.hours:
            next_h = next((h for h in sorted_hours if h > candidate_local.hour), None)
            if next_h is None:
                next_day = candidate_local.date() + timedelta(days=1)
                candidate_local = datetime(next_day.year, next_day.month, next_day.day, 0, 0, tzinfo=tz)
            else:
                candidate_local = candidate_local.replace(hour=next_h, minute=sorted_minutes[0])
            continue

        if candidate_local.minute not in parsed.minutes:
            next_m = next((m for m in sorted_minutes if m > candidate_local.minute), None)
            if next_m is None:
                candidate_local = (candidate_local + timedelta(hours=1)).replace(minute=sorted_minutes[0])
            else:
                candidate_local = candidate_local.replace(minute=next_m)
            continue

        # Verify DST round-trip so non-existent spring-forward wall times are skipped cleanly.
        cand_utc = candidate_local.astimezone(timezone.utc)
        if cand_utc > base_utc and parsed.matches_local(cand_utc.astimezone(tz)):
            return cand_utc
        candidate_local = candidate_local + timedelta(minutes=1)

    raise ScheduleValidationError("Cron 表达式在未来 4 年内没有可触发的时间")


def compute_next_run_at(
    schedule_type: str,
    schedule_config: dict[str, Any],
    tz_name: str,
    *,
    after_dt: datetime | None = None,
) -> datetime | None:
    """Compute the next UTC trigger moment strictly after ``after_dt``."""
    now_utc = _ensure_utc(after_dt or datetime.now(timezone.utc))
    tz = _get_zone(tz_name)
    stype = (schedule_type or "").strip().lower()
    cfg = schedule_config or {}

    if stype == "once":
        raw = str(cfg.get("run_at") or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScheduleValidationError("单次执行时间格式无效") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc if dt_utc > now_utc else None

    if stype == "interval":
        every_minutes = _parse_int(cfg.get("every_minutes"), field="间隔分钟数", min_val=1, max_val=43200)
        return (now_utc + timedelta(minutes=every_minutes)).replace(microsecond=0)

    if stype == "daily":
        hour = _parse_int(cfg.get("hour", 9), field="小时", min_val=0, max_val=23)
        minute = _parse_int(cfg.get("minute", 0), field="分钟", min_val=0, max_val=59)
        local_now = now_utc.astimezone(tz)
        cand = datetime(local_now.year, local_now.month, local_now.day, hour, minute, tzinfo=tz)
        if cand.astimezone(timezone.utc) <= now_utc:
            next_d = local_now.date() + timedelta(days=1)
            cand = datetime(next_d.year, next_d.month, next_d.day, hour, minute, tzinfo=tz)
        return cand.astimezone(timezone.utc)

    if stype == "weekly":
        raw_days = cfg.get("weekdays")
        if not isinstance(raw_days, list) or not raw_days:
            raise ScheduleValidationError("每周调度必须至少选择一个星期")
        weekdays = sorted({_parse_int(d, field="星期", min_val=1, max_val=7) for d in raw_days})
        hour = _parse_int(cfg.get("hour", 9), field="小时", min_val=0, max_val=23)
        minute = _parse_int(cfg.get("minute", 0), field="分钟", min_val=0, max_val=59)
        local_now = now_utc.astimezone(tz)
        for offset in range(0, 8):
            d = local_now.date() + timedelta(days=offset)
            if (d.weekday() + 1) in weekdays:
                cand = datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)
                cand_utc = cand.astimezone(timezone.utc)
                if cand_utc > now_utc:
                    return cand_utc
        raise ScheduleValidationError("无法计算每周调度下一次执行时间")

    if stype == "monthly":
        target_day = _parse_int(cfg.get("day", 1), field="每月日期", min_val=1, max_val=31)
        hour = _parse_int(cfg.get("hour", 9), field="小时", min_val=0, max_val=23)
        minute = _parse_int(cfg.get("minute", 0), field="分钟", min_val=0, max_val=59)
        local_now = now_utc.astimezone(tz)
        year, month = local_now.year, local_now.month
        for _ in range(0, 24):
            max_day = calendar.monthrange(year, month)[1]
            actual_day = min(target_day, max_day)
            cand = datetime(year, month, actual_day, hour, minute, tzinfo=tz)
            cand_utc = cand.astimezone(timezone.utc)
            if cand_utc > now_utc:
                return cand_utc
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
        raise ScheduleValidationError("无法计算每月调度下一次执行时间")

    if stype == "cron":
        parsed = parse_cron(str(cfg.get("expr") or ""))
        return _cron_next(parsed, now_utc, tz)

    raise ScheduleValidationError(f"不支持的调度类型: {schedule_type}")


def validate_and_normalize_schedule(
    schedule_type: str,
    schedule_config: dict[str, Any] | None,
    tz_name: str | None,
    *,
    min_interval_minutes: int = 5,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any], str, datetime | None]:
    """Validate schedule payload and return ``(type, normalized_config, tz_name, next_run_at)``."""
    stype = (schedule_type or "").strip().lower()
    if stype not in VALID_SCHEDULE_TYPES:
        raise ScheduleValidationError(f"不支持的调度类型: {schedule_type}")
    tz = validate_timezone(tz_name)
    cfg = dict(schedule_config or {})
    now_utc = _ensure_utc(now or datetime.now(timezone.utc))

    if stype == "once":
        raw = str(cfg.get("run_at") or "").strip()
        if not raw:
            raise ScheduleValidationError("单次定时任务必须提供执行时间 run_at")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScheduleValidationError("单次执行时间格式无效，请使用 ISO 8601 格式") from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        dt_utc = dt.astimezone(timezone.utc)
        if dt_utc <= now_utc:
            raise ScheduleValidationError("单次定时执行时间必须晚于当前时间")
        normalized = {"run_at": dt_utc.isoformat()}
        return stype, normalized, tz, dt_utc

    if stype == "interval":
        every = _parse_int(cfg.get("every_minutes"), field="间隔分钟数", min_val=1, max_val=43200)
        if every < min_interval_minutes:
            raise ScheduleValidationError(f"当前会员档位最小间隔为 {min_interval_minutes} 分钟")
        normalized = {"every_minutes": every}
        next_at = compute_next_run_at(stype, normalized, tz, after_dt=now_utc)
        return stype, normalized, tz, next_at

    if stype == "daily":
        hour = _parse_int(cfg.get("hour", 9), field="小时", min_val=0, max_val=23)
        minute = _parse_int(cfg.get("minute", 0), field="分钟", min_val=0, max_val=59)
        normalized = {"hour": hour, "minute": minute}
        next_at = compute_next_run_at(stype, normalized, tz, after_dt=now_utc)
        return stype, normalized, tz, next_at

    if stype == "weekly":
        raw_days = cfg.get("weekdays")
        if not isinstance(raw_days, list) or not raw_days:
            raise ScheduleValidationError("每周调度必须至少选择一个星期 (1-7)")
        weekdays = sorted({_parse_int(d, field="星期", min_val=1, max_val=7) for d in raw_days})
        hour = _parse_int(cfg.get("hour", 9), field="小时", min_val=0, max_val=23)
        minute = _parse_int(cfg.get("minute", 0), field="分钟", min_val=0, max_val=59)
        normalized = {"weekdays": weekdays, "hour": hour, "minute": minute}
        next_at = compute_next_run_at(stype, normalized, tz, after_dt=now_utc)
        return stype, normalized, tz, next_at

    if stype == "monthly":
        day = _parse_int(cfg.get("day", 1), field="每月日期", min_val=1, max_val=31)
        hour = _parse_int(cfg.get("hour", 9), field="小时", min_val=0, max_val=23)
        minute = _parse_int(cfg.get("minute", 0), field="分钟", min_val=0, max_val=59)
        normalized = {"day": day, "hour": hour, "minute": minute}
        next_at = compute_next_run_at(stype, normalized, tz, after_dt=now_utc)
        return stype, normalized, tz, next_at

    # cron
    parsed = parse_cron(str(cfg.get("expr") or ""))
    normalized = {"expr": parsed.expr}
    zone = ZoneInfo(tz)
    runs: list[datetime] = []
    cursor = now_utc
    for _ in range(5):
        nxt = _cron_next(parsed, cursor, zone)
        runs.append(nxt)
        cursor = nxt
    if len(runs) >= 2 and min_interval_minutes > 1:
        min_gap = min((runs[i + 1] - runs[i]).total_seconds() for i in range(len(runs) - 1))
        if min_gap < min_interval_minutes * 60:
            raise ScheduleValidationError(
                f"当前会员档位要求相邻触发间隔不少于 {min_interval_minutes} 分钟"
            )
    return stype, normalized, tz, runs[0]


def preview_next_runs(
    schedule_type: str,
    schedule_config: dict[str, Any] | None,
    tz_name: str | None,
    *,
    count: int = 5,
    min_interval_minutes: int = 5,
    now: datetime | None = None,
) -> tuple[str, list[datetime]]:
    stype, normalized, tz, first = validate_and_normalize_schedule(
        schedule_type,
        schedule_config,
        tz_name,
        min_interval_minutes=min_interval_minutes,
        now=now,
    )
    desc = describe_schedule(stype, normalized, tz)
    if first is None:
        return desc, []
    runs = [first]
    if stype == "once":
        return desc, runs
    cursor = first
    for _ in range(max(0, min(count, 10) - 1)):
        nxt = compute_next_run_at(stype, normalized, tz, after_dt=cursor)
        if nxt is None:
            break
        runs.append(nxt)
        cursor = nxt
    return desc, runs


def describe_schedule(schedule_type: str, schedule_config: dict[str, Any] | None, tz_name: str | None) -> str:
    stype = (schedule_type or "").strip().lower()
    cfg = schedule_config or {}
    tz = (tz_name or "").strip() or "Asia/Shanghai"

    if stype == "once":
        raw = str(cfg.get("run_at") or "").strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ZoneInfo(validate_timezone(tz)))
            return f"单次 · {dt.strftime('%Y-%m-%d %H:%M')}"
        except Exception:
            return "单次定时"

    if stype == "interval":
        mins = int(cfg.get("every_minutes") or 60)
        if mins % 1440 == 0:
            return f"每 {mins // 1440} 天"
        if mins % 60 == 0:
            return f"每 {mins // 60} 小时"
        return f"每 {mins} 分钟"

    hhmm = f"{int(cfg.get('hour', 9)):02d}:{int(cfg.get('minute', 0)):02d}"
    if stype == "daily":
        return f"每天 {hhmm}"
    if stype == "weekly":
        days = sorted({int(d) for d in (cfg.get("weekdays") or []) if 1 <= int(d) <= 7})
        labels = "、".join(_WEEKDAY_NAMES_ZH.get(d, str(d)) for d in days)
        return f"每周{labels} {hhmm}"
    if stype == "monthly":
        day = int(cfg.get("day") or 1)
        return f"每月 {day} 日 {hhmm}"
    if stype == "cron":
        return f"Cron: {cfg.get('expr') or ''}"
    return stype
