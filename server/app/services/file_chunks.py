from __future__ import annotations

import asyncio
import base64
import csv
import io
import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import openpyxl
from pypdf import PdfReader
from sqlalchemy import delete, func, select
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
MAX_IMAGE_CAPTION_BYTES = 10 * 1024 * 1024

_MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?\n])\s*")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".vue",
        ".go",
        ".java",
        ".kt",
        ".rs",
        ".c",
        ".cpp",
        ".h",
        ".cs",
        ".php",
        ".rb",
        ".sh",
        ".sql",
    }
)
_CODE_BOUNDARY_RE = re.compile(
    r"^(?:async\s+def|def|class|export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|interface|type)|"
    r"function|interface|type|func|pub\s+(?:async\s+)?(?:fn|struct|enum|trait)|fn\s+|struct\s+|"
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|FUNCTION|INDEX)|<script\b|<template\b|<style\b)\s*([A-Za-z_][A-Za-z0-9_]*)?",
    re.IGNORECASE,
)
_INDEX_TASKS: set[asyncio.Task[Any]] = set()


@dataclass
class ChunkSpec:
    locator: str
    section_path: str
    content: str
    chunk_type: str = "text"
    chunk_meta: dict[str, Any] = field(default_factory=dict)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return max(1, int(math.ceil(cjk * 0.72 + other * 0.28)))


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


def _chunk_markdown_lines(lines: list[str], max_chars: int = CHUNK_MAX_CHARS) -> tuple[list[ChunkSpec], bool]:
    """Heading-stack & code-fence aware Markdown chunker preserving hierarchical `section_path`."""
    if not lines:
        return [], False
    specs: list[ChunkSpec] = []
    heading_stack: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_len = 0
    start_idx = 1
    in_fence = False
    truncated = False

    def _current_path() -> str:
        return " > ".join(title for _, title in heading_stack)[:240]

    def _flush(end_idx: int) -> None:
        nonlocal buf, buf_len, truncated
        if not buf:
            return
        if len(specs) >= MAX_CHUNKS_PER_FILE:
            truncated = True
            buf = []
            buf_len = 0
            return
        specs.append(
            ChunkSpec(
                locator=f"第 {start_idx}-{end_idx} 行",
                section_path=_current_path(),
                content="\n".join(buf),
                chunk_type="text",
                chunk_meta={"line_start": start_idx, "line_end": end_idx},
            )
        )
        buf = []
        buf_len = 0

    for idx, raw_line in enumerate(lines, 1):
        if len(specs) >= MAX_CHUNKS_PER_FILE:
            truncated = True
            break
        line = (raw_line or "").rstrip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence

        if not in_fence:
            hm = _MD_HEADING_RE.match(line.strip())
            if hm:
                _flush(idx - 1)
                level = len(hm.group(1))
                title = hm.group(2).strip()[:80]
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
                start_idx = idx
                buf = [line]
                buf_len = len(line)
                continue

        if not line and not in_fence:
            continue

        # Never split inside a fenced code block unless it exceeds 2x max_chars
        hard_limit = max_chars * 2 if in_fence else max_chars
        if len(line) > hard_limit:
            _flush(idx - 1)
            rem = MAX_CHUNKS_PER_FILE - len(specs)
            if rem <= 0:
                truncated = True
                break
            for piece in _split_text_windows(line, max_chars=max_chars, budget=rem):
                specs.append(
                    ChunkSpec(
                        locator=f"第 {idx}-{idx} 行",
                        section_path=_current_path(),
                        content=piece,
                        chunk_type="text",
                        chunk_meta={"line_start": idx, "line_end": idx},
                    )
                )
            start_idx = idx + 1
            continue

        if buf and buf_len + len(line) + 1 > hard_limit:
            _flush(idx - 1)
            start_idx = idx
            buf = [line]
            buf_len = len(line)
        else:
            if not buf:
                start_idx = idx
            buf.append(line)
            buf_len += len(line) + (1 if len(buf) > 1 else 0)

    if buf and len(specs) < MAX_CHUNKS_PER_FILE:
        _flush(len(lines))
    elif buf:
        truncated = True
    return specs, truncated


