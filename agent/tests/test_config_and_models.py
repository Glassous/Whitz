from __future__ import annotations

import math

import pytest
from langchain_core.messages import HumanMessage

from app.core.config import AgentSettings
from app.core.models import (
    EmbeddingClient,
    ModelRouter,
    deterministic_embedding,
    fit_embedding,
)
from tests.conftest import FakeRedis


def test_psycopg_database_url_normalization():
    s1 = AgentSettings(database_url="postgresql+asyncpg://u:p@db:5432/whitz")
    assert s1.psycopg_database_url == "postgresql://u:p@db:5432/whitz"

    s2 = AgentSettings(database_url="postgres://u:p@db:5432/whitz")
    assert s2.psycopg_database_url == "postgresql://u:p@db:5432/whitz"


def test_fit_embedding_and_deterministic_fallback():
    padded = fit_embedding([3.0, 4.0], dim=1536)
    assert len(padded) == 1536
    assert math.isclose(padded[0], 0.6, rel_tol=1e-6)
    assert math.isclose(padded[1], 0.8, rel_tol=1e-6)
    assert math.isclose(sum(v * v for v in padded), 1.0, rel_tol=1e-6)

    sliced = fit_embedding([1.0] * 2000, dim=1536)
    assert len(sliced) == 1536
    assert math.isclose(sum(v * v for v in sliced), 1.0, rel_tol=1e-6)

    v1 = deterministic_embedding("LangGraph pgvector hybrid search")
    v2 = deterministic_embedding("LangGraph pgvector hybrid search")
    assert v1 == v2
    assert len(v1) == 1536
    assert math.isclose(sum(x * x for x in v1), 1.0, rel_tol=1e-6)


@pytest.mark.asyncio
async def test_embedding_client_unconfigured_uses_deterministic():
    settings = AgentSettings(embedding_base_url="", embedding_model="", llm_base_url="")
    client = EmbeddingClient(settings=settings)
    assert not client.is_configured
    vecs = await client.embed_texts(["hello", "world"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 1536


@pytest.mark.asyncio
async def test_model_router_selection_and_circuit_breaker():
    redis = FakeRedis()
    settings = AgentSettings(
        llm_base_url="https://api.example.com/v1",
        llm_api_key="sk-main",
        llm_model="main-model",
        llm_fast_model="fast-model",
        llm_reasoning_model="reasoning-model",
        llm_vision_model="vision-model",
        llm_supports_vision=True,
        model_cb_failure_threshold=2,
        model_cb_cooldown_seconds=30,
    )
    router = ModelRouter(settings=settings, redis_client=redis)

    assert router.infer_route("auto", [HumanMessage(content="你好")]) == "fast"
    assert router.infer_route("auto", [HumanMessage(content="请分析这个系统架构的性能瓶颈与优化方案")]) == "reasoning"
    assert router.infer_route("auto", [HumanMessage(content=[{"type": "image_url", "image_url": {"url": "x"}}])]) == "vision"
    assert router.infer_route("fast", [HumanMessage(content="请分析架构")]) == "fast"

    ep_reasoning = router.endpoint_for("reasoning")
    await router.record_failure(ep_reasoning)
    assert not await router.is_circuit_open(ep_reasoning)
    await router.record_failure(ep_reasoning)
    assert await router.is_circuit_open(ep_reasoning)

    candidates = await router.select_candidates("reasoning", [HumanMessage(content="分析")])
    assert candidates[0].route == "default"
    assert candidates[0].model == "main-model"

    await router.record_success(ep_reasoning)
    assert not await router.is_circuit_open(ep_reasoning)
    candidates_after = await router.select_candidates("reasoning", [HumanMessage(content="分析")])
    assert candidates_after[0].route == "reasoning"
