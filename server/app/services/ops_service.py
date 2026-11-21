from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.models import Conversation, OpsAlertEvent, OpsAlertRule, RunTelemetry, User
from app.db.session import detect_pgvector
from app.services.agent_client import AgentClient

logger = logging.getLogger(__name__)

SLO_AVAILABILITY_TARGET_PCT = 99.0
SLO_P95_LATENCY_TARGET_MS = 15000.0
SLO_TTFT_P95_TARGET_MS = 2500.0

SUPPORTED_METRICS: dict[str, dict[str, str]] = {
    "agent_error_rate_pct": {"label": "Agent 失败率 (%)", "unit": "%"},
    "p95_latency_ms": {"label": "P95 响应延迟 (ms)", "unit": "ms"},
    "slo_burn_rate_1h": {"label": "1h SLO 错误预算燃烧率 (x)", "unit": "x"},
    "cost_usd_1h": {"label": "近 1h 模型成本 (USD)", "unit": "$"},
    "redis_memory_pct": {"label": "Redis 内存水位 (%)", "unit": "%"},
    "pg_conn_pct": {"label": "Postgres 连接占比 (%)", "unit": "%"},
    "arq_queue_depth": {"label": "ARQ 队列积压数", "unit": "jobs"},
    "active_stuck_runs": {"label": "超时卡死任务数", "unit": "runs"},
    "agent_down": {"label": "Agent 服务不可达 (1=故障)", "unit": "bool"},
}


async def _inspect_postgres(db: AsyncSession) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    except Exception:
        return {"ok": False, "latency_ms": None, "pgvector": False}

    pgvector_ok = await detect_pgvector(db)
    active_conns = 0
    total_conns = 0
    max_conns = 0
    db_size_bytes = 0
    tables: list[dict[str, Any]] = []

    try:
        row = (
            await db.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()), "
                    "(SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'active'), "
                    "current_setting('max_connections')::int, "
                    "pg_database_size(current_database())"
                )
            )
        ).first()
        if row:
            total_conns = int(row[0] or 0)
            active_conns = int(row[1] or 0)
            max_conns = int(row[2] or 0)
            db_size_bytes = int(row[3] or 0)
    except Exception as exc:
        logger.debug("pg_stat_activity query skipped: %s", exc)

    try:
        tbl_rows = (
            await db.execute(
                text(
                    "SELECT relname, n_live_tup, n_dead_tup "
                    "FROM pg_stat_user_tables "
                    "ORDER BY n_live_tup DESC LIMIT 8"
                )
            )
        ).all()
        tables = [
            {"name": str(r[0]), "live_rows": int(r[1] or 0), "dead_rows": int(r[2] or 0)}
            for r in tbl_rows
        ]
    except Exception:
        pass

    conn_pct = round((total_conns / max_conns) * 100, 1) if max_conns > 0 else 0.0
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "pgvector": pgvector_ok,
        "active_connections": active_conns,
        "total_connections": total_conns,
        "max_connections": max_conns,
        "connection_pct": conn_pct,
        "database_size_mb": round(db_size_bytes / (1024 * 1024), 2),
        "top_tables": tables,
    }


