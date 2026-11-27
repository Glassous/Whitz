from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

from app.cache.semantic_cache import cosine_similarity
from app.core.models import deterministic_embedding
from evals.harness.metrics import mean, mrr_at_k, ndcg_at_k, percentile, recall_at_k
from whitz_rag.embeddings import char_trigrams, jaccard_sim
from whitz_rag.retriever import mmr_select_evidence, rrf_fuse_rows
from whitz_rag.tokenizer import expand_cjk_bigrams
from whitz_rag.types import EvidenceItem

DEFAULT_RAG_DATASET = Path(__file__).resolve().parents[2] / "datasets" / "rag_benchmark.json"


def _tokenize_fts(text: str) -> Counter[str]:
    expanded = expand_cjk_bigrams(text or "").lower()
    return Counter(tok for tok in expanded.split() if len(tok) >= 2)


def _bm25_rank(
    query: str,
    corpus: list[dict[str, Any]],
    doc_tokens: list[Counter[str]],
    idf: dict[str, float],
    avg_dl: float,
    *,
    limit: int = 15,
) -> list[dict[str, Any]]:
    q_toks = _tokenize_fts(query)
    if not q_toks:
        return []
    k1 = 1.5
    b = 0.75
    scored: list[tuple[float, dict[str, Any]]] = []
    for doc, d_cnt in zip(corpus, doc_tokens):
        dl = sum(d_cnt.values()) or 1
        score = 0.0
        for term, _ in q_toks.items():
            tf = d_cnt.get(term, 0)
            if tf <= 0:
                continue
            denom = tf + k1 * (1.0 - b + b * (dl / max(1.0, avg_dl)))
            score += idf.get(term, 0.0) * (tf * (k1 + 1.0)) / denom
        if score > 0.0:
            scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"chunk_id": d["id"], "doc": d, "score": s} for s, d in scored[:limit]]


def _trgm_rank(
    query: str,
    corpus: list[dict[str, Any]],
    doc_trigrams: list[set[str]],
    *,
    limit: int = 15,
) -> list[dict[str, Any]]:
    q_tri = char_trigrams(query)
    if not q_tri:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for doc, d_tri in zip(corpus, doc_trigrams):
        sim = jaccard_sim(q_tri, d_tri)
        if sim > 0.01:
            scored.append((sim, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"chunk_id": d["id"], "doc": d, "score": s} for s, d in scored[:limit]]


def _vector_rank(
    query: str,
    corpus: list[dict[str, Any]],
    doc_vecs: list[list[float]],
    *,
    limit: int = 15,
) -> list[dict[str, Any]]:
    q_vec = deterministic_embedding(query, dim=512)
    scored: list[tuple[float, dict[str, Any]]] = []
    for doc, d_vec in zip(corpus, doc_vecs):
        sim = cosine_similarity(q_vec, d_vec)
        if sim > 0.0:
            scored.append((sim, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"chunk_id": d["id"], "doc": d, "score": s} for s, d in scored[:limit]]


def _to_evidence(row: dict[str, Any]) -> EvidenceItem:
    d = row["doc"]
    content = str(d.get("content") or "")
    return EvidenceItem(
        citation_id="",
        source_type=d.get("source_type", "file"),
        source_id=str(d.get("source_id") or d["id"]),
        chunk_id=str(d["id"]),
        title=str(d.get("title") or ""),
        subtitle="",
        content=content,
        snippet=content[:200],
        score=float(row.get("rrf_score", row.get("score", 0.0))),
        metadata={"chunk_id": d["id"]},
    )


