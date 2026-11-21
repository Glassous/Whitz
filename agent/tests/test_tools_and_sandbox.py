from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import AgentSettings
from app.tools import parse_tool_error
from app.tools.builtin_tools import (
    get_builtin_tools,
    http_request,
    memory_propose,
    memory_search,
    rag_search_workspace,
    react_to_user_message,
    skill_view,
    todo_list,
    web_extract,
    web_search,
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


@pytest.mark.asyncio
async def test_http_request_curl_completeness_and_ssrf():
    tool_names = {t.name for t in get_builtin_tools()}
    assert "http_request" in tool_names

    # SSRF blocks loopback, IPv4-mapped IPv6, metadata IP, and non-HTTP schemes
    for bad_url in (
        "http://127.0.0.1:8000/secret",
        "http://[::ffff:127.0.0.1]/secret",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ):
        res = json.loads(await http_request.ainvoke({"url": bad_url}))
        assert res["ok"] is False
        assert "error" in res

    # Parameter validation
    conflict = json.loads(
        await http_request.ainvoke(
            {"url": "https://8.8.8.8/test", "method": "POST", "json_body": {"a": 1}, "body": "raw"}
        )
    )
    assert conflict["ok"] is False
    assert "json_body" in conflict["error"]

    bad_auth = json.loads(
        await http_request.ainvoke({"url": "https://8.8.8.8/test", "basic_auth": "onlyuser"})
    )
    assert bad_auth["ok"] is False
    assert "basic_auth" in bad_auth["error"]

    # Full curl-like POST JSON + headers + params + cookies + basic_auth via MockTransport
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/redirect-internal":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8000/admin"})
        if request.method == "HEAD":
            return httpx.Response(204, headers={"X-Head": "1"})
        return httpx.Response(
            201,
            headers={"X-Custom-Resp": "ok", "Set-Cookie": "sid=abc123; Path=/"},
            json={"received": json.loads(request.content.decode("utf-8")) if request.content else None},
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    async def fake_is_public(raw_url: str) -> bool:
        return raw_url.startswith("https://api.example.com")

    with (
        patch("app.tools.builtin_tools._is_public_url_async", side_effect=fake_is_public),
        patch("app.tools.builtin_tools.httpx.AsyncClient", side_effect=client_factory),
    ):
        post_res = json.loads(
            await http_request.ainvoke(
                {
                    "url": "https://api.example.com/v1/items",
                    "method": "POST",
                    "headers": {"X-Trace": "t-1", "User-Agent": "CustomCurl/1.0"},
                    "params": {"dry_run": "true"},
                    "json_body": {"name": "whitz"},
                    "cookies": {"session": "xyz"},
                    "basic_auth": "alice:secret",
                }
            )
        )
        assert post_res["ok"] is True
        assert post_res["status_code"] == 201
        assert post_res["headers"]["x-custom-resp"] == "ok"
        assert post_res["cookies"]["sid"] == "abc123"
        assert json.loads(post_res["body"]) == {"received": {"name": "whitz"}}
        req = captured[0]
        assert req.method == "POST"
        assert req.url.params["dry_run"] == "true"
        assert req.headers["user-agent"] == "CustomCurl/1.0"
        assert req.headers["x-trace"] == "t-1"
        assert req.headers["authorization"].startswith("Basic ")
        assert "session=xyz" in req.headers["cookie"]

        # HEAD request returns empty body
        head_res = json.loads(
            await http_request.ainvoke({"url": "https://api.example.com/ping", "method": "HEAD"})
        )
        assert head_res["ok"] is True
        assert head_res["status_code"] == 204
        assert head_res["body"] == ""

        # Redirect to internal IP must be blocked by _ssrf_request_hook
        redir_res = json.loads(
            await http_request.ainvoke(
                {"url": "https://api.example.com/redirect-internal", "follow_redirects": True}
            )
        )
        assert redir_res["ok"] is False
        assert "error" in redir_res


@pytest.mark.asyncio
async def test_web_search_fallback_metadata_and_parse_tool_error():
    # parse_tool_error handles http_request 4xx/5xx, denied execute_code, non-zero exit_code, and wrapped output
    assert parse_tool_error(json.dumps({"ok": False, "status_code": 404, "reason_phrase": "Not Found"}), None) == "HTTP 404 Not Found"
    assert parse_tool_error(json.dumps({"ok": True, "status_code": 200}), None) is None
    assert parse_tool_error(json.dumps({"status": "denied", "message": "用户拒绝了代码执行审批。"}), None) == "用户拒绝了代码执行审批。"
    assert parse_tool_error(json.dumps({"exit_code": 2, "stderr": "curl: (6) Could not resolve host"}), None) == "curl: (6) Could not resolve host"
    assert parse_tool_error("<untrusted_tool_result>{\"provider\":\"none\",\"error\":\"timeout\"}</untrusted_tool_result>", None) == "timeout"

    def handler_fallback(request: httpx.Request) -> httpx.Response:
        if "tavily.com" in str(request.url):
            return httpx.Response(503, json={"detail": "upstream busy"})
        if "duckduckgo.com" in str(request.url):
            return httpx.Response(200, json={"AbstractText": "Whitz docs", "Heading": "Whitz", "AbstractURL": "https://whitz.test"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler_fallback)
    real_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    with (
        patch("app.tools.builtin_tools.get_settings", return_value=AgentSettings(search_api_key="tvly-test")),
        patch("app.tools.builtin_tools.httpx.AsyncClient", side_effect=client_factory),
    ):
        res = json.loads(await web_search.ainvoke({"query": "Whitz", "max_results": 3}))
        assert res["ok"] is True
        assert res["provider"] == "duckduckgo"
        assert res["fallback_from"] == "tavily"
        assert res["result_count"] == 1