async def _inspect_redis() -> dict[str, Any]:
    redis = get_redis()
    t0 = time.perf_counter()
    try:
        ok = bool(await redis.ping())
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    except Exception:
        return {"ok": False, "latency_ms": None}

    if not hasattr(redis, "info"):
        return {
            "ok": ok,
            "latency_ms": latency_ms,
            "mode": "memory",
            "used_memory_mb": 0.0,
            "maxmemory_mb": 0.0,
            "memory_pct": 0.0,
            "connected_clients": 1,
            "hit_rate_pct": 100.0,
            "arq_queue_depth": 0,
            "arq_in_progress": 0,
        }

    used_mem = 0
    max_mem = 0
    clients = 0
    hits = 0
    misses = 0
    queue_depth = 0
    in_progress = 0

    try:
        mem_info = await redis.info("memory")
        used_mem = int(mem_info.get("used_memory") or 0)
        max_mem = int(mem_info.get("maxmemory") or 0)
        clients_info = await redis.info("clients")
        clients = int(clients_info.get("connected_clients") or 0)
        stats_info = await redis.info("stats")
        hits = int(stats_info.get("keyspace_hits") or 0)
        misses = int(stats_info.get("keyspace_misses") or 0)
    except Exception as exc:
        logger.debug("redis info failed: %s", exc)

    try:
        queue_depth = int(await redis.llen("arq:queue") or 0)
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match="arq:in-progress:*", count=100)
            in_progress += len(keys)
            if cursor == 0:
                break
    except Exception:
        pass

    mem_pct = round((used_mem / max_mem) * 100, 1) if max_mem > 0 else 0.0
    total_ops = hits + misses
    hit_rate = round((hits / total_ops) * 100, 1) if total_ops > 0 else 100.0
    return {
        "ok": ok,
        "latency_ms": latency_ms,
        "mode": "redis",
        "used_memory_mb": round(used_mem / (1024 * 1024), 2),
        "maxmemory_mb": round(max_mem / (1024 * 1024), 2),
        "memory_pct": mem_pct,
        "connected_clients": clients,
        "hit_rate_pct": hit_rate,
        "arq_queue_depth": queue_depth,
        "arq_in_progress": in_progress,
    }


async def _inspect_agent(admin: User | None) -> dict[str, Any]:
    if admin is None:
        return {"ok": False, "worker_ok": False, "latency_ms": None}
    client = AgentClient(admin.agent_namespace, admin.agent_api_key)
    t0 = time.perf_counter()
    try:
        info = await client.health_info()
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        ok = bool(info.get("ready")) if isinstance(info, dict) else bool(info)
        worker_ok = bool(info.get("redis", ok)) if (ok and isinstance(info, dict)) else False
        return {
            "ok": ok,
            "worker_ok": worker_ok,
            "latency_ms": latency_ms,
            "sandbox_mode": info.get("sandbox_mode", "disabled") if isinstance(info, dict) else "disabled",
        }
    except Exception:
        return {"ok": False, "worker_ok": False, "latency_ms": None, "sandbox_mode": "disabled"}
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


