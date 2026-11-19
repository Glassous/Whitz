from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.services.agent_client import AgentClient, AgentError

router = APIRouter(prefix="/api/agent", tags=["agent"])

_DEFAULT_TOPOLOGY = {
    "entry": "context_loader",
    "nodes": [
        {"id": "context_loader", "label": "上下文装载", "type": "loader", "description": "注入人设、授权用户画像与附件索引"},
        {"id": "agent", "label": "主控智能体", "type": "agent", "description": "自主决策：直接回答、调用工具或委派子智能体"},
        {"id": "tools", "label": "工具执行", "type": "tools", "description": "Hybrid RAG、语义记忆、Web 搜索与 MCP 工具"},
        {"id": "hitl_gate", "label": "人工确认门", "type": "interrupt", "description": "execute_code 审批与 clarify 追问中断恢复"},
        {"id": "subagent", "label": "子智能体协作", "type": "subgraph", "description": "Researcher 与 Coder 子图委派"},
        {"id": "memory_extractor", "label": "记忆沉淀", "type": "memory", "description": "提炼长期记忆提案"},
    ],
    "edges": [
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
    ],
}


@router.get("/status")
async def agent_status(user: User = Depends(get_current_user)) -> dict:
    settings = get_settings()
    client = AgentClient(user.agent_namespace, user.agent_api_key)
    try:
        info = await client.health_info()
        if not info.get("ready"):
            return {"ready": False, "status": "warming_up"}
        return {
            "ready": True,
            "status": "online",
            "engine": "langgraph",
            "model": settings.llm_model or None,
            "sandbox_mode": info.get("sandbox_mode") or settings.sandbox_mode,
        }
    except AgentError as exc:
        return {"ready": False, "status": "error", "detail": exc.detail}
    finally:
        await client.aclose()


@router.get("/topology")
async def agent_topology(user: User = Depends(get_current_user)) -> dict:
    client = AgentClient(user.agent_namespace, user.agent_api_key)
    try:
        return await client.topology()
    except AgentError:
        return _DEFAULT_TOPOLOGY
    finally:
        await client.aclose()
