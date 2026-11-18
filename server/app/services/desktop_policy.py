"""Signed desktop policy envelope (kills switch + feature gating).

The desktop client verifies ``signature`` over the raw ``payload`` bytes with an
Ed25519 public key shipped inside the app. Any rotation must therefore publish a
new public key with the client release.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import get_settings

logger = logging.getLogger("whitz.desktop_policy")

_warned_unsigned = False


def _load_private_key() -> Ed25519PrivateKey | None:
    raw = (get_settings().desktop_policy_private_key or "").strip()
    if not raw:
        return None
    try:
        if "BEGIN" in raw:
            key = serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("not an ed25519 key")
            return key
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))
    except Exception:
        logger.exception("invalid DESKTOP_POLICY_PRIVATE_KEY")
        return None


def public_key_pem() -> str | None:
    key = _load_private_key()
    if key is None:
        return None
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )


def build_payload(now: datetime | None = None) -> dict:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    not_after = now + timedelta(minutes=max(1, settings.desktop_policy_ttl_minutes))
    latest = settings.desktop_latest_app_version or settings.desktop_min_app_version
    return {
        "version": int(time.time() * 1000),
        "issued_at": now.isoformat(),
        "not_after": not_after.isoformat(),
        "work_mode": {
            "enabled": bool(settings.desktop_work_mode_enabled),
            "min_app_version": settings.desktop_min_app_version,
            "disabled_reason": (settings.desktop_work_disabled_reason or None)
            if not settings.desktop_work_mode_enabled
            else None,
        },
        "desktop": {
            "min_app_version": settings.desktop_min_app_version,
            "latest_version": latest,
        },
        "llm": {
            "enabled": True,
            "model_alias": settings.desktop_llm_model_alias,
        },
    }


def build_envelope(now: datetime | None = None) -> dict:
    payload = build_payload(now)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    key = _load_private_key()
    signature = ""
    if key is not None:
        signature = base64.b64encode(key.sign(raw.encode("utf-8"))).decode("ascii")
    else:
        global _warned_unsigned
        if not _warned_unsigned:
            _warned_unsigned = True
            logger.warning("DESKTOP_POLICY_PRIVATE_KEY is not configured; policy is unsigned")
    return {
        "payload": raw,
        "signature": signature,
        "key_id": get_settings().desktop_policy_key_id,
    }
