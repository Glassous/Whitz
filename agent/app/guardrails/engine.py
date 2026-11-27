from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from app.guardrails.pii import PiiVault
from app.guardrails.schemas import GuardrailAction, GuardrailDecision, GuardrailMatch

GuardrailMode = Literal["off", "warn", "block"]


@dataclass(frozen=True)
class _PatternRule:
    rule_id: str
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    score: int
    pattern: re.Pattern[str]


# Educational / defensive framing that should reduce false positives on benign tech questions
_BENIGN_EDUCATIONAL_RE = re.compile(
    r"(什么是|解释|原理|防御|防护|如何防止|怎么防范|论文|综述|案例分析|介绍一下|讲解|"
    r"what is|explain|how to defend|how to prevent|mitigat|defense against|paper on|overview of)",
    re.IGNORECASE,
)

# High-precision Prompt Injection & Jailbreak detection rules
_INJECTION_RULES: tuple[_PatternRule, ...] = (
    _PatternRule(
        rule_id="pi_ignore_instructions_en",
        category="prompt_injection",
        severity="high",
        score=75,
        pattern=re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+)?"
            r"(?:previous|prior|above|earlier|system)\s+(?:instructions|prompts?|rules|directives|constraints)\b",
            re.IGNORECASE,
        ),
    ),
    _PatternRule(
        rule_id="pi_ignore_instructions_zh",
        category="prompt_injection",
        severity="high",
        score=75,
        pattern=re.compile(
            r"(忽略|无视|忘掉|放弃|绕过|覆盖)(?:前面|之前|以上|所有|全部|系统)?(?:的)?(?:所有|全部)?(?:系统)?(?:指令|提示词|规则|限制|约束|设定)"
        ),
    ),
    _PatternRule(
        rule_id="pi_system_prompt_exfil_en",
        category="system_prompt_leak",
        severity="high",
        score=72,
        pattern=re.compile(
            r"\b(?:reveal|show|print|output|dump|repeat|leak|display)\s+(?:me\s+)?"
            r"(?:your\s+|the\s+)?(?:verbatim\s+|full\s+|exact\s+|hidden\s+)?"
            r"(?:system\s+prompt|system\s+instructions?|developer\s+prompt|initial\s+instructions?)\b",
            re.IGNORECASE,
        ),
    ),
    _PatternRule(
        rule_id="pi_system_prompt_exfil_zh",
        category="system_prompt_leak",
        severity="high",
        score=72,
        pattern=re.compile(
            r"(输出|打印|展示|告诉我|泄露|复述|完整给出|原样输出)(?:你|你们|当前)?(?:的)?(?:完整|全部|原始|隐藏)?\s*(?:系统提示词|system\s*prompt|初始指令|开发者指令)"
            r"|(?:把|将)(?:你的)?\s*(?:系统提示词|system\s*prompt)\s*(?:原样|完整)?\s*(?:发给我|输出|打印)",
            re.IGNORECASE,
        ),
    ),
    _PatternRule(
        rule_id="pi_jailbreak_roleplay",
        category="jailbreak",
        severity="high",
        score=75,
        pattern=re.compile(
            r"(\b(?:DAN|do anything now|developer mode|god mode|jailbreak(?:ed)?\s+mode)\b"
            r"|进入(?:开发者模式|无限制模式|越狱模式|上帝模式|DAN\s*模式)"
            r"|现在你不再受任何(?:安全|道德|规则)?限制"
            r"|you are now (?:unrestricted|unfiltered|in developer mode))",
            re.IGNORECASE,
        ),
    ),
    _PatternRule(
        rule_id="pi_delimiter_spoof",
        category="delimiter_injection",
        severity="critical",
        score=85,
        pattern=re.compile(
            r"(<\|(?:im_start|system|endoftext)\|>\s*(?:system|developer)?|"
            r"(?:^|\n)\s*(?:###\s*SYSTEM\s*:|\[SYSTEM\s+OVERRIDE\]|<system_override>))",
            re.IGNORECASE,
        ),
    ),
    _PatternRule(
        rule_id="pi_secret_exfil",
        category="credential_exfil",
        severity="critical",
        score=85,
        pattern=re.compile(
            r"((?:输出|打印|读取|泄露|告诉我|print|dump|show|reveal|cat)\s*(?:me\s+)?(?:the\s+(?:contents?\s+of\s+)?)?(?:一下|出来)?\s*"
            r"(?:环境变量|\.env|OPENAI_API_KEY|JWT_SECRET|AGENT_INTERNAL_TOKEN|DATABASE_URL|API[_\s-]?KEY|系统密钥))",
            re.IGNORECASE,
        ),
    ),
)

