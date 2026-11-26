from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import (
    ConversationFileOut,
    CreateTextFileRequest,
    FileCompleteRequest,
    FileDownloadUrlOut,
    FilePresignOut,
    FilePresignRequest,
    LibraryFileOut,
    RenameConversationFileRequest,
    UpdateTextFileContentRequest,
)
from app.core.config import Settings, get_settings
from app.db.models import Conversation, ConversationFile, ConversationFileLink, FileChunk, User
from app.db.session import get_db
from app.services import audit, cos, file_cache, file_chunks, file_parser, file_provenance, file_types, file_uploads
from app.services.mcp_files import MAX_WRITE_FILE_BYTES, WRITABLE_TEXT_EXTENSIONS

router = APIRouter(prefix="/api/conversations", tags=["files"])

MAX_PREVIEW_CHARS = 512 * 1024


async def _get_owned_file(
    file_id: uuid.UUID,
    conv: Conversation,
    db: AsyncSession,
    *,
    require_same_conversation: bool = True,
) -> ConversationFile:
    row = await db.get(ConversationFile, file_id)
    if row is None or row.user_id != conv.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    if require_same_conversation and row.conversation_id != conv.id:
        linked = await db.scalar(
            select(ConversationFileLink.id).where(
                ConversationFileLink.conversation_id == conv.id,
                ConversationFileLink.file_id == row.id,
                ConversationFileLink.user_id == conv.user_id,
            )
        )
        if linked is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return row