async def compute_slo_and_anomalies(db: AsyncSession) -> dict[str, Any]:
    """Compute multi-window SLO error-budget burn rate and Z-score statistical anomaly signals."""
    now = datetime.now(timezone.utc)
    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)

    async def _window_stats(since: datetime) -> dict[str, Any]:
        row = (
            await db.execute(
                select(
                    func.count(RunTelemetry.id),
                    func.coalesce(func.sum(case((RunTelemetry.status == "failed", 1), else_=0)), 0),
                    func.coalesce(func.sum(RunTelemetry.estimated_cost_usd), 0.0),
                    func.coalesce(func.sum(RunTelemetry.total_tokens), 0),
                ).where(RunTelemetry.created_at >= since)
            )
        ).one()
        total = int(row[0] or 0)
        failed = int(row[1] or 0)
        cost_usd = round(float(row[2] or 0.0), 4)
        tokens = int(row[3] or 0)
        err_rate = (failed / total) if total > 0 else 0.0
        pct = (
            await db.execute(
                text(
                    "SELECT "
                    "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), "
                    "percentile_cont(0.95) WITHIN GROUP (ORDER BY ttft_ms) "
                    "FROM run_telemetry WHERE created_at >= :since"
                ),
                {"since": since},
            )
        ).one()
        p95_ms = round(float(pct[0]), 1) if pct[0] is not None else 0.0
        ttft_p95_ms = round(float(pct[1]), 1) if pct[1] is not None else 0.0
        return {
            "runs": total,
            "failed": failed,
            "error_rate": err_rate,
            "success_rate_pct": round((1.0 - err_rate) * 100, 2),
            "p95_ms": p95_ms,
            "ttft_p95_ms": ttft_p95_ms,
            "cost_usd": cost_usd,
            "tokens": tokens,
        }

    w1h = await _window_stats(since_1h)
    w24h = await _window_stats(since_24h)
    w7d = await _window_stats(since_7d)

    allowed_error_rate = max(1e-6, (100.0 - SLO_AVAILABILITY_TARGET_PCT) / 100.0)
    burn_rate_1h = round(w1h["error_rate"] / allowed_error_rate, 2)
    burn_rate_24h = round(w24h["error_rate"] / allowed_error_rate, 2)
    consumed_budget_pct = (w7d["error_rate"] / allowed_error_rate) * 100.0 if w7d["runs"] > 0 else 0.0
    budget_remaining_pct = round(max(0.0, 100.0 - consumed_budget_pct), 1)
    if burn_rate_1h >= 6.0 or budget_remaining_pct <= 10.0:
        slo_status = "critical"
    elif burn_rate_1h >= 2.0 or budget_remaining_pct <= 40.0 or w24h["p95_ms"] > SLO_P95_LATENCY_TARGET_MS:
        slo_status = "warning"
    else:
        slo_status = "healthy"

    # Hourly buckets over last 7 days (excluding the current active hour) for Z-score baseline
    hourly_rows = (
        await db.execute(
            text(
                "SELECT date_trunc('hour', created_at) AS hr, "
                "count(*) AS runs, "
                "sum(case when status = 'failed' then 1 else 0 end) AS failed, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms, "
                "coalesce(sum(total_tokens), 0) AS tokens, "
                "coalesce(sum(estimated_cost_usd), 0) AS cost_usd "
                "FROM run_telemetry "
                "WHERE created_at >= :since_7d AND created_at < :since_1h "
                "GROUP BY 1 ORDER BY 1"
            ),
            {"since_7d": since_7d, "since_1h": since_1h},
        )
    ).all()

    def _zscore_check(metric: str, label: str, unit: str, current: float, series: list[float]) -> dict[str, Any]:
        if len(series) < 3:
            return {
                "metric": metric,
                "label": label,
                "unit": unit,
                "current": round(current, 3),
                "baseline_mean": round(sum(series) / len(series), 3) if series else 0.0,
                "baseline_std": 0.0,
                "z_score": 0.0,
                "is_anomaly": False,
                "sample_hours": len(series),
            }
        mean = sum(series) / len(series)
        var = sum((x - mean) ** 2 for x in series) / len(series)
        std = math.sqrt(var)
        if std < 1e-6:
            z = 0.0 if abs(current - mean) < 1e-6 else (3.0 if current > mean * 1.5 and current > 0 else 0.0)
        else:
            z = (current - mean) / std
        is_anom = z >= 2.5 and current > 0
        return {
            "metric": metric,
            "label": label,
            "unit": unit,
            "current": round(current, 3),
            "baseline_mean": round(mean, 3),
            "baseline_std": round(std, 3),
            "z_score": round(z, 2),
            "is_anomaly": is_anom,
            "sample_hours": len(series),
        }

    err_series = [(int(r[2] or 0) / int(r[1])) * 100.0 for r in hourly_rows if int(r[1] or 0) > 0]
    p95_series = [float(r[3]) for r in hourly_rows if r[3] is not None]
    tok_series = [float(r[4] or 0) for r in hourly_rows]
    cost_series = [float(r[5] or 0.0) for r in hourly_rows]

    anomalies = [
        _zscore_check("error_rate_pct", "小时错误率 (%)", "%", w1h["error_rate"] * 100.0, err_series),
        _zscore_check("p95_latency_ms", "小时 P95 延迟", "ms", w1h["p95_ms"], p95_series),
        _zscore_check("tokens_per_hour", "小时 Token 消耗", "tokens", float(w1h["tokens"]), tok_series),
        _zscore_check("cost_usd_per_hour", "小时模型费用", "USD", float(w1h["cost_usd"]), cost_series),
    ]

    return {
        "slo": {
            "availability_target_pct": SLO_AVAILABILITY_TARGET_PCT,
            "p95_target_ms": SLO_P95_LATENCY_TARGET_MS,
            "ttft_p95_target_ms": SLO_TTFT_P95_TARGET_MS,
            "actual_success_rate_24h_pct": w24h["success_rate_pct"],
            "actual_success_rate_7d_pct": w7d["success_rate_pct"],
            "actual_p95_24h_ms": w24h["p95_ms"],
            "actual_ttft_p95_24h_ms": w24h["ttft_p95_ms"],
            "error_budget_remaining_pct": budget_remaining_pct,
            "burn_rate_1h": burn_rate_1h,
            "burn_rate_24h": burn_rate_24h,
            "cost_1h_usd": w1h["cost_usd"],
            "cost_24h_usd": w24h["cost_usd"],
            "status": slo_status,
        },
        "anomalies": anomalies,
    }


