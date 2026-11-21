from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import AgentSettings
from app.tools.builtin_tools import (
    memory_propose,
    memory_search,
    rag_search_workspace,
    react_to_user_message,
    skill_view,
    todo_list,
    web_extract,
)
from app.tools.sandbox import (
    DisabledSandboxExecutor,
    DockerSandboxExecutor,
    E2BSandboxExecutor,
    get_sandbox_executor,
)


@pytest.mark.asyncio
async def test_sandbox_executors_and_docker_hardening():
    disabled = get_sandbox_executor(AgentSettings(sandbox_mode="disabled"))
    assert isinstance(disabled, DisabledSandboxExecutor)
    res_dis = await disabled.execute("print(1)")
    assert res_dis.exit_code == 1
    assert res_dis.mode == "disabled"

    e2b = get_sandbox_executor(AgentSettings(sandbox_mode="e2b", e2b_api_key=""))
    assert isinstance(e2b, E2BSandboxExecutor)
    res_e2b = await e2b.execute("print(1)")
    assert res_e2b.exit_code == 1
    assert "E2B_API_KEY" in (res_e2b.error or "")

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.side_effect = [b"42\n", b""]
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    with patch("app.tools.sandbox.docker.from_env", return_value=mock_client):
        executor = DockerSandboxExecutor()
        res_doc = await executor.execute("print(42)", language="python", timeout_seconds=10)

    assert res_doc.exit_code == 0
    assert res_doc.stdout.strip() == "42"
    run_kwargs = mock_client.containers.run.call_args.kwargs
    assert run_kwargs["network_disabled"] is True
    assert run_kwargs["read_only"] is True
    assert run_kwargs["mem_limit"] == "256m"
    assert run_kwargs["nano_cpus"] == 500_000_000
    assert run_kwargs["pids_limit"] == 64
    assert run_kwargs["cap_drop"] == ["ALL"]
    mock_container.remove.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_builtin_tools_and_ssrf_guard():
    # web_extract SSRF protection
    ssrf_res = json.loads(await web_extract.ainvoke({"url": "http://127.0.0.1:8000/secret"}))
    assert "error" in ssrf_res

    # todo_list normalization
    plan_res = json.loads(
        await todo_list.ainvoke(
            {"items": [{"content": "Step 1", "status": "in_progress"}, {"title": "Step 2"}]}
        )
    )
    assert len(plan_res["items"]) == 2
    assert plan_res["items"][0]["status"] == "in_progress"
    assert plan_res["items"][1]["status"] == "pending"

    # skill_view from config catalog
    cfg = {
        "configurable": {
            "skills_catalog": {
                "data-analyst": {
                    "name": "data-analyst",
                    "description": "Analyze CSV/XLSX files",
                    "content": "# Data Analyst\nRead schema first.",
                }
            }
        }
    }
    sk_res = json.loads(await skill_view.ainvoke({"name": "data-analyst"}, config=cfg))
    assert "Read schema first." in sk_res["content"]

    # rag_search_workspace + memory_search/propose delegation
    fake_retriever = SimpleNamespace()

    async def fake_rag(**kwargs):
        return [{"chunk_id": "1", "filename": "doc.txt", "content": "matched"}]

    fake_retriever.search = fake_rag

    fake_memory = SimpleNamespace()

    async def fake_mem_search(**kwargs):
        return [{"id": "m1", "content": "Likes dark mode"}]

    async def fake_mem_propose(**kwargs):
        return {"status": "pending_confirmation", "proposal_id": "p1"}

    fake_memory.search = fake_mem_search
    fake_memory.propose = fake_mem_propose

    run_cfg = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "c1",
            "agent_namespace": "ns1",
            "memory_enabled": True,
            "memory_require_confirm": True,
            "hybrid_retriever": fake_retriever,
            "memory_manager": fake_memory,
        }
    }
    rag_out = json.loads(await rag_search_workspace.ainvoke({"query": "matched"}, config=run_cfg))
    assert rag_out["count"] == 1
    mem_s_out = json.loads(await memory_search.ainvoke({"query": "dark"}, config=run_cfg))
    assert mem_s_out["count"] == 1
    mem_p_out = json.loads(await memory_propose.ainvoke({"content": "Uses Vim"}, config=run_cfg))
    assert mem_p_out["status"] == "pending_confirmation"


@pytest.mark.asyncio
async def test_react_to_user_message_positive_only():
    emitted: list[dict] = []
    with patch("langgraph.config.get_stream_writer", return_value=lambda ev: emitted.append(ev)):
        ok_res = json.loads(
            await react_to_user_message.ainvoke(
                {"reaction": "love", "note": "思路很清晰"},
                config={"configurable": {"ai_reactions_enabled": True}},
            )
        )
        assert ok_res["ok"] is True
        assert ok_res["reaction"] == "love"
        assert emitted == [
            {
                "type": "message.reaction",
                "author_type": "assistant",
                "reaction": "love",
                "note": "思路很清晰",
            }
        ]

        disabled_res = json.loads(
            await react_to_user_message.ainvoke(
                {"reaction": "like"},
                config={"configurable": {"ai_reactions_enabled": False}},
            )
        )
        assert disabled_res["ok"] is False
        assert disabled_res["reason"] == "ai_reactions_disabled"

    # Negative reactions must be rejected at schema/runtime level
    with pytest.raises(Exception):
        await react_to_user_message.ainvoke(
            {"reaction": "dislike"},
            config={"configurable": {"ai_reactions_enabled": True}},
        )
