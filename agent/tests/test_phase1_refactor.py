from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app import runner
from app.core.config import AgentSettings
from app.core.models import ModelEndpoint, ModelRouter
from app.core.multimodal import (
    HydratedTurnMedia,
    build_multimodal_user_message,
    downgrade_messages_native_pdf_to_text,
    extract_inline_file_ids,
    fold_multimodal_message_for_history,
    refresh_expiring_image_urls,
    upgrade_messages_images_to_base64,
)
from app.graph.subgraphs import build_researcher_subgraph
from app.rag.citations import CitationRegistry


def test_multimodal_block_refs_prevent_mixed_base64_and_url_misalignment():
    hydrated = HydratedTurnMedia(
        content_blocks=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "auto"}},
            {"type": "image_url", "image_url": {"url": "https://cos.example/img2.png", "detail": "auto"}},
            {"type": "text", "text": "<attached_file file_id=\"doc1\" filename=\"notes.md\" mode=\"full\">hello</attached_file>"},
            {"type": "file", "file": {"filename": "paper.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}},
        ],
        block_refs=[
            {"file_id": "img1", "filename": "a.png", "category": "image", "delivery": "native_image_base64"},
            {"file_id": "img2", "filename": "b.png", "category": "image", "delivery": "native_image_url", "expires_at": time.time() - 10},
            {"file_id": "doc1", "filename": "notes.md", "category": "document", "delivery": "inline_full"},
            {"file_id": "pdf1", "filename": "paper.pdf", "category": "document", "delivery": "native_pdf_file"},
        ],
        directly_delivered_ids=["img1", "img2", "doc1", "pdf1"],
        delivery_map={"img1": "native_image_base64", "img2": "native_image_url", "doc1": "inline_full", "pdf1": "native_pdf_file"},
        has_images=True,
        has_native_files=True,
        file_meta_by_id={
            "img1": {"file_id": "img1", "filename": "a.png", "category": "image", "delivery": "native_image_base64"},
            "img2": {"file_id": "img2", "filename": "b.png", "category": "image", "delivery": "native_image_url", "expires_at": time.time() - 10},
            "doc1": {"file_id": "doc1", "filename": "notes.md", "category": "document", "delivery": "inline_full"},
            "pdf1": {"file_id": "pdf1", "filename": "paper.pdf", "category": "document", "delivery": "native_pdf_file"},
        },
    )
    msg = build_multimodal_user_message("看看这两个文件", hydrated)
    folded = fold_multimodal_message_for_history(msg)
    assert isinstance(folded.content, str)
    assert "a.png (file_id=img1)" in folded.content
    assert "b.png (file_id=img2)" in folded.content
    assert "paper.pdf (file_id=pdf1)" in folded.content


@pytest.mark.asyncio
async def test_refresh_expiring_image_urls_targets_exact_file_id(monkeypatch):
    fetched: list[tuple[str, str]] = []

    async def _fake_fetch(**kwargs):
        fetched.append((kwargs["file_id"], kwargs["mode"]))
        return {"image_url": "https://cos.example/img2-fresh.png", "expires_at": time.time() + 1800}

    monkeypatch.setattr("app.core.multimodal.fetch_media_fallback", _fake_fetch)

    hydrated = HydratedTurnMedia(
        content_blocks=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "auto"}},
            {"type": "image_url", "image_url": {"url": "https://cos.example/img2-old.png", "detail": "auto"}},
        ],
        block_refs=[
            {"file_id": "img1", "filename": "a.png", "category": "image", "delivery": "native_image_base64"},
            {"file_id": "img2", "filename": "b.png", "category": "image", "delivery": "native_image_url", "expires_at": time.time() + 10},
        ],
        has_images=True,
    )
    msg = build_multimodal_user_message("分析图", hydrated)
    refreshed_msgs, changed = await refresh_expiring_image_urls(
        [msg],
        internal_mcp_base_url="http://server:8000",
        agent_namespace="u1",
        agent_api_key="k1",
    )
    assert changed is True
    assert fetched == [("img2", "url")]
    assert refreshed_msgs[0].content[2]["image_url"]["url"] == "https://cos.example/img2-fresh.png"


