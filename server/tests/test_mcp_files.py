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
        "Authorization": f"Bearer {u1.agent_api_key}",
        "X-Whitz-Namespace": u1.agent_namespace,
    }

    # Wrong token fails
    bad = await client.post(
        "/api/internal/mcp/files",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": "Bearer wrong", "X-Whitz-Profile": u1.agent_namespace},
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
    assert set(tool_names) == {
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_files",
        "write_workspace_file",
        "edit_workspace_file",
    }

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
        headers={"Authorization": f"Bearer {u2.agent_api_key}", "X-Whitz-Profile": u2.agent_namespace},
    )
    assert denied.json()["result"]["isError"] is True

    # Global file from another conversation is visible when include_global=True and readable/searchable
    other_conv_resp = await client.post(
        "/api/conversations",
        json={"title": "Global Source"},
        headers=auth_header(u1_auth["access_token"]),
    )
    other_conv_id = other_conv_resp.json()["id"]
    global_id = uuid.uuid4()
    db.add(
        ConversationFile(
            id=global_id,
            conversation_id=uuid.UUID(other_conv_id),
            user_id=u1.id,
            filename="shared.md",
            ext=".md",
            mime_type="text/markdown",
            category="document",
            size_bytes=20,
            storage_key=f"whitz/uploads/{u1.id}/{other_conv_id}/{global_id}/shared.md",
            status="ready",
            is_global=True,
        )
    )
    await db.commit()

    listed_global = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "list_workspace_files", "arguments": {"conversation_id": conv_id}},
        },
        headers=mcp_headers,
    )
    global_files = json.loads(listed_global.json()["result"]["content"][0]["text"])["files"]
    assert len(global_files) == 2
    assert {f["scope"] for f in global_files} == {"conversation", "library"}

    # write_workspace_file creates assistant artifact in COS + DB
    written_objects: dict[str, bytes] = {}

    async def _fake_put_bytes(key: str, data: bytes, content_type: str, settings=None) -> str:
        written_objects[key] = data
        return "etag-written"

    monkeypatch.setattr(cos, "put_object_bytes", _fake_put_bytes)

    write_resp = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "write_workspace_file",
                "arguments": {
                    "conversation_id": conv_id,
                    "filename": "report.html",
                    "content": "<h1>Report</h1>",
                },
            },
        },
        headers=mcp_headers,
    )
    write_payload = json.loads(write_resp.json()["result"]["content"][0]["text"])
    assert write_payload["status"] == "created"
    assert write_payload["source"] == "assistant"
    assert len(written_objects) == 1
    created_row = await db.get(ConversationFile, uuid.UUID(write_payload["file_id"]))
    assert created_row is not None and created_row.source == "assistant"

    # Reject disallowed binary/executable extensions
    bad_write = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "write_workspace_file",
                "arguments": {"conversation_id": conv_id, "filename": "bin.exe", "content": "x"},
            },
        },
        headers=mcp_headers,
    )
    assert bad_write.json()["result"]["isError"] is True

    # edit_workspace_file: targeted text replacement & line-range patch
    async def _fake_get_written(key: str, *, max_bytes: int, settings=None) -> bytes:
        return written_objects.get(key, b"line1\nline2\nline3")

    monkeypatch.setattr(cos, "get_object_bytes", _fake_get_written)
    edit_resp = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "edit_workspace_file",
                "arguments": {
                    "conversation_id": conv_id,
                    "file_id": write_payload["file_id"],
                    "old_text": "<h1>Report</h1>",
                    "new_text": "<h1>Q3 Report</h1>\n<p>Updated</p>",
                },
            },
        },
        headers=mcp_headers,
    )
    edit_payload = json.loads(edit_resp.json()["result"]["content"][0]["text"])
    assert edit_payload["status"] == "edited"
    assert edit_payload["lines_after"] == 2
    assert b"<h1>Q3 Report</h1>" in written_objects[created_row.storage_key]

    # User-side create text file, update content, inline rename, and scope=all list
    user_hdr = auth_header(u1_auth["access_token"])
    create_resp = await client.post(
        f"/api/conversations/{conv_id}/files/text",
        json={"filename": "metrics.csv", "content": "name,val\nA,1\n"},
        headers=user_hdr,
    )
    assert create_resp.status_code == 201
    csv_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/conversations/{conv_id}/files/{csv_id}/content",
        json={"content": "name,val\nA,2\nB,3\n"},
        headers=user_hdr,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["size_bytes"] == len("name,val\nA,2\nB,3\n".encode("utf-8"))

    rename_resp = await client.patch(
        f"/api/conversations/{conv_id}/files/{csv_id}",
        json={"filename": "q3_metrics.csv"},
        headers=user_hdr,
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["filename"] == "q3_metrics.csv"

    all_list = await client.get(
        f"/api/conversations/{conv_id}/files?scope=all",
        headers=user_hdr,
    )
    assert all_list.status_code == 200
    items = all_list.json()
    assert any(item["filename"] == "q3_metrics.csv" and item["conversation_title"] == "MCP Workspace" for item in items)

    get_settings.cache_clear()
