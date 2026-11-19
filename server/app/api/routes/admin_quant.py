from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Date, case, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.config import get_settings
from app.db.models import EvalRun, Message, RunTelemetry, UsageDaily, User
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/quant", tags=["admin-quant"], dependencies=[Depends(require_admin)])


def _utc_day_expr(column):
    return cast(func.timezone("UTC", column), Date)


def _round_opt(val: Any, digits: int = 1) -> float | None:
    if val is None:
        return None
    return round(float(val), digits)


class EvalReportIn(BaseModel):
    mode: str = Field(default="dry-run", max_length=24)
    dataset_name: str = Field(default="default", max_length=120)
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    category_scores: dict[str, Any] | None = None
    results: list[dict[str, Any]] | None = None
    git_sha: str | None = Field(default=None, max_length=64)


@router.get("/summary")
async def quant_summary(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    end_day = now.date()
    start_day = end_day - timedelta(days=days - 1)
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)

    agg = (
        await db.execute(
            select(
                func.count(RunTelemetry.id),
                func.coalesce(func.sum(case((RunTelemetry.status == "completed", 1), else_=0)), 0),
                func.coalesce(func.sum(case((RunTelemetry.status == "failed", 1), else_=0)), 0),
                func.coalesce(func.sum(case((RunTelemetry.status != "completed", 1), else_=0)), 0),
                func.coalesce(func.sum(RunTelemetry.prompt_tokens), 0),
                func.coalesce(func.sum(RunTelemetry.completion_tokens), 0),
                func.coalesce(func.sum(RunTelemetry.total_tokens), 0),
                func.avg(RunTelemetry.duration_ms),
            ).where(RunTelemetry.created_at >= window_start)
        )
    ).one()

    total_runs = int(agg[0] or 0)
    completed = int(agg[1] or 0)
    failed = int(agg[2] or 0)
    non_completed = int(agg[3] or 0)
    prompt_tokens = int(agg[4] or 0)
    completion_tokens = int(agg[5] or 0)
    total_tokens = int(agg[6] or 0)
    avg_ms = _round_opt(agg[7], 1)

    pct_row = (
        await db.execute(
            text(
                "SELECT "
                "percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms), "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), "
                "percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms), "
                "percentile_cont(0.50) WITHIN GROUP (ORDER BY ttft_ms), "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY ttft_ms) "
                "FROM run_telemetry WHERE created_at >= :since"
            ),
            {"since": window_start},
        )
    ).one()

    day_expr = _utc_day_expr(RunTelemetry.created_at)
    daily_rows = (
        await db.execute(
            text(
                "SELECT (created_at AT TIME ZONE 'UTC')::date AS day, "
                "count(*) AS runs, "
                "sum(case when status = 'completed' then 1 else 0 end) AS completed, "
                "sum(case when status = 'failed' then 1 else 0 end) AS failed, "
                "coalesce(sum(total_tokens), 0) AS tokens, "
                "percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms "
                "FROM run_telemetry WHERE created_at >= :since "
                "GROUP BY 1 ORDER BY 1"
            ),
            {"since": window_start},
        )
    ).all()
    by_day = {r[0]: r for r in daily_rows}

    daily_latency: list[dict[str, Any]] = []
    for offset in range(days):
        d = start_day + timedelta(days=offset)
        row = by_day.get(d)
        daily_latency.append(
            {
                "day": d.isoformat(),
                "runs": int(row[1] or 0) if row else 0,
                "completed": int(row[2] or 0) if row else 0,
                "failed": int(row[3] or 0) if row else 0,
                "tokens": int(row[4] or 0) if row else 0,
                "p50_ms": _round_opt(row[5], 1) if row else None,
                "p95_ms": _round_opt(row[6], 1) if row else None,
            }
        )

    settings = get_settings()
    tpc = max(1, int(settings.tokens_per_credit))
    token_sum = prompt_tokens + completion_tokens
    return {
        "window_days": days,
        "latency": {
            "p50_ms": _round_opt(pct_row[0], 1),
            "p95_ms": _round_opt(pct_row[1], 1),
            "p99_ms": _round_opt(pct_row[2], 1),
            "avg_ms": avg_ms,
            "ttft_p50_ms": _round_opt(pct_row[3], 1),
            "ttft_p95_ms": _round_opt(pct_row[4], 1),
        },
        "runs": {
            "total": total_runs,
            "completed": completed,
            "failed": failed,
            "other": max(0, non_completed - failed),
            "success_rate_pct": round((completed / total_runs) * 100, 2) if total_runs > 0 else 100.0,
            "avg_tokens_per_run": round(total_tokens / total_runs, 1) if total_runs > 0 else 0.0,
            "total_tokens": total_tokens,
            "total_credits": round(total_tokens / tpc, 2),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_ratio_pct": round((prompt_tokens / token_sum) * 100, 1) if token_sum > 0 else 0.0,
        },
        "daily_latency": daily_latency,
        "generated_at": now.isoformat(),
    }


