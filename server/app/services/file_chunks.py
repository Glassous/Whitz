from __future__ import annotations

import asyncio
import io
import logging
import re
import uuid
from typing import Any

import openpyxl
from pypdf import PdfReader
from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ConversationFile, FileChunk
from app.db.session import SessionLocal, detect_pgvector
from app.services import cos, embeddings, file_parser, realtime_bus
from app.services.file_types import IMAGE_EXTENSIONS

logger = logging.getLogger("whitz.file_chunks")

CHUNK_MAX_CHARS = 800
CHUNK_OVERLAP_CHARS = 120
MAX_CHUNKS_PER_FILE = 400
_MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?\n])\s*")
_INDEX_TASKS: set[asyncio.Task[Any]] = set()


def _split_text_windows(
    text: str,
    max_chars: int = CHUNK_MAX_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
    *,
    budget: int = MAX_CHUNKS_PER_FILE,
) -> list[str]:
    """Split long text preferring sentence boundaries so chunks stay semantically coherent."""
    cleaned = (text or "").strip()
    if not cleaned or budget <= 0:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: list[str] = []
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(cleaned) if s.strip()]
    buf = ""
    for sent in sentences:
        if len(chunks) >= budget:
            break
        if len(sent) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            step = max(100, max_chars - overlap)
            start = 0
            while start < len(sent) and len(chunks) < budget:
                piece = sent[start : start + max_chars].strip()
                if piece:
                    chunks.append(piece)
                if start + max_chars >= len(sent):
                    break
                start += step
            continue
        if buf and len(buf) + len(sent) + 1 > max_chars:
            chunks.append(buf)
            tail = buf[-overlap:].strip() if overlap > 0 and len(buf) > overlap else ""
            buf = f"{tail} {sent}".strip() if tail and len(tail) + len(sent) + 1 <= max_chars else sent
        else:
            buf = f"{buf} {sent}".strip() if buf else sent

    if buf and len(chunks) < budget:
        chunks.append(buf)
    return chunks


def _chunk_numbered_lines(
    lines: list[str],
    locator_fmt: str,
    max_chars: int = CHUNK_MAX_CHARS,
    *,
    track_markdown_headings: bool = False,
) -> tuple[list[tuple[str, str, str]], bool]:
    """Return ``([(locator, section_hint, content), ...], was_truncated)``."""
    if not lines:
        return [], False
    chunks: list[tuple[str, str, str]] = []
    buf: list[str] = []
    buf_len = 0
    start_idx = 1
    current_heading = ""
    truncated = False

    for idx, raw_line in enumerate(lines, 1):
        if len(chunks) >= MAX_CHUNKS_PER_FILE:
            truncated = True
            break
        line = (raw_line or "").rstrip()
        if not line:
            continue
        if track_markdown_headings:
            hm = _MD_HEADING_RE.match(line.strip())
            if hm:
                if buf:
                    chunks.append((locator_fmt.format(start=start_idx, end=idx - 1), current_heading, "\n".join(buf)))
                    buf = []
                    buf_len = 0
                current_heading = hm.group(2).strip()[:80]
                if len(chunks) >= MAX_CHUNKS_PER_FILE:
                    truncated = True
                    break

        if len(line) > max_chars:
            if buf:
                chunks.append((locator_fmt.format(start=start_idx, end=idx - 1), current_heading, "\n".join(buf)))
                buf = []
                buf_len = 0
            rem = MAX_CHUNKS_PER_FILE - len(chunks)
            if rem <= 0:
                truncated = True
                break
            pieces = _split_text_windows(line, max_chars=max_chars, budget=rem)
            for piece in pieces:
                chunks.append((locator_fmt.format(start=idx, end=idx), current_heading, piece))
            start_idx = idx + 1
            continue

        if buf and buf_len + len(line) + 1 > max_chars:
            chunks.append((locator_fmt.format(start=start_idx, end=idx - 1), current_heading, "\n".join(buf)))
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

    if buf and len(chunks) < MAX_CHUNKS_PER_FILE:
        chunks.append((locator_fmt.format(start=start_idx, end=len(lines)), current_heading, "\n".join(buf)))
    elif buf:
        truncated = True
    return chunks, truncated