def _chunk_code_lines(lines: list[str], max_chars: int = CHUNK_MAX_CHARS) -> tuple[list[ChunkSpec], bool]:
    """Boundary-aware source code chunker preferring function/class/component boundaries."""
    if not lines:
        return [], False
    specs: list[ChunkSpec] = []
    buf: list[str] = []
    buf_len = 0
    start_idx = 1
    current_symbol = ""
    truncated = False

    def _flush(end_idx: int) -> None:
        nonlocal buf, buf_len, truncated
        if not buf:
            return
        if len(specs) >= MAX_CHUNKS_PER_FILE:
            truncated = True
            buf = []
            buf_len = 0
            return
        specs.append(
            ChunkSpec(
                locator=f"第 {start_idx}-{end_idx} 行",
                section_path=current_symbol,
                content="\n".join(buf),
                chunk_type="code",
                chunk_meta={
                    "line_start": start_idx,
                    "line_end": end_idx,
                    **({"symbol": current_symbol} if current_symbol else {}),
                },
            )
        )
        buf = []
        buf_len = 0

    for idx, raw_line in enumerate(lines, 1):
        if len(specs) >= MAX_CHUNKS_PER_FILE:
            truncated = True
            break
        line = (raw_line or "").rstrip()
        stripped = line.lstrip()
        is_top_level = len(line) - len(stripped) <= 4
        bm = _CODE_BOUNDARY_RE.match(stripped) if (is_top_level and stripped) else None
        if bm and buf and buf_len >= 160:
            _flush(idx - 1)
            start_idx = idx
        if bm:
            sym = (bm.group(1) or stripped[:48]).strip()[:80]
            if sym:
                current_symbol = sym

        if buf and buf_len + len(line) + 1 > max_chars:
            # Capture overlap line BEFORE _flush clears `buf`!
            prev_last = buf[-1] if buf else ""
            overlap_line = prev_last if len(prev_last) <= CHUNK_OVERLAP_CHARS else ""
            _flush(idx - 1)
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

    if buf and len(specs) < MAX_CHUNKS_PER_FILE:
        _flush(len(lines))
    elif buf:
        truncated = True
    return specs, truncated


def _chunk_table_rows(
    rows: list[str] | list[tuple[int, str]],
    *,
    header_row: str,
    sheet_name: str = "",
    max_chars: int = CHUNK_MAX_CHARS,
    budget: int = MAX_CHUNKS_PER_FILE,
) -> tuple[list[ChunkSpec], bool]:
    """Chunk tabular rows (XLSX / CSV) while prepending the header row to EVERY chunk and tracking real row numbers."""
    if not rows or budget <= 0:
        return [], False
    specs: list[ChunkSpec] = []
    truncated = False
    header_prefix = f"表头: {header_row}\n" if header_row else ""
    effective_max = max(250, max_chars - len(header_prefix))

    normalized: list[tuple[int, str]] = [
        (r[0], r[1]) if isinstance(r, tuple) else ((2 if header_row else 1) + idx, str(r))
        for idx, r in enumerate(rows)
    ]

    buf: list[str] = []
    buf_len = 0
    start_row = normalized[0][0]
    last_row_in_buf = start_row

    def _loc(s: int, e: int) -> str:
        return f"工作表 {sheet_name} 第 {s}-{e} 行" if sheet_name else f"第 {s}-{e} 行"

    for row_no, row_text in normalized:
        if len(specs) >= budget:
            truncated = True
            break
        if buf and buf_len + len(row_text) + 1 > effective_max:
            specs.append(
                ChunkSpec(
                    locator=_loc(start_row, last_row_in_buf),
                    section_path=f"工作表: {sheet_name}" if sheet_name else "表格数据",
                    content=(header_prefix + "\n".join(buf)).strip(),
                    chunk_type="table",
                    chunk_meta={
                        **({"sheet_name": sheet_name} if sheet_name else {}),
                        "row_start": start_row,
                        "row_end": last_row_in_buf,
                        "has_header": bool(header_row),
                    },
                )
            )
            buf = [row_text]
            buf_len = len(row_text)
            start_row = row_no
            last_row_in_buf = row_no
        else:
            if not buf:
                start_row = row_no
            buf.append(row_text)
            buf_len += len(row_text) + (1 if len(buf) > 1 else 0)
            last_row_in_buf = row_no

    if buf and len(specs) < budget:
        specs.append(
            ChunkSpec(
                locator=_loc(start_row, last_row_in_buf),
                section_path=f"工作表: {sheet_name}" if sheet_name else "表格数据",
                content=(header_prefix + "\n".join(buf)).strip(),
                chunk_type="table",
                chunk_meta={
                    **({"sheet_name": sheet_name} if sheet_name else {}),
                    "row_start": start_row,
                    "row_end": last_row_in_buf,
                    "has_header": bool(header_row),
                },
            )
        )
    elif buf:
        truncated = True
    return specs, truncated