async def collect_ops_inspection(db: AsyncSession, admin: User | None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    settings = get_settings()

    pg_info = await _inspect_postgres(db)
    redis_info = await _inspect_redis()
    agent_info = await _inspect_agent(admin)

    stuck_cutoff = now - timedelta(seconds=settings.run_max_seconds)
    active_runs = int(
        await db.scalar(
            select(func.count(Conversation.id)).where(Conversation.active_run_id.is_not(None))
        )
        or 0
    )
    stuck_runs = int(
        await db.scalar(
            select(func.count(Conversation.id)).where(
                Conversation.active_run_id.is_not(None),
                Conversation.updated_at < stuck_cutoff,
            )
        )
        or 0
    )

    since_15m = now - timedelta(minutes=15)
    runs_15m = int(
        await db.scalar(select(func.count(RunTelemetry.id)).where(RunTelemetry.created_at >= since_15m)) or 0
    )
    failed_15m = int(
        await db.scalar(
            select(func.count(RunTelemetry.id)).where(
                RunTelemetry.created_at >= since_15m,
                RunTelemetry.status == "failed",
            )
        )
        or 0
    )
    error_rate_15m = round((failed_15m / runs_15m) * 100, 2) if runs_15m > 0 else 0.0

    p95_15m_raw = await db.scalar(
        text(
            "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) "
            "FROM run_telemetry WHERE created_at >= :since AND duration_ms IS NOT NULL"
        ),
        {"since": since_15m},
    )
    p95_latency_15m = round(float(p95_15m_raw), 1) if p95_15m_raw is not None else 0.0

    firing_alerts = int(
        await db.scalar(select(func.count(OpsAlertEvent.id)).where(OpsAlertEvent.status == "firing")) or 0
    )
    slo_data = await compute_slo_and_anomalies(db)

    return {
        "postgres": pg_info,
        "redis": redis_info,
        "agent": agent_info,
        "runtime": {
            "active_runs": active_runs,
            "stuck_runs": stuck_runs,
            "max_concurrent_runs": settings.max_concurrent_runs,
            "run_max_seconds": settings.run_max_seconds,
            "runs_15m": runs_15m,
            "error_rate_15m_pct": error_rate_15m,
            "p95_latency_15m_ms": p95_latency_15m,
            "firing_alerts": firing_alerts,
        },
        "slo": slo_data["slo"],
        "anomalies": slo_data["anomalies"],
        "supported_metrics": SUPPORTED_METRICS,
        "generated_at": now.isoformat(),
    }


def _compare(operator: str, current: float, threshold: float) -> bool:
    if operator == "gt":
        return current > threshold
    if operator == "gte":
        return current >= threshold
    if operator == "lt":
        return current < threshold
    if operator == "lte":
        return current <= threshold
    if operator == "eq":
        return current == threshold
    return current > threshold


async def compute_metric_value(
    db: AsyncSession,
    metric_key: str,
    window_minutes: int,
    inspection: dict[str, Any] | None = None,
) -> float:
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=max(1, window_minutes))

    if metric_key == "agent_error_rate_pct":
        total = int(await db.scalar(select(func.count(RunTelemetry.id)).where(RunTelemetry.created_at >= since)) or 0)
        if total == 0:
            return 0.0
        failed = int(
            await db.scalar(
                select(func.count(RunTelemetry.id)).where(
                    RunTelemetry.created_at >= since,
                    RunTelemetry.status == "failed",
                )
            )
            or 0
        )
        return round((failed / total) * 100, 2)

    if metric_key == "p95_latency_ms":
        val = await db.scalar(
            text(
                "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) "
                "FROM run_telemetry WHERE created_at >= :since AND duration_ms IS NOT NULL"
            ),
            {"since": since},
        )
        return round(float(val), 1) if val is not None else 0.0

    if metric_key == "active_stuck_runs":
        settings = get_settings()
        cutoff = now - timedelta(seconds=settings.run_max_seconds)
        return float(
            await db.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.active_run_id.is_not(None),
                    Conversation.updated_at < cutoff,
                )
            )
            or 0
        )

    if inspection is None:
        inspection = await collect_ops_inspection(db, None)

    if metric_key == "slo_burn_rate_1h":
        slo_info = (inspection or {}).get("slo")
        if not isinstance(slo_info, dict):
            slo_info = (await compute_slo_and_anomalies(db))["slo"]
        return float(slo_info.get("burn_rate_1h") or 0.0)

    if metric_key == "cost_usd_1h":
        since_1h = now - timedelta(hours=1)
        val = await db.scalar(
            select(func.coalesce(func.sum(RunTelemetry.estimated_cost_usd), 0.0)).where(
                RunTelemetry.created_at >= since_1h
            )
        )
        return round(float(val or 0.0), 4)

    if metric_key == "redis_memory_pct":
        return float(inspection.get("redis", {}).get("memory_pct") or 0.0)
    if metric_key == "pg_conn_pct":
        return float(inspection.get("postgres", {}).get("connection_pct") or 0.0)
    if metric_key == "arq_queue_depth":
        return float(inspection.get("redis", {}).get("arq_queue_depth") or 0.0)
    if metric_key == "agent_down":
        return 0.0 if inspection.get("agent", {}).get("ok") else 1.0
    return 0.0


