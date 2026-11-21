from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import (
    ConversationFileOut,
    FileCompleteRequest,
    FileDownloadUrlOut,
    FilePresignOut,
    FilePresignRequest,
    LibraryFileOut,
)
from app.core.config import Settings, get_settings
from app.db.models import Conversation, ConversationFile, FileChunk, User
from app.db.session import get_db
from app.services import audit, cos, file_chunks, file_parser
from app.services.file_types import FileValidationError, validate_upload_request

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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return row


async def cleanup_expired_pending_files(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> int:
    settings = get_settings()
    ttl = max(60, int(settings.pending_file_ttl_seconds or 1800))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ttl)

    stmt = select(ConversationFile).where(
        ConversationFile.status == "pending",
        or_(
            ConversationFile.expires_cleanup_at <= now,
            ConversationFile.created_at < cutoff,
        ),
    )
    if user_id is not None:
        stmt = stmt.where(ConversationFile.user_id == user_id)
    if conversation_id is not None:
        stmt = stmt.where(ConversationFile.conversation_id == conversation_id)

    expired = list((await db.execute(stmt)).scalars().all())
    if not expired:
        return 0

    keys = [row.storage_key for row in expired if row.storage_key]
    for row in expired:
        await db.delete(row)
    await db.commit()

    if keys and settings.cos_configured:
        if background_tasks is not None:
            background_tasks.add_task(cos.delete_objects, keys)
        else:
            await cos.delete_objects(keys, settings=settings)
    return len(expired)


def serialize_file_out(
    row: ConversationFile,
    *,
    settings: Settings | None = None,
    conversation_title: str | None = None,
    as_library: bool = False,
) -> ConversationFileOut | LibraryFileOut:
    s = settings or get_settings()
    base = ConversationFileOut.model_validate(row).model_dump()
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
        base["conversation_title"] = conversation_title
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
    conv: Conversation = Depends(get_owned_conversation),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationFileOut]:
    await cleanup_expired_pending_files(db, conversation_id=conv.id, background_tasks=background_tasks)
    settings = get_settings()
    result = await db.execute(
        select(ConversationFile)
        .where(
            ConversationFile.conversation_id == conv.id,
            ConversationFile.status == "ready",
        )
        .order_by(ConversationFile.created_at.asc())
    )
    rows = list(result.scalars().all())
    return [serialize_file_out(row, settings=settings) for row in rows]


@router.post("/{conversation_id}/files/presign", response_model=FilePresignOut)
async def presign_upload(
    body: FilePresignRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    conv: Conversation = Depends(get_owned_conversation),
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

    await cleanup_expired_pending_files(db, conversation_id=conv.id, background_tasks=background_tasks)

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
            f"单个对话最多上传 {settings.max_files_per_conversation} 个文件，请先清理部分文件",
        )

    file_id = uuid.uuid4()
    storage_key = cos.build_storage_key(user.id, conv.id, file_id, info.filename, settings=settings)

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
        conversation_id=conv.id,
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
        "file.presign",
        actor=user,
        target_type="conversation_file",
        target_id=file_id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": info.filename, "size_bytes": info.size_bytes},
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
    record.error_message = None
    record.expires_cleanup_at = None
    record.etag = (body.etag if body and body.etag else None) or meta.get("etag")
    await db.commit()
    await db.refresh(record)

    await file_chunks.index_file_chunks_safe(db, record)

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
