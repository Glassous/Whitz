from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Canonical allowed extensions -> (category, default_mime)
ALLOWED_FILE_TYPES: dict[str, tuple[str, str]] = {
    # Documents
    ".pdf": ("document", "application/pdf"),
    ".docx": ("document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".txt": ("document", "text/plain"),
    ".md": ("document", "text/markdown"),
    ".markdown": ("document", "text/markdown"),
    # Spreadsheets & structured data
    ".xlsx": ("spreadsheet", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".csv": ("spreadsheet", "text/csv"),
    ".tsv": ("spreadsheet", "text/tab-separated-values"),
    ".json": ("spreadsheet", "application/json"),
    ".jsonl": ("spreadsheet", "application/x-ndjson"),
    ".yaml": ("spreadsheet", "application/x-yaml"),
    ".yml": ("spreadsheet", "application/x-yaml"),
    ".xml": ("spreadsheet", "application/xml"),
    # Code & configs
    ".py": ("code", "text/x-python"),
    ".js": ("code", "text/javascript"),
    ".ts": ("code", "text/typescript"),
    ".tsx": ("code", "text/tsx"),
    ".jsx": ("code", "text/jsx"),
    ".vue": ("code", "text/plain"),
    ".html": ("code", "text/html"),
    ".css": ("code", "text/css"),
    ".sql": ("code", "application/sql"),
    ".sh": ("code", "text/x-shellscript"),
    ".log": ("code", "text/plain"),
    ".ini": ("code", "text/plain"),
    ".toml": ("code", "application/toml"),
    # Images
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
    ".gif": ("image", "image/gif"),
}

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

BLOCKED_MIME_PREFIXES = ("video/", "audio/")
BLOCKED_MIME_TYPES = frozenset(
    {
        "application/zip",
        "application/x-zip-compressed",
        "application/x-rar-compressed",
        "application/vnd.rar",
        "application/x-7z-compressed",
        "application/x-tar",
        "application/gzip",
        "application/x-gzip",
        "application/x-msdownload",
        "application/x-dosexec",
        "application/x-executable",
        "application/x-mach-binary",
        "application/x-sh",
        "image/svg+xml",
    }
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ValidatedFileInfo:
    filename: str
    ext: str
    category: str
    mime_type: str
    size_bytes: int


class FileValidationError(ValueError):
    pass


def sanitize_filename(raw: str, max_length: int = 200) -> str:
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = _CONTROL_RE.sub("", name)
    name = _SPACE_RE.sub(" ", name).strip()
    name = name.lstrip(".")
    if not name:
        return ""
    if len(name) <= max_length:
        return name
    stem, ext = os.path.splitext(name)
    keep = max(1, max_length - len(ext))
    return stem[:keep].rstrip() + ext


def validate_upload_request(
    raw_filename: str,
    raw_mime_type: str | None,
    size_bytes: int,
    max_size_bytes: int,
) -> ValidatedFileInfo:
    filename = sanitize_filename(raw_filename)
    if not filename:
        raise FileValidationError("文件名不能为空")

    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    spec = ALLOWED_FILE_TYPES.get(ext)
    if spec is None:
        raise FileValidationError(
            f"不支持的文件类型（{ext or '无扩展名'}）。支持文档（PDF/DOCX/TXT/MD）、表格数据（XLSX/CSV/JSON/YAML/XML）、常见代码与图片（PNG/JPG/WebP/GIF）"
        )

    category, canonical_mime = spec
    if size_bytes <= 0:
        raise FileValidationError("不支持空文件（0 字节）")
    if size_bytes > max_size_bytes:
        max_mb = max(1, max_size_bytes // (1024 * 1024))
        raise FileValidationError(f"文件大小超过上限（最大 {max_mb} MB）")

    declared = (raw_mime_type or "").split(";", 1)[0].strip().lower()
    if declared and declared != "application/octet-stream":
        if declared.startswith(BLOCKED_MIME_PREFIXES) or declared in BLOCKED_MIME_TYPES:
            raise FileValidationError(f"不支持的文件 MIME 类型: {declared}")
        if category == "image" and not declared.startswith("image/"):
            raise FileValidationError(f"图片文件 MIME 类型不匹配: {declared}")
        if category != "image" and declared.startswith("image/"):
            raise FileValidationError(f"文件扩展名与图片 MIME 类型不匹配: {declared}")
        mime_type = declared[:128]
    else:
        mime_type = canonical_mime

    return ValidatedFileInfo(
        filename=filename,
        ext=ext,
        category=category,
        mime_type=mime_type,
        size_bytes=int(size_bytes),
    )
