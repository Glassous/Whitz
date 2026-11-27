from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.cache import InMemoryCacheStore, SemanticCache
from evals.harness.metrics import percentile

DEFAULT_CACHE_DATASET = Path(__file__).resolve().parents[2] / "datasets" / "semantic_cache_dataset.json"


async def run_cache_bench_suite(dataset_path: Path = DEFAULT_CACHE_DATASET) -> dict[str, Any]:
    """Evaluate two-tier semantic cache hit rate, false-hit rate, bypass accuracy, and tenant isolation."""
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    store = InMemoryCacheStore()
    cache = SemanticCache(
        store=store,
        embedding_client=None,
        enabled=True,
        similarity_threshold=0.90,
        ttl_seconds=3600,
        max_entries_per_user=64,
        allow_deterministic_fallback=True,
    )

    seed_responses: dict[str, str] = {}
    for seed in data.get("seed_entries") or []:
        seed_responses[seed["id"]] = str(seed["response"])
        await cache.store_response(
            user_id=str(seed["user_id"]),
            query=str(seed["query"]),
            response_text=str(seed["response"]),
            model_route="default",
            model_name="mock-model",
            original_tokens=int(seed.get("tokens") or 0),
        )

    pos_total = pos_hits = 0
    neg_total = neg_false_hits = 0
    iso_total = iso_passed = 0
    bypass_total = bypass_passed = 0
    tokens_saved = 0
    latencies: list[float] = []
    results: list[dict[str, Any]] = []

    for case in data.get("lookup_cases") or []:
        res = await cache.lookup(
            user_id=str(case["user_id"]),
            query=str(case["query"]),
            model_route="default",
            has_attachments=bool(case.get("has_attachments", False)),
            history_len=int(case.get("history_len", 0)),
            has_pii=bool(case.get("has_pii", False)),
        )
        latencies.append(res.latency_ms)
        expect_hit = bool(case["expect_hit"])
        cat = str(case.get("category") or "general")

        ok = res.hit == expect_hit
        if ok and expect_hit and case.get("expected_seed"):
            expected_resp = seed_responses.get(str(case["expected_seed"]), "")
            ok = bool(res.entry and res.entry.response_text == expected_resp)
        if case.get("expect_hit_type"):
            ok = ok and (res.hit_type == str(case["expect_hit_type"]))

        if cat in ("exact", "semantic_positive"):
            pos_total += 1
            if ok and res.hit:
                pos_hits += 1
                if res.entry:
                    tokens_saved += res.entry.original_tokens
        elif cat == "hard_negative":
            neg_total += 1
            if res.hit:
                neg_false_hits += 1
        elif cat == "tenant_isolation":
            iso_total += 1
            if ok:
                iso_passed += 1
        elif cat == "bypass":
            bypass_total += 1
            if ok:
                bypass_passed += 1

        results.append(
            {
                "id": case["id"],
                "category": f"cache_{cat}",
                "passed": ok,
                "hit": res.hit,
                "hit_type": res.hit_type,
                "similarity": round(res.similarity, 4),
            }
        )

    # Verify epoch invalidation works cleanly
    await cache.invalidate_user("user-a")
    post_inv = await cache.lookup(
        user_id="user-a",
        query="What is Reciprocal Rank Fusion in hybrid RAG?",
        model_route="default",
    )
    inv_ok = not post_inv.hit
    results.append(
        {
            "id": "epoch-invalidation-01",
            "category": "cache_invalidation",
            "passed": inv_ok,
            "hit": post_inv.hit,
            "hit_type": post_inv.hit_type,
            "similarity": round(post_inv.similarity, 4),
        }
    )

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    return {
        "suite": "cache",
        "dataset_name": data.get("dataset_name", "whitz-semantic-cache-v1"),
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / max(1, total), 4),
        "metrics": {
            "positive_hit_rate": round(pos_hits / max(1, pos_total), 4),
            "false_hit_rate": round(neg_false_hits / max(1, neg_total), 4),
            "tenant_isolation_rate": round(iso_passed / max(1, iso_total), 4),
            "bypass_accuracy": round(bypass_passed / max(1, bypass_total), 4),
            "invalidation_ok": 1.0 if inv_ok else 0.0,
            "tokens_saved_sample": tokens_saved,
            "p95_latency_ms": percentile(latencies, 95),
        },
        "results": results,
    }
