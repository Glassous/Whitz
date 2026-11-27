from __future__ import annotations

import pytest

from evals.harness.metrics import mrr_at_k, ndcg_at_k, precision_recall_f1, recall_at_k
from evals.harness.runner import check_regressions, run_harness


def test_ir_metrics_math() -> None:
    assert recall_at_k(["d1", "d2", "d3"], {"d2", "d4"}, k=3) == 0.5
    assert mrr_at_k(["d1", "d2", "d3"], {"d2", "d3"}, k=3) == 0.5
    assert mrr_at_k(["d1", "d2"], {"d9"}, k=2) == 0.0
    assert round(ndcg_at_k(["d1", "d2"], {"d1": 2, "d2": 1}, k=2), 4) == 1.0
    assert ndcg_at_k(["d2", "d1"], {"d1": 2, "d2": 1}, k=2) < 1.0
    prf = precision_recall_f1(tp=8, fp=2, fn=0)
    assert prf["precision"] == 0.8
    assert prf["recall"] == 1.0


@pytest.mark.asyncio
async def test_offline_eval_harness_all_suites_pass_and_admin_schema_compatible() -> None:
    report = await run_harness(suite_names=["rag", "guardrails", "cache", "agent_core"])
    assert report.total >= 70
    assert report.passed == report.total
    assert report.pass_rate == 1.0

    # RAG ablation checks
    rag = report.suites["rag"]
    assert rag["metrics"]["recall_at_5"] >= 0.85
    assert "hybrid_rrf_mmr" in rag["ablations"]
    assert "vector_only" in rag["ablations"]

    # Guardrails checks
    guard = report.suites["guardrails"]
    assert guard["metrics"]["attack_tpr"] == 1.0
    assert guard["metrics"]["benign_fpr"] == 0.0
    assert guard["metrics"]["pii_f1"] == 1.0

    # Cache checks
    cache = report.suites["cache"]
    assert cache["metrics"]["false_hit_rate"] == 0.0
    assert cache["metrics"]["tenant_isolation_rate"] == 1.0

    # Admin Quant EvalReportIn payload compatibility
    payload = report.to_admin_quant_payload()
    for required_key in ("mode", "dataset_name", "total", "passed", "pass_rate", "category_scores", "results"):
        assert required_key in payload

    # Markdown report generation
    md = report.to_markdown()
    assert "RAG Retrieval Ablation Study" in md
    assert "hybrid_rrf_mmr" in md


def test_regression_gate_detects_degradation() -> None:
    baseline = {
        "suites": {
            "rag": {"metrics": {"recall_at_5": 0.95, "mrr_at_5": 0.90}},
            "guardrails": {"metrics": {"attack_tpr": 1.0, "benign_fpr": 0.0}},
        }
    }
    degraded = {
        "rag": {"metrics": {"recall_at_5": 0.88, "mrr_at_5": 0.90}},
        "guardrails": {"metrics": {"attack_tpr": 1.0, "benign_fpr": 0.10}},
    }
    regs = check_regressions(degraded, baseline, max_drop=0.02)
    keys = {(r["suite"], r["metric"]) for r in regs}
    assert ("rag", "recall_at_5") in keys
    assert ("guardrails", "benign_fpr") in keys
