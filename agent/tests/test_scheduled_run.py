from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import AgentSettings
from app.core.models import ModelRouter
from app.graph.builder import build_agent_graph


class CapturingChatModel(BaseChatModel):
    responses: list[AIMessage]
    bound_tool_names: list[str] = []
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "capturing"

    def bind_tools(self, tools: Any, **kwargs: Any):
        self.bound_tool_names = [t.name for t in tools]
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        idx = min(self.cursor, len(self.responses) - 1)
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages)


class FakeRouter(ModelRouter):
    def __init__(self, model: CapturingChatModel) -> None:
        super().__init__(
            settings=AgentSettings(
                llm_base_url="https://mock.local/v1",
                llm_api_key="sk-mock",
                llm_model="mock-gpt",
                llm_adaptive_probe_enabled=False,
            )
        )
        self.model = model

    def build_chat_model(self, ep, **kwargs):
        return self.model


@pytest.mark.asyncio
async def test_unattended_mode_omits_hitl_tools_and_blocks_hitl_gate():
    checkpointer = InMemorySaver()
    # Even if a model hallucinates a call to clarify, hitl_gate must NOT interrupt when allow_hitl=False.
    model = CapturingChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-clarify-1",
                        "name": "clarify",
                        "args": {"question": "请问需要哪一天的？"},
                    }
                ],
            ),
            AIMessage(content="已完成后台定时汇总任务。"),
        ]
    )
    router = FakeRouter(model)
    graph = build_agent_graph(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": f"sched-{uuid.uuid4().hex[:8]}",
            "user_id": "u1",
            "conversation_id": "c1",
            "allow_hitl": False,
            "model_router": router,
        }
    }
    res = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "生成日报"}],
            "allow_hitl": False,
        },
        config=config,
    )
    assert "clarify" not in model.bound_tool_names
    assert "execute_code" not in model.bound_tool_names
    assert "react_to_user_message" not in model.bound_tool_names
    assert res["final_output"] == "已完成后台定时汇总任务。"
    tool_msgs = [m for m in res["messages"] if getattr(m, "name", None) == "clarify"]
    assert len(tool_msgs) == 1
    parsed = json.loads(tool_msgs[0].content)
    assert parsed["status"] == "blocked"
