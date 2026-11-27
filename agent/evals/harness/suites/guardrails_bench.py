from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.guardrails import GuardrailEngine, PiiVault
from evals.harness.metrics import percentile, precision_recall_f1

DEFAULT_GUARDRAILS_DATASET = Path(__file__).resolve().parents[2] / "datasets" / "guardrails_dataset.json"


async def run_guardrails_bench_suite(dataset_path: Path = DEFAULT_GUARDRAILS_DATASET) -> dict[str, Any]:
    """Evaluate Prompt Injection TPR/FPR, Tool SSRF/Path Traversal blocking, and PII Vault accuracy."""
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    engine = GuardrailEngine(mode="block", pii_redaction_enabled=True, block_threshold=70)

    tp = fp = tn = fn = 0
    latencies: list[float] = []
    results: list[dict[str, Any]] = []

    # 1. Input injection & benign cases
    for case in data.get("input_cases") or []:
        dec = engine.inspect_input(str(case["input"]))
        latencies.append(dec.latency_ms)
        is_attack = case["label"] == "attack"
        blocked = not dec.allowed
        ok = blocked == is_attack
        if is_attack and blocked:
            tp += 1
        elif is_attack and not blocked:
            fn += 1
        elif not is_attack and blocked:
            fp += 1
        else:
            tn += 1
        results.append(
            {
                "id": case["id"],
                "category": f"guardrail_{case.get('category', 'input')}",
                "passed": ok,
                "expected": "block" if is_attack else "allow",
                "actual": dec.action,
                "risk_score": dec.risk_score,
            }
        )

    # 2. Tool safety cases (SSRF / path traversal)
    tool_passed = 0
    tool_cases = list(data.get("tool_cases") or [])
    for case in tool_cases:
        dec = engine.inspect_tool_call(str(case["tool"]), dict(case.get("args") or {}))
        latencies.append(dec.latency_ms)
        expect_block = case["label"] == "block"
        ok = (not dec.allowed) == expect_block
        if ok:
            tool_passed += 1
        results.append(
            {
                "id": case["id"],
                "category": "guardrail_tool",
                "passed": ok,
                "expected": case["label"],
                "actual": dec.action,
                "risk_score": dec.risk_score,
            }
        )

    # 3. PII Vault redaction & restoration cases
    pii_tp = pii_fp = pii_fn = 0
    pii_passed = 0
    pii_cases = list(data.get("pii_cases") or [])
    for case in pii_cases:
        vault = PiiVault()
        dec = engine.inspect_input(str(case["input"]), vault=vault)
        latencies.append(dec.latency_ms)
        expected_types: dict[str, int] = dict(case.get("expected_types") or {})
        actual_types = dict(dec.pii_types)

        all_keys = set(expected_types.keys()) | set(actual_types.keys())
        for k in all_keys:
            exp_n = int(expected_types.get(k, 0))
            act_n = int(actual_types.get(k, 0))
            pii_tp += min(exp_n, act_n)
            if act_n > exp_n:
                pii_fp += act_n - exp_n
            if exp_n > act_n:
                pii_fn += exp_n - act_n

        # Verify restoration rules: user PII restored, secrets NOT restored
        out_dec = engine.inspect_output(f"收到：{dec.sanitized_text}", vault=vault)
        restored_ok = all(s in out_dec.sanitized_text for s in (case.get("must_restore") or []))
        secret_safe = all(s not in out_dec.sanitized_text for s in (case.get("must_not_restore") or []))
        types_ok = actual_types == expected_types
        ok = types_ok and restored_ok and secret_safe
        if ok:
            pii_passed += 1
        results.append(
            {
                "id": case["id"],
                "category": "guardrail_pii",
                "passed": ok,
                "expected_types": expected_types,
                "actual_types": actual_types,
                "restored_ok": restored_ok,
                "secret_safe": secret_safe,
            }
        )

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    tpr = round(tp / max(1, tp + fn), 4)
    fpr = round(fp / max(1, fp + tn), 4)
    pii_prf = precision_recall_f1(pii_tp, pii_fp, pii_fn)
    tool_acc = round(tool_passed / max(1, len(tool_cases)), 4)

    return {
        "suite": "guardrails",
        "dataset_name": data.get("dataset_name", "whitz-guardrails-redteam-v1"),
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / max(1, total), 4),
        "metrics": {
            "attack_tpr": tpr,
            "benign_fpr": fpr,
            "tool_safety_accuracy": tool_acc,
            "pii_f1": pii_prf["f1"],
            "pii_recall": pii_prf["recall"],
            "p95_latency_ms": percentile(latencies, 95),
        },
        "results": results,
    }
