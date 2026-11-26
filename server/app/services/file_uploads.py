from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Conversation, ConversationFile, ConversationFileLink, User
from app.services import cos, file_cache, file_chunks, file_parser, realtime_bus
from app.services.file_types import FileValidationError, validate_upload_request

SYNC_INDEX_MAX_BYTES = 128 * 1024


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


async def list_conversation_workspace_files(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    order_asc: bool = False,
) -> list[ConversationFile]:
    """Return all ready files belonging to ``conversation_id`` directly OR mounted via ``conversation_file_links``."""
    linked_ids = select(ConversationFileLink.file_id).where(
        ConversationFileLink.conversation_id == conversation_id,
        ConversationFileLink.user_id == user_id,
    )
    order_col = ConversationFile.created_at.asc() if order_asc else ConversationFile.created_at.desc()
    stmt = (
        select(ConversationFile)
        .where(
            ConversationFile.user_id == user_id,
            ConversationFile.status == "ready",
            or_(
                ConversationFile.conversation_id == conversation_id,
                ConversationFile.id.in_(linked_ids),
            ),
        )
        .order_by(order_col)
    )
    return list((await db.execute(stmt)).scalars().all())


async def link_files_to_conversation(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    files: list[ConversationFile],
) -> int:
    """Persistently attach library files to a conversation workspace (idempotent)."""
    if not files:
        return 0
    candidate_ids = [f.id for f in files if f.conversation_id != conversation_id]
    if not candidate_ids:
        return 0
    existing_ids = set(
        (
            await db.execute(
                select(ConversationFileLink.file_id).where(
                    ConversationFileLink.conversation_id == conversation_id,
                    ConversationFileLink.file_id.in_(candidate_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    added = 0
    for fid in candidate_ids:
        if fid in existing_ids:
            continue
        db.add(
            ConversationFileLink(
                conversation_id=conversation_id,
                file_id=fid,
                user_id=user_id,
            )
        )
        added += 1
    if added:
        await db.commit()
    return added


async def unlink_file_from_conversation(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    file_id: uuid.UUID,
) -> int:
    res = await db.execute(
        delete(ConversationFileLink).where(
            ConversationFileLink.conversation_id == conversation_id,
            ConversationFileLink.file_id == file_id,
            ConversationFileLink.user_id == user_id,
        )
    )
    return int(res.rowcount or 0)


async def presign_file_upload(
    db: AsyncSession,
    *,
    user: User,
    conversation: Conversation | None,
    filename: str,
    mime_type: str | None,
    size_bytes: int,
    background_tasks: BackgroundTasks | None = None,
    settings: Settings | None = None,
) -> tuple[ConversationFile, dict[str, Any]]:
    s = settings or get_settings()
    if not s.cos_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储服务尚未配置")

    try:
        info = validate_upload_request(
            filename,
            mime_type,
            size_bytes,
            s.max_file_size_bytes,
        )
    except FileValidationError as exc:
        raise HTTPException(422, str(exc)) from exc

    await cleanup_expired_pending_files(
        db,
        user_id=user.id if conversation is None else None,
        conversation_id=conversation.id if conversation is not None else None,
        background_tasks=background_tasks,
    )

    if conversation is not None:
        existing_count = await db.scalar(
            select(func.count())
            .select_from(ConversationFile)
            .where(
                ConversationFile.conversation_id == conversation.id,
                ConversationFile.status.in_(("ready", "pending")),
            )
        )
        if int(existing_count or 0) >= s.max_files_per_conversation:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"单个对话最多上传 {s.max_files_per_conversation} 个文件，请先清理部分文件",
            )

    file_id = uuid.uuid4()
    conv_id = conversation.id if conversation is not None else None
    storage_key = cos.build_storage_key(user.id, conv_id, file_id, info.filename, settings=s)

    try:
        signed = await cos.presign_put(
            key=storage_key,
            content_type=info.mime_type,
            content_length=info.size_bytes,
            settings=s,
        )
    except cos.CosError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    ttl = max(60, int(s.pending_file_ttl_seconds or 1800))
    record = ConversationFile(
        id=file_id,
        conversation_id=conv_id,
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

    payload = {
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
    return record, payload


async def complete_file_upload(
    db: AsyncSession,
    *,
    record: ConversationFile,
    user: User,
    etag: str | None = None,
    settings: Settings | None = None,
) -> ConversationFile:
    s = settings or get_settings()
    if record.status == "ready":
        return record

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

    # Zero-overhead 32-byte magic header check for images, PDFs, DOCX, XLSX
    if record.category == "image" or (record.ext or "").lower() in (".pdf", ".docx", ".xlsx"):
        head_bytes = await cos.get_object_head_bytes(record.storage_key, num_bytes=32, settings=s)
        magic_err = file_parser.sniff_file_header(head_bytes, ext=record.ext, category=record.category)
        if magic_err:
            record.status = "failed"
            record.error_message = magic_err
            await db.commit()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, magic_err)

    record.status = "ready"
    record.is_global = True
    record.error_message = None
    record.expires_cleanup_at = None
    record.etag = (etag or None) or meta.get("etag")

    # Images NEVER block /complete for Vision Captioning (current turn sends original image natively!).
    # Small text/code/docs (<= 128KB) index quickly inline; larger docs index asynchronously.
    is_async_index = (
        (record.category == "image" and bool(s.rag_image_indexing_enabled))
        or (record.category != "image" and int(record.size_bytes or 0) > SYNC_INDEX_MAX_BYTES)
    )
    record.index_status = "indexing" if is_async_index else "ready"
    await db.commit()
    await db.refresh(record)
    file_cache.invalidate_file_cache(record.id)

    if is_async_index:
        file_chunks.schedule_file_indexing(record.id, user.id)
    elif record.category != "image":
        await file_chunks.index_file_chunks_safe(db, record)
        await db.refresh(record)

    event_payload: dict[str, Any] = {
        "action": "added",
        "file_id": str(record.id),
        "index_status": record.index_status,
    }
    if record.conversation_id is not None:
        event_payload["conversation_id"] = str(record.conversation_id)
    await realtime_bus.publish_user_event(user.id, "library.updated", event_payload)
    return record
