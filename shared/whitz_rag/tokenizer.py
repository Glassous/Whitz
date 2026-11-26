from __future__ import annotations

import math
import re

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}")


def estimate_tokens(text: str) -> int:
    """Estimate LLM token count for mixed CJK/Latin text."""
    if not text:
        return 0
    cjk = len(_CJK_CHAR_RE.findall(text))
    other = len(text) - cjk
    return max(1, int(math.ceil(cjk * 0.72 + other * 0.28)))


def expand_cjk_bigrams(text: str, *, max_bigrams: int = 240) -> str:
    """Append deduplicated CJK bigrams to improve PostgreSQL `simple` FTS recall on Chinese text."""
    if not text:
        return ""
    bigrams: list[str] = []
    seen: set[str] = set()
    for match in _CJK_RUN_RE.finditer(text):
        run = match.group(0)
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in seen:
                seen.add(bg)
                bigrams.append(bg)
                if len(bigrams) >= max_bigrams:
                    break
        if len(bigrams) >= max_bigrams:
            break
    if not bigrams:
        return text
    return f"{text}\n{' '.join(bigrams)}"