async def cleanup_expired_pending_files(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> int:
    return await file_uploads.cleanup_expired_pending_files(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        background_tasks=background_tasks,
    )


def serialize_file_out(
    row: ConversationFile,
    *,
    settings: Settings | None = None,
    conversation_title: str | None = None,
    provenance: dict[str, Any] | None = None,
    as_library: bool = False,
) -> ConversationFileOut | LibraryFileOut:
    s = settings or get_settings()
    base = ConversationFileOut.model_validate(row).model_dump()
    if provenance:
        if provenance.get("conversation_title") is not None:
            base["conversation_title"] = provenance["conversation_title"]
        if provenance.get("conversation_kind") is not None:
            base["conversation_kind"] = provenance["conversation_kind"]
        if provenance.get("qa_snippet") is not None:
            base["qa_snippet"] = provenance["qa_snippet"]
        if provenance.get("turn_role") is not None:
            base["turn_role"] = provenance["turn_role"]
    if conversation_title is not None:
        base["conversation_title"] = conversation_title
    if row.status == "ready" and s.cos_configured and row.storage_key:
        try:
            urls = cos.presign_preview_urls(
                row.storage_key,
                row.filename,
                row.category,
                settings=s,
            )
            base["preview_url"] = urls["preview_url"]
            base["thumb_url"] = urls["thumb_url"]
            base["preview_expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=urls["expires_in"])
        except cos.CosError:
            pass
    if as_library:
        return LibraryFileOut(**base)
    return ConversationFileOut(**base)


async def read_preview_content_payload(
    row: ConversationFile,
    *,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    if row.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "文件尚未就绪")
    ext = (row.ext or os.path.splitext(row.filename)[1]).lower()
    if row.category == "image" or ext == ".pdf":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "该文件类型请使用临时预览链接查看")

    settings = get_settings()
    max_download = max(settings.max_file_size_bytes, 10 * 1024 * 1024)
    try:
        raw = await cos.get_object_bytes(
            row.storage_key,
            max_bytes=max_download,
            settings=settings,
        )
    except cos.CosError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    if ext == ".xlsx":
        try:
            parsed = file_parser._read_xlsx(
                raw,
                sheet_name=sheet_name,
                start_line=1,
                max_lines=500,
                max_chars=MAX_PREVIEW_CHARS,
            )
        except file_parser.FileParseError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {
            "file_id": str(row.id),
            "filename": row.filename,
            "ext": ext,
            "category": row.category,
            "mime_type": row.mime_type,
            "format": "xlsx",
            "content": parsed.get("content") or "",
            "sheets": parsed.get("sheets") or [],
            "sheet": parsed.get("sheet"),
            "truncated": bool(parsed.get("truncated") or parsed.get("has_more")),
            "size_bytes": row.size_bytes,
        }

    if ext == ".docx":
        try:
            parsed = file_parser.read_file_content(
                raw,
                ext=".docx",
                mime_type=row.mime_type,
                start_line=1,
                max_lines=500,
            )
        except file_parser.FileParseError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {
            "file_id": str(row.id),
            "filename": row.filename,
            "ext": ext,
            "category": row.category,
            "mime_type": row.mime_type,
            "format": "docx",
            "content": parsed.get("content") or "",
            "truncated": bool(parsed.get("truncated") or parsed.get("has_more")),
            "size_bytes": row.size_bytes,
        }

    text = file_parser.decode_text(raw)
    truncated = len(text) > MAX_PREVIEW_CHARS
    if truncated:
        text = text[:MAX_PREVIEW_CHARS]
    return {
        "file_id": str(row.id),
        "filename": row.filename,
        "ext": ext,
        "category": row.category,
        "mime_type": row.mime_type,
        "format": "text",
        "content": text,
        "truncated": truncated,
        "size_bytes": row.size_bytes,
    }


@router.get("/{conversation_id}/files", response_model=list[ConversationFileOut])
async def list_files(
    background_tasks: BackgroundTasks,
    scope: Literal["conversation", "all"] = Query(default="conversation"),
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationFileOut]:
    await cleanup_expired_pending_files(
        db,
        user_id=user.id if scope == "all" else None,
        conversation_id=None if scope == "all" else conv.id,
        background_tasks=background_tasks,
    )
    settings = get_settings()
    if scope == "all":
        result = await db.execute(
            select(ConversationFile)
            .outerjoin(Conversation, ConversationFile.conversation_id == Conversation.id)
            .where(
                ConversationFile.user_id == user.id,
                ConversationFile.status == "ready",
            )
            .order_by(
                func.coalesce(Conversation.last_message_at, ConversationFile.created_at).desc(),
                ConversationFile.created_at.desc(),
            )
            .limit(200)
        )
    else:
        rows = await file_uploads.list_conversation_workspace_files(
            db,
            user_id=user.id,
            conversation_id=conv.id,
            order_asc=False,
        )
        provenance_map = await file_provenance.resolve_files_provenance(db, user, rows)
        return [
            serialize_file_out(row, settings=settings, provenance=provenance_map.get(row.id))
            for row in rows
        ]
    rows = list(result.scalars().all())
    provenance_map = await file_provenance.resolve_files_provenance(db, user, rows)
    return [
        serialize_file_out(row, settings=settings, provenance=provenance_map.get(row.id))
        for row in rows
    ]


@router.post("/{conversation_id}/files/presign", response_model=FilePresignOut)
async def presign_upload(
    body: FilePresignRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    record, payload = await file_uploads.presign_file_upload(
        db,
        user=user,
        conversation=conv,
        filename=body.filename,
        mime_type=body.mime_type,
        size_bytes=body.size_bytes,
        background_tasks=background_tasks,
    )
    await audit.record(
        "file.presign",
        actor=user,
        target_type="conversation_file",
        target_id=record.id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": record.filename, "size_bytes": record.size_bytes},
    )
    return payload


@router.post("/{conversation_id}/files/{file_id}/complete", response_model=ConversationFileOut)
async def complete_upload(
    file_id: uuid.UUID,
    request: Request,
    body: FileCompleteRequest | None = None,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationFileOut:
    record = await _get_owned_file(file_id, conv, db)
    settings = get_settings()
    if record.status == "ready":
        return serialize_file_out(record, settings=settings)

    record = await file_uploads.complete_file_upload(
        db,
        record=record,
        user=user,
        etag=body.etag if body else None,
        settings=settings,
    )
    await audit.record(
        "file.complete",
        actor=user,
        target_type="conversation_file",
        target_id=record.id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": record.filename},
    )
    return serialize_file_out(record, settings=settings)


@router.get("/{conversation_id}/files/{file_id}/download-url", response_model=FileDownloadUrlOut)
async def get_download_url(
    file_id: uuid.UUID,
    inline: bool = Query(default=False),
    conv: Conversation = Depends(get_owned_conversation),
    db: AsyncSession = Depends(get_db),
) -> dict:
    record = await _get_owned_file(file_id, conv, db, require_same_conversation=False)
    if record.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "文件尚未就绪")
    settings = get_settings()
    try:
        url = cos.presign_get(
            key=record.storage_key,
            filename=record.filename,
            inline=inline,
            settings=settings,
        )
    except cos.CosError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return {"url": url, "expires_in": settings.cos_download_expires_seconds}


@router.get("/{conversation_id}/files/{file_id}/preview-content")
async def get_preview_content(
    file_id: uuid.UUID,
    sheet_name: str | None = Query(default=None, max_length=128),
    conv: Conversation = Depends(get_owned_conversation),
    db: AsyncSession = Depends(get_db),
) -> dict:
    record = await _get_owned_file(file_id, conv, db, require_same_conversation=False)
    return await read_preview_content_payload(record, sheet_name=sheet_name)


@router.post("/{conversation_id}/files/text", response_model=ConversationFileOut, status_code=status.HTTP_201_CREATED)
async def create_text_file(
    body: CreateTextFileRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationFileOut:
    settings = get_settings()
    if not settings.cos_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储服务尚未配置")

    filename = file_types.sanitize_filename(body.filename)
    if not filename:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件名不能为空")
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext not in WRITABLE_TEXT_EXTENSIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"不支持创建扩展名 {ext or '无扩展名'} 的文本文件，请使用 .md、.txt、.csv、.html、.json、.py 等格式",
        )

    raw_bytes = (body.content or "").encode("utf-8")
    if len(raw_bytes) > MAX_WRITE_FILE_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件内容超过 2 MB 上限")

    category, mime_type = file_types.ALLOWED_FILE_TYPES[ext]

    existing = (
        await db.execute(
            select(ConversationFile)
            .where(
                ConversationFile.conversation_id == conv.id,
                ConversationFile.user_id == user.id,
                ConversationFile.filename == filename,
                ConversationFile.status == "ready",
            )
            .order_by(ConversationFile.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if existing is not None:
        if not body.overwrite:
            raise HTTPException(status.HTTP_409_CONFLICT, f"工作区已存在同名文件 {filename}")
        try:
            etag = await cos.put_object_bytes(existing.storage_key, raw_bytes, mime_type, settings=settings)
        except cos.CosError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        existing.ext = ext
        existing.mime_type = mime_type
        existing.category = category
        existing.size_bytes = len(raw_bytes)
        existing.etag = etag
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        await file_chunks.index_file_chunks_safe(db, existing, raw=raw_bytes)
        await db.refresh(existing)
        row = existing
    else:
        existing_count = await db.scalar(
            select(func.count())
            .select_from(ConversationFile)
            .where(
                ConversationFile.conversation_id == conv.id,
                ConversationFile.status.in_(("ready", "pending")),
            )
        )
        if int(existing_count or 0) >= settings.max_files_per_conversation:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"单个对话最多保留 {settings.max_files_per_conversation} 个文件，请先清理部分文件",
            )
        file_id = uuid.uuid4()
        storage_key = cos.build_storage_key(user.id, conv.id, file_id, filename, settings=settings)
        try:
            etag = await cos.put_object_bytes(storage_key, raw_bytes, mime_type, settings=settings)
        except cos.CosError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        row = ConversationFile(
            id=file_id,
            conversation_id=conv.id,
            user_id=user.id,
            filename=filename,
            ext=ext,
            mime_type=mime_type,
            category=category,
            size_bytes=len(raw_bytes),
            storage_key=storage_key,
            etag=etag,
            status="ready",
            source="user",
            is_global=True,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        await file_chunks.index_file_chunks_safe(db, row, raw=raw_bytes)
        await db.refresh(row)

    from app.services import realtime_bus

    await realtime_bus.publish_user_event(
        user.id,
        "library.updated",
        {"action": "added", "file_id": str(row.id), "conversation_id": str(conv.id)},
    )
    await audit.record(
        "file.create_text",
        actor=user,
        target_type="conversation_file",
        target_id=row.id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": row.filename, "size_bytes": row.size_bytes},
    )
    provenance_map = await file_provenance.resolve_files_provenance(db, user, [row])
    return serialize_file_out(row, settings=settings, provenance=provenance_map.get(row.id))


@router.put("/{conversation_id}/files/{file_id}/content", response_model=ConversationFileOut)
async def update_file_content(
    file_id: uuid.UUID,
    body: UpdateTextFileContentRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationFileOut:
    settings = get_settings()
    if not settings.cos_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储服务尚未配置")

    record = await _get_owned_file(file_id, conv, db, require_same_conversation=False)
    if record.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "文件尚未就绪")

    ext = (record.ext or os.path.splitext(record.filename)[1]).lower()
    if ext not in WRITABLE_TEXT_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "该文件类型不支持在线文本编辑")

    raw_bytes = (body.content or "").encode("utf-8")
    if len(raw_bytes) > MAX_WRITE_FILE_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件内容超过 2 MB 上限")

    try:
        etag = await cos.put_object_bytes(record.storage_key, raw_bytes, record.mime_type, settings=settings)
    except cos.CosError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    record.size_bytes = len(raw_bytes)
    record.etag = etag
    record.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(record)
    file_cache.invalidate_file_cache(record.id)
    await file_chunks.index_file_chunks_safe(db, record, raw=raw_bytes)
    await db.refresh(record)

    from app.services import realtime_bus

    await realtime_bus.publish_user_event(
        user.id,
        "library.updated",
        {"action": "updated", "file_id": str(record.id), "conversation_id": str(record.conversation_id or conv.id)},
    )
    await audit.record(
        "file.update_content",
        actor=user,
        target_type="conversation_file",
        target_id=record.id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": record.filename, "size_bytes": record.size_bytes},
    )
    provenance_map = await file_provenance.resolve_files_provenance(db, user, [record])
    return serialize_file_out(record, settings=settings, provenance=provenance_map.get(record.id))


@router.patch("/{conversation_id}/files/{file_id}", response_model=ConversationFileOut)
async def rename_file(
    file_id: uuid.UUID,
    body: RenameConversationFileRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationFileOut:
    record = await _get_owned_file(file_id, conv, db, require_same_conversation=False)
    cleaned = file_types.sanitize_filename(body.filename)
    if not cleaned:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件名不能为空")

    _, new_ext = os.path.splitext(cleaned)
    new_ext = new_ext.lower()
    if not new_ext:
        # Preserve original extension if user omitted it during inline rename
        cleaned = f"{cleaned}{record.ext}"
        new_ext = record.ext.lower()
    if new_ext not in file_types.ALLOWED_FILE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"不支持的文件扩展名：{new_ext}")

    old_filename = record.filename
    new_category, new_mime = file_types.ALLOWED_FILE_TYPES[new_ext]
    record.filename = cleaned
    record.ext = new_ext
    record.category = new_category
    record.mime_type = new_mime
    record.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(record)
    if cleaned != old_filename:
        await file_chunks.sync_filename_change(db, record)

    from app.services import realtime_bus

    await realtime_bus.publish_user_event(
        user.id,
        "library.updated",
        {"action": "renamed", "file_id": str(record.id), "conversation_id": str(record.conversation_id or conv.id)},
    )
    await audit.record(
        "file.rename",
        actor=user,
        target_type="conversation_file",
        target_id=record.id,
        request=request,
        metadata={"old_filename": old_filename, "new_filename": cleaned},
    )
    settings = get_settings()
    provenance_map = await file_provenance.resolve_files_provenance(db, user, [record])
    return serialize_file_out(record, settings=settings, provenance=provenance_map.get(record.id))


@router.delete("/{conversation_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Detach a file from the side chat workspace while keeping it in the global Library."""
    record = await _get_owned_file(file_id, conv, db)
    filename = record.filename
    await file_uploads.unlink_file_from_conversation(
        db,
        user_id=user.id,
        conversation_id=conv.id,
        file_id=record.id,
    )
    if record.conversation_id == conv.id:
        record.conversation_id = None
        record.is_global = True
        await db.execute(
            update(FileChunk)
            .where(FileChunk.file_id == record.id)
            .values(conversation_id=None, is_global=True)
        )
    await db.commit()
    await audit.record(
        "file.detach_workspace",
        actor=user,
        target_type="conversation_file",
        target_id=file_id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": filename},
    )
