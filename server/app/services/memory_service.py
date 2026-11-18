from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.models import User
from app.services import provisioning

logger = logging.getLogger("whitz.memory")

MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375
ENTRY_DELIMITER = "\n§\n"

_TARGET_SPEC: dict[str, tuple[str, int]] = {
    "memory": ("MEMORY.md", MEMORY_CHAR_LIMIT),
    "user": ("USER.md", USER_CHAR_LIMIT),
}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class MemoryServiceError(ValueError):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _memories_dir(profile: str) -> Path:
    return provisioning.profile_dir(profile) / "memories"


def _pending_dir(profile: str) -> Path:
    return provisioning.profile_dir(profile) / "pending" / "memory"


def _meta_path(profile: str) -> Path:
    return _memories_dir(profile) / ".whitz_memory_meta.json"


def _normalize_target(target: str | None) -> str:
    cleaned = (target or "memory").strip().lower()
    if cleaned in ("user", "user.md", "profile"):
        return "user"
    if cleaned in ("memory", "memory.md", "memories", ""):
        return "memory"
    raise MemoryServiceError(f"不支持的记忆目标类型: {target}", 400)


def _sanitize_entry_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    # Prevent user text from injecting standalone § delimiters.
    text = re.sub(r"(?m)^\s*§\s*$", "-", text)
    return text.strip()


