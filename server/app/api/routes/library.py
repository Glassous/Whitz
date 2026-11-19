from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
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
    FileDownloadUrlOut,
    LibraryFileOut,
    LibraryFileUpdateRequest,
)
from app.core.config import get_settings
from app.db.models import Conversation, ConversationFile, FileChunk, User
from app.db.session import get_db
from app.services import audit, cos, file_types

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
        select(ConversationFile, Conversation.title)
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
    if is_global is not None:
        stmt = stmt.where(ConversationFile.is_global.is_(is_global))
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
    items = [
        serialize_file_out(file_row, settings=settings, conversation_title=conv_title, as_library=True)
        for file_row, conv_title in rows
    ]
    return {
        "items": items,
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


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
    if body.is_global is not None and body.is_global != row.is_global:
        row.is_global = body.is_global
        changes["is_global"] = body.is_global
        await db.execute(
            update(FileChunk).where(FileChunk.file_id == row.id).values(is_global=body.is_global)
        )

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
    need_clone = [by_id[fid] for fid in unique_ids if by_id[fid].conversation_id != conv.id]
    if need_clone:
        existing_count = await db.scalar(
            select(func.count())
            .select_from(ConversationFile)
            .where(
                ConversationFile.conversation_id == conv.id,
                ConversationFile.status.in_(("ready", "pending")),
            )
        )
        if int(existing_count or 0) + len(need_clone) > settings.max_files_per_conversation:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"单个对话最多包含 {settings.max_files_per_conversation} 个文件，请先清理部分文件",
            )
        if not settings.cos_configured:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储服务尚未配置")

    attached_rows: list[ConversationFile] = []
    created_rows: list[ConversationFile] = []
    for fid in unique_ids:
        src = by_id[fid]
        if src.conversation_id == conv.id:
            attached_rows.append(src)
            continue

        max_copy_bytes = max(settings.max_file_size_bytes, int(src.size_bytes or 0) + 1024)
        try:
            raw = await cos.get_object_bytes(
                src.storage_key,
                max_bytes=max_copy_bytes,
                settings=settings,
            )
            new_id = uuid.uuid4()
            new_key = cos.build_storage_key(user.id, conv.id, new_id, src.filename, settings=settings)
            etag = await cos.put_object_bytes(new_key, raw, src.mime_type, settings=settings)
        except cos.CosError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc

        clone = ConversationFile(
            id=new_id,
            conversation_id=conv.id,
            user_id=user.id,
            filename=src.filename,
            ext=src.ext,
            mime_type=src.mime_type,
            category=src.category,
            size_bytes=len(raw) if raw is not None else src.size_bytes,
            storage_key=new_key,
            etag=etag,
            status="ready",
            source=src.source,
            is_global=False,
        )
        db.add(clone)
        created_rows.append(clone)
        attached_rows.append(clone)

    if created_rows:
        await db.commit()
        for clone in created_rows:
            await db.refresh(clone)

    await audit.record(
        "library.file_attach",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={"requested": len(unique_ids), "cloned": len(created_rows)},
    )
    return [serialize_file_out(row, settings=settings) for row in attached_rows]