def _chunk_numbered_lines(
    lines: list[str],
    locator_fmt: str,
    max_chars: int = CHUNK_MAX_CHARS,
    *,
    meta_prefix: str = "line",
) -> tuple[list[ChunkSpec], bool]:
    if not lines:
        return [], False
    specs: list[ChunkSpec] = []
    buf: list[str] = []
    buf_len = 0
    start_idx = 1
    truncated = False

    for idx, raw_line in enumerate(lines, 1):
        if len(specs) >= MAX_CHUNKS_PER_FILE:
            truncated = True
            break
        line = (raw_line or "").rstrip()
        if not line:
            continue

        if len(line) > max_chars:
            if buf:
                specs.append(
                    ChunkSpec(
                        locator=locator_fmt.format(start=start_idx, end=idx - 1),
                        section_path="",
                        content="\n".join(buf),
                        chunk_type="text",
                        chunk_meta={f"{meta_prefix}_start": start_idx, f"{meta_prefix}_end": idx - 1},
                    )
                )
                buf = []
                buf_len = 0
            rem = MAX_CHUNKS_PER_FILE - len(specs)
            if rem <= 0:
                truncated = True
                break
            for piece in _split_text_windows(line, max_chars=max_chars, budget=rem):
                specs.append(
                    ChunkSpec(
                        locator=locator_fmt.format(start=idx, end=idx),
                        section_path="",
                        content=piece,
                        chunk_type="text",
                        chunk_meta={f"{meta_prefix}_start": idx, f"{meta_prefix}_end": idx},
                    )
                )
            start_idx = idx + 1
            continue

        if buf and buf_len + len(line) + 1 > max_chars:
            specs.append(
                ChunkSpec(
                    locator=locator_fmt.format(start=start_idx, end=idx - 1),
                    section_path="",
                    content="\n".join(buf),
                    chunk_type="text",
                    chunk_meta={f"{meta_prefix}_start": start_idx, f"{meta_prefix}_end": idx - 1},
                )
            )
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

    if buf and len(specs) < MAX_CHUNKS_PER_FILE:
        specs.append(
            ChunkSpec(
                locator=locator_fmt.format(start=start_idx, end=len(lines)),
                section_path="",
                content="\n".join(buf),
                chunk_type="text",
                chunk_meta={f"{meta_prefix}_start": start_idx, f"{meta_prefix}_end": len(lines)},
            )
        )
    elif buf:
        truncated = True
    return specs, truncated


