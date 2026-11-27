from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Order matters: secrets & structured IDs before generic phone/card patterns
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
_CN_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?(1[3-9]\d{9})(?!\d)")
_CN_ID_CARD_RE = re.compile(
    r"(?<!\d)([1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])(?!\d)"
)
_BANK_CARD_RE = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SECRET", re.compile(r"\b(sk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,})\b")),
    ("SECRET", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})\b")),
    ("SECRET", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("SECRET", re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b")),
)

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CODES = "10X98765432"


def _valid_cn_id_card(raw: str) -> bool:
    if len(raw) != 18:
        return False
    if not raw[:17].isdigit():
        return False
    total = sum(int(raw[i]) * _ID_WEIGHTS[i] for i in range(17))
    return _ID_CHECK_CODES[total % 11] == raw[17].upper()


def _valid_luhn(number: str) -> bool:
    if not number.isdigit() or not (16 <= len(number) <= 19):
        return False
    # Reject trivial repeated digits or sequential strings like 0000... / 1234...
    if len(set(number)) <= 2:
        return False
    total = 0
    rev = number[::-1]
    for idx, ch in enumerate(rev):
        d = int(ch)
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class PiiVault:
    """Per-run reversible PII vault for redacting sensitive entities before LLM calls
    and selectively restoring non-secret user PII in final responses.
    """

    _value_to_token: dict[str, str] = field(default_factory=dict)
    _token_to_value: dict[str, str] = field(default_factory=dict)
    _token_types: dict[str, str] = field(default_factory=dict)
    _type_counters: dict[str, int] = field(default_factory=dict)

    @property
    def entity_count(self) -> int:
        return len(self._token_to_value)

    @property
    def entity_type_counts(self) -> dict[str, int]:
        return dict(self._type_counters)

    def _register(self, entity_type: str, value: str) -> str:
        existing = self._value_to_token.get(value)
        if existing is not None:
            return existing
        cnt = self._type_counters.get(entity_type, 0) + 1
        self._type_counters[entity_type] = cnt
        token = f"__PII_{entity_type}_{cnt}__"
        self._value_to_token[value] = token
        self._token_to_value[token] = value
        self._token_types[token] = entity_type
        return token

    def _sub_pattern(
        self,
        text: str,
        entity_type: str,
        pattern: re.Pattern[str],
        *,
        validator: Callable[[str], bool] | None = None,
        group_index: int = 0,
    ) -> str:
        def _repl(match: re.Match[str]) -> str:
            val = match.group(group_index)
            if validator is not None and not validator(val):
                return match.group(0)
            token = self._register(entity_type, val)
            if group_index == 0:
                return token
            full = match.group(0)
            return full.replace(val, token, 1)

        return pattern.sub(_repl, text)

    def redact(self, text: str) -> tuple[str, dict[str, int]]:
        """Redact PII & secrets in `text`, returning (sanitized_text, delta_type_counts)."""
        if not text:
            return text, {}
        before_counts = dict(self._type_counters)
        out = text
        for etype, pat in _SECRET_PATTERNS:
            out = self._sub_pattern(out, etype, pat, group_index=1)
        out = self._sub_pattern(out, "ID_CARD", _CN_ID_CARD_RE, validator=_valid_cn_id_card, group_index=1)
        out = self._sub_pattern(out, "EMAIL", _EMAIL_RE, group_index=0)
        out = self._sub_pattern(out, "PHONE", _CN_PHONE_RE, group_index=1)
        out = self._sub_pattern(out, "BANK_CARD", _BANK_CARD_RE, validator=_valid_luhn, group_index=1)

        delta: dict[str, int] = {}
        for k, v in self._type_counters.items():
            diff = v - before_counts.get(k, 0)
            if diff > 0:
                delta[k] = diff
        return out, delta

    def restore(self, text: str, *, restore_secrets: bool = False) -> str:
        """Restore placeholders back to original values (secrets remain masked by default)."""
        if not text or not self._token_to_value:
            return text
        out = text
        for token, val in self._token_to_value.items():
            etype = self._token_types.get(token, "")
            if etype == "SECRET" and not restore_secrets:
                continue
            if token in out:
                out = out.replace(token, val)
        return out
