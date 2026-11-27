from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.metrics import AUDIT_WRITE_FAILURES_TOTAL
from app.core.security import get_client_ip
from app.db.models import AuditLog, User
from app.db.session import SessionLocal

logger = logging.getLogger("whitz.audit")

GENESIS_HASH = "0" * 64
_AUDIT_CHAIN_LOCK_ID = 72910421

_ACTION_BASE_RISK: dict[str, int] = {
    "auth.login_failed": 35,
    "auth.register": 15,
    "auth.password_reset": 45,
    "user.password_change": 45,
    "admin.user_update": 65,
    "admin.session_revoke": 60,
    "admin.run_force_stop": 70,
    "admin.credit_adjust": 60,
    "admin.membership_update": 65,
    "admin.audit_export": 55,
    "admin.pricing_update": 55,
    "admin.pricing_recalculate": 45,
    "admin.feedback_update": 30,
    "ops.alert_rule.create": 40,
    "ops.alert_rule.update": 45,
    "ops.alert_rule.delete": 55,
    "ops.alert.ack": 25,
    "quant.eval.run": 20,
    "chat.rate_limited": 30,
    "chat.credits_exhausted": 25,
    "schedule.create": 20,
    "schedule.update": 20,
    "schedule.delete": 25,
    "schedule.run_now": 15,
    "schedule.proposal.resolve": 20,
    "guardrail.input_blocked": 75,
    "guardrail.tool_blocked": 80,
    "guardrail.pii_redacted": 25,
}


def compute_risk_score(
    action: str,
    *,
    outcome: str = "success",
    severity: str = "info",
    metadata: dict[str, Any] | None = None,
) -> int:
    """Compute a deterministic 0-100 risk score for audit prioritization and anomaly triage."""
    score = _ACTION_BASE_RISK.get(action, 10)
    if action.startswith("admin.") and action not in _ACTION_BASE_RISK:
        score = max(score, 50)
    if action.startswith("ops.") and action not in _ACTION_BASE_RISK:
        score = max(score, 35)
    if outcome != "success":
        score += 20
    if severity == "warning":
        score = max(score, 45)
    elif severity == "critical":
        score = max(score, 85)
    if isinstance(metadata, dict) and metadata.get("mask_pii") is False:
        score += 15
    return max(0, min(100, int(score)))


def _canonical_json(value: Any) -> str:
    if value is None:
        return "null"
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_record_hash(
    *,
    prev_hash: str,
    created_at: datetime,
    actor_user_id: uuid.UUID | None,
    actor_email: str | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    outcome: str,
    severity: str,
    risk_score: int,
    metadata: dict[str, Any] | None,
    diff: dict[str, Any] | None,
) -> str:
    """Compute a tamper-evident HMAC-SHA256 digest chained to ``prev_hash``."""
    ts = created_at.astimezone(timezone.utc) if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    payload = "|".join(
        [
            prev_hash or GENESIS_HASH,
            ts.isoformat(),
            str(actor_user_id) if actor_user_id else "",
            actor_email or "",
            action or "",
            target_type or "",
            target_id or "",
            outcome or "",
            severity or "",
            str(int(risk_score)),
            _canonical_json(metadata),
            _canonical_json(diff),
        ]
    )
    settings = get_settings()
    secret = (settings.audit_hmac_secret or settings.jwt_secret or "").encode("utf-8")
    if secret:
        return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*" * max(1, len(local) - 1)
    else:
        masked_local = local[:2] + "*" * min(6, len(local) - 2)
    return f"{masked_local}@{domain}"


def mask_ip(ip: str | None) -> str | None:
    if not ip:
        return ip
    if "." in ip:
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.*.*"
    if ":" in ip:
        parts = ip.split(":")
        return ":".join(parts[:3]) + ":*:*"
    return "***"


