from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Date, case, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.config import get_settings
from app.db.models import (
    EvalRun,
    MessageReaction,
    RunTelemetry,
    UsageDaily,
    User,
    UserFeedback,
)
from app.db.session import get_db
from app.services import audit, pricing, reactions

router = APIRouter(prefix="/api/admin/quant", tags=["admin-quant"], dependencies=[Depends(require_admin)])

_DATASET_CANDIDATES = (
    Path(__file__).resolve().parents[4] / "agent" / "evals" / "dataset.json",
    Path("/app/agent_evals/dataset.json"),
)


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


class ModelPricingUpsertIn(BaseModel):
    model_pattern: str = Field(min_length=1, max_length=120)
    display_name: str = Field(default="", max_length=120)
    input_usd_per_1m: float = Field(ge=0.0, le=10000.0)
    output_usd_per_1m: float = Field(ge=0.0, le=10000.0)
    is_active: bool = True


class FeedbackAdminUpdateIn(BaseModel):
    status: Literal["new", "reviewed", "resolved"]
    admin_note: str | None = Field(default=None, max_length=500)


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
                func.coalesce(func.sum(RunTelemetry.estimated_cost_usd), 0.0),
                func.coalesce(func.sum(case((RunTelemetry.is_regenerated.is_(True), 1), else_=0)), 0),
                func.coalesce(func.sum(RunTelemetry.hitl_denied_count), 0),
                func.coalesce(func.sum(RunTelemetry.tool_calls_count), 0),
                func.coalesce(func.sum(RunTelemetry.tool_errors_count), 0),
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
    total_cost_usd = round(float(agg[8] or 0.0), 4)
    regenerated_runs = int(agg[9] or 0)
    hitl_denied = int(agg[10] or 0)
    tool_calls_total = int(agg[11] or 0)
    tool_errors_total = int(agg[12] or 0)

    custom_rates = await pricing.list_custom_rates(db)
    # If stored cost is zero on legacy rows with tokens, compute display cost cleanly
    if total_cost_usd == 0.0 and total_tokens > 0:
        tel_rows = (
            await db.execute(
                select(
                    RunTelemetry.model_name,
                    RunTelemetry.model_route,
                    RunTelemetry.prompt_tokens,
                    RunTelemetry.completion_tokens,
                    RunTelemetry.estimated_cost_usd,
                ).where(RunTelemetry.created_at >= window_start)
            )
        ).all()
        computed_sum = 0.0
        for mname, mroute, pt, ct, stored_c in tel_rows:
            c = float(stored_c or 0.0)
            if c <= 0.0 and (int(pt or 0) + int(ct or 0)) > 0:
                c = pricing.calculate_cost_usd(
                    model_name=mname,
                    model_route=mroute,
                    prompt_tokens=int(pt or 0),
                    completion_tokens=int(ct or 0),
                    custom_rates=custom_rates,
                )
            computed_sum += c
        total_cost_usd = round(computed_sum, 4)

    baseline_reasoning_cost_usd = round(
        pricing.calculate_reasoning_baseline_cost_usd(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            custom_rates=custom_rates,
        ),
        4,
    )
    routing_savings_usd = round(max(0.0, baseline_reasoning_cost_usd - total_cost_usd), 4)
    routing_savings_pct = (
        round((routing_savings_usd / baseline_reasoning_cost_usd) * 100, 1)
        if baseline_reasoning_cost_usd > 0
        else 0.0
    )

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

    daily_rows = (
        await db.execute(
            text(
                "SELECT (created_at AT TIME ZONE 'UTC')::date AS day, "
                "count(*) AS runs, "
                "sum(case when status = 'completed' then 1 else 0 end) AS completed, "
                "sum(case when status = 'failed' then 1 else 0 end) AS failed, "
                "coalesce(sum(total_tokens), 0) AS tokens, "
                "percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms, "
                "coalesce(sum(estimated_cost_usd), 0) AS cost_usd "
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
                "cost_usd": round(float(row[7] or 0.0), 4) if row else 0.0,
            }
        )

    # User reaction CSAT & AI positive reaction stats in window
    reaction_rows = (
        await db.execute(
            select(MessageReaction.author_type, MessageReaction.reaction, func.count(MessageReaction.id))
            .where(MessageReaction.created_at >= window_start)
            .group_by(MessageReaction.author_type, MessageReaction.reaction)
        )
    ).all()
    user_total_reactions = 0
    user_positive_reactions = 0
    ai_positive_reactions = 0
    for author_type, rname, cnt in reaction_rows:
        c = int(cnt or 0)
        if author_type == "assistant":
            ai_positive_reactions += c
        else:
            user_total_reactions += c
            if rname in reactions.POSITIVE_REACTIONS:
                user_positive_reactions += c
    csat_pct = (
        round((user_positive_reactions / user_total_reactions) * 100, 1)
        if user_total_reactions > 0
        else None
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
        "finops": {
            "total_cost_usd": total_cost_usd,
            "avg_cost_per_run_usd": round(total_cost_usd / total_runs, 5) if total_runs > 0 else 0.0,
            "baseline_reasoning_cost_usd": baseline_reasoning_cost_usd,
            "routing_savings_usd": routing_savings_usd,
            "routing_savings_pct": routing_savings_pct,
        },
        "quality": {
            "regenerate_count": regenerated_runs,
            "regenerate_rate_pct": round((regenerated_runs / total_runs) * 100, 2) if total_runs > 0 else 0.0,
            "hitl_denied_count": hitl_denied,
            "hitl_deny_rate_pct": round((hitl_denied / total_runs) * 100, 2) if total_runs > 0 else 0.0,
            "tool_calls_total": tool_calls_total,
            "tool_error_rate_pct": round((tool_errors_total / max(1, tool_calls_total)) * 100, 2)
            if tool_calls_total > 0
            else 0.0,
            "user_reactions_total": user_total_reactions,
            "user_positive_reactions": user_positive_reactions,
            "csat_pct": csat_pct,
            "ai_positive_reactions": ai_positive_reactions,
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
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms, "
                "coalesce(sum(estimated_cost_usd), 0) AS cost_usd "
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
            "cost_usd": round(float(r[5] or 0.0), 4),
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
                func.coalesce(func.sum(RunTelemetry.estimated_cost_usd), 0.0),
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
            "cost_usd": round(float(r[4] or 0.0), 4),
        }
        for r in model_rows
    ]

    tier_rows = (
        await db.execute(
            select(
                User.membership_tier,
                func.count(func.distinct(RunTelemetry.user_id)),
                func.count(RunTelemetry.id),
                func.coalesce(func.sum(RunTelemetry.total_tokens), 0),
                func.coalesce(func.sum(RunTelemetry.estimated_cost_usd), 0.0),
            )
            .join(User, RunTelemetry.user_id == User.id)
            .where(RunTelemetry.created_at >= since)
            .group_by(User.membership_tier)
        )
    ).all()
    tier_economics = [
        {
            "tier": str(r[0] or "free"),
            "active_users": int(r[1] or 0),
            "runs": int(r[2] or 0),
            "tokens": int(r[3] or 0),
            "cost_usd": round(float(r[4] or 0.0), 4),
            "avg_cost_per_user_usd": round(float(r[4] or 0.0) / max(1, int(r[1] or 0)), 4),
        }
        for r in tier_rows
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
        "tier_economics": tier_economics,
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

    dau = int(
        await db.scalar(
            select(func.count(func.distinct(UsageDaily.user_id))).where(
                UsageDaily.day == today,
                or_(UsageDaily.messages > 0, UsageDaily.runs > 0),
            )
        )
        or 0
    )
    mau_since = today - timedelta(days=29)
    mau = int(
        await db.scalar(
            select(func.count(func.distinct(UsageDaily.user_id))).where(
                UsageDaily.day >= mau_since,
                or_(UsageDaily.messages > 0, UsageDaily.runs > 0),
            )
        )
        or 0
    )
    stickiness_pct = round((dau / mau) * 100, 1) if mau > 0 else 0.0

    cohort_days = min(30, days)
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
                "d14_pct": _ret_pct(14),
                "d30_pct": _ret_pct(30),
            }
        )

    return {
        "window_days": days,
        "stickiness": {"dau": dau, "mau": mau, "dau_mau_pct": stickiness_pct},
        "funnel": funnel,
        "cohorts": cohorts,
        "since": since.isoformat(),
        "generated_at": now.isoformat(),
    }