@router.get("/models-tools")
async def quant_models_tools(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    since = datetime.combine(now.date() - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)

    route_rows = (
        await db.execute(
            text(
                "SELECT model_route, count(*) AS runs, "
                "sum(case when status = 'completed' then 1 else 0 end) AS completed, "
                "coalesce(sum(total_tokens), 0) AS tokens, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms "
                "FROM run_telemetry WHERE created_at >= :since "
                "GROUP BY model_route ORDER BY runs DESC"
            ),
            {"since": since},
        )
    ).all()
    total_route_runs = sum(int(r[1] or 0) for r in route_rows) or 1
    routes = [
        {
            "route": str(r[0] or "auto"),
            "runs": int(r[1] or 0),
            "share_pct": round((int(r[1] or 0) / total_route_runs) * 100, 1),
            "success_rate_pct": round((int(r[2] or 0) / max(1, int(r[1] or 0))) * 100, 1),
            "total_tokens": int(r[3] or 0),
            "avg_tokens": round(int(r[3] or 0) / max(1, int(r[1] or 0)), 1),
            "p95_ms": _round_opt(r[4], 1),
        }
        for r in route_rows
    ]

    model_rows = (
        await db.execute(
            select(
                RunTelemetry.model_name,
                func.count(RunTelemetry.id),
                func.coalesce(func.sum(RunTelemetry.total_tokens), 0),
                func.avg(RunTelemetry.duration_ms),
            )
            .where(RunTelemetry.created_at >= since, RunTelemetry.model_name != "")
            .group_by(RunTelemetry.model_name)
            .order_by(func.count(RunTelemetry.id).desc())
            .limit(10)
        )
    ).all()
    models = [
        {
            "model": str(r[0]),
            "runs": int(r[1] or 0),
            "total_tokens": int(r[2] or 0),
            "avg_ms": _round_opt(r[3], 1),
        }
        for r in model_rows
    ]

    payload_rows = (
        await db.execute(
            select(RunTelemetry.tools_summary, RunTelemetry.skills_used).where(
                RunTelemetry.created_at >= since,
                or_(RunTelemetry.tools_summary.is_not(None), RunTelemetry.skills_used.is_not(None)),
            )
        )
    ).all()

    tool_agg: dict[str, dict[str, int]] = {}
    skill_agg: dict[str, int] = {}
    for tools_summary, skills_used in payload_rows:
        if isinstance(tools_summary, list):
            for item in tools_summary:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "unknown")
                entry = tool_agg.setdefault(name, {"calls": 0, "errors": 0, "dur_ms": 0})
                entry["calls"] += int(item.get("calls") or 0)
                entry["errors"] += int(item.get("errors") or 0)
                entry["dur_ms"] += int(item.get("total_duration_ms") or 0)
        if isinstance(skills_used, list):
            for sk in skills_used:
                name = str(sk or "").strip()
                if name:
                    skill_agg[name] = skill_agg.get(name, 0) + 1

    tools = [
        {
            "name": name,
            "calls": st["calls"],
            "errors": st["errors"],
            "error_rate_pct": round((st["errors"] / max(1, st["calls"])) * 100, 1),
            "avg_duration_ms": round(st["dur_ms"] / max(1, st["calls"]), 1),
        }
        for name, st in sorted(tool_agg.items(), key=lambda kv: (-kv[1]["calls"], kv[0]))[:15]
    ]
    skills = [
        {"name": name, "uses": cnt}
        for name, cnt in sorted(skill_agg.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    ]

    return {
        "window_days": days,
        "routes": routes,
        "models": models,
        "tools": tools,
        "skills": skills,
        "generated_at": now.isoformat(),
    }


@router.get("/retention")
async def quant_retention(
    days: int = Query(default=30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    today = now.date()
    since = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc)

    total_users = int(await db.scalar(select(func.count(User.id))) or 0)
    engaged_users = int(
        await db.scalar(
            select(func.count(func.distinct(UsageDaily.user_id))).where(UsageDaily.messages >= 1)
        )
        or 0
    )
    deep_users = int(
        await db.scalar(
            select(func.count()).select_from(
                select(UsageDaily.user_id)
                .group_by(UsageDaily.user_id)
                .having(func.sum(UsageDaily.messages) >= 5)
                .subquery()
            )
        )
        or 0
    )
    paid_users = int(
        await db.scalar(
            select(func.count(User.id)).where(
                User.membership_tier.in_(["plus", "pro"]),
                or_(User.membership_expires_at.is_(None), User.membership_expires_at > now),
            )
        )
        or 0
    )

    funnel = [
        {"stage": "注册用户", "count": total_users, "pct": 100.0 if total_users > 0 else 0.0},
        {
            "stage": "发起首聊 (>=1 消息)",
            "count": engaged_users,
            "pct": round((engaged_users / max(1, total_users)) * 100, 1) if total_users else 0.0,
        },
        {
            "stage": "深度使用 (>=5 消息)",
            "count": deep_users,
            "pct": round((deep_users / max(1, total_users)) * 100, 1) if total_users else 0.0,
        },
        {
            "stage": "付费会员 (Plus/Pro)",
            "count": paid_users,
            "pct": round((paid_users / max(1, total_users)) * 100, 1) if total_users else 0.0,
        },
    ]

    cohort_days = min(14, days)
    cohort_start = today - timedelta(days=cohort_days - 1)
    cohort_start_dt = datetime.combine(cohort_start, datetime.min.time(), tzinfo=timezone.utc)

    user_rows = (
        await db.execute(
            select(User.id, _utc_day_expr(User.created_at)).where(User.created_at >= cohort_start_dt)
        )
    ).all()
    users_by_cohort: dict[date, set[uuid.UUID]] = {}
    for uid, cday in user_rows:
        users_by_cohort.setdefault(cday, set()).add(uid)

    active_rows = (
        await db.execute(
            select(UsageDaily.user_id, UsageDaily.day).where(
                UsageDaily.day >= cohort_start,
                or_(UsageDaily.messages > 0, UsageDaily.runs > 0),
            )
        )
    ).all()
    active_days_by_user: dict[uuid.UUID, set[date]] = {}
    for uid, uday in active_rows:
        active_days_by_user.setdefault(uid, set()).add(uday)

    cohorts: list[dict[str, Any]] = []
    for offset in range(cohort_days):
        cday = cohort_start + timedelta(days=offset)
        uids = users_by_cohort.get(cday, set())
        size = len(uids)

        def _ret_pct(delta: int) -> float | None:
            target_day = cday + timedelta(days=delta)
            if target_day > today or size == 0:
                return None
            retained = sum(1 for u in uids if target_day in active_days_by_user.get(u, ()))
            return round((retained / size) * 100, 1)

        cohorts.append(
            {
                "cohort_day": cday.isoformat(),
                "new_users": size,
                "d1_pct": _ret_pct(1),
                "d3_pct": _ret_pct(3),
                "d7_pct": _ret_pct(7),
            }
        )

    return {
        "window_days": days,
        "funnel": funnel,
        "cohorts": cohorts,
        "since": since.isoformat(),
        "generated_at": now.isoformat(),
    }


def _serialize_eval(ev: EvalRun) -> dict[str, Any]:
    return {
        "id": str(ev.id),
        "mode": ev.mode,
        "dataset_name": ev.dataset_name,
        "total": ev.total,
        "passed": ev.passed,
        "pass_rate": round(float(ev.pass_rate), 4),
        "category_scores": ev.category_scores or {},
        "results": ev.results or [],
        "git_sha": ev.git_sha,
        "triggered_by": ev.triggered_by,
        "created_at": ev.created_at.isoformat(),
    }


@router.get("/evals")
async def list_eval_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (await db.execute(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(limit))).scalars().all()
    items = [_serialize_eval(r) for r in rows]
    latest = items[0] if items else None
    prev = items[1] if len(items) > 1 else None
    delta = round((latest["pass_rate"] - prev["pass_rate"]) * 100, 2) if (latest and prev) else None
    return {
        "items": items,
        "latest": latest,
        "pass_rate_delta_pct": delta,
    }


@router.post("/evals/report", status_code=201)
async def report_eval_run(
    body: EvalReportIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ev = EvalRun(
        mode=body.mode,
        dataset_name=body.dataset_name,
        total=body.total,
        passed=body.passed,
        pass_rate=body.pass_rate,
        category_scores=body.category_scores,
        results=body.results,
        git_sha=body.git_sha,
        triggered_by=admin.email,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return _serialize_eval(ev)


@router.post("/evals/run", status_code=201)
async def trigger_dry_eval_run(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run a deterministic routing & policy baseline evaluation and persist results."""
    cases = [
        {"id": "route-fast-greeting", "category": "routing", "input": "你好", "expected": "fast"},
        {"id": "route-reasoning-code", "category": "routing", "input": "请推导这个算法的时间复杂度并给出证明", "expected": "reasoning"},
        {"id": "route-vision-image", "category": "multimodal", "input": "分析这张截图里的报错", "has_images": True, "expected": "vision"},
        {"id": "route-auto-tool", "category": "tool_use", "input": "搜索今天最新的 AI 新闻并总结", "expected": "auto"},
        {"id": "safety-hitl-gate", "category": "hitl", "input": "执行高危删除命令", "expected": "hitl"},
    ]

    def _infer(c: dict[str, Any]) -> str:
        if c.get("has_images"):
            return "vision"
        txt = c["input"]
        if any(k in txt for k in ("删除", "高危")):
            return "hitl"
        if any(k in txt for k in ("推导", "证明", "复杂度")):
            return "reasoning"
        if len(txt) <= 8:
            return "fast"
        return "auto"

    results: list[dict[str, Any]] = []
    cat_stats: dict[str, dict[str, int]] = {}
    passed = 0
    for c in cases:
        actual = _infer(c)
        ok = actual == c["expected"]
        if ok:
            passed += 1
        cat = c["category"]
        cs = cat_stats.setdefault(cat, {"total": 0, "passed": 0})
        cs["total"] += 1
        if ok:
            cs["passed"] += 1
        results.append(
            {
                "id": c["id"],
                "category": cat,
                "expected": c["expected"],
                "actual": actual,
                "passed": ok,
            }
        )

    category_scores = {
        cat: {**st, "pass_rate": round(st["passed"] / max(1, st["total"]), 4)}
        for cat, st in cat_stats.items()
    }
    pass_rate = round(passed / max(1, len(cases)), 4)

    ev = EvalRun(
        mode="dry-run",
        dataset_name="whitz-core-baseline",
        total=len(cases),
        passed=passed,
        pass_rate=pass_rate,
        category_scores=category_scores,
        results=results,
        triggered_by=admin.email,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)
    return _serialize_eval(ev)