async def dispatch_webhook(webhook_url: str, payload: dict[str, Any]) -> str:
    url = (webhook_url or "").strip()
    if not url:
        return "skipped"
    text_msg = payload.get("message") or f"[{payload.get('severity', 'info').upper()}] {payload.get('rule_name')}"
    body = {
        **payload,
        "msg_type": "text",
        "text": text_msg,
        "content": {"text": text_msg},
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=body)
            return f"http_{resp.status_code}"
    except Exception as exc:
        logger.warning("Webhook delivery failed url=%s err=%s", url, exc)
        return "failed"


async def evaluate_alert_rules(db: AsyncSession, admin: User | None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    inspection = await collect_ops_inspection(db, admin)
    rules = (await db.execute(select(OpsAlertRule).where(OpsAlertRule.enabled.is_(True)))).scalars().all()

    evaluated = 0
    triggered = 0
    events_out: list[dict[str, Any]] = []

    for rule in rules:
        evaluated += 1
        current = await compute_metric_value(db, rule.metric_key, rule.window_minutes, inspection=inspection)
        if not _compare(rule.operator, current, rule.threshold):
            continue

        if rule.last_triggered_at is not None:
            last = rule.last_triggered_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last) < timedelta(minutes=max(1, rule.cooldown_minutes)):
                continue

        msg = (
            f"告警 [{rule.name}] 触发：{rule.metric_key} 当前值 {current} "
            f"({rule.operator} 阈值 {rule.threshold})"
        )
        webhook_status = await dispatch_webhook(
            rule.webhook_url or "",
            {
                "event": "whitz.ops.alert",
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "metric_key": rule.metric_key,
                "current_value": current,
                "threshold": rule.threshold,
                "severity": rule.severity,
                "message": msg,
                "triggered_at": now.isoformat(),
            },
        )
        event = OpsAlertEvent(
            rule_id=rule.id,
            rule_name=rule.name,
            metric_key=rule.metric_key,
            current_value=current,
            threshold=rule.threshold,
            severity=rule.severity,
            status="firing",
            message=msg[:500],
            webhook_status=webhook_status,
        )
        db.add(event)
        rule.last_triggered_at = now
        triggered += 1
        events_out.append(
            {
                "rule_name": rule.name,
                "metric_key": rule.metric_key,
                "current_value": current,
                "threshold": rule.threshold,
                "severity": rule.severity,
                "webhook_status": webhook_status,
            }
        )

    if triggered > 0:
        await db.commit()

    return {
        "evaluated": evaluated,
        "triggered": triggered,
        "events": events_out,
        "evaluated_at": now.isoformat(),
    }
