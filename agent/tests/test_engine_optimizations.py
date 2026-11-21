"""Unit tests for Stage 2 Agent Engine optimizations (RAG, MMR, Rerank, Checkpoint, Graph)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import AgentSettings
from app.core.models import (
    EmbeddingClient,
    ModelRouter,
    RerankClient,
)
from app.graph.builder import _extract_text, _merge_usage
from app.rag.hybrid_retriever import RetrievedChunk, mmr_select
from app.runner import checkpoint_thread_id


def test_checkpoint_thread_id_is_scoped_per_run():
    t1 = checkpoint_thread_id("thread-abc", "run-1")
    t2 = checkpoint_thread_id("thread-abc", "run-2")
    assert t1 != t2
    assert t1.startswith("thread-abc:")
    assert t2.startswith("thread-abc:")


def test_extract_text_handles_string_and_multimodal_blocks():
    assert _extract_text("hello") == "hello"
    blocks = [
        {"type": "text", "text": "Look at this "},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        {"type": "text", "text": "diagram"},
    ]
    assert _extract_text(blocks) == "Look at this diagram"


def test_merge_usage_accumulates_multi_step_tokens():
    from langchain_core.messages import AIMessage

    u1 = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    msg = AIMessage(content="ok", usage_metadata={"input_tokens": 150, "output_tokens": 40, "total_tokens": 190})
    merged = _merge_usage(u1, msg)
    assert merged["prompt_tokens"] == 250
    assert merged["completion_tokens"] == 60
    assert merged["total_tokens"] == 310


@pytest.mark.asyncio
async def test_resolve_thinking_decision_preserves_default_and_handles_modes():
    reg = ModelRouter(AgentSettings(llm_model="deepseek-chat", llm_thinking_mode="auto"))
    assert await reg.resolve_thinking_decision("default", [{"role": "user", "content": "hi"}]) == (
        False,
        "default",
        "explicit_default_route",
    )
    assert await reg.resolve_thinking_decision("reasoning", [{"role": "user", "content": "hi"}]) == (
        True,
        "reasoning",
        "explicit_reasoning_route",
    )
    en, route, reason = await reg.resolve_thinking_decision(
        "auto", [{"role": "user", "content": "你好"}]
    )
    assert en is False and reason == "trivial_query"
    en2, route2, reason2 = await reg.resolve_thinking_decision(
        "auto",
        [{"role": "user", "content": "请帮我详细分析分布式事务中两阶段提交与Saga模式的性能对比和架构设计方案"}],
    )
    assert en2 is True and reason2 == "heuristic_complex_thinking"


def test_mmr_select_promotes_diversity():
    chunks = [
        RetrievedChunk(
            chunk_id="c1",
            file_id="f1",
            filename="doc1.md",
            conversation_id=None,
            is_global=True,
            chunk_index=0,
            locator="chunk 0",
            content="PostgreSQL pgvector HNSW index optimization guide",
            rrf_score=0.95,
        ),
        RetrievedChunk(
            chunk_id="c2",
            file_id="f1",
            filename="doc1.md",
            conversation_id=None,
            is_global=True,
            chunk_index=1,
            locator="chunk 1",
            content="PostgreSQL pgvector HNSW index optimization guide repeated text",
            rrf_score=0.94,
        ),
        RetrievedChunk(
            chunk_id="c3",
            file_id="f2",
            filename="doc2.md",
            conversation_id=None,
            is_global=True,
            chunk_index=0,
            locator="chunk 0",
            content="Redis Streams consumer group and XADD event replay architecture",
            rrf_score=0.90,
        ),
    ]
    selected = mmr_select(chunks, top_k=2, lambda_mult=0.6)
    assert len(selected) == 2
    assert selected[0].chunk_id == "c1"
    # c3 is orthogonal to c1, so MMR should prefer c3 over near-duplicate c2
    assert selected[1].chunk_id == "c3"


@pytest.mark.asyncio
async def test_rerank_client_dashscope_native_protocol(monkeypatch):
    client = RerankClient(
        AgentSettings(
            rerank_base_url="https://llm-example.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            rerank_api_key="sk-test",
            rerank_model="qwen3.7-text-rerank",
        )
    )
    assert client.is_configured is True

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "output": {
            "results": [
                {"index": 2, "relevance_score": 0.92},
                {"index": 0, "relevance_score": 0.41},
            ]
        }
    }

    captured = {}

    async def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return fake_resp

    fake_http = MagicMock()
    fake_http.post = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr("app.core.models._get_shared_api_client", lambda: fake_http)

    ranked = await client.rerank("query text", ["doc0", "doc1", "doc2"], top_n=2)
    assert captured["url"].endswith("/services/rerank/text-rerank/text-rerank")
    assert "input" in captured["json"]
    assert "parameters" in captured["json"]
    assert ranked == [(2, 0.92), (0, 0.41)]


@pytest.mark.asyncio
async def test_rerank_client_openai_flat_protocol(monkeypatch):
    client = RerankClient(
        AgentSettings(
            rerank_base_url="https://api.jina.ai/v1",
            rerank_api_key="jina-test",
            rerank_model="jina-reranker-v2-base-multilingual",
        )
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.88},
        ]
    }

    captured = {}

    async def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return fake_resp

    fake_http = MagicMock()
    fake_http.post = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr("app.core.models._get_shared_api_client", lambda: fake_http)

    ranked = await client.rerank("q", ["a", "b"], top_n=1)
    assert captured["url"] == "https://api.jina.ai/v1/rerank"
    assert captured["json"]["query"] == "q"
    assert ranked == [(1, 0.88)]


@pytest.mark.asyncio
async def test_embedding_client_unconfigured_returns_none():
    client = EmbeddingClient(
        AgentSettings(
            embedding_base_url="",
            embedding_api_key="",
            embedding_model="qwen3.7-text-embedding-flash",
            embedding_dimensions=1536,
        )
    )
    assert client.is_configured is False
    assert await client.embed_query("hello") is None
    assert await client.embed_texts(["hello", "world"]) is None


@pytest.mark.asyncio
async def test_embedding_client_auto_halves_batch_on_400(monkeypatch):
    client = EmbeddingClient(
        AgentSettings(
            embedding_base_url="https://embed.test/v1",
            embedding_api_key="sk-test",
            embedding_model="qwen3.7-text-embedding-flash",
            embedding_dimensions=4,
            embedding_batch_size=4,
        )
    )
    calls: list[int] = []

    async def fake_post(url, json=None, headers=None, timeout=None):
        inputs = json["input"]
        calls.append(len(inputs))
        resp = MagicMock()
        if len(inputs) > 2:
            resp.status_code = 400
            resp.text = "batch size exceeded"
            return resp
        resp.status_code = 200
        resp.json.return_value = {
            "data": [{"index": i, "embedding": [1.0, 0.0, 0.0, 0.0]} for i in range(len(inputs))]
        }
        return resp

    fake_http = MagicMock()
    fake_http.post = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr("app.core.models._get_shared_api_client", lambda: fake_http)

    vecs = await client.embed_texts(["a", "b", "c", "d"])
    assert vecs is not None and len(vecs) == 4
    # First tried 4 -> 400 -> halved to 2 + 2
    assert calls == [4, 2, 2]
