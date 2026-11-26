from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import ConversationFile
from app.services import cos, file_parser


@dataclass
class ParsedFileData:
    """Cached parsed representation of a workspace/library file (never holds huge image blobs)."""

    format: str
    ext: str
    mime_type: str
    size_bytes: int
    approx_bytes: int
    lines: list[str] = field(default_factory=list)
    pdf_pages: list[str] = field(default_factory=list)
    is_scanned_pdf: bool = False
    xlsx_sheets: list[str] = field(default_factory=list)
    xlsx_rows_by_sheet: dict[str, list[str]] = field(default_factory=dict)
    image_width: int | None = None
    image_height: int | None = None
    outline: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)


class ParsedFileCache:
    """2C4G-friendly bounded in-process LRU+TTL cache eliminating redundant COS downloads & reparsing."""

    def __init__(self, max_bytes: int | None = None, ttl_seconds: float = 300.0) -> None:
        self._explicit_max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, ParsedFileData] = OrderedDict()
        self._total_bytes: int = 0

    @property
    def max_bytes(self) -> int:
        if self._explicit_max_bytes is not None:
            return self._explicit_max_bytes
        mb = max(4, int(getattr(get_settings(), "file_parse_cache_max_mb", 32) or 32))
        return mb * 1024 * 1024

    @staticmethod
    def build_key(file_id: uuid.UUID | str, version_tag: str) -> str:
        return f"{file_id}:{version_tag}"

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._entries.items() if (now - v.created_at) > self.ttl_seconds]
        for k in expired:
            item = self._entries.pop(k, None)
            if item is not None:
                self._total_bytes = max(0, self._total_bytes - item.approx_bytes)

    def get(self, key: str) -> ParsedFileData | None:
        self._evict_expired()
        item = self._entries.get(key)
        if item is None:
            return None
        self._entries.move_to_end(key)
        return item

    def set(self, key: str, value: ParsedFileData) -> None:
        self._evict_expired()
        limit = self.max_bytes
        if value.approx_bytes > limit // 2:
            # Never let a single giant file monopolize the cache
            return
        existing = self._entries.pop(key, None)
        if existing is not None:
            self._total_bytes = max(0, self._total_bytes - existing.approx_bytes)
        while self._entries and (self._total_bytes + value.approx_bytes) > limit:
            _, oldest = self._entries.popitem(last=False)
            self._total_bytes = max(0, self._total_bytes - oldest.approx_bytes)
        self._entries[key] = value
        self._total_bytes += value.approx_bytes

    def invalidate_file(self, file_id: uuid.UUID | str) -> None:
        prefix = f"{file_id}:"
        to_remove = [k for k in self._entries if k.startswith(prefix)]
        for k in to_remove:
            item = self._entries.pop(k, None)
            if item is not None:
                self._total_bytes = max(0, self._total_bytes - item.approx_bytes)

    def clear(self) -> None:
        self._entries.clear()
        self._total_bytes = 0

    @property
    def stats(self) -> dict[str, int]:
        return {"entries": len(self._entries), "total_bytes": self._total_bytes, "max_bytes": self.max_bytes}


_GLOBAL_CACHE = ParsedFileCache()


def get_file_cache() -> ParsedFileCache:
    return _GLOBAL_CACHE


def invalidate_file_cache(file_id: uuid.UUID | str) -> None:
    _GLOBAL_CACHE.invalidate_file(file_id)


def _version_tag(record: ConversationFile) -> str:
    if record.etag:
        return str(record.etag)
    ts = record.updated_at or record.created_at
    return f"{int(record.size_bytes or 0)}:{ts.isoformat() if ts else '0'}"


async def get_or_parse_file(
    record: ConversationFile,
    *,
    raw: bytes | None = None,
    settings: Settings | None = None,
) -> ParsedFileData:
    """Return cached parsed file structure or download from COS once and parse off-loop."""
    cache = get_file_cache()
    key = cache.build_key(record.id, _version_tag(record))
    if raw is None:
        cached = cache.get(key)
        if cached is not None:
            return cached

    s = settings or get_settings()
    if raw is None:
        max_download = max(s.max_file_size_bytes, 25 * 1024 * 1024)
        raw = await cos.get_object_bytes(
            record.storage_key,
            max_bytes=max_download,
            settings=s,
        )

    parsed_dict = await asyncio.to_thread(
        file_parser.parse_file_for_cache,
        raw,
        filename=record.filename,
        ext=record.ext,
        mime_type=record.mime_type,
    )
    entry = ParsedFileData(
        format=parsed_dict["format"],
        ext=parsed_dict["ext"],
        mime_type=parsed_dict["mime_type"],
        size_bytes=int(record.size_bytes or len(raw)),
        approx_bytes=int(parsed_dict["approx_bytes"]),
        lines=parsed_dict.get("lines") or [],
        pdf_pages=parsed_dict.get("pdf_pages") or [],
        is_scanned_pdf=bool(parsed_dict.get("is_scanned_pdf", False)),
        xlsx_sheets=parsed_dict.get("xlsx_sheets") or [],
        xlsx_rows_by_sheet=parsed_dict.get("xlsx_rows_by_sheet") or {},
        image_width=parsed_dict.get("image_width"),
        image_height=parsed_dict.get("image_height"),
        outline=parsed_dict.get("outline") or {},
    )
    cache.set(key, entry)
    return entry