@pytest.mark.asyncio
async def test_upgrade_image_url_to_base64_targets_exact_file_id_when_mixed(monkeypatch):
    fetched: list[str] = []

    async def _fake_fetch(**kwargs):
        fetched.append(kwargs["file_id"])
        return {"image_url": "data:image/jpeg;base64,NEWB64"}

    monkeypatch.setattr("app.core.multimodal.fetch_media_fallback", _fake_fetch)

    hydrated = HydratedTurnMedia(
        content_blocks=[
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,OLD", "detail": "auto"}},
            {"type": "image_url", "image_url": {"url": "https://cos.example/img2.jpg", "detail": "auto"}},
        ],
        block_refs=[
            {"file_id": "img1", "filename": "a.png", "category": "image", "delivery": "native_image_base64"},
            {"file_id": "img2", "filename": "b.jpg", "category": "image", "delivery": "native_image_url"},
        ],
        has_images=True,
    )
    msg = build_multimodal_user_message("对比", hydrated)
    upgraded_msgs, changed = await upgrade_messages_images_to_base64(
        [msg],
        internal_mcp_base_url="http://server:8000",
        agent_namespace="u1",
        agent_api_key="k1",
    )
    assert changed is True
    assert fetched == ["img2"]
    assert upgraded_msgs[0].content[2]["image_url"]["url"] == "data:image/jpeg;base64,NEWB64"


def test_extract_inline_file_ids_deduplicates():
    u1 = str(uuid.uuid4())
    u2 = str(uuid.uuid4())
    text = f"对比 [[file:{u1}|a.pdf]] 和 [[file:{u2}|b.png]] 再看 [[file:{u1}|a.pdf]]"
    assert extract_inline_file_ids(text) == [u1, u2]


def test_model_router_pdf_never_routes_to_fast_and_4xx_skips_cb():
    s = AgentSettings(
        llm_base_url="https://api.example/v1",
        llm_api_key="k",
        llm_model="main-model",
        llm_fast_model="fast-model",
    )
    router = ModelRouter(settings=s)
    pdf_msg = HumanMessage(
        content=[
            {"type": "text", "text": "总结下"},
            {"type": "file", "file": {"filename": "a.pdf", "file_data": "data:application/pdf;base64,AAA"}},
        ]
    )
    assert router.infer_route("auto", [pdf_msg]) == "default"
    assert router.is_transient_provider_error(RuntimeError("Error code: 400 - invalid_request_error")) is False
    assert router.is_transient_provider_error(RuntimeError("503 Service Unavailable")) is True
    assert router.is_transient_url_expiry_error(RuntimeError("403 AccessDenied Request has expired")) is True


def test_citation_registry_rehydrates_without_number_collision():
    reg = CitationRegistry.from_serialized(
        [
            {"citation_id": "S1", "source_type": "file", "source_id": "f1", "locator": "p1"},
            {"citation_id": "S2", "source_type": "memory", "source_id": "m1", "locator": "mem"},
        ]
    )
    assert reg.next_index == 3
    assert [c["citation_id"] for c in reg.all_citations()] == ["S1", "S2"]


@pytest.mark.asyncio
async def test_subagent_forced_synthesis_when_max_iterations_reached():
    class _FakeLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages, config=None):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{"id": "tc1", "name": "knowledge_search", "args": {"query": "test"}}],
                )
            return AIMessage(content="综合检索结果：关键结论已完成汇总。")

    class _FakeRouter:
        settings = AgentSettings()

        async def select_candidates(self, *a, **kw):
            return [ModelEndpoint(route="default", base_url="http://x", api_key="k", model="m")]

        async def is_capability_unsupported(self, *a, **kw):
            return False

        def _has_image_content(self, *a, **kw):
            return False

        def build_chat_model(self, *a, **kw):
            return llm

        async def get_chat_model(self, *a, **kw):
            return llm, ModelEndpoint(route="default", base_url="http://x", api_key="k", model="m")

        async def record_success(self, ep):
            pass

        async def record_failure(self, ep, exc=None):
            pass

    llm = _FakeLLM()
    sub = build_researcher_subgraph()
    res = await sub.ainvoke(
        {"role": "researcher", "parent_call_id": "p1", "task": "调研测试", "max_iterations": 1, "messages": []},
        config={"configurable": {"model_router": _FakeRouter()}},
    )
    assert "关键结论已完成汇总" in res["result"]
    assert llm.calls == 2
