from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    MemoryEntryCreateRequest,
    MemoryEntryUpdateRequest,
    MemoryOverviewOut,
    MemoryPendingResolveRequest,
    MemorySettingsUpdateRequest,
)
from app.db.models import User
from app.db.session import get_db
from app.services import audit, memory_service

router = APIRouter(prefix="/api/users/me/memory", tags=["memory"])


@router.get("", response_model=MemoryOverviewOut)
async def get_memory_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.put("/settings", response_model=MemoryOverviewOut)
async def update_memory_settings(
    body: MemorySettingsUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    if body.enabled is True:
        already_consented = bool(user.memory_enabled and user.memory_consented_at)
        if not already_consented and not body.consent:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "开启长期记忆前请先确认授权")
        user.memory_enabled = True
        if body.consent or user.memory_consented_at is None:
            user.memory_consented_at = datetime.now(timezone.utc)
    elif body.enabled is False:
        user.memory_enabled = False

    if body.require_confirm is not None:
        user.memory_require_confirm = body.require_confirm

    await db.commit()
    await db.refresh(user)

    await audit.record(
        "user.memory_settings_update",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={
            "memory_enabled": user.memory_enabled,
            "memory_require_confirm": user.memory_require_confirm,
        },
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.post("/entries", response_model=MemoryOverviewOut, status_code=status.HTTP_201_CREATED)
async def create_memory_entry(
    body: MemoryEntryCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        entry = await memory_service.add_entry(
            db,
            user.id,
            body.target,
            body.content,
            source="manual",
        )
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "memory.entry_create",
        actor=user,
        target_type="memory_entry",
        target_id=entry["id"],
        request=request,
        metadata={"target": entry["target"]},
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.patch("/entries/{entry_id}", response_model=MemoryOverviewOut)
async def update_memory_entry(
    entry_id: str,
    body: MemoryEntryUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        updated = await memory_service.update_entry(
            db,
            user.id,
            entry_id,
            body.content,
            new_target=body.target,
        )
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "memory.entry_update",
        actor=user,
        target_type="memory_entry",
        target_id=updated["id"],
        request=request,
        metadata={"target": updated["target"]},
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.delete("/entries/{entry_id}", response_model=MemoryOverviewOut)
async def delete_memory_entry(
    entry_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        await memory_service.delete_entry(db, user.id, entry_id)
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "memory.entry_delete",
        actor=user,
        target_type="memory_entry",
        target_id=entry_id,
        request=request,
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.delete("", response_model=MemoryOverviewOut)
async def clear_memory(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    await memory_service.clear_all(db, user.id)
    await audit.record(
        "memory.clear_all",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.post("/pending/{pending_id}", response_model=MemoryOverviewOut)
async def resolve_pending_memory(
    pending_id: str,
    body: MemoryPendingResolveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        await memory_service.resolve_pending(
            db,
            user.id,
            pending_id,
            body.action,
            content_override=body.content,
        )
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "memory.pending_resolve",
        actor=user,
        target_type="memory_pending",
        target_id=pending_id,
        request=request,
        metadata={"action": body.action},
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))
