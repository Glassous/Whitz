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
async def test_embedding_client_unconfigured_returns_none_no_hash_pollution():
    settings = AgentSettings(embedding_base_url="", embedding_model="", llm_base_url="")
    client = EmbeddingClient(settings=settings)
    assert not client.is_configured
    vecs = await client.embed_texts(["hello", "world"])
    assert vecs is None
    assert await client.embed_query("hello") is None


def test_rerank_client_protocol_detection():
    from app.core.models import RerankClient

    assert RerankClient._is_dashscope_native(
        "https://llm-421ioelqkhtzi1ak.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    assert not RerankClient._is_dashscope_native("https://api.siliconflow.cn/v1/rerank")
    assert RerankClient._normalize_url("https://api.siliconflow.cn/v1") == "https://api.siliconflow.cn/v1/rerank"


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
    assert router.infer_route("auto", [HumanMessage(content="请分析这个系统架构的性能瓶颈与优化方案")]) == "default"
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


@pytest.mark.asyncio
async def test_autonomous_thinking_decision_and_param_styles(monkeypatch):
    settings = AgentSettings(
        llm_base_url="https://api.example.com/v1",
        llm_api_key="sk-main",
        llm_model="deepseek-flash",
        llm_reasoning_model="deepseek-reasoner",
        llm_fast_model="deepseek-fast",
    )
    router = ModelRouter(settings=settings)

    # Explicit overrides & trivial greetings (default route is preserved!)
    assert (await router.resolve_thinking_decision("reasoning", [HumanMessage(content="hi")]))[:2] == (True, "reasoning")
    assert (await router.resolve_thinking_decision("fast", [HumanMessage(content="复杂架构设计")]))[:2] == (False, "fast")
    assert (await router.resolve_thinking_decision("default", [HumanMessage(content="复杂架构设计")]))[:2] == (False, "default")
    assert (await router.resolve_thinking_decision("auto", [HumanMessage(content="你好")]))[:2] == (False, "fast")

    # Zero-latency heuristic routes complex analysis to reasoning and simple factual queries directly
    assert (await router.resolve_thinking_decision("auto", [HumanMessage(content="请对比三种分布式锁方案并给出死锁证明")]))[:2] == (True, "reasoning")
    assert (await router.resolve_thinking_decision("auto", [HumanMessage(content="Python 3.13 是哪天发布的？")]))[:2] == (False, "default")

    # Restore build_chat_model and check vendor thinking param styles
    router2 = ModelRouter(settings=settings)
    m_ds = router2.build_chat_model(router2.endpoint_for("default"), thinking_enabled=True)
    assert m_ds.extra_body == {"thinking": {"type": "enabled"}}

    qwen_router = ModelRouter(settings=AgentSettings(llm_base_url="https://api.example.com/v1", llm_model="qwen3-32b"))
    m_qw = qwen_router.build_chat_model(qwen_router.endpoint_for("default"), thinking_enabled=False)
    assert m_qw.extra_body == {"enable_thinking": False}

    assert ModelRouter.is_unsupported_thinking_param_error(RuntimeError("400 unknown field extra_body.thinking"))
    ep_ds = router2.endpoint_for("default")
    router2.mark_thinking_param_unsupported(ep_ds)
    m_fallback = router2.build_chat_model(ep_ds, thinking_enabled=True)
    assert not m_fallback.extra_body

    # Check WhitzChatOpenAI preserves delta.reasoning_content
    from langchain_core.messages import AIMessageChunk

    gen_chunk = m_fallback._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"content": "", "reasoning_content": "逐步推演中..."}}]},
        AIMessageChunk,
        None,
    )
    assert gen_chunk is not None
    assert gen_chunk.message.additional_kwargs.get("reasoning_content") == "逐步推演中..."