async def run_rag_bench_suite(dataset_path: Path = DEFAULT_RAG_DATASET) -> dict[str, Any]:
    """Run offline ablation benchmark comparing Vector, Lexical, Hybrid RRF, and Hybrid RRF + MMR."""
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    corpus: list[dict[str, Any]] = list(data["corpus"])
    queries: list[dict[str, Any]] = list(data["queries"])

    # Pre-index corpus
    doc_texts = [f"{d.get('title', '')} {d.get('content', '')}" for d in corpus]
    doc_vecs = [deterministic_embedding(txt, dim=512) for txt in doc_texts]
    doc_tokens = [_tokenize_fts(txt) for txt in doc_texts]
    doc_trigrams = [char_trigrams(txt) for txt in doc_texts]
    n_docs = max(1, len(corpus))
    avg_dl = sum(sum(c.values()) for c in doc_tokens) / n_docs
    df: Counter[str] = Counter()
    for cnt in doc_tokens:
        for term in cnt:
            df[term] += 1
    idf = {term: math.log(1.0 + (n_docs - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

    strategies = ("vector_only", "lexical_only", "hybrid_rrf", "hybrid_rrf_mmr")
    acc: dict[str, dict[str, list[float]]] = {
        s: {"recall_3": [], "recall_5": [], "mrr_5": [], "ndcg_5": [], "latency_ms": []}
        for s in strategies
    }

    case_results: list[dict[str, Any]] = []
    passed = 0

    for item in queries:
        q = str(item["query"])
        rel_grades: dict[str, float] = {str(k): float(v) for k, v in (item.get("relevant") or {}).items()}
        rel_ids = set(rel_grades.keys())

        # 1. vector_only
        t0 = time.perf_counter()
        vec_rows = _vector_rank(q, corpus, doc_vecs, limit=15)
        vec_ms = (time.perf_counter() - t0) * 1000.0

        # 2. lexical_only (CJK Bigram BM25 + Trigram fused)
        t1 = time.perf_counter()
        fts_rows = _bm25_rank(q, corpus, doc_tokens, idf, avg_dl, limit=15)
        trgm_rows = _trgm_rank(q, corpus, doc_trigrams, limit=15)
        lex_rows = rrf_fuse_rows([fts_rows, trgm_rows], rrf_k=60, top_k=10, weights=(1.2, 0.8))
        lex_ms = (time.perf_counter() - t1) * 1000.0

        # 3. hybrid_rrf (3-leg RRF matching Whitz UnifiedKnowledgeRetriever)
        t2 = time.perf_counter()
        fused_rows = rrf_fuse_rows([vec_rows, fts_rows, trgm_rows], rrf_k=60, top_k=12, weights=(1.25, 1.0, 1.0))
        rrf_ms = vec_ms + lex_ms + (time.perf_counter() - t2) * 1000.0

        # 4. hybrid_rrf_mmr
        t3 = time.perf_counter()
        ev_items = [_to_evidence(r) for r in fused_rows]
        mmr_items = mmr_select_evidence(ev_items, top_k=8, lambda_mult=0.75, max_per_source=4)
        mmr_ms = rrf_ms + (time.perf_counter() - t3) * 1000.0

        ranked_by_strategy = {
            "vector_only": ([r["chunk_id"] for r in vec_rows], vec_ms),
            "lexical_only": ([r["chunk_id"] for r in lex_rows], lex_ms),
            "hybrid_rrf": ([r["chunk_id"] for r in fused_rows], rrf_ms),
            "hybrid_rrf_mmr": ([str(it.metadata.get("chunk_id") or "") for it in mmr_items], mmr_ms),
        }

        for strat, (ids, ms) in ranked_by_strategy.items():
            acc[strat]["recall_3"].append(recall_at_k(ids, rel_ids, 3))
            acc[strat]["recall_5"].append(recall_at_k(ids, rel_ids, 5))
            acc[strat]["mrr_5"].append(mrr_at_k(ids, rel_ids, 5))
            acc[strat]["ndcg_5"].append(ndcg_at_k(ids, rel_grades, 5))
            acc[strat]["latency_ms"].append(ms)

        hybrid_ids = ranked_by_strategy["hybrid_rrf_mmr"][0]
        hit_top5 = recall_at_k(hybrid_ids, rel_ids, 5) > 0.0
        if hit_top5:
            passed += 1
        case_results.append(
            {
                "id": item["id"],
                "category": "rag_hybrid",
                "passed": hit_top5,
                "top3": hybrid_ids[:3],
                "expected": sorted(rel_ids),
                "recall_5": round(recall_at_k(hybrid_ids, rel_ids, 5), 4),
                "mrr_5": round(mrr_at_k(hybrid_ids, rel_ids, 5), 4),
            }
        )

    ablations: dict[str, dict[str, float]] = {}
    for strat in strategies:
        ablations[strat] = {
            "recall_at_3": mean(acc[strat]["recall_3"]),
            "recall_at_5": mean(acc[strat]["recall_5"]),
            "mrr_at_5": mean(acc[strat]["mrr_5"]),
            "ndcg_at_5": mean(acc[strat]["ndcg_5"]),
            "p95_latency_ms": percentile(acc[strat]["latency_ms"], 95),
        }

    hybrid_metrics = ablations["hybrid_rrf_mmr"]
    vec_metrics = ablations["vector_only"]
    return {
        "suite": "rag",
        "dataset_name": data.get("dataset_name", "whitz-rag-hybrid-benchmark-v1"),
        "total": len(queries),
        "passed": passed,
        "pass_rate": round(passed / max(1, len(queries)), 4),
        "metrics": {
            "recall_at_3": hybrid_metrics["recall_at_3"],
            "recall_at_5": hybrid_metrics["recall_at_5"],
            "mrr_at_5": hybrid_metrics["mrr_at_5"],
            "ndcg_at_5": hybrid_metrics["ndcg_at_5"],
            "p95_latency_ms": hybrid_metrics["p95_latency_ms"],
            "recall_5_gain_vs_vector": round(hybrid_metrics["recall_at_5"] - vec_metrics["recall_at_5"], 4),
            "mrr_5_gain_vs_vector": round(hybrid_metrics["mrr_at_5"] - vec_metrics["mrr_at_5"], 4),
        },
        "ablations": ablations,
        "results": case_results,
    }