def _chunk_file_bytes_structured(raw: bytes, *, ext: str) -> tuple[list[ChunkSpec], bool]:
    norm_ext = (ext or "").lower()
    if norm_ext in IMAGE_EXTENSIONS or not raw:
        return [], False

    if norm_ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception:
            return [], False
        specs: list[ChunkSpec] = []
        truncated = False
        total_pages = len(reader.pages)
        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception:
                continue
            rem = MAX_CHUNKS_PER_FILE - len(specs)
            if rem <= 0:
                truncated = True
                break
            for piece in _split_text_windows(page_text, budget=rem):
                specs.append(
                    ChunkSpec(
                        locator=f"第 {page_num} 页",
                        section_path="",
                        content=piece,
                        chunk_type="text",
                        chunk_meta={"page": page_num, "total_pages": total_pages},
                    )
                )
        return specs, truncated

    if norm_ext == ".docx":
        try:
            lines = file_parser._docx_lines(raw)
        except file_parser.FileParseError:
            return [], False
        return _chunk_numbered_lines(lines, "第 {start}-{end} 段", meta_prefix="para")

    if norm_ext == ".xlsx":
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception:
            return [], False
        specs = []
        truncated = False
        try:
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                header_row = ""
                header_idx = 1
                data_rows: list[tuple[int, str]] = []
                for idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                    if idx > 5000:
                        truncated = True
                        break
                    cells = ["" if val is None else str(val).replace("\n", " ").strip() for val in row]
                    if not any(cells):
                        continue
                    joined = " | ".join(cells)
                    if not header_row:
                        header_row = joined
                        header_idx = idx
                    else:
                        data_rows.append((idx, joined))
                rem = MAX_CHUNKS_PER_FILE - len(specs)
                if rem <= 0:
                    truncated = True
                    break
                if not data_rows and header_row:
                    data_rows = [(header_idx, header_row)]
                    header_row = ""
                sheet_specs, sheet_trunc = _chunk_table_rows(
                    data_rows, header_row=header_row, sheet_name=sheet, budget=rem
                )
                if sheet_trunc:
                    truncated = True
                specs.extend(sheet_specs)
        finally:
            wb.close()
        return specs, truncated

    if norm_ext in (".csv", ".tsv"):
        text = file_parser.decode_text(raw)
        delim = "\t" if norm_ext == ".tsv" else ","
        reader_csv = csv.reader(io.StringIO(text), delimiter=delim)
        header_row = ""
        header_idx = 1
        data_rows_csv: list[tuple[int, str]] = []
        truncated = False
        for idx, row in enumerate(reader_csv, 1):
            if idx > 5000:
                truncated = True
                break
            cells = [c.replace("\n", " ").strip() for c in row]
            if not any(cells):
                continue
            joined = " | ".join(cells)
            if not header_row:
                header_row = joined
                header_idx = idx
            else:
                data_rows_csv.append((idx, joined))
        if not data_rows_csv and header_row:
            data_rows_csv = [(header_idx, header_row)]
            header_row = ""
        csv_specs, csv_trunc = _chunk_table_rows(data_rows_csv, header_row=header_row)
        return csv_specs, (truncated or csv_trunc)

    text = file_parser.decode_text(raw)
    lines = text.splitlines()
    if norm_ext in (".md", ".markdown"):
        return _chunk_markdown_lines(lines)
    if norm_ext in _CODE_EXTENSIONS:
        return _chunk_code_lines(lines)
    return _chunk_numbered_lines(lines, "第 {start}-{end} 行")


def chunk_file_bytes(raw: bytes, *, ext: str) -> list[tuple[str, str]]:
    """Backward-compatible helper returning ``[(locator, content), ...]``."""
    specs, _ = _chunk_file_bytes_structured(raw, ext=ext)
    return [(s.locator, s.content) for s in specs]


