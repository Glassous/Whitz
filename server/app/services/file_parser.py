from __future__ import annotations

import base64
import io
from typing import Any

import docx
import openpyxl
from pypdf import PdfReader

from app.services.file_types import IMAGE_EXTENSIONS

DEFAULT_MAX_CHARS = 12_000
MAX_IMAGE_EMBED_BYTES = 10 * 1024 * 1024


class FileParseError(ValueError):
    pass


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
    max_lines: int = 200,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    total = len(lines)
    start = max(1, int(start_line))
    count = max(1, min(500, int(max_lines)))
    if total == 0:
        return {
            "total_lines": 0,
            "start_line": 1,
            "end_line": 0,
            "has_more": False,
            "truncated": False,
            "content": "",
        }
    if start > total:
        return {
            "total_lines": total,
            "start_line": start,
            "end_line": total,
            "has_more": False,
            "truncated": False,
            "content": "",
        }
    end = min(total, start + count - 1)
    numbered = [f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1)]
    text, clipped = _clip_chars("\n".join(numbered), max_chars)
    return {
        "total_lines": total,
        "start_line": start,
        "end_line": end,
        "has_more": end < total or clipped,
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
    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        raise FileParseError(f"无法解析 PDF 文件: {exc}") from exc
    total_pages = len(reader.pages)
    if total_pages == 0:
        return {"format": "pdf", "total_pages": 0, "page_start": 0, "page_end": 0, "has_more": False, "content": ""}

    p_start = max(1, int(page_start or 1))
    p_end = min(total_pages, int(page_end or min(total_pages, p_start + 4)))
    if p_start > total_pages:
        p_start = total_pages
        p_end = total_pages
    if p_end < p_start:
        p_end = p_start

    chunks: list[str] = []
    for page_num in range(p_start, p_end + 1):
        try:
            page_text = (reader.pages[page_num - 1].extract_text() or "").strip()
        except Exception:
            page_text = ""
        chunks.append(f"--- 第 {page_num} / {total_pages} 页 ---\n{page_text or '（本页无可提取文本）'}")

    text, clipped = _clip_chars("\n\n".join(chunks), max_chars)
    return {
        "format": "pdf",
        "total_pages": total_pages,
        "page_start": p_start,
        "page_end": p_end,
        "has_more": p_end < total_pages or clipped,
        "truncated": clipped,
        "content": text,
    }


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


def _read_xlsx(
    raw: bytes,
    *,
    sheet_name: str | None = None,
    start_line: int = 1,
    max_lines: int = 200,
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
        max_rows_collect = max(5000, start_line + max_lines + 50)
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
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return None


def read_file_content(
    raw: bytes,
    *,
    ext: str,
    mime_type: str,
    start_line: int = 1,
    max_lines: int = 200,
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
                "content": f"图片大小 {len(raw)} 字节，超出内联查看上限（10 MB）。",
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
