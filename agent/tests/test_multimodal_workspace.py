import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from app.core.config import AgentSettings
from app.core.models import (
    ModelEndpoint,
    ModelRouter,
    _UNSUPPORTED_NATIVE_PDF_MODELS,
    _URL_UNSUPPORTED_VISION_MODELS,
)
from app.core.multimodal import (
    HydratedTurnMedia,
    build_ephemeral_image_observation,
    build_multimodal_user_message,
    fold_multimodal_message_for_history,
)
from app.graph.builder import _prepare_llm_messages, build_agent_graph
from app.rag.query_rewriter import build_query_plan
from whitz_rag.types import RagScope


@pytest.mark.asyncio
async def test_query_plan_skips_redundant_prefetch_for_directly_delivered_image():
    fid = "11111111-1111-1111-1111-111111111111"
    hydrated = HydratedTurnMedia(
        content_blocks=[{"type": "image_url", "image_url": {"url": "https://cos.example/a.png", "detail": "auto"}}],
        directly_delivered_ids=[fid],
        delivery_map={fid: "native_image_url"},
        has_images=True,
    )
    msg = build_multimodal_user_message("看看这张图写了什么", hydrated)
    plan = await build_query_plan(
        messages=[msg],
        rag_scope=RagScope(),
        attachments=[{"file_id": fid, "filename": "a.png", "category": "image", "attached": True}],
        directly_delivered_file_ids=[fid],
        memory_enabled=False,
        memory_index="",
        conversation_kind="side",
        allow_llm_rewrite=False,
    )
    assert plan.should_prefetch is False
    assert plan.skipped_reason == "directly_delivered_native"


def test_multimodal_user_message_supports_empty_text_image_only():
    hydrated = HydratedTurnMedia(
        content_blocks=[{"type": "image_url", "image_url": {"url": "https://cos.example/pic.jpg", "detail": "auto"}}],
        directly_delivered_ids=["fid-1"],
        delivery_map={"fid-1": "native_image_url"},
        has_images=True,
    )
    msg = build_multimodal_user_message("", hydrated)
    assert isinstance(msg.content, list)
    assert msg.content[0]["type"] == "text"
    assert "图片" in msg.content[0]["text"]
    assert msg.content[1]["type"] == "image_url"


def test_prepare_llm_messages_folds_older_turn_media_but_preserves_latest_turn():
    old_hydrated = HydratedTurnMedia(
        content_blocks=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA", "detail": "auto"}}],
        directly_delivered_ids=["fid-old"],
        delivery_map={"fid-old": "native_image_base64"},
        has_images=True,
        file_meta_by_id={"fid-old": {"file_id": "fid-old", "filename": "old.png", "category": "image"}},
    )
    new_hydrated = HydratedTurnMedia(
        content_blocks=[{"type": "image_url", "image_url": {"url": "https://cos.example/new.png", "detail": "auto"}}],
        directly_delivered_ids=["fid-new"],
        delivery_map={"fid-new": "native_image_url"},
        has_images=True,
        file_meta_by_id={"fid-new": {"file_id": "fid-new", "filename": "new.png", "category": "image"}},
    )
    msgs = [
        SystemMessage(id="whitz-system-context", content="sys"),
        build_multimodal_user_message("第一轮看图", old_hydrated),
        AIMessage(content="第一轮回复"),
        build_multimodal_user_message("第二轮新图", new_hydrated),
    ]
    prepared = _prepare_llm_messages(msgs, max_prompt_tokens=16000)
    assert isinstance(prepared[1].content, str)
    assert "old.png" in prepared[1].content
    assert "AAA" not in prepared[1].content
    assert isinstance(prepared[3].content, list)
    assert prepared[3].content[1]["image_url"]["url"] == "https://cos.example/new.png"