def _chunk_file_bytes_with_meta(raw: bytes, *, ext: str) -> tuple[list[tuple[str, str, str]], bool]:
    norm_ext = (ext or "").lower()
    if norm_ext in IMAGE_EXTENSIONS or not raw:
        return [], False

    if norm_ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception:
            return [], False
        chunks: list[tuple[str, str, str]] = []
        truncated = False
        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception:
                continue
            rem = MAX_CHUNKS_PER_FILE - len(chunks)
            if rem <= 0:
                truncated = True
                break
            for piece in _split_text_windows(page_text, budget=rem):
                chunks.append((f"第 {page_num} 页", "", piece))
        return chunks, truncated

    if norm_ext == ".docx":
        try:
            lines = file_parser._docx_lines(raw)
        except file_parser.FileParseError:
            return [], False
        return _chunk_numbered_lines(lines, "第 {start}-{end} 段")

    if norm_ext == ".xlsx":
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception:
            return [], False
        chunks = []
        truncated = False
        try:
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                sheet_lines: list[str] = []
                for idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                    if idx > 5000:
                        truncated = True
                        break
                    cells = ["" if val is None else str(val).replace("\n", " ") for val in row]
                    if any(cells):
                        sheet_lines.append("\t".join(cells))
                sheet_chunks, sheet_trunc = _chunk_numbered_lines(
                    sheet_lines, f"工作表 {sheet} 第 {{start}}-{{end}} 行"
                )
                if sheet_trunc:
                    truncated = True
                for loc, sec, text in sheet_chunks:
                    if len(chunks) >= MAX_CHUNKS_PER_FILE:
                        truncated = True
                        return chunks, truncated
                    chunks.append((loc, sec, text))
        finally:
            wb.close()
        return chunks, truncated

    text = file_parser.decode_text(raw)
    return _chunk_numbered_lines(
        text.splitlines(),
        "第 {start}-{end} 行",
        track_markdown_headings=(norm_ext in (".md", ".markdown")),
    )


def chunk_file_bytes(raw: bytes, *, ext: str) -> list[tuple[str, str]]:
    """Backward-compatible helper returning ``[(locator, content), ...]``."""
    triples, _ = _chunk_file_bytes_with_meta(raw, ext=ext)
    return [(loc, content) for loc, _, content in triples]


def _build_context_header(record: ConversationFile, locator: str, section: str) -> str:
    parts = [f"文件: {record.filename}"]
    if record.category:
        parts.append(f"类型: {record.category}")
    if section:
        parts.append(f"章节: {section}")
    if locator:
        parts.append(f"位置: {locator}")
    return "[" + " | ".join(parts) + "]"


async def index_file_chunks(
    db: AsyncSession,
    record: ConversationFile,
    *,
    raw: bytes | None = None,
) -> int:
    if record.status != "ready" or record.category == "image":
        record.index_status = "ready"
        record.indexed_chunks = 0
        await db.commit()
        return 0
    await detect_pgvector(db)

    settings = get_settings()
    if raw is None:
        if not settings.cos_configured or not record.storage_key:
            record.index_status = "ready"
            await db.commit()
            return 0
        max_download = max(settings.max_file_size_bytes, 25 * 1024 * 1024)
        raw = await cos.get_object_bytes(
            record.storage_key,
            max_bytes=max_download,
            settings=settings,
        )

    # Run CPU-bound PDF/DOCX/XLSX parsing off the asyncio event loop
    triples, truncated = await asyncio.to_thread(_chunk_file_bytes_with_meta, raw, ext=record.ext)
    await db.execute(delete(FileChunk).where(FileChunk.file_id == record.id))
    if not triples:
        record.index_status = "ready"
        record.indexed_chunks = 0
        await db.commit()
        return 0

    headers = [_build_context_header(record, loc, sec) for loc, sec, _ in triples]
    embed_inputs = [f"{hdr}\n{content}" for hdr, (_, _, content) in zip(headers, triples)]

    vectors: list[list[float]] | None = None
    if embeddings.is_embedding_configured():
        vectors = await embeddings.embed_texts(embed_inputs)

    rows: list[FileChunk] = []
    for idx, ((locator, _sec, content), ctx_header) in enumerate(zip(triples, headers)):
        vec = vectors[idx] if vectors and idx < len(vectors) else None
        indexed_text = f"{ctx_header}\n{content}"
        rows.append(
            FileChunk(
                file_id=record.id,
                conversation_id=record.conversation_id,
                user_id=record.user_id,
                is_global=bool(record.is_global),
                chunk_index=idx,
                locator=locator[:160],
                context_header=ctx_header,
                content=content,
                search_tsv=func.to_tsvector("simple", indexed_text),
                embedding=vec,
            )
        )
    db.add_all(rows)
    record.index_status = "partial" if truncated else "ready"
    record.indexed_chunks = len(rows)
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
        try:
            record.index_status = "failed"
            await db.commit()
        except Exception:
            pass
        return 0


def schedule_file_indexing(file_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Schedule non-blocking background chunking & vectorization after upload completion."""

    async def _runner() -> None:
        try:
            async with SessionLocal() as db:
                rec = await db.get(ConversationFile, file_id)
                if rec is None or rec.status != "ready":
                    return
                await index_file_chunks_safe(db, rec)
                await realtime_bus.publish_user_event(
                    user_id,
                    "library.updated",
                    {
                        "action": "indexed",
                        "file_id": str(file_id),
                        "index_status": rec.index_status,
                        "indexed_chunks": rec.indexed_chunks,
                    },
                )
        except Exception as exc:
            logger.debug("Background file indexing task failed for file=%s: %s", file_id, exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_runner())
    _INDEX_TASKS.add(task)
    task.add_done_callback(_INDEX_TASKS.discard)
