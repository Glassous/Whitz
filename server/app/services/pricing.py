from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelPricing, RunTelemetry

# Fallback USD rates per 1M tokens when no custom DB override exists.
DEFAULT_MODEL_RATES: list[dict[str, Any]] = [
    {"model_pattern": "deepseek-reasoner", "display_name": "DeepSeek R1 / Reasoner", "input_usd_per_1m": 0.55, "output_usd_per_1m": 2.19},
    {"model_pattern": "deepseek-chat", "display_name": "DeepSeek Chat / V3", "input_usd_per_1m": 0.27, "output_usd_per_1m": 1.10},
    {"model_pattern": "qwen-max", "display_name": "Qwen Max", "input_usd_per_1m": 1.60, "output_usd_per_1m": 6.40},
    {"model_pattern": "qwen-plus", "display_name": "Qwen Plus", "input_usd_per_1m": 0.40, "output_usd_per_1m": 1.20},
    {"model_pattern": "qwen-turbo", "display_name": "Qwen Turbo", "input_usd_per_1m": 0.08, "output_usd_per_1m": 0.24},
    {"model_pattern": "gpt-4o-mini", "display_name": "GPT-4o Mini", "input_usd_per_1m": 0.15, "output_usd_per_1m": 0.60},
    {"model_pattern": "gpt-4o", "display_name": "GPT-4o", "input_usd_per_1m": 2.50, "output_usd_per_1m": 10.00},
    {"model_pattern": "o3-mini", "display_name": "OpenAI o3-mini", "input_usd_per_1m": 1.10, "output_usd_per_1m": 4.40},
    {"model_pattern": "claude-3-5-sonnet", "display_name": "Claude 3.5 Sonnet", "input_usd_per_1m": 3.00, "output_usd_per_1m": 15.00},
]

ROUTE_FALLBACK_RATES: dict[str, tuple[float, float]] = {
    "fast": (0.15, 0.60),
    "default": (0.40, 1.50),
    "auto": (0.40, 1.50),
    "vision": (1.20, 4.80),
    "reasoning": (1.50, 6.00),
}


def match_rate(
    model_name: str | None,
    model_route: str | None,
    custom_rates: list[dict[str, Any]] | None = None,
) -> tuple[float, float]:
    """Resolve ``(input_usd_per_1m, output_usd_per_1m)`` by DB pricing table, defaults, then route."""
    cleaned_model = (model_name or "").strip().lower()
    cleaned_route = (model_route or "auto").strip().lower() or "auto"

    candidates = [*(custom_rates or []), *DEFAULT_MODEL_RATES]
    if cleaned_model:
        # Exact match first, then longest prefix/substring match
        for item in candidates:
            if not item.get("is_active", True):
                continue
            pat = str(item.get("model_pattern") or "").strip().lower()
            if pat and cleaned_model == pat:
                return float(item["input_usd_per_1m"]), float(item["output_usd_per_1m"])
        best_match: tuple[int, float, float] | None = None
        for item in candidates:
            if not item.get("is_active", True):
                continue
            pat = str(item.get("model_pattern") or "").strip().lower()
            if pat and pat in cleaned_model:
                score = len(pat)
                if best_match is None or score > best_match[0]:
                    best_match = (score, float(item["input_usd_per_1m"]), float(item["output_usd_per_1m"]))
        if best_match is not None:
            return best_match[1], best_match[2]

    return ROUTE_FALLBACK_RATES.get(cleaned_route, ROUTE_FALLBACK_RATES["default"])


def calculate_cost_usd(
    *,
    model_name: str | None,
    model_route: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    custom_rates: list[dict[str, Any]] | None = None,
) -> float:
    in_rate, out_rate = match_rate(model_name, model_route, custom_rates)
    cost = (max(0, int(prompt_tokens)) * in_rate + max(0, int(completion_tokens)) * out_rate) / 1_000_000.0
    return round(cost, 6)


