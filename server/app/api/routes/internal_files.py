from __future__ import annotations

import base64
import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.mcp import _authenticate_namespace
from app.core.config import Settings, get_settings
from app.db.models import ConversationFile, User
from app.db.session import get_db
from app.services import cos, file_cache, file_parser

logger = logging.getLogger("whitz.internal_files")

router = APIRouter(prefix="/api/internal/files", tags=["internal-files"])


class PrepareTurnFilesRequest(BaseModel):
    conversation_id: str | None = None
    file_ids: list[str] = Field(default_factory=list, max_length=20)
    prefer_image_mode: Literal["url_first", "base64", "url_only"] | None = None
    allow_native_pdf: bool = True
    inline_token_budget: int | None = None
    single_file_max_tokens: int | None = None


async def _get_owned_ready_file(db: AsyncSession, user: User, raw_file_id: str) -> ConversationFile:
    try:
        file_uuid = uuid.UUID(str(raw_file_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在") from exc
    row = await db.get(ConversationFile, file_uuid)
    if row is None or row.user_id != user.id or row.status != "ready":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在或尚未就绪")
    return row


async def _build_image_payload(
    row: ConversationFile,
    *,
    mode: str,
    settings: Settings,
) -> dict[str, Any]:
    """Hydrate an image attachment using zero-RAM COS original URL first, or uncompressed base64 <= threshold."""
    base_meta: dict[str, Any] = {
        "file_id": str(row.id),
        "filename": row.filename,
        "ext": row.ext,
        "category": "image",
        "mime_type": row.mime_type,
        "size_bytes": int(row.size_bytes or 0),
    }
    if mode in ("url_first", "url_only") and settings.cos_configured and row.storage_key:
        try:
            url = cos.presign_ai_media_url(
                key=row.storage_key,
                size_bytes=int(row.size_bytes or 0),
                expires_seconds=900,
                settings=settings,
            )
            return {
                **base_meta,
                "delivery": "native_image_url",
                "image_url": url,
                "compressed": False,
            }
        except cos.CosError as exc:
            if mode == "url_only":
                return {**base_meta, "delivery": "error", "error": str(exc)}
            logger.debug("COS AI media presign failed for %s; falling back to base64: %s", row.id, exc)

    # Base64 fallback (or explicit base64 mode): uncompressed original when <= threshold
    max_download = max(settings.max_file_size_bytes, 25 * 1024 * 1024)
    compress_threshold = max(1, int(getattr(settings, "llm_image_compress_threshold_mb", 5) or 5)) * 1024 * 1024
    try:
        raw = await cos.get_object_bytes(row.storage_key, max_bytes=max_download, settings=settings)
        out_bytes, out_mime, width, height, compressed = file_parser.normalize_image_for_base64(
            raw,
            mime_type=row.mime_type,
            max_raw_bytes=compress_threshold,
        )
        b64 = base64.b64encode(out_bytes).decode("ascii")
        return {
            **base_meta,
            "mime_type": out_mime,
            "delivery": "native_image_base64",
            "image_url": f"data:{out_mime};base64,{b64}",
            "width": width,
            "height": height,
            "compressed": compressed,
        }
    except (cos.CosError, file_parser.FileParseError) as exc:
        return {**base_meta, "delivery": "error", "error": str(exc)}


async def _build_document_payload(
    row: ConversationFile,
    *,
    allow_native_pdf: bool,
    remaining_token_budget: int,
    single_file_max_tokens: int,
    settings: Settings,
) -> tuple[dict[str, Any], int]:
    """Hydrate a non-image current-turn attachment via Native PDF -> Inline Full Text -> Outline + RAG."""
    base_meta: dict[str, Any] = {
        "file_id": str(row.id),
        "filename": row.filename,
        "ext": row.ext,
        "category": row.category,
        "mime_type": row.mime_type,
        "size_bytes": int(row.size_bytes or 0),
        "index_status": row.index_status,
    }
    ext = (row.ext or "").lower()
    size_bytes = int(row.size_bytes or 0)

    # Tier 2: Capability-negotiated Native PDF File Block
    pdf_mode = (getattr(settings, "llm_native_pdf_mode", "auto") or "auto").strip().lower()
    pdf_max_bytes = max(1, int(getattr(settings, "llm_native_pdf_max_mb", 8) or 8)) * 1024 * 1024
    pdf_max_pages = max(1, int(getattr(settings, "llm_native_pdf_max_pages", 30) or 30))

    if ext == ".pdf" and allow_native_pdf and pdf_mode != "disabled" and size_bytes <= pdf_max_bytes:
        try:
            max_download = max(settings.max_file_size_bytes, 25 * 1024 * 1024)
            raw = await cos.get_object_bytes(row.storage_key, max_bytes=max_download, settings=settings)
            parsed = await file_cache.get_or_parse_file(row, raw=raw, settings=settings)
            page_count = len(parsed.pdf_pages)
            if page_count <= pdf_max_pages:
                b64 = base64.b64encode(raw).decode("ascii")
                return (
                    {
                        **base_meta,
                        "delivery": "native_pdf_file",
                        "file_data": f"data:application/pdf;base64,{b64}",
                        "page_count": page_count,
                        "is_scanned_pdf": parsed.is_scanned_pdf,
                        "stats": {"total_pages": page_count, "is_scanned_pdf": parsed.is_scanned_pdf},
                    },
                    0,
                )
        except (cos.CosError, file_parser.FileParseError) as exc:
            logger.debug("Native PDF hydration failed for %s: %s", row.id, exc)
            return {**base_meta, "delivery": "error", "error": str(exc)}, 0

    # Tier 3: Parsed text direct full-context injection vs structural outline + RAG
    try:
        parsed = await file_cache.get_or_parse_file(row, settings=settings)
    except (cos.CosError, file_parser.FileParseError) as exc:
        return {**base_meta, "delivery": "error", "error": str(exc)}, 0

    effective_budget = min(max(0, remaining_token_budget), max(500, single_file_max_tokens))
    full_text, est_tokens, stats = file_parser.extract_full_text_for_injection(
        parsed,
        max_tokens=effective_budget,
    )
    if full_text is not None:
        return (
            {
                **base_meta,
                "delivery": "inline_full",
                "content": full_text,
                "estimated_tokens": est_tokens,
                "stats": stats,
                "is_scanned_pdf": parsed.is_scanned_pdf,
            },
            est_tokens,
        )

    outline_text = file_parser.format_outline_text(parsed, filename=row.filename)
    return (
        {
            **base_meta,
            "delivery": "outline_rag",
            "outline": outline_text,
            "estimated_tokens": est_tokens,
            "stats": stats,
            "is_scanned_pdf": parsed.is_scanned_pdf,
        },
        0,
    )


@router.post("/prepare-turn")
async def prepare_turn_files(
    body: PrepareTurnFilesRequest,
    authorization: str | None = Header(default=None),
    x_whitz_profile: str | None = Header(default=None),
    x_whitz_namespace: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Batch-hydrate current-turn attached files for agent-worker in a single internal call."""
    user = await _authenticate_namespace(db, authorization, x_whitz_namespace or x_whitz_profile)
    settings = get_settings()

    uuids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw_id in body.file_ids:
        try:
            fid = uuid.UUID(str(raw_id))
        except (TypeError, ValueError):
            continue
        if fid not in seen:
            seen.add(fid)
            uuids.append(fid)

    if not uuids:
        return {"items": []}

    rows = list(
        (
            await db.execute(
                select(ConversationFile).where(
                    ConversationFile.id.in_(uuids),
                    ConversationFile.user_id == user.id,
                    ConversationFile.status == "ready",
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}

    image_mode = (body.prefer_image_mode or getattr(settings, "llm_image_delivery_mode", "url_first") or "url_first").strip().lower()
    remaining_budget = int(
        body.inline_token_budget
        if body.inline_token_budget is not None
        else getattr(settings, "attachment_inline_max_tokens", 14000)
    )
    single_cap = int(
        body.single_file_max_tokens
        if body.single_file_max_tokens is not None
        else getattr(settings, "attachment_single_file_max_tokens", 8000)
    )

    items: list[dict[str, Any]] = []
    for fid in uuids:
        row = by_id.get(fid)
        if row is None:
            continue
        if row.category == "image":
            items.append(await _build_image_payload(row, mode=image_mode, settings=settings))
        else:
            item, used_tokens = await _build_document_payload(
                row,
                allow_native_pdf=body.allow_native_pdf,
                remaining_token_budget=remaining_budget,
                single_file_max_tokens=single_cap,
                settings=settings,
            )
            remaining_budget = max(0, remaining_budget - used_tokens)
            items.append(item)

    return {"items": items}


@router.get("/{file_id}/media")
async def get_file_media_fallback(
    file_id: str,
    mode: Literal["url", "base64", "text_fallback"] = Query(default="base64"),
    max_tokens: int = Query(default=8000, ge=500, le=32000),
    authorization: str | None = Header(default=None),
    x_whitz_profile: str | None = Header(default=None),
    x_whitz_namespace: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """On-demand fallback endpoint when upstream LLM rejects remote image URL or native PDF file block."""
    user = await _authenticate_namespace(db, authorization, x_whitz_namespace or x_whitz_profile)
    row = await _get_owned_ready_file(db, user, file_id)
    settings = get_settings()

    if row.category == "image":
        eff_mode = "url_only" if mode == "url" else "base64"
        return await _build_image_payload(row, mode=eff_mode, settings=settings)

    item, _ = await _build_document_payload(
        row,
        allow_native_pdf=False,
        remaining_token_budget=max_tokens,
        single_file_max_tokens=max_tokens,
        settings=settings,
    )
    return item
