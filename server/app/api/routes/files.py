import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import (
    ConversationFileOut,
    FileCompleteRequest,
    FileDownloadUrlOut,
    FilePresignOut,
    FilePresignRequest,
)
from app.core.config import get_settings
from app.db.models import Conversation, ConversationFile, User
from app.db.session import get_db
from app.services import audit, cos
from app.services.file_types import FileValidationError, validate_upload_request

router = APIRouter(prefix="/api/conversations", tags=["files"])


async def _get_owned_file(
    file_id: uuid.UUID,
    conv: Conversation,
    db: AsyncSession,
) -> ConversationFile:
    row = await db.get(ConversationFile, file_id)
    if row is None or row.conversation_id != conv.id or row.user_id != conv.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return row


@router.get("/{conversation_id}/files", response_model=list[ConversationFileOut])
async def list_files(
    conv: Conversation = Depends(get_owned_conversation),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationFile]:
    result = await db.execute(
        select(ConversationFile)
        .where(
            ConversationFile.conversation_id == conv.id,
            ConversationFile.status == "ready",
        )
        .order_by(ConversationFile.created_at.asc())
    )
    return list(result.scalars().all())


@router.post("/{conversation_id}/files/presign", response_model=FilePresignOut)
async def presign_upload(
    body: FilePresignRequest,
    request: Request,
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
) -> ConversationFile:
    record = await _get_owned_file(file_id, conv, db)
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

    record.status = "ready"
    record.error_message = None
    record.etag = (body.etag if body and body.etag else None) or meta.get("etag")
    await db.commit()
    await db.refresh(record)

    await audit.record(
        "file.complete",
        actor=user,
        target_type="conversation_file",
        target_id=record.id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": record.filename},
    )
    return record


@router.get("/{conversation_id}/files/{file_id}/download-url", response_model=FileDownloadUrlOut)
async def get_download_url(
    file_id: uuid.UUID,
    inline: bool = Query(default=False),
    conv: Conversation = Depends(get_owned_conversation),
    db: AsyncSession = Depends(get_db),
) -> dict:
    record = await _get_owned_file(file_id, conv, db)
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


@router.delete("/{conversation_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    record = await _get_owned_file(file_id, conv, db)
    storage_key = record.storage_key
    filename = record.filename
    await db.delete(record)
    await db.commit()
    background_tasks.add_task(cos.delete_object, storage_key)
    await audit.record(
        "file.delete",
        actor=user,
        target_type="conversation_file",
        target_id=file_id,
        request=request,
        metadata={"conversation_id": str(conv.id), "filename": filename},
    )
