from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from app import runner
from app.core.config import AgentSettings
from app.core.models import ModelRouter
from app.graph.builder import build_agent_graph
from app.graph.topology import get_graph_topology
from app.tools.sandbox import SandboxResult
from tests.conftest import FakeRedis


class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage]
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        idx = min(self.cursor, len(self.responses) - 1)
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages)


class FakeRouter(ModelRouter):
    def __init__(self, scripted: ScriptedChatModel) -> None:
        super().__init__(
            settings=AgentSettings(
                llm_base_url="https://mock.local/v1",
                llm_api_key="sk-mock",
                llm_model="mock-gpt",
                llm_adaptive_probe_enabled=False,
            )
        )
        self.scripted = scripted

    def build_chat_model(self, ep, **kwargs):
        return self.scripted


class ApprovedSandbox:
    async def execute(self, code: str, *, language: str = "python", timeout_seconds: int = 30) -> SandboxResult:
        return SandboxResult(exit_code=0, stdout="55\n", stderr="", language=language, mode="docker")


def test_topology_matches_graph_nodes():
    topo = get_graph_topology()
    node_ids = {n["id"] for n in topo["nodes"]}
    assert node_ids == {"context_loader", "agent", "tools", "hitl_gate", "subagent", "memory_extractor"}
    compiled = build_agent_graph()
    graph_nodes = set(compiled.get_graph().nodes.keys())
    assert node_ids.issubset(graph_nodes)


