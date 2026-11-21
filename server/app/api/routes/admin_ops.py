from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models import OpsAlertEvent, OpsAlertRule, User
from app.db.session import get_db
from app.services import audit, ops_service

router = APIRouter(prefix="/api/admin/ops", tags=["admin-ops"], dependencies=[Depends(require_admin)])


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    metric_key: str = Field(min_length=1, max_length=64)
    operator: Literal["gt", "gte", "lt", "lte", "eq"] = "gt"
    threshold: float
    window_minutes: int = Field(default=15, ge=1, le=1440)
    cooldown_minutes: int = Field(default=30, ge=1, le=10080)
    severity: Literal["info", "warning", "critical"] = "warning"
    webhook_url: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    operator: Literal["gt", "gte", "lt", "lte", "eq"] | None = None
    threshold: float | None = None
    window_minutes: int | None = Field(default=None, ge=1, le=1440)
    cooldown_minutes: int | None = Field(default=None, ge=1, le=10080)
    severity: Literal["info", "warning", "critical"] | None = None
    webhook_url: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


def _serialize_rule(rule: OpsAlertRule) -> dict:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "metric_key": rule.metric_key,
        "metric_label": ops_service.SUPPORTED_METRICS.get(rule.metric_key, {}).get("label", rule.metric_key),
        "operator": rule.operator,
        "threshold": rule.threshold,
        "window_minutes": rule.window_minutes,
        "cooldown_minutes": rule.cooldown_minutes,
        "severity": rule.severity,
        "webhook_url": rule.webhook_url,
        "enabled": rule.enabled,
        "last_triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        "created_at": rule.created_at.isoformat(),
    }


def _serialize_event(ev: OpsAlertEvent) -> dict:
    return {
        "id": str(ev.id),
        "rule_id": str(ev.rule_id) if ev.rule_id else None,
        "rule_name": ev.rule_name,
        "metric_key": ev.metric_key,
        "current_value": ev.current_value,
        "threshold": ev.threshold,
        "severity": ev.severity,
        "status": ev.status,
        "message": ev.message,
        "webhook_status": ev.webhook_status,
        "acked_at": ev.acked_at.isoformat() if ev.acked_at else None,
        "created_at": ev.created_at.isoformat(),
    }


@router.get("/inspection")
async def get_ops_inspection(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await ops_service.collect_ops_inspection(db, admin)


@router.get("/slo")
async def get_ops_slo(
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await ops_service.compute_slo_and_anomalies(db)


@router.get("/alerts")
async def list_alerts(
    event_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rules = (await db.execute(select(OpsAlertRule).order_by(OpsAlertRule.created_at.desc()))).scalars().all()
    stmt = select(OpsAlertEvent).order_by(OpsAlertEvent.created_at.desc()).limit(limit)
    if event_status:
        stmt = stmt.where(OpsAlertEvent.status == event_status)
    events = (await db.execute(stmt)).scalars().all()
    return {
        "rules": [_serialize_rule(r) for r in rules],
        "events": [_serialize_event(e) for e in events],
        "supported_metrics": ops_service.SUPPORTED_METRICS,
    }


@router.post("/alerts/rules", status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    body: AlertRuleCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.metric_key not in ops_service.SUPPORTED_METRICS:
        raise HTTPException(status_code=400, detail="unsupported_metric_key")
    rule = OpsAlertRule(
        name=body.name.strip(),
        metric_key=body.metric_key,
        operator=body.operator,
        threshold=body.threshold,
        window_minutes=body.window_minutes,
        cooldown_minutes=body.cooldown_minutes,
        severity=body.severity,
        webhook_url=body.webhook_url.strip() if body.webhook_url else None,
        enabled=body.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    await audit.record(
        "ops.alert_rule.create",
        actor=admin,
        target_type="ops_alert_rule",
        target_id=str(rule.id),
        request=request,
        metadata={"name": rule.name, "metric_key": rule.metric_key},
    )
    return _serialize_rule(rule)


@router.patch("/alerts/rules/{rule_id}")
async def update_alert_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rule = await db.get(OpsAlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="alert_rule_not_found")
    before = _serialize_rule(rule)
    for field in ("name", "operator", "threshold", "window_minutes", "cooldown_minutes", "severity", "enabled"):
        val = getattr(body, field)
        if val is not None:
            setattr(rule, field, val.strip() if isinstance(val, str) else val)
    if body.webhook_url is not None:
        rule.webhook_url = body.webhook_url.strip() or None
    await db.commit()
    await db.refresh(rule)
    after = _serialize_rule(rule)
    await audit.record(
        "ops.alert_rule.update",
        actor=admin,
        target_type="ops_alert_rule",
        target_id=str(rule.id),
        request=request,
        metadata={"name": rule.name, "metric_key": rule.metric_key},
        diff={"before": before, "after": after},
    )
    return after


@router.delete("/alerts/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await db.get(OpsAlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="alert_rule_not_found")
    snapshot = _serialize_rule(rule)
    await db.delete(rule)
    await db.commit()
    await audit.record(
        "ops.alert_rule.delete",
        actor=admin,
        target_type="ops_alert_rule",
        target_id=str(rule_id),
        severity="warning",
        request=request,
        metadata={"name": snapshot["name"], "metric_key": snapshot["metric_key"]},
        diff={"before": snapshot, "after": None},
    )


@router.post("/alerts/rules/{rule_id}/test")
async def test_alert_rule_webhook(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    rule = await db.get(OpsAlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="alert_rule_not_found")
    if not rule.webhook_url:
        raise HTTPException(status_code=400, detail="webhook_url_not_configured")
    status_str = await ops_service.dispatch_webhook(
        rule.webhook_url,
        {
            "event": "whitz.ops.alert.test",
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "metric_key": rule.metric_key,
            "severity": rule.severity,
            "message": f"[测试通知] Whitz 运维告警规则「{rule.name}」Webhook 连通性测试成功。",
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"ok": status_str.startswith("http_2"), "webhook_status": status_str}


@router.post("/alerts/{event_id}/ack")
async def ack_alert_event(
    event_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ev = await db.get(OpsAlertEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="alert_event_not_found")
    prev_status = ev.status
    ev.status = "acked"
    ev.acked_by = admin.id
    ev.acked_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ev)
    await audit.record(
        "ops.alert.ack",
        actor=admin,
        target_type="ops_alert_event",
        target_id=str(ev.id),
        request=request,
        metadata={"rule_name": ev.rule_name, "metric_key": ev.metric_key},
        diff={"before": {"status": prev_status}, "after": {"status": "acked"}},
    )
    return _serialize_event(ev)


@router.post("/alerts/evaluate")
async def evaluate_alerts(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await ops_service.evaluate_alert_rules(db, admin)