def calculate_reasoning_baseline_cost_usd(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    custom_rates: list[dict[str, Any]] | None = None,
) -> float:
    """Estimate baseline USD cost if every run had used the reasoning tier without smart routing."""
    in_rate, out_rate = match_rate("__route:reasoning__", "reasoning", custom_rates)
    for item in custom_rates or []:
        if item.get("is_active", True) and str(item.get("model_pattern") or "").lower() == "route:reasoning":
            in_rate = float(item["input_usd_per_1m"])
            out_rate = float(item["output_usd_per_1m"])
            break
    cost = (max(0, int(prompt_tokens)) * in_rate + max(0, int(completion_tokens)) * out_rate) / 1_000_000.0
    return round(cost, 6)


async def list_custom_rates(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(ModelPricing).order_by(ModelPricing.model_pattern.asc()))).scalars().all()
    return [
        {
            "id": str(r.id),
            "model_pattern": r.model_pattern,
            "display_name": r.display_name,
            "input_usd_per_1m": float(r.input_usd_per_1m),
            "output_usd_per_1m": float(r.output_usd_per_1m),
            "is_active": bool(r.is_active),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


async def resolve_and_calculate_cost(
    db: AsyncSession,
    *,
    model_name: str | None,
    model_route: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    try:
        rates = await list_custom_rates(db)
    except Exception:
        rates = []
    return calculate_cost_usd(
        model_name=model_name,
        model_route=model_route,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        custom_rates=rates,
    )


async def upsert_model_pricing(
    db: AsyncSession,
    *,
    model_pattern: str,
    display_name: str,
    input_usd_per_1m: float,
    output_usd_per_1m: float,
    is_active: bool = True,
    actor_id: uuid.UUID | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pattern = model_pattern.strip()
    existing = (
        await db.execute(select(ModelPricing).where(ModelPricing.model_pattern == pattern))
    ).scalar_one_or_none()
    before = (
        {
            "model_pattern": existing.model_pattern,
            "display_name": existing.display_name,
            "input_usd_per_1m": float(existing.input_usd_per_1m),
            "output_usd_per_1m": float(existing.output_usd_per_1m),
            "is_active": bool(existing.is_active),
        }
        if existing
        else None
    )
    if existing is None:
        existing = ModelPricing(
            model_pattern=pattern,
            display_name=display_name.strip() or pattern,
            input_usd_per_1m=max(0.0, float(input_usd_per_1m)),
            output_usd_per_1m=max(0.0, float(output_usd_per_1m)),
            is_active=bool(is_active),
            updated_by=actor_id,
        )
        db.add(existing)
    else:
        existing.display_name = display_name.strip() or existing.display_name or pattern
        existing.input_usd_per_1m = max(0.0, float(input_usd_per_1m))
        existing.output_usd_per_1m = max(0.0, float(output_usd_per_1m))
        existing.is_active = bool(is_active)
        existing.updated_by = actor_id
    await db.commit()
    await db.refresh(existing)
    after = {
        "id": str(existing.id),
        "model_pattern": existing.model_pattern,
        "display_name": existing.display_name,
        "input_usd_per_1m": float(existing.input_usd_per_1m),
        "output_usd_per_1m": float(existing.output_usd_per_1m),
        "is_active": bool(existing.is_active),
        "updated_at": existing.updated_at.isoformat() if existing.updated_at else None,
    }
    return after, {"before": before, "after": after}


async def recalculate_telemetry_costs(db: AsyncSession, *, days: int = 30) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 365)))
    rates = await list_custom_rates(db)
    rows = (
        await db.execute(select(RunTelemetry).where(RunTelemetry.created_at >= since))
    ).scalars().all()
    updated = 0
    for row in rows:
        new_cost = calculate_cost_usd(
            model_name=row.model_name,
            model_route=row.model_route,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            custom_rates=rates,
        )
        if abs(float(row.estimated_cost_usd or 0.0) - new_cost) > 1e-7:
            row.estimated_cost_usd = new_cost
            updated += 1
    if updated > 0:
        await db.commit()
    return updated