def _parse_entries(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    parts = re.split(r"(?:^|\n)\s*§\s*(?:\n|$)", text)
    return [part.strip() for part in parts if part.strip()]


def _serialize_entries(entries: list[str]) -> str:
    cleaned = [e.strip() for e in entries if e.strip()]
    return ENTRY_DELIMITER.join(cleaned)


def _deterministic_id(target: str, content: str, seen: set[str]) -> str:
    digest = hashlib.sha256(f"{target}\n{content}".encode("utf-8")).hexdigest()[:12]
    candidate = f"{target}_{digest}"
    if candidate not in seen:
        seen.add(candidate)
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in seen:
        suffix += 1
    unique = f"{candidate}_{suffix}"
    seen.add(unique)
    return unique


def _load_meta(profile: str) -> dict[str, dict[str, Any]]:
    path = _meta_path(profile)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_meta(profile: str, meta: dict[str, dict[str, Any]]) -> None:
    d = _memories_dir(profile)
    d.mkdir(parents=True, exist_ok=True)
    _meta_path(profile).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_dt(value: Any, fallback: datetime | None = None) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return fallback


def _read_target_raw(profile: str, target: str) -> tuple[list[str], int, datetime | None]:
    filename, _ = _TARGET_SPEC[target]
    path = _memories_dir(profile) / filename
    if not path.is_file():
        return [], 0, None
    try:
        raw = path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return [], 0, None
    entries = _parse_entries(raw)
    serialized = _serialize_entries(entries)
    return entries, len(serialized), mtime


def _write_target_entries(profile: str, target: str, entries: list[str]) -> int:
    filename, limit = _TARGET_SPEC[target]
    serialized = _serialize_entries(entries)
    if len(serialized) > limit:
        raise MemoryServiceError(
            f"超出 {filename} 字符上限（当前 {len(serialized)} / {limit} 字符），请精简或删除旧记忆",
            400,
        )
    d = _memories_dir(profile)
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(serialized, encoding="utf-8")
    return len(serialized)


def list_entries(profile: str) -> tuple[list[dict[str, Any]], int, int]:
    meta = _load_meta(profile)
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    counts = {"memory": 0, "user": 0}

    for target in ("memory", "user"):
        entries, char_count, mtime = _read_target_raw(profile, target)
        counts[target] = char_count
        for content in entries:
            entry_id = _deterministic_id(target, content, seen)
            info = meta.get(entry_id) if isinstance(meta.get(entry_id), dict) else {}
            created_at = _parse_dt(info.get("created_at"), fallback=mtime)
            updated_at = _parse_dt(info.get("updated_at"), fallback=created_at)
            items.append(
                {
                    "id": entry_id,
                    "target": target,
                    "content": content,
                    "source": str(info.get("source") or "agent"),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
    return items, counts["memory"], counts["user"]


def add_entry(
    profile: str,
    target: str,
    raw_content: str,
    *,
    source: str = "manual",
) -> dict[str, Any]:
    norm_target = _normalize_target(target)
    content = _sanitize_entry_text(raw_content)
    if not content:
        raise MemoryServiceError("记忆内容不能为空", 400)

    entries, _, _ = _read_target_raw(profile, norm_target)
    if content in entries:
        raise MemoryServiceError("该记忆条目已存在", 409)

    next_entries = [*entries, content]
    _write_target_entries(profile, norm_target, next_entries)

    now = datetime.now(timezone.utc)
    seen: set[str] = set()
    entry_id = ""
    for item in next_entries:
        entry_id = _deterministic_id(norm_target, item, seen)

    meta = _load_meta(profile)
    meta[entry_id] = {
        "source": source,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    _save_meta(profile, meta)
    return {
        "id": entry_id,
        "target": norm_target,
        "content": content,
        "source": source,
        "created_at": now,
        "updated_at": now,
    }


def update_entry(
    profile: str,
    entry_id: str,
    raw_content: str,
    *,
    new_target: str | None = None,
) -> dict[str, Any]:
    content = _sanitize_entry_text(raw_content)
    if not content:
        raise MemoryServiceError("记忆内容不能为空", 400)

    items, _, _ = list_entries(profile)
    matched = next((item for item in items if item["id"] == entry_id), None)
    if matched is None:
        raise MemoryServiceError("记忆条目不存在", 404)

    current_target = matched["target"]
    dest_target = _normalize_target(new_target) if new_target is not None else current_target
    old_entries, _, _ = _read_target_raw(profile, current_target)

    # Locate exact index of the matching deterministic ID inside current_target.
    seen: set[str] = set()
    target_idx: int | None = None
    for idx, text in enumerate(old_entries):
        if _deterministic_id(current_target, text, seen) == entry_id:
            target_idx = idx
            break
    if target_idx is None:
        raise MemoryServiceError("记忆条目不存在", 404)

    now = datetime.now(timezone.utc)
    meta = _load_meta(profile)
    prev_meta = meta.pop(entry_id, {})
    created_at_iso = prev_meta.get("created_at") or now.isoformat()

    if dest_target == current_target:
        for idx, existing in enumerate(old_entries):
            if idx != target_idx and existing == content:
                raise MemoryServiceError("目标中已存在相同的记忆条目", 409)
        next_entries = list(old_entries)
        next_entries[target_idx] = content
        _write_target_entries(profile, current_target, next_entries)
        seen_after: set[str] = set()
        new_id = ""
        for idx, text in enumerate(next_entries):
            cid = _deterministic_id(current_target, text, seen_after)
            if idx == target_idx:
                new_id = cid
                break
    else:
        dest_entries, _, _ = _read_target_raw(profile, dest_target)
        if content in dest_entries:
            raise MemoryServiceError("目标中已存在相同的记忆条目", 409)
        next_dest = [*dest_entries, content]
        _write_target_entries(profile, dest_target, next_dest)
        next_old = [text for idx, text in enumerate(old_entries) if idx != target_idx]
        _write_target_entries(profile, current_target, next_old)
        seen_after = set()
        new_id = ""
        for text in next_dest:
            new_id = _deterministic_id(dest_target, text, seen_after)

    meta[new_id] = {
        "source": "manual",
        "created_at": created_at_iso,
        "updated_at": now.isoformat(),
    }
    _save_meta(profile, meta)
    return {
        "id": new_id,
        "target": dest_target,
        "content": content,
        "source": "manual",
        "created_at": _parse_dt(created_at_iso, fallback=now),
        "updated_at": now,
    }


def delete_entry(profile: str, entry_id: str) -> None:
    for target in ("memory", "user"):
        entries, _, _ = _read_target_raw(profile, target)
        seen: set[str] = set()
        for idx, text in enumerate(entries):
            if _deterministic_id(target, text, seen) == entry_id:
                next_entries = [item for i, item in enumerate(entries) if i != idx]
                _write_target_entries(profile, target, next_entries)
                meta = _load_meta(profile)
                if entry_id in meta:
                    meta.pop(entry_id, None)
                    _save_meta(profile, meta)
                return
    raise MemoryServiceError("记忆条目不存在", 404)


def clear_all(profile: str) -> None:
    mem_dir = _memories_dir(profile)
    if mem_dir.is_dir():
        for name in ("MEMORY.md", "USER.md", ".whitz_memory_meta.json"):
            target = mem_dir / name
            if target.exists():
                target.unlink(missing_ok=True)
    pend_dir = _pending_dir(profile)
    if pend_dir.is_dir():
        for file_path in pend_dir.glob("*.json"):
            file_path.unlink(missing_ok=True)


def _normalize_pending_record(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    pending_id = str(raw.get("id") or path.stem).strip() or path.stem
    try:
        target = _normalize_target(str(raw.get("target") or "memory"))
    except MemoryServiceError:
        target = "memory"

    action = str(raw.get("action") or "add").strip().lower()
    if action not in ("add", "replace", "remove"):
        action = "add"

    content = str(raw.get("content") or raw.get("new_text") or raw.get("text") or "").strip()
    raw_old = raw.get("old_content") if raw.get("old_content") is not None else raw.get("old_text")
    old_content = str(raw_old).strip() if isinstance(raw_old, str) and raw_old.strip() else None

    conv_id: uuid.UUID | None = None
    raw_conv = raw.get("conversation_id")
    if isinstance(raw_conv, str) and raw_conv.strip():
        try:
            conv_id = uuid.UUID(raw_conv.strip())
        except ValueError:
            conv_id = None

    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        mtime = datetime.now(timezone.utc)
    created_at = _parse_dt(raw.get("created_at"), fallback=mtime)

    return {
        "id": pending_id,
        "target": target,
        "action": action,
        "content": content,
        "old_content": old_content,
        "conversation_id": conv_id,
        "created_at": created_at,
    }


def list_pending(profile: str) -> list[dict[str, Any]]:
    pend_dir = _pending_dir(profile)
    if not pend_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(pend_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skip malformed pending memory file %s: %s", path.name, exc)
            continue
        if not isinstance(data, dict):
            continue
        items.append(_normalize_pending_record(path, data))
    items.sort(key=lambda item: item.get("created_at") or datetime.min.replace(tzinfo=timezone.utc))
    return items


def _find_pending_file(profile: str, pending_id: str) -> tuple[Path, dict[str, Any]]:
    if not _SAFE_ID_RE.match(pending_id) or ".." in pending_id:
        raise MemoryServiceError("无效的待审批记忆 ID", 400)
    pend_dir = _pending_dir(profile)
    if not pend_dir.is_dir():
        raise MemoryServiceError("待审批记忆不存在", 404)

    direct = pend_dir / f"{pending_id}.json"
    candidates = [direct] if direct.is_file() else sorted(pend_dir.glob("*.json"))
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        norm = _normalize_pending_record(path, data)
        if path.stem == pending_id or norm["id"] == pending_id:
            return path, norm
    raise MemoryServiceError("待审批记忆不存在", 404)


def resolve_pending(
    profile: str,
    pending_id: str,
    action: str,
    *,
    content_override: str | None = None,
) -> None:
    path, item = _find_pending_file(profile, pending_id)
    if action == "reject":
        path.unlink(missing_ok=True)
        return
    if action != "approve":
        raise MemoryServiceError(f"不支持的审批动作: {action}", 400)

    target = item["target"]
    op = item["action"]
    resolved_text = _sanitize_entry_text(content_override if content_override is not None else item["content"])
    entries, _, _ = _read_target_raw(profile, target)
    now = datetime.now(timezone.utc)
    meta = _load_meta(profile)

    if op == "remove":
        needle = (item.get("old_content") or resolved_text).strip()
        if not needle:
            raise MemoryServiceError("待删除内容为空", 400)
        next_entries = [e for e in entries if e != needle]
        if len(next_entries) == len(entries):
            next_entries = [e for e in entries if needle not in e]
        _write_target_entries(profile, target, next_entries)
        path.unlink(missing_ok=True)
        return

    if not resolved_text:
        raise MemoryServiceError("记忆内容不能为空", 400)

    if op == "replace":
        old_text = (item.get("old_content") or "").strip()
        replaced = False
        next_entries: list[str] = []
        for entry in entries:
            if not replaced and old_text and (entry == old_text or old_text in entry):
                next_entries.append(resolved_text)
                replaced = True
            else:
                next_entries.append(entry)
        if not replaced:
            if old_text:
                raise MemoryServiceError("原记忆条目已不存在，无法替换", 409)
            if resolved_text not in entries:
                next_entries.append(resolved_text)
        _write_target_entries(profile, target, next_entries)
    else:
        next_entries = list(entries)
        if resolved_text not in next_entries:
            next_entries.append(resolved_text)
        _write_target_entries(profile, target, next_entries)

    seen: set[str] = set()
    for text in next_entries:
        cid = _deterministic_id(target, text, seen)
        if text == resolved_text:
            meta[cid] = {
                "source": "agent",
                "created_at": meta.get(cid, {}).get("created_at") or now.isoformat(),
                "updated_at": now.isoformat(),
            }
    _save_meta(profile, meta)
    path.unlink(missing_ok=True)


def get_overview(user: User) -> dict[str, Any]:
    entries, memory_chars, user_chars = list_entries(user.hermes_profile)
    pending = list_pending(user.hermes_profile)
    return {
        "memory_enabled": bool(user.memory_enabled and user.memory_consented_at),
        "memory_consented_at": user.memory_consented_at,
        "memory_require_confirm": bool(user.memory_require_confirm),
        "entries": entries,
        "pending": pending,
        "char_count": memory_chars,
        "char_limit": MEMORY_CHAR_LIMIT,
        "memory_char_count": memory_chars,
        "memory_char_limit": MEMORY_CHAR_LIMIT,
        "user_char_count": user_chars,
        "user_char_limit": USER_CHAR_LIMIT,
    }
