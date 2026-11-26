from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import agent as agent_routes
from app.api.routes import search as search_routes
from app.services.agent_client import AgentError


def test_search_helpers_escape_like_and_build_snippet():
    assert search_routes._escape_like("100%_a\\b") == "100\\%\\_a\\\\b"

    long_text = "prefix " * 20 + "TARGET_KEY" + " suffix" * 20
    snippet = search_routes._build_snippet(long_text, "target_key", before=10, after=20)
    assert "TARGET_KEY" in snippet
    assert snippet.startswith("…") and snippet.endswith("…")

    no_match = search_routes._build_snippet("alpha beta gamma", "missing", before=5, after=5)
    assert no_match == "alpha beta…"
    assert search_routes._build_snippet("   ", "x") == ""


@pytest.mark.asyncio
async def test_unified_search_blank_query_and_rate_limit(monkeypatch):
    user = SimpleNamespace(id="u-1", assistant_name="Whitz")
    empty_res = await search_routes.unified_semantic_search(q="   ", sources="all", limit=10, user=user, db=None)
    assert empty_res == {"query": "", "files": [], "memories": [], "chats": [], "total": 0}

    async def deny(_key: str) -> bool:
        return False

    monkeypatch.setattr(search_routes.unified_search_limiter, "allow", deny)
    with pytest.raises(HTTPException) as exc:
        await search_routes.unified_semantic_search(q="hello", sources="all", limit=10, user=user, db=None)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_agent_status_and_topology_fallback(monkeypatch):
    class DownAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        async def health_info(self):
            raise AgentError(503, "agent down")

        async def topology(self):
            raise AgentError(503, "agent down")

        async def aclose(self):
            pass

    monkeypatch.setattr(agent_routes, "AgentClient", DownAgent)
    user = SimpleNamespace(agent_namespace="ns", agent_api_key="k")

    status_out = await agent_routes.agent_status(user=user)
    assert status_out == {"ready": False, "status": "error", "detail": "agent down"}

    topo_out = await agent_routes.agent_topology(user=user)
    assert topo_out["entry"] == "context_loader"
    assert len(topo_out["nodes"]) >= 5
