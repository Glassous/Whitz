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


@pytest.mark.asyncio
async def test_main_chat_prompt_ordering_token_budget_and_cross_chat_tools():
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from app.graph.builder import SYSTEM_CONTEXT_MSG_ID, _build_system_prompt, _prepare_llm_messages
    from app.tools.builtin_tools import get_builtin_tools
    from tests.conftest import FakePGPool

    # 1. Prefix-cache-friendly ordering: assistant_name + rolling_summary before dynamic time & cross_chat_context
    prompt = _build_system_prompt(
        {
            "conversation_kind": "main",
            "assistant_name": "小智",
            "persona": "直接、清晰",
            "profile_context": "后端工程师",
            "rolling_summary": "之前讨论过 PostgreSQL 索引优化。",
            "cross_chat_context": "### 近期旁聊目录\n- [id=abc] Vim 调研",
            "timezone": "Asia/Shanghai",
        },
        {},
    )
    assert "你是 小智 智能助理" in prompt
    assert "## 主聊天历史滚动摘要" in prompt
    assert "## 跨旁聊全局记忆" in prompt
    assert prompt.index("## 主聊天历史滚动摘要") < prompt.index("## 当前时间") < prompt.index("## 跨旁聊全局记忆")

    # 2. Hard token budget trims older turns while preserving tool_call / ToolMessage boundaries
    sys_msg = SystemMessage(id=SYSTEM_CONTEXT_MSG_ID, content="SYS")
    msgs: list[BaseMessage] = [sys_msg]
    for i in range(12):
        msgs.append(HumanMessage(content=f"旧问题 {i}: " + ("数据" * 200)))
        msgs.append(AIMessage(content="", tool_calls=[{"id": f"tc_{i}", "name": "web_search", "args": {"query": f"q{i}"}}]))
        msgs.append(ToolMessage(tool_call_id=f"tc_{i}", name="web_search", content="结果" * 200))
        msgs.append(AIMessage(content=f"旧回答 {i}: " + ("总结" * 150)))

    trimmed = _prepare_llm_messages(msgs, max_prompt_tokens=900, max_verbatim_messages=4)
    assert isinstance(trimmed[0], SystemMessage)
    assert len(trimmed) < len(msgs)
    # First non-system message must never be an orphan ToolMessage
    assert not isinstance(trimmed[1], ToolMessage)
    # Latest user/assistant turn is preserved
    assert any("旧回答 11" in str(m.content) for m in trimmed)

    # 3. Cross-chat tools are exposed ONLY when include_cross_chat=True and enforce user_id filter
    from datetime import datetime, timezone

    uid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now_dt = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    side_tools = {t.name for t in get_builtin_tools(include_cross_chat=False)}
    assert "search_chat_history" not in side_tools
    assert "read_conversation_history" not in side_tools

    def responder(sql: str, params: tuple):
        if "FROM conversations WHERE id = %s AND user_id = %s" in sql:
            return [(uuid.UUID(cid), "side", "Vim 调研")]
        if "FROM messages" in sql and "ORDER BY created_at ASC" in sql:
            return [(uuid.UUID(mid), "user", "怎么配置 LazyVim？", now_dt)]
        if "FROM messages m" in sql:
            return [(uuid.UUID(mid), uuid.UUID(cid), "side", "Vim 调研", "user", "LazyVim 快捷键", now_dt)]
        return []

    pool = FakePGPool(responder=responder)
    main_tools = {t.name: t for t in get_builtin_tools(include_cross_chat=True)}
    assert "search_chat_history" in main_tools
    assert "read_conversation_history" in main_tools

    cfg = {"configurable": {"pool": pool, "user_id": uid, "conversation_id": cid}}
    search_out = await main_tools["search_chat_history"].ainvoke({"query": "LazyVim"}, config=cfg)
    assert "Vim 调研" in search_out
    assert any("c.user_id = %s" in sql and params[0] == uuid.UUID(uid) for sql, params in pool.queries)

    read_out = await main_tools["read_conversation_history"].ainvoke({"conversation_id": cid}, config=cfg)
    assert "怎么配置 LazyVim" in read_out
    assert any("WHERE id = %s AND user_id = %s" in sql and params[1] == uuid.UUID(uid) for sql, params in pool.queries)


@pytest.mark.asyncio
async def test_subgraph_emits_tool_events_to_runner_stream(monkeypatch):
    import app.graph.subgraphs as sg

    redis = FakeRedis()
    checkpointer = InMemorySaver()
    scripted = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_sub_ws",
                        "name": "delegate_subtask",
                        "args": {"role": "researcher", "task": "搜索最新状态"},
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_ws_inner",
                        "name": "web_search",
                        "args": {"query": "whitz status"},
                    }
                ],
            ),
            AIMessage(content="子智能体检索完成。"),
            AIMessage(content="主智能体已整合结果。"),
        ]
    )
    fake_router = FakeRouter(scripted)
    monkeypatch.setattr(runner, "ModelRouter", lambda *a, **kw: fake_router)
    monkeypatch.setattr(sg, "ModelRouter", lambda *a, **kw: fake_router)

    class FakeSearchTool:
        name = "web_search"
        description = "search"

        async def ainvoke(self, args, config=None):
            return json.dumps({"ok": True, "provider": "tavily", "result_count": 1, "results": [{"title": "OK"}]})

    monkeypatch.setattr(sg, "_select_subagent_tools", lambda role, config: [FakeSearchTool()])

    run_id = uuid.uuid4().hex
    meta = await runner.execute_run(
        run_id,
        {
            "thread_id": "thread-sub-tool",
            "conversation_id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "input": "研究一下状态",
            "memory_enabled": False,
        },
        redis=redis,
        checkpointer=checkpointer,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert meta["status"] == "completed"
    completed_tools = [
        json.loads(fields["data"])["tool"]
        for _, fields in redis.streams[runner.events_key(run_id)]
        if fields["event"] == "tool.completed"
    ]
    assert "web_search" in completed_tools
    assert "delegate_subtask" in completed_tools


@pytest.mark.asyncio
async def test_runtime_config_scales_recursion_and_tool_limits():
    cfg = await runner._build_runtime_config(
        {"conversation_id": "conv-1", "max_tool_iterations": 200},
        run_id="run-pro",
        redis=FakeRedis(),
        pool=None,
        store=None,
        settings=AgentSettings(internal_mcp_base_url=""),
    )
    assert cfg["configurable"]["max_tool_iterations"] == 200
    assert cfg["configurable"]["max_subagent_iterations"] == 25
    assert cfg["recursion_limit"] >= 600