@pytest.mark.asyncio
async def test_execute_and_resume_hitl_execute_code(monkeypatch):
    redis = FakeRedis()
    checkpointer = InMemorySaver()
    scripted = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_exec_1",
                        "name": "execute_code",
                        "args": {"code": "print(sum(range(11)))", "language": "python", "reason": "计算和"},
                    }
                ],
            ),
            AIMessage(content="计算结果是 55。"),
        ]
    )
    fake_router = FakeRouter(scripted)

    monkeypatch.setattr(runner, "ModelRouter", lambda *a, **kw: fake_router)
    monkeypatch.setattr(runner, "get_sandbox_executor", lambda *a, **kw: ApprovedSandbox())

    run_id = uuid.uuid4().hex
    payload = {
        "thread_id": "thread-hitl-1",
        "conversation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "input": "请用 python 计算 0 到 10 的和",
        "memory_enabled": False,
        "model_route": "auto",
    }

    meta1 = await runner.execute_run(
        run_id,
        payload,
        redis=redis,
        checkpointer=checkpointer,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert meta1["status"] == "waiting_for_approval"
    assert len(meta1["pending_controls"]) == 1

    stream_events = [fields["event"] for _, fields in redis.streams[runner.events_key(run_id)]]
    assert "run.started" in stream_events
    assert "approval.request" in stream_events
    assert "run.completed" not in stream_events

    meta2 = await runner.resume_run(
        run_id,
        {"choice": "once"},
        redis=redis,
        checkpointer=checkpointer,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert meta2["status"] == "completed"
    assert "55" in meta2["output"]

    all_events = [(fields["event"], json.loads(fields["data"])) for _, fields in redis.streams[runner.events_key(run_id)]]
    event_names = [e for e, _ in all_events]
    assert "tool.completed" in event_names
    assert "run.completed" in event_names


@pytest.mark.asyncio
async def test_execute_and_resume_clarify_and_subagent(monkeypatch):
    redis = FakeRedis()
    checkpointer = InMemorySaver()
    scripted = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_clarify_1",
                        "name": "clarify",
                        "args": {"question": "请问目标格式是 CSV 还是 JSON？", "options": ["CSV", "JSON"]},
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_sub_1",
                        "name": "delegate_subtask",
                        "args": {"role": "researcher", "task": "整理 CSV 导出最佳实践"},
                    }
                ],
            ),
            AIMessage(content="Researcher 建议使用 UTF-8 BOM CSV。"),
            AIMessage(content="已按您的要求确认采用 CSV 格式，并整理好方案。"),
        ]
    )
    fake_router = FakeRouter(scripted)
    monkeypatch.setattr(runner, "ModelRouter", lambda *a, **kw: fake_router)
    # Also ensure subgraphs receive the fake router
    import app.graph.subgraphs as sg

    monkeypatch.setattr(sg, "ModelRouter", lambda *a, **kw: fake_router)

    run_id = uuid.uuid4().hex
    payload = {
        "thread_id": "thread-clarify-1",
        "conversation_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "input": "帮我导出一份数据报告",
        "memory_enabled": False,
    }
    meta1 = await runner.execute_run(
        run_id,
        payload,
        redis=redis,
        checkpointer=checkpointer,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert meta1["status"] == "waiting_for_clarify"

    meta2 = await runner.resume_run(
        run_id,
        {"answer": "CSV"},
        redis=redis,
        checkpointer=checkpointer,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert meta2["status"] == "completed"
    assert "CSV" in meta2["output"]
    node_events = [
        json.loads(fields["data"])["node"]
        for _, fields in redis.streams[runner.events_key(run_id)]
        if fields["event"] == "graph.node"
    ]
    assert "subagent" in node_events
    assert "hitl_gate" in node_events


@pytest.mark.asyncio
async def test_pre_cancelled_run_emits_run_cancelled():
    redis = FakeRedis()
    run_id = uuid.uuid4().hex
    await redis.set(runner.cancel_key(run_id), "1")
    meta = await runner.execute_run(
        run_id,
        {"thread_id": "t-cancel", "conversation_id": str(uuid.uuid4()), "user_id": str(uuid.uuid4()), "input": "hi"},
        redis=redis,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert meta["status"] == "cancelled"
    ev_names = [fields["event"] for _, fields in redis.streams[runner.events_key(run_id)]]
    assert ev_names == ["run.cancelled"]


@pytest.mark.asyncio
async def test_time_injection_message_hygiene_and_thinking_escalation(monkeypatch):
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from app.graph.builder import SYSTEM_CONTEXT_MSG_ID, _build_system_prompt, _prepare_llm_messages, format_current_time

    # 1. Time injection works even without profile_context and handles invalid timezone cleanly
    now_sh = format_current_time("Asia/Shanghai")
    assert "Asia/Shanghai" in now_sh
    now_fallback = format_current_time("Invalid/Zone")
    assert "Asia/Shanghai" in now_fallback

    prompt = _build_system_prompt({"persona": "", "profile_context": "", "timezone": "UTC"}, {})
    assert "## 当前时间" in prompt
    assert "UTC" in prompt

    # 2. _prepare_llm_messages keeps system prompt at index 0 and folds oversized older ToolMessages
    old_tool = ToolMessage(tool_call_id="c1", name="web_search", content="x" * 2000)
    recent_msgs = [HumanMessage(content=f"q{i}") for i in range(8)]
    prepared = _prepare_llm_messages([HumanMessage(content="old"), old_tool, *recent_msgs, SystemMessage(id=SYSTEM_CONTEXT_MSG_ID, content="SYS")])
    assert isinstance(prepared[0], SystemMessage)
    assert prepared[0].content == "SYS"
    assert "历史工具输出已折叠" in prepared[2].content

    # 3. request_deep_thinking escalates thinking_enabled in the agent loop
    redis = FakeRedis()
    checkpointer = InMemorySaver()
    seen_thinking: list[bool | None] = []

    class RecordingRouter(ModelRouter):
        def __init__(self, scripted: ScriptedChatModel) -> None:
            super().__init__(
                settings=AgentSettings(
                    llm_base_url="https://mock.local/v1",
                    llm_api_key="sk-mock",
                    llm_model="mock-gpt",
                    llm_adaptive_probe_enabled=False,
                )
            )
            self.scripted = scripted

        def build_chat_model(self, ep, **kwargs):
            seen_thinking.append(kwargs.get("thinking_enabled"))
            return self.scripted

    scripted = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_think_1",
                        "name": "request_deep_thinking",
                        "args": {"reason": "发现多源冲突需要深度推演"},
                    }
                ],
            ),
            AIMessage(content="已完成深度推演并给出最终结论。"),
        ]
    )
    monkeypatch.setattr(runner, "ModelRouter", lambda *a, **kw: RecordingRouter(scripted))

    run_id = uuid.uuid4().hex
    meta = await runner.execute_run(
        run_id,
        {
            "thread_id": "thread-think-esc",
            "conversation_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "input": "请核查这个复杂问题",
            "timezone": "Asia/Shanghai",
        },
        redis=redis,
        checkpointer=checkpointer,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert meta["status"] == "completed"
    assert seen_thinking == [False, True]
    assert "深度推演" in meta["output"]
