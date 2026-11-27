from __future__ import annotations

import pytest

from app.cache import InMemoryCacheStore, SemanticCache


@pytest.mark.asyncio
async def test_semantic_cache_exact_and_semantic_hit_and_tenant_isolation() -> None:
    store = InMemoryCacheStore()
    cache = SemanticCache(
        store=store,
        enabled=True,
        similarity_threshold=0.90,
        ttl_seconds=3600,
        allow_deterministic_fallback=True,
    )

    stored = await cache.store_response(
        user_id="tenant-1",
        query="What is Reciprocal Rank Fusion in hybrid RAG?",
        response_text="RRF fuses ranked lists via 1/(k + rank).",
        model_route="default",
        model_name="mock-llm",
        original_tokens=450,
    )
    assert stored is True

    # L1 exact hit (whitespace/case normalized)
    exact = await cache.lookup(
        user_id="tenant-1",
        query="  what is reciprocal rank fusion in hybrid rag? ",
        model_route="default",
    )
    assert exact.hit is True
    assert exact.hit_type == "hit_exact"
    assert exact.similarity == 1.0
    assert exact.entry is not None and exact.entry.original_tokens == 450

    # L2 semantic hit (punctuation difference)
    sem = await cache.lookup(
        user_id="tenant-1",
        query="What is Reciprocal Rank Fusion in hybrid RAG",
        model_route="default",
    )
    assert sem.hit is True
    assert sem.hit_type == "hit_semantic"
    assert sem.similarity >= 0.90

    # Hard negative must NOT false-hit
    neg = await cache.lookup(
        user_id="tenant-1",
        query="How does Kubernetes HPA autoscale pods?",
        model_route="default",
    )
    assert neg.hit is False
    assert neg.hit_type == "miss"

    # Strict multi-tenant isolation
    other = await cache.lookup(
        user_id="tenant-2",
        query="What is Reciprocal Rank Fusion in hybrid RAG?",
        model_route="default",
    )
    assert other.hit is False


@pytest.mark.asyncio
async def test_semantic_cache_bypass_and_epoch_invalidation() -> None:
    store = InMemoryCacheStore()
    cache = SemanticCache(store=store, enabled=True, allow_deterministic_fallback=True)
    await cache.store_response(
        user_id="u1",
        query="解释 FastAPI 依赖注入的工作机制",
        response_text="FastAPI 使用 Depends 解析依赖树。",
        model_route="default",
        original_tokens=300,
    )

    # Realtime query, attachments, PII, and deictic follow-ups must bypass
    assert (await cache.lookup(user_id="u1", query="今天最新的 AI 新闻有哪些？")).hit_type == "bypass"
    assert (await cache.lookup(user_id="u1", query="解释 FastAPI 依赖注入的工作机制", has_attachments=True)).hit_type == "bypass"
    assert (await cache.lookup(user_id="u1", query="解释 FastAPI 依赖注入的工作机制", has_pii=True)).hit_type == "bypass"
    assert (await cache.lookup(user_id="u1", query="请继续展开说说上面那个", history_len=2)).hit_type == "bypass"

    # Write-side-effect runs must not be cached
    not_stored = await cache.store_response(
        user_id="u1",
        query="帮我把报告写入工作区文件",
        response_text="已写入。",
        tool_events=[{"tool": "write_workspace_file", "status": "completed"}],
    )
    assert not_stored is False

    # Epoch invalidation clears visibility immediately
    assert (await cache.lookup(user_id="u1", query="解释 FastAPI 依赖注入的工作机制", model_route="default")).hit is True
    await cache.invalidate_user("u1")
    assert (await cache.lookup(user_id="u1", query="解释 FastAPI 依赖注入的工作机制", model_route="default")).hit is False
