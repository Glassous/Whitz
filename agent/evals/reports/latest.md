# Whitz Eval Harness Report

- **Mode**: `offline-harness` | **Git SHA**: `945ab56` | **Generated**: `2026-11-27T07:46:20.250522+00:00`
- **Overall Pass Rate**: **94/94 (100.00%)**
- **Regression Gate**: PASSED

## Suite Summary

| Suite | Passed / Total | Pass Rate | Key Metrics |
| --- | --- | --- | --- |
| `rag` | 24/24 | 100.00% | `recall_at_3=0.875`, `recall_at_5=0.9167`, `mrr_at_5=1.0`, `ndcg_at_5=0.9547`, `p95_latency_ms=6.4224`, `recall_5_gain_vs_vector=0.0417`, `mrr_5_gain_vs_vector=0.1146` |
| `guardrails` | 41/41 | 100.00% | `attack_tpr=1.0`, `benign_fpr=0.0`, `tool_safety_accuracy=1.0`, `pii_f1=1.0`, `pii_recall=1.0`, `p95_latency_ms=0.116` |
| `cache` | 17/17 | 100.00% | `positive_hit_rate=1.0`, `false_hit_rate=0.0`, `tenant_isolation_rate=1.0`, `bypass_accuracy=1.0`, `invalidation_ok=1.0`, `tokens_saved_sample=3150`, `p95_latency_ms=0.4121` |
| `agent_core` | 12/12 | 100.00% | `routing_accuracy=1.0`, `topology_valid=1.0` |

## RAG Retrieval Ablation Study

| Strategy | Recall@3 | Recall@5 | MRR@5 | NDCG@5 | P95 Latency (ms) |
| --- | --- | --- | --- | --- | --- |
| `vector_only` | 0.8333 | 0.8750 | 0.8854 | 0.8660 | 3.830 |
| `lexical_only` | 0.9167 | 0.9375 | 1.0000 | 0.9643 | 0.472 |
| `hybrid_rrf` | 0.8958 | 0.9167 | 1.0000 | 0.9570 | 4.177 |
| `hybrid_rrf_mmr` | 0.8750 | 0.9167 | 1.0000 | 0.9547 | 6.422 |
