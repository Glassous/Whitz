from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    MemoryCollectionCreateRequest,
    MemoryCollectionUpdateRequest,
    MemoryEntryCreateRequest,
    MemoryEntryUpdateRequest,
    MemoryOverviewOut,
    MemoryPendingResolveRequest,
    MemorySearchRequest,
    MemorySearchResponse,
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
        user.memory_enabled = True
        if body.consent and user.memory_consented_at is None:
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


@router.post("/collections", response_model=MemoryOverviewOut, status_code=status.HTTP_201_CREATED)
async def create_memory_collection(
    body: MemoryCollectionCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        col = await memory_service.create_collection(
            db,
            user.id,
            name=body.name,
            slug=body.slug,
            description=body.description,
            char_limit=body.char_limit,
        )
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "memory.collection_create",
        actor=user,
        target_type="memory_collection",
        target_id=col["id"],
        request=request,
        metadata={"slug": col["slug"], "name": col["name"]},
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.patch("/collections/{collection_id}", response_model=MemoryOverviewOut)
async def update_memory_collection(
    collection_id: str,
    body: MemoryCollectionUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        col = await memory_service.update_collection(
            db,
            user.id,
            collection_id,
            name=body.name,
            description=body.description,
            enabled=body.enabled,
            char_limit=body.char_limit,
            sort_order=body.sort_order,
        )
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "memory.collection_update",
        actor=user,
        target_type="memory_collection",
        target_id=col["id"],
        request=request,
        metadata={"slug": col["slug"], "enabled": col["enabled"]},
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.delete("/collections/{collection_id}", response_model=MemoryOverviewOut)
async def delete_memory_collection(
    collection_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        await memory_service.delete_collection(db, user.id, collection_id)
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "memory.collection_delete",
        actor=user,
        target_type="memory_collection",
        target_id=collection_id,
        request=request,
    )
    return MemoryOverviewOut(**(await memory_service.get_overview(db, user)))


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(
    body: MemorySearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemorySearchResponse:
    hits = await memory_service.search_entries_rag(
        db,
        user.id,
        body.query,
        collection=body.collection,
        limit=body.limit,
    )
    return MemorySearchResponse(
        query=body.query,
        collection=body.collection,
        count=len(hits),
        results=hits,
    )


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
            collection_id=body.collection_id,
            title=body.title,
            tags=body.tags,
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
            new_collection_id=body.collection_id,
            title=body.title,
            tags=body.tags,
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
    collection_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryOverviewOut:
    try:
        await memory_service.clear_all(db, user.id, collection_id=collection_id)
    except memory_service.MemoryServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    await audit.record(
        "memory.clear_all",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"collection_id": collection_id} if collection_id else None,
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
