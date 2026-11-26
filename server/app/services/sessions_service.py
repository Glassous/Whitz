"""Shared user session listing and revocation service (batch Redis MGET)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import UserSessionOut
from app.core.security import are_sessions_revoked, revoke_session
from app.db.models import RefreshToken


async def list_user_active_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    current_session_id: uuid.UUID | None = None,
) -> list[UserSessionOut]:
    now = datetime.now(timezone.utc)
    rows = list(
        (
            await db.execute(
                select(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > now,
                )
                .order_by(RefreshToken.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    grouped: dict[uuid.UUID, dict] = {}
    for row in rows:
        sid = row.session_id or row.family_id or row.id
        last_used = row.last_used_at or row.created_at
        existing = grouped.get(sid)
        if existing is None:
            grouped[sid] = {
                "session_id": sid,
                "user_agent": row.user_agent,
                "client_ip": row.client_ip,
                "last_used_at": last_used,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "is_current": current_session_id is not None and sid == current_session_id,
            }
        else:
            if row.created_at < existing["created_at"]:
                existing["created_at"] = row.created_at
            if row.expires_at > existing["expires_at"]:
                existing["expires_at"] = row.expires_at
            if last_used >= (existing["last_used_at"] or existing["created_at"]):
                existing["last_used_at"] = last_used
                if row.user_agent:
                    existing["user_agent"] = row.user_agent
                if row.client_ip:
                    existing["client_ip"] = row.client_ip

    try:
        revoked_map = await are_sessions_revoked(list(grouped.keys()))
    except Exception:
        revoked_map = {}

    sessions: list[UserSessionOut] = []
    for sid, item in grouped.items():
        if revoked_map.get(sid, False):
            continue
        sessions.append(UserSessionOut(**item))

    sessions.sort(
        key=lambda s: (
            1 if s.is_current else 0,
            s.last_used_at or s.created_at,
            s.created_at,
        ),
        reverse=True,
    )
    return sessions


async def revoke_user_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    exclude_session_id: uuid.UUID | None = None,
) -> int:
    now = datetime.now(timezone.utc)
    rows = list(
        (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > now,
                )
            )
        )
        .scalars()
        .all()
    )
    revoke_ids: set[uuid.UUID] = set()
    revoked_rows = 0
    for row in rows:
        sid = row.session_id or row.family_id or row.id
        if exclude_session_id is not None and sid == exclude_session_id:
            continue
        row.revoked_at = now
        revoked_rows += 1
        revoke_ids.add(sid)
        if row.session_id is not None:
            revoke_ids.add(row.session_id)
        if row.family_id is not None:
            revoke_ids.add(row.family_id)

    if revoked_rows:
        await db.commit()

    for sid in revoke_ids:
        await revoke_session(sid)
    return len(revoke_ids)


async def revoke_single_user_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> bool:
    rows = list(
        (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    or_(
                        RefreshToken.session_id == session_id,
                        RefreshToken.family_id == session_id,
                        RefreshToken.id == session_id,
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return False

    now = datetime.now(timezone.utc)
    revoke_ids: set[uuid.UUID] = {session_id}
    for row in rows:
        if row.revoked_at is None:
            row.revoked_at = now
        if row.session_id is not None:
            revoke_ids.add(row.session_id)
        if row.family_id is not None:
            revoke_ids.add(row.family_id)
    await db.commit()
    for sid in revoke_ids:
        await revoke_session(sid)
    return True
