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
from app.services import audit, cos, file_cache, file_chunks, file_types, file_uploads

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


@router.get("/api/library/search")
async def search_library_content(
    q: str = Query(..., min_length=1, max_length=300),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Hybrid RAG search across document contents in the user's personal library."""
    from whitz_rag import UnifiedKnowledgeRetriever

    from app.db.session import detect_pgvector
    from app.services import embeddings

    term = q.strip()
    if not term:
        return {"query": "", "count": 0, "results": []}
    await detect_pgvector(db)
    retriever = UnifiedKnowledgeRetriever(
        session=db,
        embedding_client=embeddings.get_embedding_client(),
        rerank_client=embeddings.get_rerank_client(),
    )
    items = await retriever.search_files(
        user_id=str(user.id),
        query=term,
        top_k=limit,
        expand_neighbors=False,
        apply_rerank=True,
    )
    return {
        "query": term,
        "count": len(items),
        "results": [
            {
                "file_id": str((it.metadata or {}).get("file_id") or it.source_id),
                "filename": str((it.metadata or {}).get("filename") or it.title),
                "locator": str((it.metadata or {}).get("locator") or it.subtitle),
                "section_path": str((it.metadata or {}).get("section_path") or ""),
                "chunk_type": str((it.metadata or {}).get("chunk_type") or "text"),
                "snippet": it.snippet,
                "content": it.content[:600],
                "score": round(float(it.score), 4),
                "confidence": it.confidence,
            }
            for it in items
        ],
    }


@router.post("/api/library/files/{file_id}/reindex", response_model=LibraryFileOut)
async def reindex_library_file(
    file_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryFileOut:
    """Manually re-parse and re-vectorize a library file (sync for small files, queued for large/image files)."""
    row = await _get_owned_library_file(file_id, user, db)
    if row.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "文件尚未就绪")

    settings = get_settings()
    is_async = settings.app_env == "production" and (
        row.category == "image" or int(row.size_bytes or 0) > 256 * 1024
    )
    row.index_status = "indexing"
    row.index_error = None
    await db.commit()
    await db.refresh(row)

    if is_async:
        file_chunks.schedule_file_indexing(row.id, user.id)
    else:
        await file_chunks.index_file_chunks_safe(db, row)
        await db.refresh(row)

    from app.services import realtime_bus

    await realtime_bus.publish_user_event(
        user.id,
        "library.updated",
        {
            "action": "reindexed",
            "file_id": str(row.id),
            "index_status": row.index_status,
            "indexed_chunks": row.indexed_chunks,
        },
    )
    await audit.record(
        "library.file_reindex",
        actor=user,
        target_type="conversation_file",
        target_id=row.id,
        request=request,
        metadata={"filename": row.filename, "index_status": row.index_status},
    )
    conv_title = None
    if row.conversation_id is not None:
        conv_title = await db.scalar(select(Conversation.title).where(Conversation.id == row.conversation_id))
    return serialize_file_out(row, settings=settings, conversation_title=conv_title, as_library=True)


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
    record, payload = await file_uploads.presign_file_upload(
        db,
        user=user,
        conversation=None,
        filename=body.filename,
        mime_type=body.mime_type,
        size_bytes=body.size_bytes,
        background_tasks=background_tasks,
    )
    await audit.record(
        "library.file_presign",
        actor=user,
        target_type="conversation_file",
        target_id=record.id,
        request=request,
        metadata={"filename": record.filename, "size_bytes": record.size_bytes},
    )
    return payload


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

    record = await file_uploads.complete_file_upload(
        db,
        record=record,
        user=user,
        etag=body.etag if body else None,
        settings=settings,
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
    if "filename" in changes:
        await file_chunks.sync_filename_change(db, row)

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
    file_cache.invalidate_file_cache(file_id)
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
    linked_count = await file_uploads.link_files_to_conversation(
        db,
        user_id=user.id,
        conversation_id=conv.id,
        files=attached_rows,
    )

    await audit.record(
        "library.file_attach",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={"requested": len(unique_ids), "linked": linked_count, "cloned": 0},
    )
    return [serialize_file_out(row, settings=settings) for row in attached_rows]