def test_model_router_upgrades_to_vision_when_visual_observation_present():
    settings = AgentSettings(
        llm_base_url="https://api.example.com/v1",
        llm_api_key="sk-test",
        llm_model="gpt-text-only",
        llm_supports_vision=False,
        llm_fast_model="gpt-fast",
        llm_vision_model="gpt-4o-vision",
    )
    router = ModelRouter(settings=settings)
    obs = build_ephemeral_image_observation(
        file_id="f1", filename="screen.png", image_url="https://cos.example/screen.png"
    )
    # Even if selected_route was previously "fast", presence of image_url must upgrade to "vision"!
    route = router.infer_route("fast", [HumanMessage(content="看看之前的截图"), obs])
    assert route == "vision"


@pytest.mark.asyncio
async def test_tools_node_unwraps_image_into_visual_observation_and_injects_edit_conv_id(monkeypatch):
    seen_edit_conv_ids: list[str] = []

    @tool
    async def read_workspace_file(conversation_id: str, file_id: str = "") -> str:
        """Fake read_workspace_file returning visual attachment payload."""
        return json.dumps(
            {
                "file_id": file_id,
                "filename": "diagram.png",
                "format": "image",
                "mime_type": "image/png",
                "size_bytes": 4096,
                "image_url": "https://cos.example/diagram.png",
                "whitz_visual_attachment": True,
            },
            ensure_ascii=False,
        )

    @tool
    async def edit_workspace_file(conversation_id: str, file_id: str = "", old_text: str = "", new_text: str = "") -> str:
        """Fake edit_workspace_file verifying conversation_id auto-injection."""
        seen_edit_conv_ids.append(conversation_id)
        return json.dumps({"status": "edited", "file_id": file_id}, ensure_ascii=False)

    calls: list[list[Any]] = []

    class _FakeBoundLLM:
        def __init__(self, ep: ModelEndpoint) -> None:
            self.ep = ep

        async def ainvoke(self, messages, config=None):
            calls.append(list(messages))
            if len(calls) == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "tc-1", "name": "read_workspace_file", "args": {"file_id": "img-123"}},
                        {"id": "tc-2", "name": "edit_workspace_file", "args": {"file_id": "doc-1", "old_text": "a", "new_text": "b"}},
                    ],
                )
            return AIMessage(content="我看到了架构图并完成了编辑。")

    class _FakeLLM:
        def __init__(self, ep: ModelEndpoint) -> None:
            self.ep = ep

        def bind_tools(self, tools):
            return _FakeBoundLLM(self.ep)

        async def ainvoke(self, messages, config=None):
            return AIMessage(content="fallback")

    class _TestRouter(ModelRouter):
        def build_chat_model(self, ep: ModelEndpoint, **kwargs):
            return _FakeLLM(ep)

    settings = AgentSettings(
        llm_base_url="https://api.example.com/v1",
        llm_api_key="sk-test",
        llm_model="gpt-4o",
        llm_supports_vision=True,
    )
    router = _TestRouter(settings=settings)
    graph = build_agent_graph()

    res = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="读一下图并顺便改一下文档")],
            "conversation_id": "conv-abc",
            "user_id": "u-1",
            "memory_enabled": False,
        },
        config={
            "configurable": {
                "conversation_id": "conv-abc",
                "user_id": "u-1",
                "model_router": router,
                "mcp_tools": [read_workspace_file, edit_workspace_file],
            }
        },
    )

    assert res["final_output"] == "我看到了架构图并完成了编辑。"
    assert seen_edit_conv_ids == ["conv-abc"]
    assert len(calls) == 2

    # Verify the 2nd LLM invocation received compact ToolMessages + trailing ephemeral image_url HumanMessage!
    second_call_msgs = calls[1]
    tool_msgs = [m for m in second_call_msgs if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2
    img_tool_msg = next(m for m in tool_msgs if m.tool_call_id == "tc-1")
    assert "visual_attached" in img_tool_msg.content
    assert "https://cos.example/diagram.png" not in img_tool_msg.content  # Clean compact ToolMessage!

    obs_msgs = [
        m
        for m in second_call_msgs
        if isinstance(m, HumanMessage) and (m.additional_kwargs or {}).get("whitz_ephemeral_media")
    ]
    assert len(obs_msgs) == 1
    assert isinstance(obs_msgs[0].content, list)
    assert obs_msgs[0].content[1]["type"] == "image_url"
    assert obs_msgs[0].content[1]["image_url"]["url"] == "https://cos.example/diagram.png"


@pytest.mark.asyncio
async def test_agent_node_auto_fallbacks_url_to_base64_and_native_pdf_to_text(monkeypatch):
    _URL_UNSUPPORTED_VISION_MODELS.clear()
    _UNSUPPORTED_NATIVE_PDF_MODELS.clear()

    async def _fake_fallback(*, file_id: str, mode: str, **kwargs):
        if mode == "base64":
            return {"delivery": "native_image_base64", "image_url": "data:image/png;base64,iVBORw0KGgo="}
        return {"delivery": "inline_full", "file_id": file_id, "filename": "spec.pdf", "content": "第1页真实正文"}

    monkeypatch.setattr("app.core.multimodal.fetch_media_fallback", _fake_fallback)

    attempts: list[list[Any]] = []

    class _FlakyProviderLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages, config=None):
            attempts.append(list(messages))
            last_human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
            if isinstance(last_human.content, list):
                for blk in last_human.content:
                    if isinstance(blk, dict) and blk.get("type") == "image_url":
                        if str(blk["image_url"]["url"]).startswith("https://"):
                            raise RuntimeError("Error code: 400 - invalid_image_url: failed to download image")
                    if isinstance(blk, dict) and blk.get("type") == "file":
                        raise RuntimeError("Error code: 400 - unknown variant 'file', unsupported content type")
            return AIMessage(content="降级重试成功并准确回答。")

    class _TestRouter(ModelRouter):
        def build_chat_model(self, ep: ModelEndpoint, **kwargs):
            return _FlakyProviderLLM()

    settings = AgentSettings(
        llm_base_url="https://relay.example.com/v1",
        llm_api_key="sk-test",
        llm_model="custom-vlm",
        llm_supports_vision=True,
    )
    router = _TestRouter(settings=settings)
    graph = build_agent_graph()

    hydrated = HydratedTurnMedia(
        content_blocks=[
            {"type": "image_url", "image_url": {"url": "https://cos.example/p.png", "detail": "auto"}},
            {"type": "file", "file": {"filename": "spec.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}},
        ],
        directly_delivered_ids=["fid-img", "fid-pdf"],
        delivery_map={"fid-img": "native_image_url", "fid-pdf": "native_pdf_file"},
        has_images=True,
        has_native_files=True,
        file_meta_by_id={
            "fid-img": {"file_id": "fid-img", "filename": "p.png", "category": "image", "delivery": "native_image_url"},
            "fid-pdf": {"file_id": "fid-pdf", "filename": "spec.pdf", "category": "document", "delivery": "native_pdf_file"},
        },
    )
    res = await graph.ainvoke(
        {
            "messages": [build_multimodal_user_message("分析图和PDF", hydrated)],
            "conversation_id": "conv-fb",
            "user_id": "u-1",
            "memory_enabled": False,
            "directly_delivered_file_ids": ["fid-img", "fid-pdf"],
            "attachment_delivery_map": hydrated.delivery_map,
        },
        config={
            "configurable": {
                "conversation_id": "conv-fb",
                "user_id": "u-1",
                "agent_namespace": "ns-1",
                "agent_api_key": "k-1",
                "internal_mcp_base_url": "http://server:8000",
                "model_router": router,
            }
        },
    )
    assert res["final_output"] == "降级重试成功并准确回答。"
    assert len(attempts) == 3  # 1st fails URL -> 2nd fails native PDF -> 3rd succeeds with base64 + parsed text!
    ep = router.endpoint_for("default")
    assert router.is_image_url_unsupported(ep) is True
    assert router.is_native_pdf_unsupported(ep) is True
    _URL_UNSUPPORTED_VISION_MODELS.clear()
    _UNSUPPORTED_NATIVE_PDF_MODELS.clear()
