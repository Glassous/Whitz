from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    run_id: str
    thread_id: str
    conversation_id: str
    conversation_kind: str
    assistant_name: str
    rolling_summary: str
    cross_chat_context: str
    user_id: str
    agent_namespace: str
    persona: str
    profile_context: str
    timezone: str
    instructions: str
    attachments: list[dict[str, Any]]
    skills: list[dict[str, Any]]
    requested_skills: list[str]
    memory_enabled: bool
    memory_require_confirm: bool
    allow_hitl: bool
    requested_route: str
    selected_route: str
    selected_model: str
    thinking_enabled: bool
    thinking_escalated: bool
    plan: dict[str, Any] | None
    tool_call_count: int
    max_tool_iterations: int
    usage: dict[str, int]
    subagent_outputs: Annotated[list[dict[str, Any]], operator.add]
    memory_extracted: bool
    final_output: str


class SubagentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    role: str
    task: str
    context: str
    result: str
    iterations: int
    usage: dict[str, int]
