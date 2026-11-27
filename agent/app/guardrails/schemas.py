from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GuardrailAction = Literal["allow", "warn", "redact", "block"]
GuardrailStage = Literal["input", "tool", "output"]


@dataclass(frozen=True)
class GuardrailMatch:
    rule_id: str
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    score: int
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "score": self.score,
            "snippet": self.snippet,
        }


@dataclass
class GuardrailDecision:
    stage: GuardrailStage
    allowed: bool
    action: GuardrailAction
    risk_score: int = 0
    matches: list[GuardrailMatch] = field(default_factory=list)
    sanitized_text: str = ""
    pii_count: int = 0
    pii_types: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    reason: str = ""

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "allowed": self.allowed,
            "action": self.action,
            "risk_score": self.risk_score,
            "pii_count": self.pii_count,
            "pii_types": dict(self.pii_types),
            "matches": [m.to_dict() for m in self.matches],
            "latency_ms": round(self.latency_ms, 3),
            "reason": self.reason,
        }