# Output leakage signatures (internal system prompt markers or raw secrets)
_OUTPUT_LEAK_RULES: tuple[_PatternRule, ...] = (
    _PatternRule(
        rule_id="out_system_prompt_fingerprint",
        category="system_prompt_leak",
        severity="high",
        score=75,
        pattern=re.compile(
            r"(whitz-system-context|核心常驻记忆（L0|本轮知识库预召回证据（引用事实时)",
            re.IGNORECASE,
        ),
    ),
)

_SENSITIVE_PATH_RE = re.compile(
    r"(\.\./|\.\.\\|/etc/passwd|/etc/shadow|/proc/self/environ|\.env(?:\.prod|\.local)?\b|id_rsa\b)",
    re.IGNORECASE,
)

_PRIVATE_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal", "host.docker.internal"})


def _is_ssrf_target(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False, ""
    scheme = (parsed.scheme or "").lower()
    if scheme and scheme not in ("http", "https"):
        return True, f"disallowed_scheme:{scheme}"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, ""
    if host in _PRIVATE_HOSTNAMES or host.endswith(".internal") or host.endswith(".local"):
        return True, f"private_host:{host}"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True, f"private_ip:{host}"
    except ValueError:
        pass
    return False, ""


class GuardrailEngine:
    """Multi-stage security guardrail engine for Whitz Agent:
    - Input stage: Prompt Injection / Jailbreak scoring + reversible PII Vault redaction
    - Tool stage: SSRF & sensitive path validation before tool execution
    - Output stage: System prompt & secret leakage filtering + PII restoration
    """

    def __init__(
        self,
        *,
        mode: GuardrailMode = "block",
        pii_redaction_enabled: bool = True,
        block_threshold: int = 70,
        warn_threshold: int = 40,
    ) -> None:
        self.mode: GuardrailMode = mode
        self.pii_redaction_enabled = pii_redaction_enabled
        self.block_threshold = int(block_threshold)
        self.warn_threshold = int(warn_threshold)

    def inspect_input(self, text: str, *, vault: PiiVault | None = None) -> GuardrailDecision:
        t0 = time.perf_counter()
        raw = text or ""
        if self.mode == "off":
            return GuardrailDecision(
                stage="input",
                allowed=True,
                action="allow",
                risk_score=0,
                sanitized_text=raw,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        matches: list[GuardrailMatch] = []
        raw_score = 0
        is_educational = bool(_BENIGN_EDUCATIONAL_RE.search(raw))

        for rule in _INJECTION_RULES:
            m = rule.pattern.search(raw)
            if not m:
                continue
            # Educational questions mentioning concepts without imperative attack framing get dampened,
            # except delimiter spoofing or direct credential exfil which are never benign.
            effective_score = rule.score
            if is_educational and rule.category not in ("delimiter_injection", "credential_exfil"):
                # Still block if explicitly trying to override or extract system prompt
                if rule.rule_id not in ("pi_ignore_instructions_en", "pi_ignore_instructions_zh"):
                    effective_score = max(20, rule.score - 45)
            matches.append(
                GuardrailMatch(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    severity=rule.severity,
                    score=effective_score,
                    snippet=m.group(0)[:120],
                )
            )
            raw_score = max(raw_score, effective_score)

        # Compound bonus when multiple distinct injection categories trigger simultaneously
        distinct_cats = {m.category for m in matches}
        if len(distinct_cats) >= 2:
            raw_score = min(100, raw_score + 15)

        sanitized = raw
        pii_delta: dict[str, int] = {}
        if self.pii_redaction_enabled and raw:
            eff_vault = vault if vault is not None else PiiVault()
            sanitized, pii_delta = eff_vault.redact(raw)

        pii_count = sum(pii_delta.values())
        allowed = True
        action: GuardrailAction = "allow"
        reason = ""

        if raw_score >= self.block_threshold:
            if self.mode == "block":
                allowed = False
                action = "block"
                cats = ", ".join(sorted(distinct_cats))
                reason = f"检测到高风险安全威胁（{cats}），已由安全护栏拦截。"
            else:
                action = "warn"
                reason = f"检测到高风险安全信号（warn 模式放行）：{', '.join(sorted(distinct_cats))}"
        elif raw_score >= self.warn_threshold:
            action = "warn"
            reason = f"检测到中风险安全信号：{', '.join(sorted(distinct_cats))}"
        elif pii_count > 0:
            action = "redact"
            reason = f"已自动脱敏 {pii_count} 处敏感信息"

        return GuardrailDecision(
            stage="input",
            allowed=allowed,
            action=action,
            risk_score=raw_score,
            matches=matches,
            sanitized_text=sanitized,
            pii_count=pii_count,
            pii_types=pii_delta,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            reason=reason,
        )

    def inspect_tool_call(self, tool_name: str, tool_args: dict[str, Any] | None) -> GuardrailDecision:
        t0 = time.perf_counter()
        if self.mode == "off":
            return GuardrailDecision(
                stage="tool",
                allowed=True,
                action="allow",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        args = tool_args if isinstance(tool_args, dict) else {}
        matches: list[GuardrailMatch] = []
        score = 0

        # 1. SSRF protection for network tools
        if tool_name in ("http_request", "web_extract", "fetch_url"):
            for key in ("url", "urls", "endpoint"):
                val = args.get(key)
                candidates = val if isinstance(val, list) else ([val] if isinstance(val, str) else [])
                for u in candidates:
                    bad, detail = _is_ssrf_target(str(u))
                    if bad:
                        matches.append(
                            GuardrailMatch(
                                rule_id="tool_ssrf_private_target",
                                category="ssrf",
                                severity="critical",
                                score=90,
                                snippet=f"{detail} ({str(u)[:80]})",
                            )
                        )
                        score = max(score, 90)

        # 2. Sensitive path traversal check on file/code tools
        for key in ("path", "file_path", "filename", "code", "command"):
            val = args.get(key)
            if isinstance(val, str) and val:
                m = _SENSITIVE_PATH_RE.search(val)
                if m:
                    matches.append(
                        GuardrailMatch(
                            rule_id="tool_sensitive_path",
                            category="path_traversal",
                            severity="high",
                            score=80,
                            snippet=m.group(0)[:80],
                        )
                    )
                    score = max(score, 80)

        allowed = True
        action: GuardrailAction = "allow"
        reason = ""
        if score >= self.block_threshold:
            if self.mode == "block":
                allowed = False
                action = "block"
                reason = f"工具 `{tool_name}` 参数触发安全护栏拦截（{matches[0].category}）。"
            else:
                action = "warn"
                reason = f"工具 `{tool_name}` 参数触发安全告警（warn 模式放行）。"

        return GuardrailDecision(
            stage="tool",
            allowed=allowed,
            action=action,
            risk_score=score,
            matches=matches,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            reason=reason,
        )

    def inspect_output(self, text: str, *, vault: PiiVault | None = None) -> GuardrailDecision:
        t0 = time.perf_counter()
        raw = text or ""
        if self.mode == "off":
            return GuardrailDecision(
                stage="output",
                allowed=True,
                action="allow",
                sanitized_text=raw,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        matches: list[GuardrailMatch] = []
        score = 0
        out = raw

        for rule in _OUTPUT_LEAK_RULES:
            m = rule.pattern.search(out)
            if m:
                matches.append(
                    GuardrailMatch(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        severity=rule.severity,
                        score=rule.score,
                        snippet=m.group(0)[:80],
                    )
                )
                score = max(score, rule.score)

        # Scrub any raw secrets that might have been echoed in output
        secret_vault = PiiVault()
        redacted_out, delta = secret_vault.redact(out)
        secret_count = delta.get("SECRET", 0)
        if secret_count > 0:
            # Only keep secret redactions in output, do not re-mask normal user PII we are about to restore
            for token, orig in secret_vault._token_to_value.items():
                if secret_vault._token_types.get(token) == "SECRET" and orig in out:
                    out = out.replace(orig, "[REDACTED_SECRET]")
            matches.append(
                GuardrailMatch(
                    rule_id="out_secret_redacted",
                    category="credential_leak",
                    severity="high",
                    score=70,
                    snippet=f"redacted {secret_count} secret(s)",
                )
            )
            score = max(score, 70)

        if vault is not None:
            out = vault.restore(out, restore_secrets=False)

        action: GuardrailAction = "allow"
        if secret_count > 0:
            action = "redact"
        elif score >= self.warn_threshold:
            action = "warn"

        return GuardrailDecision(
            stage="output",
            allowed=True,
            action=action,
            risk_score=score,
            matches=matches,
            sanitized_text=out,
            pii_count=secret_count,
            pii_types={"SECRET": secret_count} if secret_count else {},
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )
