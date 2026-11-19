from __future__ import annotations

from typing import Any

GRAPH_NODES: list[dict[str, Any]] = [
    {
        "id": "context_loader",
        "label": "上下文装载",
        "type": "loader",
        "kind": "loader",
        "description": "注入人设、授权用户画像、附件元数据列表与技能摘要（不预灌全量文档）",
    },
    {
        "id": "agent",
        "label": "主控智能体",
        "type": "agent",
        "kind": "agent",
        "description": "Agent-First 自主决策：直接回答、调用工具、人工确认或委派子智能体",
    },
    {
        "id": "tools",
        "label": "工具执行",
        "type": "tools",
        "kind": "tools",
        "description": "Hybrid RAG、语义记忆、Web 搜索、MCP 文件/技能、任务规划",
    },
    {
        "id": "hitl_gate",
        "label": "人工确认门",
        "type": "interrupt",
        "kind": "interrupt",
        "description": "execute_code 审批与 clarify 追问的 LangGraph Checkpoint 中断恢复",
    },
    {
        "id": "subagent",
        "label": "子智能体协作",
        "type": "subgraph",
        "kind": "subgraph",
        "description": "Researcher（深度检索）与 Coder（分析/沙箱编程）子图",
    },
    {
        "id": "memory_extractor",
        "label": "记忆沉淀",
        "type": "memory",
        "kind": "memory",
        "description": "提炼长期记忆并按设置直写或提交待确认提案",
    },
]

GRAPH_EDGES: list[dict[str, Any]] = [
    {"source": "__start__", "target": "context_loader", "conditional": False, "label": "start"},
    {"source": "context_loader", "target": "agent", "conditional": False, "label": "ready"},
    {"source": "agent", "target": "tools", "conditional": True, "label": "tool_calls"},
    {"source": "agent", "target": "hitl_gate", "conditional": True, "label": "hitl"},
    {"source": "agent", "target": "subagent", "conditional": True, "label": "delegate"},
    {"source": "agent", "target": "memory_extractor", "conditional": True, "label": "memory_enabled"},
    {"source": "agent", "target": "__end__", "conditional": True, "label": "finish"},
    {"source": "tools", "target": "agent", "conditional": False, "label": "observe"},
    {"source": "hitl_gate", "target": "agent", "conditional": False, "label": "resume"},
    {"source": "subagent", "target": "agent", "conditional": False, "label": "report"},
    {"source": "memory_extractor", "target": "__end__", "conditional": False, "label": "done"},
]

SUBGRAPHS: list[dict[str, Any]] = [
    {
        "id": "researcher",
        "label": "Researcher 子图",
        "nodes": ["planner", "worker", "tools", "synthesizer"],
        "description": "多跳 Hybrid RAG、记忆检索与 Web 检索综合研究",
    },
    {
        "id": "coder",
        "label": "Coder 子图",
        "nodes": ["planner", "worker", "tools", "synthesizer"],
        "description": "文件读写、数据分析与沙箱代码执行（受 HITL 审批门保护）",
    },
]


def get_graph_topology() -> dict[str, Any]:
    return {
        "nodes": GRAPH_NODES,
        "edges": GRAPH_EDGES,
        "subgraphs": SUBGRAPHS,
        "entry": "context_loader",
    }
