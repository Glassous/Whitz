from __future__ import annotations

import base64
import io
import math
import re
from typing import Any

import docx
import openpyxl
from pypdf import PdfReader

from app.services.file_types import IMAGE_EXTENSIONS

DEFAULT_MAX_CHARS = 18_000
DEFAULT_MAX_LINES = 250
DEFAULT_PDF_PAGE_BATCH = 8
MAX_IMAGE_EMBED_BYTES = 20 * 1024 * 1024
MAX_XLSX_CACHE_ROWS = 5000

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_CODE_SYMBOL_RE = re.compile(
    r"^\s*(?:async\s+def|def|class|export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|interface|type)|"
    r"function|interface|type|func|pub\s+(?:async\s+)?(?:fn|struct|enum|trait)|CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|FUNCTION))\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


class FileParseError(ValueError):
    pass


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return max(1, int(math.ceil(cjk * 0.72 + other * 0.28)))


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clip_chars(text: str, limit: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n…（内容已截断，请缩小读取范围或翻页继续读取）", True


def _slice_lines(
    lines: list[str],
    start_line: int = 1,
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    total = len(lines)
    start = max(1, int(start_line))
    count = max(1, min(600, int(max_lines)))
    if total == 0:
        return {
            "total_lines": 0,
            "start_line": 1,
            "end_line": 0,
            "has_more": False,
            "next_start_line": None,
            "truncated": False,
            "content": "",
        }
    if start > total:
        return {
            "total_lines": total,
            "start_line": start,
            "end_line": total,
            "has_more": False,
            "next_start_line": None,
            "truncated": False,
            "content": "",
        }
    end = min(total, start + count - 1)
    numbered = [f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1)]
    text, clipped = _clip_chars("\n".join(numbered), max_chars)
    has_more = end < total or clipped
    return {
        "total_lines": total,
        "start_line": start,
        "end_line": end,
        "has_more": has_more,
        "next_start_line": (end + 1) if end < total else None,
        "truncated": clipped,
        "content": text,
    }


def count_pdf_pages_fast(raw: bytes) -> int:
    """Count PDF pages without running expensive text extraction."""
    try:
        reader = PdfReader(io.BytesIO(raw))
        return len(reader.pages)
    except Exception as exc:
        raise FileParseError(f"无法解析 PDF 文件: {exc}") from exc


def _extract_pdf_pages(raw: bytes) -> tuple[list[str], bool]:
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        raise FileParseError(f"无法解析 PDF 文件: {exc}") from exc
    pages: list[str] = []
    non_empty_chars = 0
    for page in reader.pages:
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception:
            page_text = ""
        pages.append(page_text)
        non_empty_chars += len(page_text)
    total = len(pages)
    is_scanned = total > 0 and (non_empty_chars / total) < 30
    return pages, is_scanned


def _slice_pdf_pages(
    pages: list[str],
    *,
    is_scanned: bool = False,
    page_start: int | None = None,
    page_end: int | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    total_pages = len(pages)
    if total_pages == 0:
        return {
            "format": "pdf",
            "total_pages": 0,
            "page_start": 0,
            "page_end": 0,
            "has_more": False,
            "next_page_start": None,
            "is_scanned_pdf": False,
            "truncated": False,
            "content": "",
        }

    p_start = max(1, int(page_start or 1))
    default_end = min(total_pages, p_start + DEFAULT_PDF_PAGE_BATCH - 1)
    p_end = min(total_pages, int(page_end or default_end))
    if p_start > total_pages:
        p_start = total_pages
        p_end = total_pages
    if p_end < p_start:
        p_end = p_start

    chunks: list[str] = []
    for page_num in range(p_start, p_end + 1):
        page_text = pages[page_num - 1]
        chunks.append(f"--- 第 {page_num} / {total_pages} 页 ---\n{page_text or '（本页无可提取文本，可能为图片/扫描页）'}")

    text, clipped = _clip_chars("\n\n".join(chunks), max_chars)
    has_more = p_end < total_pages or clipped
    return {
        "format": "pdf",
        "total_pages": total_pages,
        "page_start": p_start,
        "page_end": p_end,
        "has_more": has_more,
        "next_page_start": (p_end + 1) if p_end < total_pages else None,
        "is_scanned_pdf": is_scanned,
        "truncated": clipped,
        "content": text,
    }


def _read_pdf(
    raw: bytes,
    *,
    page_start: int | None = None,
    page_end: int | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    pages, is_scanned = _extract_pdf_pages(raw)
    return _slice_pdf_pages(
        pages,
        is_scanned=is_scanned,
        page_start=page_start,
        page_end=page_end,
        max_chars=max_chars,
    )


def _docx_lines(raw: bytes) -> list[str]:
    try:
        document = docx.Document(io.BytesIO(raw))
    except Exception as exc:
        raise FileParseError(f"无法解析 Word 文档: {exc}") from exc

    lines: list[str] = []
    for p in document.paragraphs:
        txt = p.text.strip()
        if txt:
            lines.append(txt)
    for ti, table in enumerate(document.tables, 1):
        lines.append(f"[表格 {ti}]")
        for row in table.rows:
            cells = [" ".join(cell.text.split()) for cell in row.cells]
            lines.append(" | ".join(cells))
    return lines


def _extract_xlsx_sheets(raw: bytes, *, max_rows_per_sheet: int = MAX_XLSX_CACHE_ROWS) -> tuple[list[str], dict[str, list[str]]]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise FileParseError(f"无法解析 Excel 文件: {exc}") from exc

    rows_by_sheet: dict[str, list[str]] = {}
    try:
        sheets = list(wb.sheetnames)
        for sheet in sheets:
            ws = wb[sheet]
            lines: list[str] = []
            for idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                if idx > max_rows_per_sheet:
                    break
                cells = ["" if val is None else str(val).replace("\n", " ") for val in row]
                if any(cells):
                    lines.append("\t".join(cells))
            rows_by_sheet[sheet] = lines
    finally:
        wb.close()
    return sheets, rows_by_sheet


def _read_xlsx(
    raw: bytes,
    *,
    sheet_name: str | None = None,
    start_line: int = 1,
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:
        raise FileParseError(f"无法解析 Excel 文件: {exc}") from exc

    try:
        sheets = list(wb.sheetnames)
        if not sheets:
            return {"format": "xlsx", "sheets": [], "sheet": None, "total_lines": 0, "content": ""}
        target = sheet_name if sheet_name in sheets else sheets[0]
        ws = wb[target]
        lines: list[str] = []
        max_rows_collect = max(MAX_XLSX_CACHE_ROWS, start_line + max_lines + 50)
        for idx, row in enumerate(ws.iter_rows(values_only=True), 1):
            if idx > max_rows_collect:
                break
            cells = ["" if val is None else str(val).replace("\n", " ") for val in row]
            if any(cells):
                lines.append("\t".join(cells))
    finally:
        wb.close()

    sliced = _slice_lines(lines, start_line=start_line, max_lines=max_lines, max_chars=max_chars)
    return {
        "format": "xlsx",
        "sheets": sheets,
        "sheet": target,
        **sliced,
    }


def _sniff_image_mime(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def sniff_file_header(head_bytes: bytes | None, *, ext: str, category: str) -> str | None:
    """Validate file magic header bytes (fail-closed for binary checked types); return error message or None."""
    norm_ext = (ext or "").lower()
    requires_magic = category == "image" or norm_ext in IMAGE_EXTENSIONS or norm_ext in (".pdf", ".docx", ".xlsx")
    if not head_bytes:
        if requires_magic:
            return "无法读取文件头进行格式校验，请重试上传"
        return None
    if category == "image" or norm_ext in IMAGE_EXTENSIONS:
        if not _sniff_image_mime(head_bytes):
            return "图片文件头无效或已损坏，请检查真实文件格式后重新上传"
        return None
    if norm_ext == ".pdf":
        if not head_bytes.lstrip().startswith(b"%PDF-"):
            return "PDF 文件头无效或已损坏，请确认文件为有效 PDF"
        return None
    if norm_ext in (".docx", ".xlsx"):
        if not head_bytes.startswith(b"PK\x03\x04"):
            return f"{norm_ext.upper()} 文件格式无效或已损坏"
        return None
    return None


def _image_dimensions_lightweight(raw: bytes) -> tuple[int | None, int | None]:
    """Read image dimensions without decoding full pixel buffers (zero-cost header inspection)."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None, None


def normalize_image_for_base64(
    raw: bytes,
    *,
    mime_type: str = "image/png",
    max_raw_bytes: int = 5 * 1024 * 1024,
    max_edge: int = 2048,
) -> tuple[bytes, str, int | None, int | None, bool]:
    """Prepare image bytes for base64 fallback delivery.

    - If ``len(raw) <= max_raw_bytes`` (default 5 MB): returns the **original uncompressed bytes** untouched!
    - Only if ``len(raw) > max_raw_bytes``: lazily uses Pillow for EXIF auto-orient + proportional downscale
      so 2C4G RAM and provider payload caps stay safe.

    Returns ``(out_bytes, out_mime, width, height, was_compressed)``.
    """
    sniffed = _sniff_image_mime(raw)
    if not sniffed:
        raise FileParseError("图片文件头无效或已损坏")
    w, h = _image_dimensions_lightweight(raw)

    if len(raw) <= max_raw_bytes:
        return raw, sniffed, w, h, False

    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            orig_w, orig_h = im.size
            longest = max(orig_w, orig_h)
            if longest > max_edge:
                scale = max_edge / float(longest)
                new_size = (max(1, int(orig_w * scale)), max(1, int(orig_h * scale)))
                im = im.resize(new_size, Image.Resampling.LANCZOS)
            out_w, out_h = im.size
            has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            buf = io.BytesIO()
            if has_alpha:
                im.save(buf, format="WEBP", quality=88, method=4)
                return buf.getvalue(), "image/webp", out_w, out_h, True
            if im.mode != "RGB":
                im = im.convert("RGB")
            im.save(buf, format="JPEG", quality=88, optimize=True)
            return buf.getvalue(), "image/jpeg", out_w, out_h, True
    except Exception:
        # Fallback cleanly to raw bytes if Pillow fails on exotic subformats
        return raw, sniffed or mime_type, w, h, False


def _build_text_outline(lines: list[str], ext: str) -> dict[str, Any]:
    headings: list[str] = []
    symbols: list[str] = []
    norm_ext = (ext or "").lower()
    for idx, line in enumerate(lines[:2000], 1):
        s = line.strip()
        if not s:
            continue
        if norm_ext in (".md", ".markdown"):
            hm = _MD_HEADING_RE.match(s)
            if hm:
                headings.append(f"L{idx}: {hm.group(1)} {hm.group(2).strip()[:80]}")
                if len(headings) >= 24:
                    break
        else:
            sm = _CODE_SYMBOL_RE.match(line)
            if sm:
                symbols.append(f"L{idx}: {sm.group(1)}")
                if len(symbols) >= 30:
                    break
    preview_lines = [f"{i}: {ln[:200]}" for i, ln in enumerate(lines[:12], 1)]
    return {
        "total_lines": len(lines),
        "headings": headings,
        "symbols": symbols,
        "head_preview": "\n".join(preview_lines),
    }


def parse_file_for_cache(
    raw: bytes,
    *,
    filename: str,
    ext: str,
    mime_type: str,
) -> dict[str, Any]:
    """Parse file once into a cache-friendly structure with structural outline & stats."""
    norm_ext = (ext or "").lower()
    if norm_ext in IMAGE_EXTENSIONS:
        sniffed = _sniff_image_mime(raw)
        if not sniffed:
            raise FileParseError("图片文件头无效或已损坏")
        w, h = _image_dimensions_lightweight(raw)
        return {
            "format": "image",
            "ext": norm_ext,
            "mime_type": sniffed,
            "approx_bytes": 512,
            "image_width": w,
            "image_height": h,
            "outline": {
                "format": "image",
                "filename": filename,
                "mime_type": sniffed,
                "size_bytes": len(raw),
                "width": w,
                "height": h,
            },
        }

    if norm_ext == ".pdf":
        pages, is_scanned = _extract_pdf_pages(raw)
        approx = sum(len(p.encode("utf-8", errors="ignore")) for p in pages) + 512
        first_preview = (pages[0][:600] if pages and pages[0] else "").strip()
        return {
            "format": "pdf",
            "ext": norm_ext,
            "mime_type": mime_type or "application/pdf",
            "approx_bytes": approx,
            "pdf_pages": pages,
            "is_scanned_pdf": is_scanned,
            "outline": {
                "format": "pdf",
                "filename": filename,
                "total_pages": len(pages),
                "is_scanned_pdf": is_scanned,
                "head_preview": first_preview,
            },
        }

    if norm_ext == ".docx":
        lines = _docx_lines(raw)
        approx = sum(len(ln.encode("utf-8", errors="ignore")) for ln in lines) + 512
        return {
            "format": "docx",
            "ext": norm_ext,
            "mime_type": mime_type,
            "approx_bytes": approx,
            "lines": lines,
            "outline": {
                "format": "docx",
                "filename": filename,
                "total_lines": len(lines),
                "head_preview": "\n".join(f"{i}: {ln[:200]}" for i, ln in enumerate(lines[:12], 1)),
            },
        }

    if norm_ext == ".xlsx":
        sheets, rows_by_sheet = _extract_xlsx_sheets(raw)
        approx = sum(
            sum(len(ln.encode("utf-8", errors="ignore")) for ln in rows)
            for rows in rows_by_sheet.values()
        ) + 512
        sheet_summaries: list[dict[str, Any]] = []
        for sname in sheets:
            srows = rows_by_sheet.get(sname) or []
            sheet_summaries.append(
                {
                    "sheet": sname,
                    "row_count": len(srows),
                    "header": srows[0][:300] if srows else "",
                    "sample_rows": srows[1:5],
                }
            )
        return {
            "format": "xlsx",
            "ext": norm_ext,
            "mime_type": mime_type,
            "approx_bytes": approx,
            "xlsx_sheets": sheets,
            "xlsx_rows_by_sheet": rows_by_sheet,
            "outline": {
                "format": "xlsx",
                "filename": filename,
                "sheets": sheets,
                "sheet_summaries": sheet_summaries,
            },
        }

    text = decode_text(raw)
    lines = text.splitlines()
    approx = len(text.encode("utf-8", errors="ignore")) + 512
    outline = _build_text_outline(lines, norm_ext)
    outline["format"] = "text"
    outline["filename"] = filename
    return {
        "format": "text",
        "ext": norm_ext,
        "mime_type": mime_type,
        "approx_bytes": approx,
        "lines": lines,
        "outline": outline,
    }


def read_from_parsed(
    parsed: Any,
    *,
    start_line: int = 1,
    max_lines: int = DEFAULT_MAX_LINES,
    page_start: int | None = None,
    page_end: int | None = None,
    sheet_name: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Slice a cached ``ParsedFileData`` object without touching COS or re-parsing."""
    fmt = parsed.format
    if fmt == "pdf":
        return _slice_pdf_pages(
            parsed.pdf_pages,
            is_scanned=parsed.is_scanned_pdf,
            page_start=page_start,
            page_end=page_end,
            max_chars=max_chars,
        )
    if fmt == "xlsx":
        sheets = parsed.xlsx_sheets
        if not sheets:
            return {"format": "xlsx", "sheets": [], "sheet": None, "total_lines": 0, "content": ""}
        target = sheet_name if sheet_name in sheets else sheets[0]
        rows = parsed.xlsx_rows_by_sheet.get(target) or []
        sliced = _slice_lines(rows, start_line=start_line, max_lines=max_lines, max_chars=max_chars)
        return {"format": "xlsx", "sheets": sheets, "sheet": target, **sliced}
    if fmt == "docx":
        return {"format": "docx", **_slice_lines(parsed.lines, start_line=start_line, max_lines=max_lines, max_chars=max_chars)}
    return {"format": "text", **_slice_lines(parsed.lines, start_line=start_line, max_lines=max_lines, max_chars=max_chars)}


def extract_full_text_for_injection(
    parsed: Any,
    *,
    max_tokens: int,
) -> tuple[str | None, int, dict[str, Any]]:
    """Build complete structured text for direct current-turn injection if it fits ``max_tokens``.

    Returns ``(full_text_or_none, estimated_tokens, stats)``.
    """
    fmt = parsed.format
    if fmt == "pdf":
        total_pages = len(parsed.pdf_pages)
        stats: dict[str, Any] = {"total_pages": total_pages, "is_scanned_pdf": parsed.is_scanned_pdf}
        if total_pages == 0:
            return "", 0, stats
        parts = [
            f"--- 第 {idx} / {total_pages} 页 ---\n{txt or '（本页无可提取文本，可能为扫描图/纯图表页）'}"
            for idx, txt in enumerate(parsed.pdf_pages, 1)
        ]
        full = "\n\n".join(parts)
        est = estimate_tokens(full)
        return (full if est <= max_tokens else None), est, stats

    if fmt == "xlsx":
        sheets = parsed.xlsx_sheets
        total_rows = sum(len(parsed.xlsx_rows_by_sheet.get(s) or []) for s in sheets)
        stats = {"sheets": sheets, "total_rows": total_rows}
        parts = []
        for s in sheets:
            rows = parsed.xlsx_rows_by_sheet.get(s) or []
            numbered = [f"{i}: {r}" for i, r in enumerate(rows, 1)]
            parts.append(f"=== 工作表: {s}（共 {len(rows)} 行）===\n" + "\n".join(numbered))
        full = "\n\n".join(parts)
        est = estimate_tokens(full)
        return (full if est <= max_tokens else None), est, stats

    lines = parsed.lines
    stats = {"total_lines": len(lines)}
    if not lines:
        return "", 0, stats
    full = "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines, 1))
    est = estimate_tokens(full)
    return (full if est <= max_tokens else None), est, stats


def format_outline_text(parsed: Any, *, filename: str) -> str:
    """Format a compact structural map for oversized files."""
    outline = parsed.outline or {}
    fmt = parsed.format
    if fmt == "pdf":
        total_pages = outline.get("total_pages", len(parsed.pdf_pages))
        lines = [f"PDF 文档《{filename}》共 {total_pages} 页。"]
        if parsed.is_scanned_pdf:
            lines.append("注意：检测到该 PDF 可提取文本极少，疑似扫描件或纯图文档。")
        head = (outline.get("head_preview") or "").strip()
        if head:
            lines.append(f"首页摘录：\n{head}")
        return "\n".join(lines)
    if fmt == "xlsx":
        lines = [f"Excel 表格《{filename}》包含工作表：{', '.join(parsed.xlsx_sheets)}"]
        for sm in (outline.get("sheet_summaries") or [])[:6]:
            lines.append(f"- 工作表「{sm['sheet']}」（{sm['row_count']} 行）表头：{sm.get('header') or '无'}")
            for sample in (sm.get("sample_rows") or [])[:2]:
                lines.append(f"  样本：{sample[:240]}")
        return "\n".join(lines)
    lines = [f"文件《{filename}》（{fmt}）共 {len(parsed.lines)} 行。"]
    headings = outline.get("headings") or []
    symbols = outline.get("symbols") or []
    if headings:
        lines.append("章节目录：\n" + "\n".join(f"  {h}" for h in headings[:16]))
    if symbols:
        lines.append("主要符号/定义：" + "，".join(symbols[:20]))
    head = (outline.get("head_preview") or "").strip()
    if head:
        lines.append(f"开头预览：\n{head}")
    return "\n".join(lines)


def read_file_content(
    raw: bytes,
    *,
    ext: str,
    mime_type: str,
    start_line: int = 1,
    max_lines: int = DEFAULT_MAX_LINES,
    page_start: int | None = None,
    page_end: int | None = None,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        sniffed = _sniff_image_mime(raw)
        if not sniffed:
            raise FileParseError("图片文件头无效或已损坏")
        if len(raw) > MAX_IMAGE_EMBED_BYTES:
            return {
                "format": "image",
                "mime_type": sniffed,
                "size_bytes": len(raw),
                "image_base64": None,
                "content": f"图片大小 {len(raw)} 字节，超出内联查看上限（20 MB）。",
            }
        return {
            "format": "image",
            "mime_type": sniffed,
            "size_bytes": len(raw),
            "image_base64": base64.b64encode(raw).decode("ascii"),
            "content": f"图片读取成功（MIME: {sniffed}，大小: {len(raw)} 字节）。",
        }

    if ext == ".pdf":
        return _read_pdf(raw, page_start=page_start, page_end=page_end)
    if ext == ".docx":
        return {"format": "docx", **_slice_lines(_docx_lines(raw), start_line=start_line, max_lines=max_lines)}
    if ext == ".xlsx":
        return _read_xlsx(raw, sheet_name=sheet_name, start_line=start_line, max_lines=max_lines)

    text = decode_text(raw)
    lines = text.splitlines()
    return {"format": "text", **_slice_lines(lines, start_line=start_line, max_lines=max_lines)}


def search_file_content(
    raw: bytes,
    *,
    ext: str,
    query: str,
    max_hits: int = 20,
) -> list[dict[str, Any]]:
    needle = (query or "").strip().lower()
    if not needle:
        return []
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        return []

    hits: list[dict[str, Any]] = []
    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception:
            return []
        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                continue
            for line_no, line in enumerate(page_text.splitlines(), 1):
                if needle in line.lower():
                    hits.append({"location": f"第 {page_num} 页 第 {line_no} 行", "snippet": line.strip()[:300]})
                    if len(hits) >= max_hits:
                        return hits
        return hits

    if ext == ".docx":
        try:
            lines = _docx_lines(raw)
        except FileParseError:
            return []
        for line_no, line in enumerate(lines, 1):
            if needle in line.lower():
                hits.append({"location": f"第 {line_no} 段/行", "snippet": line.strip()[:300]})
                if len(hits) >= max_hits:
                    return hits
        return hits

    if ext == ".xlsx":
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception:
            return []
        try:
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                for row_no, row in enumerate(ws.iter_rows(values_only=True), 1):
                    row_text = "\t".join("" if v is None else str(v) for v in row)
                    if needle in row_text.lower():
                        hits.append({"location": f"工作表 {sheet} 第 {row_no} 行", "snippet": row_text.strip()[:300]})
                        if len(hits) >= max_hits:
                            return hits
        finally:
            wb.close()
        return hits

    text = decode_text(raw)
    for line_no, line in enumerate(text.splitlines(), 1):
        if needle in line.lower():
            hits.append({"location": f"第 {line_no} 行", "snippet": line.strip()[:300]})
            if len(hits) >= max_hits:
                return hits
    return hits


def search_parsed_content(parsed: Any, *, query: str, max_hits: int = 12) -> list[dict[str, Any]]:
    """Fast in-memory keyword search against a cached ``ParsedFileData``."""
    needle = (query or "").strip().lower()
    if not needle or parsed.format == "image":
        return []
    hits: list[dict[str, Any]] = []
    if parsed.format == "pdf":
        for page_num, page_text in enumerate(parsed.pdf_pages, 1):
            for line_no, line in enumerate(page_text.splitlines(), 1):
                if needle in line.lower():
                    hits.append({"location": f"第 {page_num} 页 第 {line_no} 行", "snippet": line.strip()[:300]})
                    if len(hits) >= max_hits:
                        return hits
        return hits
    if parsed.format == "xlsx":
        for sheet in parsed.xlsx_sheets:
            for row_no, row_text in enumerate(parsed.xlsx_rows_by_sheet.get(sheet) or [], 1):
                if needle in row_text.lower():
                    hits.append({"location": f"工作表 {sheet} 第 {row_no} 行", "snippet": row_text.strip()[:300]})
                    if len(hits) >= max_hits:
                        return hits
        return hits
    loc_unit = "段/行" if parsed.format == "docx" else "行"
    for line_no, line in enumerate(parsed.lines, 1):
        if needle in line.lower():
            hits.append({"location": f"第 {line_no} {loc_unit}", "snippet": line.strip()[:300]})
            if len(hits) >= max_hits:
                return hits
    return hits
