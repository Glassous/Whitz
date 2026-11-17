import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import ConversationFile, User
from app.services import cos
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_mcp_files_auth_and_tools(client, register, db, monkeypatch):
    monkeypatch.setenv("COS_SECRET_ID", "AKIDtest")
    monkeypatch.setenv("COS_SECRET_KEY", "SecretTest")
    monkeypatch.setenv("COS_BUCKET", "whitz-1250000000")
    monkeypatch.setenv("COS_REGION", "ap-shanghai")
    get_settings.cache_clear()

    u1_auth = await register(email="mcp1@test.local", display_name="MCP1")
    u2_auth = await register(email="mcp2@test.local", display_name="MCP2")

    u1 = (await db.execute(select(User).where(User.email == "mcp1@test.local"))).scalar_one()

    conv_resp = await client.post(
        "/api/conversations",
        json={"title": "MCP Workspace"},
        headers=auth_header(u1_auth["access_token"]),
    )
    conv_id = conv_resp.json()["id"]

    file_id = uuid.uuid4()
    db.add(
        ConversationFile(
            id=file_id,
            conversation_id=uuid.UUID(conv_id),
            user_id=u1.id,
            filename="guide.txt",
            ext=".txt",
            mime_type="text/plain",
            category="document",
            size_bytes=30,
            storage_key=f"whitz/uploads/{u1.id}/{conv_id}/{file_id}/guide.txt",
            status="ready",
        )
    )
    await db.commit()

    async def _fake_get_bytes(key: str, *, max_bytes: int, settings=None) -> bytes:
        return "第一行介绍\n第二行关键指标: 99.5%\n第三行结束".encode("utf-8")

    monkeypatch.setattr(cos, "get_object_bytes", _fake_get_bytes)

    mcp_headers = {
        "Authorization": f"Bearer {u1.hermes_api_key}",
        "X-Whitz-Profile": u1.hermes_profile,
    }

    # Wrong token fails
    bad = await client.post(
        "/api/internal/mcp/files",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": "Bearer wrong", "X-Whitz-Profile": u1.hermes_profile},
    )
    assert bad.status_code == 401

    # Initialize
    init = await client.post(
        "/api/internal/mcp/files",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        headers=mcp_headers,
    )
    assert init.status_code == 200
    assert init.json()["result"]["serverInfo"]["name"] == "whitz-files"

    # Notification -> 202
    notif = await client.post(
        "/api/internal/mcp/files",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=mcp_headers,
    )
    assert notif.status_code == 202

    # List tools
    tools_resp = await client.post(
        "/api/internal/mcp/files",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=mcp_headers,
    )
    tool_names = [t["name"] for t in tools_resp.json()["result"]["tools"]]
    assert set(tool_names) == {"list_workspace_files", "read_workspace_file", "search_workspace_files"}

    # Call list_workspace_files
    listed = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_workspace_files", "arguments": {"conversation_id": conv_id}},
        },
        headers=mcp_headers,
    )
    listed_payload = json.loads(listed.json()["result"]["content"][0]["text"])
    assert listed_payload["count"] == 1
    assert listed_payload["files"][0]["filename"] == "guide.txt"

    # Call read_workspace_file
    read_resp = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "read_workspace_file",
                "arguments": {"conversation_id": conv_id, "file_id": str(file_id), "start_line": 1, "max_lines": 2},
            },
        },
        headers=mcp_headers,
    )
    read_payload = json.loads(read_resp.json()["result"]["content"][0]["text"])
    assert "第一行介绍" in read_payload["content"]
    assert read_payload["has_more"] is True

    # Call search_workspace_files
    search_resp = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "search_workspace_files",
                "arguments": {"conversation_id": conv_id, "query": "99.5%"},
            },
        },
        headers=mcp_headers,
    )
    search_payload = json.loads(search_resp.json()["result"]["content"][0]["text"])
    assert search_payload["matched_files"][0]["hits"][0]["location"] == "第 2 行"

    # Cross-user MCP call blocked
    u2 = (await db.execute(select(User).where(User.email == "mcp2@test.local"))).scalar_one()
    denied = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "list_workspace_files", "arguments": {"conversation_id": conv_id}},
        },
        headers={"Authorization": f"Bearer {u2.hermes_api_key}", "X-Whitz-Profile": u2.hermes_profile},
    )
    assert denied.json()["result"]["isError"] is True
    get_settings.cache_clear()
