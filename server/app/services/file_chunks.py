from __future__ import annotations

import io
import logging
from typing import Any

import openpyxl
from pypdf import PdfReader
from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ConversationFile, FileChunk
from app.db.session import detect_pgvector
from app.services import cos, embeddings, file_parser
from app.services.file_types import IMAGE_EXTENSIONS

logger = logging.getLogger("whitz.file_chunks")

CHUNK_MAX_CHARS = 800
CHUNK_OVERLAP_CHARS = 120
MAX_CHUNKS_PER_FILE = 400


def _split_text_windows(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    chunks: list[str] = []
    step = max(100, max_chars - overlap)
    start = 0
    while start < len(cleaned) and len(chunks) < MAX_CHUNKS_PER_FILE:
        piece = cleaned[start : start + max_chars].strip()
        if piece:
            chunks.append(piece)
        if start + max_chars >= len(cleaned):
            break
        start += step
    return chunks


def _chunk_numbered_lines(
    lines: list[str],
    locator_fmt: str,
    max_chars: int = CHUNK_MAX_CHARS,
) -> list[tuple[str, str]]:
    if not lines:
        return []
    chunks: list[tuple[str, str]] = []
    buf: list[str] = []
    buf_len = 0
    start_idx = 1

    for idx, raw_line in enumerate(lines, 1):
        line = (raw_line or "").rstrip()
        if not line:
            continue
        if len(line) > max_chars:
            if buf:
                chunks.append((locator_fmt.format(start=start_idx, end=idx - 1), "\n".join(buf)))
                buf = []
                buf_len = 0
            for piece in _split_text_windows(line, max_chars=max_chars):
                chunks.append((locator_fmt.format(start=idx, end=idx), piece))
            start_idx = idx + 1
            continue

        if buf and buf_len + len(line) + 1 > max_chars:
            chunks.append((locator_fmt.format(start=start_idx, end=idx - 1), "\n".join(buf)))
            # Keep 1 line of overlap when small
            overlap_line = buf[-1] if len(buf[-1]) <= CHUNK_OVERLAP_CHARS else ""
            if overlap_line:
                buf = [overlap_line, line]
                buf_len = len(overlap_line) + 1 + len(line)
                start_idx = max(1, idx - 1)
            else:
                buf = [line]
                buf_len = len(line)
                start_idx = idx
        else:
            if not buf:
                start_idx = idx
            buf.append(line)
            buf_len += len(line) + (1 if len(buf) > 1 else 0)

        if len(chunks) >= MAX_CHUNKS_PER_FILE:
            break

    if buf and len(chunks) < MAX_CHUNKS_PER_FILE:
        chunks.append((locator_fmt.format(start=start_idx, end=len(lines)), "\n".join(buf)))
    return chunks


def chunk_file_bytes(raw: bytes, *, ext: str) -> list[tuple[str, str]]:
    norm_ext = (ext or "").lower()
    if norm_ext in IMAGE_EXTENSIONS or not raw:
        return []

    if norm_ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception:
            return []
        chunks: list[tuple[str, str]] = []
        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception:
                continue
            for piece in _split_text_windows(page_text):
                chunks.append((f"第 {page_num} 页", piece))
                if len(chunks) >= MAX_CHUNKS_PER_FILE:
                    return chunks
        return chunks

    if norm_ext == ".docx":
        try:
            lines = file_parser._docx_lines(raw)
        except file_parser.FileParseError:
            return []
        return _chunk_numbered_lines(lines, "第 {start}-{end} 段")

    if norm_ext == ".xlsx":
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception:
            return []
        chunks = []
        try:
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                sheet_lines: list[str] = []
                for idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                    if idx > 5000:
                        break
                    cells = ["" if val is None else str(val).replace("\n", " ") for val in row]
                    if any(cells):
                        sheet_lines.append("\t".join(cells))
                for loc, text in _chunk_numbered_lines(sheet_lines, f"工作表 {sheet} 第 {{start}}-{{end}} 行"):
                    chunks.append((loc, text))
                    if len(chunks) >= MAX_CHUNKS_PER_FILE:
                        return chunks
        finally:
            wb.close()
        return chunks

    text = file_parser.decode_text(raw)
    return _chunk_numbered_lines(text.splitlines(), "第 {start}-{end} 行")


async def index_file_chunks(
    db: AsyncSession,
    record: ConversationFile,
    *,
    raw: bytes | None = None,
) -> int:
    if record.status != "ready" or record.category == "image":
        return 0
    await detect_pgvector(db)

    settings = get_settings()
    if raw is None:
        if not settings.cos_configured or not record.storage_key:
            return 0
        max_download = max(settings.max_file_size_bytes, 25 * 1024 * 1024)
        raw = await cos.get_object_bytes(
            record.storage_key,
            max_bytes=max_download,
            settings=settings,
        )

    chunks = chunk_file_bytes(raw, ext=record.ext)
    await db.execute(delete(FileChunk).where(FileChunk.file_id == record.id))
    if not chunks:
        await db.commit()
        return 0

    vectors: list[list[float]] | None = None
    if embeddings.is_embedding_configured():
        vectors = await embeddings.embed_texts([text for _, text in chunks])

    rows: list[FileChunk] = []
    for idx, (locator, content) in enumerate(chunks):
        vec = vectors[idx] if vectors and idx < len(vectors) else None
        rows.append(
            FileChunk(
                file_id=record.id,
                conversation_id=record.conversation_id,
                user_id=record.user_id,
                is_global=bool(record.is_global),
                chunk_index=idx,
                locator=locator[:160],
                content=content,
                search_tsv=func.to_tsvector("simple", content),
                embedding=vec,
            )
        )
    db.add_all(rows)
    await db.commit()
    return len(rows)


async def index_file_chunks_safe(
    db: AsyncSession,
    record: ConversationFile,
    *,
    raw: bytes | None = None,
) -> int:
    try:
        return await index_file_chunks(db, record, raw=raw)
    except Exception as exc:
        logger.warning("File chunk indexing skipped for file=%s: %s", record.id, exc)
        return 0
