from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation
from app.api.routes.files import (
    cleanup_expired_pending_files,
    read_preview_content_payload,
    serialize_file_out,
)
from app.api.schemas import (
    AttachLibraryFilesRequest,
    ConversationFileOut,
    FileCompleteRequest,
    FileDownloadUrlOut,
    FilePresignOut,
    FilePresignRequest,
    LibraryFileOut,
    LibraryFileUpdateRequest,
)
from app.core.config import get_settings
from app.db.models import Conversation, ConversationFile, User
from app.db.session import get_db
from app.services import audit, cos, file_chunks, file_types
from app.services.file_types import FileValidationError, validate_upload_request

router = APIRouter(tags=["library"])


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _get_owned_library_file(
    file_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> ConversationFile:
    row = await db.get(ConversationFile, file_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return row


@router.get("/api/library/files")
async def list_library_files(
    background_tasks: BackgroundTasks,
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=24),
    is_global: bool | None = Query(default=None),
    source: str | None = Query(default=None, max_length=24),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await cleanup_expired_pending_files(db, user_id=user.id, background_tasks=background_tasks)

    stmt = (
        select(ConversationFile, Conversation.title, Conversation.kind)
        .outerjoin(Conversation, ConversationFile.conversation_id == Conversation.id)
        .where(
            ConversationFile.user_id == user.id,
            ConversationFile.status == "ready",
        )
    )
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(ConversationFile.filename.ilike(pattern, escape="\\"))
    if category and category.strip():
        stmt = stmt.where(ConversationFile.category == category.strip())
    if source and source.strip():
        stmt = stmt.where(ConversationFile.source == source.strip())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(
            stmt.order_by(ConversationFile.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    settings = get_settings()
    assistant_label = (user.assistant_name or "").strip() or "Whitz"
    items = [
        serialize_file_out(
            file_row,
            settings=settings,
            conversation_title=(
                f"{assistant_label}（主聊）" if conv_kind == "main" else conv_title
            ),
            as_library=True,
        )
        for file_row, conv_title, conv_kind in rows
    ]
    return {
        "items": items,
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


@router.post("/api/library/files/presign", response_model=FilePresignOut)
async def presign_library_upload(
    body: FilePresignRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    if not settings.cos_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储服务尚未配置")

    try:
        info = validate_upload_request(
            body.filename,
            body.mime_type,
            body.size_bytes,
            settings.max_file_size_bytes,
        )
    except FileValidationError as exc:
        raise HTTPException(422, str(exc)) from exc

    await cleanup_expired_pending_files(db, user_id=user.id, background_tasks=background_tasks)

    file_id = uuid.uuid4()
    storage_key = cos.build_storage_key(user.id, None, file_id, info.filename, settings=settings)
    try:
        signed = await cos.presign_put(
            key=storage_key,
            content_type=info.mime_type,
            content_length=info.size_bytes,
            settings=settings,
        )
    except cos.CosError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    ttl = max(60, int(settings.pending_file_ttl_seconds or 1800))
    record = ConversationFile(
        id=file_id,
        conversation_id=None,
        user_id=user.id,
        filename=info.filename,
        ext=info.ext,
        mime_type=info.mime_type,
        category=info.category,
        size_bytes=info.size_bytes,
        storage_key=storage_key,
        status="pending",
        source="user",
        is_global=True,
        expires_cleanup_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
    )
    db.add(record)
    await db.commit()

    await audit.record(
        "library.file_presign",
        actor=user,
        target_type="conversation_file",
        target_id=file_id,
        request=request,
        metadata={"filename": info.filename, "size_bytes": info.size_bytes},
    )
    return {
        "file_id": file_id,
        "filename": info.filename,
        "ext": info.ext,
        "category": info.category,
        "mime_type": info.mime_type,
        "size_bytes": info.size_bytes,
        "upload_url": signed["url"],
        "method": signed["method"],
        "headers": signed["headers"],
        "expires_in": signed["expires_in"],
    }


@router.post("/api/library/files/{file_id}/complete", response_model=LibraryFileOut)
async def complete_library_upload(
    file_id: uuid.UUID,
    request: Request,
    body: FileCompleteRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryFileOut:
    record = await _get_owned_library_file(file_id, user, db)
    settings = get_settings()
    if record.status == "ready":
        return serialize_file_out(record, settings=settings, conversation_title=None, as_library=True)

    try:
        meta = await cos.head_object(record.storage_key)
    except cos.CosError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    if meta is None:
        record.status = "failed"
        record.error_message = "COS 中未找到已上传对象"
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件尚未上传完成，请重试")

    actual_size = meta.get("content_length")
    if actual_size is not None and actual_size != record.size_bytes:
        record.status = "failed"
        record.error_message = f"文件大小校验不匹配: 预期 {record.size_bytes}, 实际 {actual_size}"
        await db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "上传文件大小与签名不一致")

    record.status = "ready"
    record.is_global = True
    record.error_message = None
    record.expires_cleanup_at = None
    record.etag = (body.etag if body and body.etag else None) or meta.get("etag")
    is_large_async = (
        settings.app_env == "production"
        and record.category != "image"
        and int(record.size_bytes or 0) > 256 * 1024
    )
    record.index_status = "indexing" if is_large_async else "ready"
    await db.commit()
    await db.refresh(record)

    if is_large_async:
        file_chunks.schedule_file_indexing(record.id, user.id)
    else:
        await file_chunks.index_file_chunks_safe(db, record)
        await db.refresh(record)

    from app.services import realtime_bus

    await realtime_bus.publish_user_event(
        user.id,
        "library.updated",
        {"action": "added", "file_id": str(record.id), "index_status": record.index_status},
    )

    await audit.record(
        "library.file_complete",
        actor=user,
        target_type="conversation_file",
        target_id=record.id,
        request=request,
        metadata={"filename": record.filename},
    )
    return serialize_file_out(record, settings=settings, conversation_title=None, as_library=True)


@router.patch("/api/library/files/{file_id}", response_model=LibraryFileOut)
async def update_library_file(
    file_id: uuid.UUID,
    body: LibraryFileUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryFileOut:
    row = await _get_owned_library_file(file_id, user, db)
    if row.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "文件尚未就绪")

    changes: dict = {}
    # All library files are globally shared; keep is_global=True regardless of legacy payloads.
    if not row.is_global:
        row.is_global = True

    if body.filename is not None:
        cleaned = file_types.sanitize_filename(body.filename)
        if not cleaned:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件名不能为空")
        _, new_ext = os.path.splitext(cleaned)
        if not new_ext and row.ext:
            cleaned = f"{cleaned}{row.ext}"
            new_ext = row.ext
        new_ext = new_ext.lower()
        if new_ext != (row.ext or "").lower():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "重命名文件时不能更改文件扩展名")
        if cleaned != row.filename:
            row.filename = cleaned
            changes["filename"] = cleaned

    await db.commit()
    await db.refresh(row)

    conv_title = None
    if row.conversation_id is not None:
        conv_title = await db.scalar(select(Conversation.title).where(Conversation.id == row.conversation_id))

    if changes:
        await audit.record(
            "library.file_update",
            actor=user,
            target_type="conversation_file",
            target_id=row.id,
            request=request,
            metadata=changes,
        )

    return serialize_file_out(row, settings=get_settings(), conversation_title=conv_title, as_library=True)


@router.delete("/api/library/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_file(
    file_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_owned_library_file(file_id, user, db)
    storage_key = row.storage_key
    filename = row.filename
    await db.delete(row)
    await db.commit()
    if storage_key:
        background_tasks.add_task(cos.delete_object, storage_key)
    from app.services import realtime_bus

    await realtime_bus.publish_user_event(
        user.id,
        "library.updated",
        {"action": "deleted", "file_id": str(file_id)},
    )
    await audit.record(
        "library.file_delete",
        actor=user,
        target_type="conversation_file",
        target_id=file_id,
        request=request,
        metadata={"filename": filename},
    )


@router.get("/api/library/files/{file_id}/download-url", response_model=FileDownloadUrlOut)
async def get_library_download_url(
    file_id: uuid.UUID,
    inline: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_owned_library_file(file_id, user, db)
    if row.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "文件尚未就绪")
    settings = get_settings()
    try:
        url = cos.presign_get(
            key=row.storage_key,
            filename=row.filename,
            inline=inline,
            settings=settings,
        )
    except cos.CosError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return {"url": url, "expires_in": settings.cos_download_expires_seconds}


@router.get("/api/library/files/{file_id}/preview-content")
async def get_library_preview_content(
    file_id: uuid.UUID,
    sheet_name: str | None = Query(default=None, max_length=128),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_owned_library_file(file_id, user, db)
    return await read_preview_content_payload(row, sheet_name=sheet_name)


@router.post("/api/conversations/{conversation_id}/files/attach", response_model=list[ConversationFileOut])
async def attach_library_files(
    body: AttachLibraryFilesRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationFileOut]:
    await cleanup_expired_pending_files(db, conversation_id=conv.id, background_tasks=background_tasks)

    unique_ids = list(dict.fromkeys(body.file_ids))
    rows = list(
        (
            await db.execute(
                select(ConversationFile).where(
                    ConversationFile.id.in_(unique_ids),
                    ConversationFile.user_id == user.id,
                    ConversationFile.status == "ready",
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}
    if len(by_id) != len(unique_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "部分文件不存在、未就绪或无权访问")

    settings = get_settings()
    attached_rows = [by_id[fid] for fid in unique_ids]

    await audit.record(
        "library.file_attach",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={"requested": len(unique_ids), "cloned": 0},
    )
    return [serialize_file_out(row, settings=settings) for row in attached_rows]