@router.get("/feedback")
async def quant_feedback_overview(
    days: int = Query(default=30, ge=1, le=90),
    status_filter: str | None = Query(default=None, pattern="^(new|reviewed|resolved)$"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    reaction_rows = (
        await db.execute(
            select(MessageReaction.author_type, MessageReaction.reaction, func.count(MessageReaction.id))
            .where(MessageReaction.created_at >= since)
            .group_by(MessageReaction.author_type, MessageReaction.reaction)
        )
    ).all()
    user_breakdown: dict[str, int] = {}
    ai_breakdown: dict[str, int] = {}
    for author_type, rname, cnt in reaction_rows:
        target = ai_breakdown if author_type == "assistant" else user_breakdown
        target[str(rname)] = int(cnt or 0)

    reason_rows = (
        await db.execute(
            select(MessageReaction.reason_code, func.count(MessageReaction.id))
            .where(
                MessageReaction.created_at >= since,
                MessageReaction.author_type == "user",
                MessageReaction.reason_code.is_not(None),
                MessageReaction.reason_code != "",
            )
            .group_by(MessageReaction.reason_code)
            .order_by(func.count(MessageReaction.id).desc())
            .limit(8)
        )
    ).all()
    dislike_reasons = [{"reason": str(r[0]), "count": int(r[1] or 0)} for r in reason_rows]

    fb_stmt = (
        select(UserFeedback, User.email, User.display_name)
        .join(User, UserFeedback.user_id == User.id)
        .order_by(UserFeedback.created_at.desc())
        .limit(50)
    )
    if status_filter:
        fb_stmt = fb_stmt.where(UserFeedback.status == status_filter)
    fb_rows = (await db.execute(fb_stmt)).all()

    avg_rating_raw = await db.scalar(
        select(func.avg(UserFeedback.rating)).where(UserFeedback.created_at >= since)
    )
    total_feedbacks = int(
        await db.scalar(select(func.count(UserFeedback.id)).where(UserFeedback.created_at >= since)) or 0
    )

    feedbacks = [
        {
            "id": str(fb.id),
            "user_id": str(fb.user_id),
            "user_email": email,
            "user_display_name": display_name,
            "rating": fb.rating,
            "sentiment": fb.sentiment,
            "category": fb.category,
            "content": fb.content,
            "status": fb.status,
            "admin_note": fb.admin_note,
            "created_at": fb.created_at.isoformat(),
            "updated_at": fb.updated_at.isoformat(),
        }
        for fb, email, display_name in fb_rows
    ]

    return {
        "window_days": days,
        "reactions": {
            "user_breakdown": user_breakdown,
            "user_total": sum(user_breakdown.values()),
            "ai_breakdown": ai_breakdown,
            "ai_total": sum(ai_breakdown.values()),
            "dislike_reasons": dislike_reasons,
        },
        "product_feedback": {
            "total": total_feedbacks,
            "avg_rating": round(float(avg_rating_raw), 2) if avg_rating_raw is not None else None,
            "items": feedbacks,
        },
        "generated_at": now.isoformat(),
    }


@router.patch("/feedback/{feedback_id}")
async def update_feedback_status(
    feedback_id: uuid.UUID,
    body: FeedbackAdminUpdateIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    fb = await db.get(UserFeedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="feedback_not_found")
    before = {"status": fb.status, "admin_note": fb.admin_note}
    fb.status = body.status
    if body.admin_note is not None:
        fb.admin_note = body.admin_note.strip() or None
    await db.commit()
    await db.refresh(fb)
    after = {"status": fb.status, "admin_note": fb.admin_note}
    await audit.record(
        "admin.feedback_update",
        actor=admin,
        target_type="user_feedback",
        target_id=str(fb.id),
        request=request,
        diff={"before": before, "after": after},
    )
    return {
        "id": str(fb.id),
        "status": fb.status,
        "admin_note": fb.admin_note,
        "updated_at": fb.updated_at.isoformat(),
    }


@router.get("/pricing")
async def get_model_pricing(db: AsyncSession = Depends(get_db)) -> dict:
    custom = await pricing.list_custom_rates(db)
    return {
        "custom": custom,
        "defaults": pricing.DEFAULT_MODEL_RATES,
        "route_fallbacks": [
            {"route": k, "input_usd_per_1m": v[0], "output_usd_per_1m": v[1]}
            for k, v in pricing.ROUTE_FALLBACK_RATES.items()
        ],
    }


@router.put("/pricing")
async def upsert_model_pricing(
    body: ModelPricingUpsertIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    saved, diff = await pricing.upsert_model_pricing(
        db,
        model_pattern=body.model_pattern,
        display_name=body.display_name,
        input_usd_per_1m=body.input_usd_per_1m,
        output_usd_per_1m=body.output_usd_per_1m,
        is_active=body.is_active,
        actor_id=admin.id,
    )
    await audit.record(
        "admin.pricing_update",
        actor=admin,
        target_type="model_pricing",
        target_id=saved["id"],
        request=request,
        metadata={"model_pattern": saved["model_pattern"]},
        diff=diff,
    )
    return saved


@router.post("/pricing/recalculate")
async def recalculate_pricing(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    updated = await pricing.recalculate_telemetry_costs(db, days=days)
    await audit.record(
        "admin.pricing_recalculate",
        actor=admin,
        target_type="run_telemetry",
        request=request,
        metadata={"days": days, "updated_rows": updated},
    )
    return {"days": days, "updated_rows": updated}


@router.get("/export")
async def export_quant_csv(
    request: Request,
    days: int = Query(default=30, ge=1, le=90),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    summary_data = await quant_summary(days=days, db=db)
    await audit.record(
        "admin.quant_export",
        actor=admin,
        target_type="quant_report",
        request=request,
        metadata={"days": days},
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["day", "runs", "completed", "failed", "tokens", "p50_ms", "p95_ms", "cost_usd"])
    for row in summary_data["daily_latency"]:
        writer.writerow(
            [
                row["day"],
                row["runs"],
                row["completed"],
                row["failed"],
                row["tokens"],
                row["p50_ms"] if row["p50_ms"] is not None else "",
                row["p95_ms"] if row["p95_ms"] is not None else "",
                row["cost_usd"],
            ]
        )
    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="whitz-quant-{days}d-{ts_tag}.csv"'},
    )


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
    request: Request,
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
    await audit.record(
        "quant.eval.report",
        actor=admin,
        target_type="eval_run",
        target_id=str(ev.id),
        request=request,
        metadata={"dataset_name": ev.dataset_name, "pass_rate": ev.pass_rate},
    )
    return _serialize_eval(ev)


def _load_golden_cases() -> tuple[str, list[dict[str, Any]]]:
    for path in _DATASET_CANDIDATES:
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, list) and raw:
                    return "whitz-agent-golden", raw
            except Exception:
                pass
    return "whitz-core-baseline", [
        {"id": "route-fast-greeting", "category": "routing", "input": "你好", "expected_route": "fast"},
        {
            "id": "route-reasoning-code",
            "category": "routing",
            "input": "请推导这个算法的时间复杂度并给出证明",
            "expected_route": "reasoning",
        },
        {
            "id": "route-vision-image",
            "category": "multimodal",
            "input": "分析这张截图里的报错",
            "has_images": True,
            "expected_route": "vision",
        },
        {
            "id": "route-auto-tool",
            "category": "tool_use",
            "input": "搜索今天最新的 AI 新闻并总结",
            "expected_route": "default",
        },
        {
            "id": "safety-hitl-gate",
            "category": "hitl",
            "input": "请用 Python 计算斐波那契数列第 20 项并验证结果",
            "expected_route": "reasoning",
        },
    ]


def _infer_route_deterministic(case: dict[str, Any]) -> str:
    req = str(case.get("requested_route") or "auto").strip().lower()
    if req in ("fast", "reasoning", "vision", "default"):
        return req
    if case.get("has_images"):
        return "vision"
    txt = str(case.get("input") or "").strip()
    low = txt.lower().strip("!！。.~～ ")
    if (
        low in {"hi", "hello", "hey", "你好", "您好", "在吗", "谢谢", "感谢", "ok", "好的", "嗯"}
        or (low.startswith(("你好", "您好", "hi ", "hello ")) and len(low) <= 24)
        or (len(low) <= 8 and "?" not in low and "？" not in low)
    ):
        return "fast"
    if len(txt) >= 180 or "```" in txt or any(
        k in txt.lower()
        for k in (
            "推导",
            "证明",
            "算法",
            "复杂度",
            "重构",
            "架构",
            "系统设计",
            "五步计划",
            "计算",
            "python",
            "调研",
            "对比",
            "最佳实践",
        )
    ):
        return "reasoning"
    return "default"


@router.post("/evals/run", status_code=201)
async def trigger_dry_eval_run(
    request: Request,
    dataset: Literal["baseline", "golden"] = Query(default="baseline"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run deterministic routing & policy evaluation against baseline or golden dataset."""
    if dataset == "golden":
        dataset_name, cases = _load_golden_cases()
    else:
        dataset_name = "whitz-core-baseline"
        cases = [
            {"id": "route-fast-greeting", "category": "routing", "input": "你好", "expected_route": "fast"},
            {
                "id": "route-reasoning-code",
                "category": "routing",
                "input": "请推导这个算法的时间复杂度并给出证明",
                "expected_route": "reasoning",
            },
            {
                "id": "route-vision-image",
                "category": "multimodal",
                "input": "分析这张截图里的报错",
                "has_images": True,
                "expected_route": "vision",
            },
            {
                "id": "route-auto-tool",
                "category": "tool_use",
                "input": "搜索今天最新的 AI 新闻并总结",
                "expected_route": "default",
            },
            {
                "id": "safety-hitl-gate",
                "category": "hitl",
                "input": "请用 Python 计算斐波那契数列第 20 项并验证结果",
                "expected_route": "reasoning",
            },
        ]

    results: list[dict[str, Any]] = []
    cat_stats: dict[str, dict[str, int]] = {}
    passed = 0
    for c in cases:
        expected = str(c.get("expected_route") or c.get("expected") or "default")
        actual = _infer_route_deterministic(c)
        ok = actual == expected
        if ok:
            passed += 1
        cat = str(c.get("category") or "general")
        cs = cat_stats.setdefault(cat, {"total": 0, "passed": 0})
        cs["total"] += 1
        if ok:
            cs["passed"] += 1
        results.append(
            {
                "id": str(c.get("id") or f"case-{len(results) + 1}"),
                "category": cat,
                "expected": expected,
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
        dataset_name=dataset_name,
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
    await audit.record(
        "quant.eval.run",
        actor=admin,
        target_type="eval_run",
        target_id=str(ev.id),
        request=request,
        metadata={"dataset_name": dataset_name, "total": ev.total, "passed": ev.passed, "pass_rate": ev.pass_rate},
    )
    return _serialize_eval(ev)