def _build_extractive_summary(filename: str, specs: list[ChunkSpec]) -> tuple[str, list[str]]:
    """Zero-LLM-cost document summary & keywords from headings + opening/closing chunks."""
    if not specs:
        return "", []
    headings = list(dict.fromkeys(s.section_path for s in specs if s.section_path))[:8]
    sample_parts: list[str] = []
    if headings:
        sample_parts.append("结构章节：" + " / ".join(headings))
    first_excerpt = " ".join(specs[0].content.split())[:220]
    if first_excerpt:
        sample_parts.append("开头摘要：" + first_excerpt)
    if len(specs) > 2:
        mid_excerpt = " ".join(specs[len(specs) // 2].content.split())[:140]
        if mid_excerpt:
            sample_parts.append("中段要点：" + mid_excerpt)
    summary = "；".join(sample_parts)[:520]

    token_src = f"{filename} {' '.join(headings)} {first_excerpt}"
    raw_tokens = re.findall(r"[\w\u4e00-\u9fff]{2,18}", token_src)
    keywords = list(dict.fromkeys(raw_tokens))[:10]
    return summary, keywords


def _is_vision_caption_configured() -> bool:
    settings = get_settings()
    if not getattr(settings, "rag_image_indexing_enabled", True):
        return False
    base = (settings.llm_vision_base_url or settings.llm_base_url or "").strip().rstrip("/")
    model = (settings.llm_vision_model or (settings.llm_model if settings.llm_supports_vision else "")).strip()
    return bool(base and model and not base.startswith("http://llm.test"))


async def _caption_image_with_vision(
    raw: bytes | None,
    *,
    filename: str,
    mime_type: str,
    storage_key: str = "",
    size_bytes: int = 0,
) -> str | None:
    """Use configured vision LLM to generate a searchable caption + OCR text for an uploaded image.

    Prefers native COS signed URL (zero RAM / zero base64 inflation), falling back to base64 if URL is unavailable.
    """
    settings = get_settings()
    if not _is_vision_caption_configured():
        return None

    base = (settings.llm_vision_base_url or settings.llm_base_url or "").strip().rstrip("/")
    api_key = (settings.llm_vision_api_key or settings.llm_api_key or "").strip()
    model = (settings.llm_vision_model or (settings.llm_model if settings.llm_supports_vision else "")).strip()

    image_url_value: str | None = None
    if storage_key and settings.cos_configured:
        try:
            image_url_value = cos.presign_ai_media_url(
                key=storage_key,
                size_bytes=int(size_bytes or (len(raw) if raw else 0)),
                expires_seconds=600,
                settings=settings,
            )
        except cos.CosError:
            image_url_value = None

    if not image_url_value:
        if not raw or len(raw) > MAX_IMAGE_CAPTION_BYTES:
            return None
        sniffed = file_parser._sniff_image_mime(raw) or mime_type or "image/png"
        b64 = base64.b64encode(raw).decode("ascii")
        image_url_value = f"data:{sniffed};base64,{b64}"

    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"请为图片文件「{filename}」生成一段便于知识库检索的结构化中文描述（150-300字）："
                            "1) 概括图片主题/场景/图表类型；2) 完整提取图片中的关键文字、数字、代码、表格或界面标签（OCR）；"
                            "不要寒暄，直接输出纯文本。"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url_value}},
                ],
            }
        ],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 400,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0), trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                return None
            data = resp.json()
        choices = data.get("choices") or []
        msg = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        content = (msg or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()[:1200]
        if isinstance(content, list):
            txt = "".join(str(p.get("text") or "") for p in content if isinstance(p, dict)).strip()
            return txt[:1200] if txt else None
    except Exception as exc:
        logger.debug("Vision captioning skipped for %s: %s", filename, exc)
    return None


def _build_context_header(record: ConversationFile, locator: str, section: str) -> str:
    parts = [f"文件: {record.filename}"]
    if record.category:
        parts.append(f"类型: {record.category}")
    if section:
        parts.append(f"章节: {section}")
    if locator:
        parts.append(f"位置: {locator}")
    return "[" + " | ".join(parts) + "]"


async def sync_filename_change(db: AsyncSession, record: ConversationFile) -> int:
    """Synchronize `file_chunks.context_header` and `search_tsv` when a file is renamed."""
    rows = list(
        (
            await db.execute(
                select(FileChunk).where(FileChunk.file_id == record.id).order_by(FileChunk.chunk_index.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    for chunk in rows:
        sec = getattr(chunk, "section_path", "") or ""
        new_header = _build_context_header(record, chunk.locator or "", sec)
        chunk.context_header = new_header
        chunk.search_tsv = func.to_tsvector("simple", f"{new_header}\n{chunk.content}")
    await db.commit()
    return len(rows)


async def index_file_chunks(
    db: AsyncSession,
    record: ConversationFile,
    *,
    raw: bytes | None = None,
) -> int:
    if record.status != "ready":
        record.index_status = "ready"
        record.indexed_chunks = 0
        await db.commit()
        return 0
    await detect_pgvector(db)

    settings = get_settings()
    if raw is None and record.category != "image":
        if not settings.cos_configured or not record.storage_key:
            record.index_status = "ready"
            record.indexed_chunks = 0
            await db.commit()
            return 0
        max_download = max(settings.max_file_size_bytes, 25 * 1024 * 1024)
        raw = await cos.get_object_bytes(
            record.storage_key,
            max_bytes=max_download,
            settings=settings,
        )

    specs: list[ChunkSpec] = []
    truncated = False
    vision_failed = False

    if record.category == "image":
        vision_configured = _is_vision_caption_configured()
        if raw is None and vision_configured and not (settings.cos_configured and record.storage_key):
            vision_configured = False
        caption = await _caption_image_with_vision(
            raw,
            filename=record.filename,
            mime_type=record.mime_type,
            storage_key=record.storage_key or "",
            size_bytes=int(record.size_bytes or 0),
        )
        if caption:
            specs = [
                ChunkSpec(
                    locator="图片内容与文字识别",
                    section_path="视觉摘要",
                    content=caption,
                    chunk_type="image_caption",
                    chunk_meta={"mime_type": record.mime_type, "size_bytes": record.size_bytes},
                )
            ]
        elif vision_configured:
            vision_failed = True
    else:
        # Run CPU-bound PDF/DOCX/XLSX/Code parsing off the asyncio event loop
        specs, truncated = await asyncio.to_thread(_chunk_file_bytes_structured, raw or b"", ext=record.ext)

    await db.execute(delete(FileChunk).where(FileChunk.file_id == record.id))
    if not specs:
        record.index_status = "failed" if vision_failed else "ready"
        record.indexed_chunks = 0
        record.index_error = "视觉摘要生成失败，请稍后重试索引" if vision_failed else None
        record.indexed_at = datetime.now(timezone.utc)
        await db.commit()
        return 0

    summary_text, keywords = _build_extractive_summary(record.filename, specs)
    if record.category == "image" and specs:
        summary_text = specs[0].content[:480]

    # When large documents hit chunk cap, prepend a dedicated summary chunk so document overview stays searchable
    if truncated and summary_text:
        specs = [
            ChunkSpec(
                locator="文档总览摘要",
                section_path="总览",
                content=f"文件《{record.filename}》因篇幅较长已部分切片。{summary_text}",
                chunk_type="summary",
                chunk_meta={"truncated": True},
            ),
            *specs[: MAX_CHUNKS_PER_FILE - 1],
        ]

    headers = [_build_context_header(record, s.locator, s.section_path) for s in specs]
    embed_inputs = [f"{hdr}\n{s.content}" for hdr, s in zip(headers, specs)]

    vectors: list[list[float]] | None = None
    model_tag: str | None = None
    embedding_failed = False
    if embeddings.is_embedding_configured():
        vectors = await embeddings.embed_texts(embed_inputs)
        if vectors:
            model_tag = embeddings.current_embedding_model_tag() or None
        else:
            embedding_failed = True

    rows: list[FileChunk] = []
    for idx, (spec, ctx_header) in enumerate(zip(specs, headers)):
        vec = vectors[idx] if vectors and idx < len(vectors) else None
        indexed_text = f"{ctx_header}\n{spec.content}"
        rows.append(
            FileChunk(
                file_id=record.id,
                conversation_id=record.conversation_id,
                user_id=record.user_id,
                is_global=bool(record.is_global),
                chunk_index=idx,
                locator=spec.locator[:160],
                context_header=ctx_header,
                section_path=spec.section_path[:240],
                chunk_type=spec.chunk_type[:24],
                token_count=_estimate_tokens(spec.content),
                chunk_meta=spec.chunk_meta or None,
                content=spec.content,
                search_tsv=func.to_tsvector("simple", indexed_text),
                embedding=vec,
                embedding_model=model_tag if vec is not None else None,
            )
        )
    db.add_all(rows)
    record.index_status = "partial" if (truncated or embedding_failed) else "ready"
    record.indexed_chunks = len(rows)
    record.summary = summary_text
    record.keywords = keywords
    record.embedding_model = model_tag
    record.index_error = "向量化服务暂不可用，仅完成全文索引" if embedding_failed else None
    record.indexed_at = datetime.now(timezone.utc)
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
            record.index_error = str(exc)[:480]
            await db.commit()
        except Exception:
            pass
        return 0


def schedule_file_indexing(file_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Schedule durable background chunking & vectorization via Redis job queue (fallback: local task)."""
    from app.services import rag_jobs

    if rag_jobs.enqueue_file_index_nowait(file_id, user_id):
        return

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