async def record(
    action: str,
    *,
    actor: User | uuid.UUID | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    outcome: str = "success",
    severity: str = "info",
    risk_score: int | None = None,
    request: Request | None = None,
    session_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    diff: dict | None = None,
) -> None:
    settings = get_settings()
    if not settings.audit_enabled:
        return
    actor_user_id: uuid.UUID | None = None
    if isinstance(actor, User):
        actor_user_id = actor.id
        actor_email = actor_email or actor.email
    elif isinstance(actor, uuid.UUID):
        actor_user_id = actor
    if session_id is None and request is not None:
        candidate = getattr(request.state, "session_id", None)
        if isinstance(candidate, uuid.UUID):
            session_id = candidate

    ip = None
    user_agent = None
    request_id = None
    if request is not None:
        ip = get_client_ip(request)
        user_agent = (request.headers.get("user-agent") or "")[:256] or None
        request_id = getattr(request.state, "request_id", None)

    eff_risk = (
        max(0, min(100, int(risk_score)))
        if risk_score is not None
        else compute_risk_score(action, outcome=outcome, severity=severity, metadata=metadata)
    )
    now = datetime.now(timezone.utc)
    target_id_str = str(target_id) if target_id is not None else None

    try:
        async with SessionLocal() as db:
            try:
                await db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _AUDIT_CHAIN_LOCK_ID})
            except Exception:
                pass
            prev_hash = (
                await db.scalar(
                    select(AuditLog.record_hash)
                    .where(AuditLog.record_hash.is_not(None))
                    .order_by(AuditLog.id.desc())
                    .limit(1)
                )
            ) or GENESIS_HASH
            rec_hash = compute_record_hash(
                prev_hash=prev_hash,
                created_at=now,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                action=action,
                target_type=target_type,
                target_id=target_id_str,
                outcome=outcome,
                severity=severity,
                risk_score=eff_risk,
                metadata=metadata,
                diff=diff,
            )
            row = AuditLog(
                created_at=now,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                action=action,
                target_type=target_type,
                target_id=target_id_str,
                outcome=outcome,
                severity=severity,
                risk_score=eff_risk,
                ip=ip,
                user_agent=user_agent,
                request_id=request_id,
                session_id=session_id,
                metadata_=metadata,
                diff=diff,
                prev_hash=prev_hash,
                record_hash=rec_hash,
            )
            db.add(row)
            await db.commit()
    except Exception:
        AUDIT_WRITE_FAILURES_TOTAL.labels(action=action or "unknown").inc()
        logger.warning("audit write failed action=%s", action, exc_info=True)


async def verify_hash_chain(db: AsyncSession, *, limit: int = 1000) -> dict[str, Any]:
    """Verify hash-chain continuity and HMAC integrity over the latest ``limit`` audit records."""
    rows = list(
        (
            await db.execute(
                select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(int(limit), 10000)))
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    if not rows:
        return {
            "valid": True,
            "checked_count": 0,
            "hashed_count": 0,
            "legacy_unhashed_count": 0,
            "broken_at_id": None,
            "reason": None,
            "first_id": None,
            "last_id": None,
        }

    legacy_unhashed = 0
    hashed_count = 0
    prev_expected_hash: str | None = None
    for row in rows:
        if not row.record_hash:
            if hashed_count > 0:
                return {
                    "valid": False,
                    "checked_count": len(rows),
                    "hashed_count": hashed_count,
                    "legacy_unhashed_count": legacy_unhashed,
                    "broken_at_id": row.id,
                    "reason": "missing_record_hash_after_hashed_entry",
                    "first_id": rows[0].id,
                    "last_id": rows[-1].id,
                }
            legacy_unhashed += 1
            continue

        hashed_count += 1
        if prev_expected_hash is not None and row.prev_hash != prev_expected_hash:
            return {
                "valid": False,
                "checked_count": len(rows),
                "hashed_count": hashed_count,
                "legacy_unhashed_count": legacy_unhashed,
                "broken_at_id": row.id,
                "reason": "prev_hash_mismatch",
                "first_id": rows[0].id,
                "last_id": rows[-1].id,
            }

        expected_hash = compute_record_hash(
            prev_hash=row.prev_hash or GENESIS_HASH,
            created_at=row.created_at,
            actor_user_id=row.actor_user_id,
            actor_email=row.actor_email,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            outcome=row.outcome,
            severity=row.severity,
            risk_score=int(row.risk_score or 0),
            metadata=row.metadata_,
            diff=row.diff,
        )
        if not hmac.compare_digest(expected_hash, row.record_hash):
            return {
                "valid": False,
                "checked_count": len(rows),
                "hashed_count": hashed_count,
                "legacy_unhashed_count": legacy_unhashed,
                "broken_at_id": row.id,
                "reason": "record_hash_tampered",
                "first_id": rows[0].id,
                "last_id": rows[-1].id,
            }
        prev_expected_hash = row.record_hash

    return {
        "valid": True,
        "checked_count": len(rows),
        "hashed_count": hashed_count,
        "legacy_unhashed_count": legacy_unhashed,
        "broken_at_id": None,
        "reason": None,
        "first_id": rows[0].id,
        "last_id": rows[-1].id,
    }
