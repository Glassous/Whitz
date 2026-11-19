import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes import agent as agent_routes
from app.api.routes import chat as chat_routes
from app.core.config import get_settings
from app.db.models import (
    Conversation,
    ConversationFile,
    CreditLedger,
    MemoryPendingProposal,
    Message,
    SkillPendingProposal,
    User,
)
from app.services import chat_stream, chat_tickets
from tests.conftest import auth_header


def _parse_sse_events(body_text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    cur_event = "message"
    data_lines: list[str] = []
    for raw_line in body_text.splitlines():
        line = raw_line.rstrip("\r")
        if line == "":
            if data_lines:
                raw_data = "\n".join(data_lines)
                try:
                    parsed = json.loads(raw_data)
                except json.JSONDecodeError:
                    parsed = {"raw": raw_data}
                events.append((cur_event, parsed))
                cur_event = "message"
                data_lines = []
            continue
        if line.startswith("event:"):
            cur_event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        raw_data = "\n".join(data_lines)
        try:
            parsed = json.loads(raw_data)
        except json.JSONDecodeError:
            parsed = {"raw": raw_data}
        events.append((cur_event, parsed))
    return events


async def _issue_send_headers(client, token: str, conv_id: str) -> dict[str, str]:
    nonce = uuid.uuid4().hex[:16]
    resp = await client.post(
        f"/api/conversations/{conv_id}/tickets",
        json={"action": "send", "nonce": nonce},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    ticket = resp.json()["ticket"]
    return {
        **auth_header(token),
        chat_tickets.TICKET_HEADER: ticket,
        chat_tickets.NONCE_HEADER: nonce,
    }


async def test_conversation_pinning_and_ordering(register, client, db):
    reg = await register(email="pin@test.local", display_name="PinUser")
    headers = auth_header(reg["access_token"])

    c1 = (await client.post("/api/conversations", json={"title": "普通会话1"}, headers=headers)).json()
    c2 = (await client.post("/api/conversations", json={"title": "普通会话2"}, headers=headers)).json()
    c3 = (await client.post("/api/conversations", json={"title": "将置顶会话"}, headers=headers)).json()

    now = datetime.now(timezone.utc)
    conv1 = await db.get(Conversation, uuid.UUID(c1["id"]))
    conv2 = await db.get(Conversation, uuid.UUID(c2["id"]))
    conv3 = await db.get(Conversation, uuid.UUID(c3["id"]))
    conv1.last_message_at = now - timedelta(minutes=2)
    conv2.last_message_at = now - timedelta(minutes=1)
    conv3.last_message_at = now - timedelta(minutes=5)
    await db.commit()

    pin_resp = await client.patch(
        f"/api/conversations/{c3['id']}",
        json={"is_pinned": True},
        headers=headers,
    )
    assert pin_resp.status_code == 200
    assert pin_resp.json()["is_pinned"] is True
    assert pin_resp.json()["pinned_at"] is not None
    assert pin_resp.json()["title"] == "将置顶会话"

    pin_c1 = await client.patch(
        f"/api/conversations/{c1['id']}",
        json={"is_pinned": True},
        headers=headers,
    )
    assert pin_c1.status_code == 200

    listed = (await client.get("/api/conversations", headers=headers)).json()
    assert [item["id"] for item in listed] == [c1["id"], c3["id"], c2["id"]]

    unpin_c1 = await client.patch(
        f"/api/conversations/{c1['id']}",
        json={"is_pinned": False},
        headers=headers,
    )
    assert unpin_c1.status_code == 200
    assert unpin_c1.json()["is_pinned"] is False
    assert unpin_c1.json()["pinned_at"] is None

    listed2 = (await client.get("/api/conversations", headers=headers)).json()
    assert [item["id"] for item in listed2] == [c3["id"], c2["id"], c1["id"]]


async def test_send_message_injects_profile_skills_global_file_artifacts_graph_and_pending_events(
    register, client, db, engine, monkeypatch
):
    monkeypatch.setenv("COS_SECRET_ID", "AKIDtest")
    monkeypatch.setenv("COS_SECRET_KEY", "SecretTest")
    monkeypatch.setenv("COS_BUCKET", "whitz-1250000000")
    monkeypatch.setenv("COS_REGION", "ap-shanghai")
    get_settings.cache_clear()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(chat_stream, "SessionLocal", session_factory)

    reg = await register(email="stream@test.local", display_name="StreamUser")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "stream@test.local"))).scalar_one()

    await client.patch("/api/users/me", json={"occupation": "算法工程师"}, headers=headers)
    ctx_resp = await client.patch(
        "/api/users/me/profile-context",
        json={"enabled": True, "consent": True},
        headers=headers,
    )
    assert ctx_resp.status_code == 200

    sk_resp = await client.post(
        "/api/skills",
        json={"name": "viz-helper", "description": "生成可视化网页", "content": "# Viz"},
        headers=headers,
    )
    assert sk_resp.status_code == 201

    other_conv = (await client.post("/api/conversations", json={"title": "资料源"}, headers=headers)).json()
    global_file_id = uuid.uuid4()
    db.add(
        ConversationFile(
            id=global_file_id,
            conversation_id=uuid.UUID(other_conv["id"]),
            user_id=user.id,
            filename="company-spec.md",
            ext=".md",
            mime_type="text/markdown",
            category="document",
            size_bytes=50,
            storage_key=f"whitz/uploads/{user.id}/{other_conv['id']}/{global_file_id}/company-spec.md",
            status="ready",
            is_global=True,
        )
    )
    await db.commit()

    conv = (await client.post("/api/conversations", json={"title": "主任务"}, headers=headers)).json()
    conv_id = conv["id"]

    recorded_runs: list[dict] = []
    artifact_id = uuid.uuid4()

    class MockStreamAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            self.namespace = namespace or ""

        async def health(self) -> bool:
            return True

        async def create_run(self, **kwargs) -> dict:
            recorded_runs.append(kwargs)
            return {"run_id": "run-art-1"}

        async def stream_events(self, run_id: str, *, last_event_id: str | None = None):
            yield (
                "graph.node",
                {
                    "node": "agent",
                    "status": "running",
                    "label": "主控智能体",
                    "route": "reasoning",
                    "model": "test-reasoning-model",
                },
            )
            yield (
                "tool.started",
                {
                    "tool": "write_workspace_file",
                    "call_id": "call-write-1",
                    "args": {"filename": "report.html"},
                    "preview": {"filename": "report.html"},
                },
            )
            async with session_factory() as inner_db:
                inner_db.add(
                    ConversationFile(
                        id=artifact_id,
                        conversation_id=uuid.UUID(conv_id),
                        user_id=user.id,
                        filename="report.html",
                        ext=".html",
                        mime_type="text/html",
                        category="code",
                        size_bytes=200,
                        storage_key=f"whitz/uploads/{user.id}/{conv_id}/{artifact_id}/report.html",
                        status="ready",
                        source="assistant",
                    )
                )
                inner_db.add(
                    MemoryPendingProposal(
                        user_id=user.id,
                        conversation_id=uuid.UUID(conv_id),
                        target="user",
                        action="add",
                        content="偏好 HTML 报表",
                    )
                )
                inner_db.add(
                    SkillPendingProposal(
                        user_id=user.id,
                        conversation_id=uuid.UUID(conv_id),
                        name="html-pro",
                        description="HTML",
                        content="# HTML",
                    )
                )
                await inner_db.commit()

            yield (
                "tool.completed",
                {
                    "tool": "write_workspace_file",
                    "call_id": "call-write-1",
                    "duration_ms": 45.2,
                    "preview": json.dumps({"status": "created", "file_id": str(artifact_id), "filename": "report.html"}),
                },
            )
            yield ("message.delta", {"delta": "报告已生成。"})
            yield ("run.completed", {"output": "报告已生成。", "usage": {"total_tokens": 5000}})

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(chat_routes, "AgentClient", MockStreamAgent)
    monkeypatch.setattr(chat_stream, "AgentClient", MockStreamAgent)

    send_headers = await _issue_send_headers(client, reg["access_token"], conv_id)
    resp = await client.post(
        f"/api/conversations/{conv_id}/messages",
        json={
            "content": "结合公司规范生成可视化报告",
            "file_ids": [str(global_file_id)],
            "skill_names": ["viz-helper"],
            "model_route": "reasoning",
        },
        headers=send_headers,
    )
    assert resp.status_code == 200, resp.text
    events = _parse_sse_events(resp.text)
    ev_names = [name for name, _ in events]
    assert "graph.node" in ev_names
    graph_ev = next(data for name, data in events if name == "graph.node")
    assert graph_ev["node"] == "agent"
    assert graph_ev["route"] == "reasoning"

    assert "workspace.file_created" in ev_names
    file_ev = next(data for name, data in events if name == "workspace.file_created")
    assert file_ev["id"] == str(artifact_id)
    assert file_ev["file_id"] == str(artifact_id)
    assert file_ev["file"]["id"] == str(artifact_id)
    assert file_ev["file"]["filename"] == "report.html"
    assert file_ev["file"]["source"] == "assistant"
    assert "memory.pending" in ev_names
    assert "skills.pending" in ev_names
    assert "run.completed" in ev_names
    completed_ev = next(data for name, data in events if name == "run.completed")
    assert completed_ev["artifacts"][0]["id"] == str(artifact_id)
    assert completed_ev["artifacts"][0]["file_id"] == str(artifact_id)

    assert len(recorded_runs) == 1
    assert recorded_runs[0]["model_route"] == "reasoning"
    inst = recorded_runs[0]["instructions"] or ""
    assert "算法工程师" in inst
    assert "viz-helper" in inst
    assert "company-spec.md" in inst
    assert "stream@test.local" not in inst

    detail = (await client.get(f"/api/conversations/{conv_id}", headers=headers)).json()
    msgs = detail["messages"]
    user_msg = next(m for m in msgs if m["role"] == "user")
    asst_msg = next(m for m in msgs if m["role"] == "assistant")
    assert user_msg["tool_payload"]["skills"] == ["viz-helper"]
    assert user_msg["tool_payload"]["attachments"][0]["id"] == str(global_file_id)
    assert asst_msg["tool_payload"]["artifacts"][0]["id"] == str(artifact_id)
    assert asst_msg["tool_payload"]["artifacts"][0]["file_id"] == str(artifact_id)
    assert asst_msg["tool_payload"]["artifacts"][0]["filename"] == "report.html"
    assert asst_msg["run_id"] == "run-art-1"
    get_settings.cache_clear()


async def test_artifact_id_contract_on_run_completed_and_reconnect_normalization(
    register, client, db, engine, monkeypatch
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(chat_stream, "SessionLocal", session_factory)

    reg = await register(email="artid@test.local", display_name="ArtIdUser")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "artid@test.local"))).scalar_one()

    conv = (await client.post("/api/conversations", json={"title": "产物契约"}, headers=headers)).json()
    conv_id = conv["id"]
    artifact_id = uuid.uuid4()

    class MockLateArtifactAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            pass

        async def health(self) -> bool:
            return True

        async def create_run(self, **kwargs) -> dict:
            return {"run_id": "run-art-late"}

        async def stream_events(self, run_id: str, *, last_event_id: str | None = None):
            async with session_factory() as inner_db:
                inner_db.add(
                    ConversationFile(
                        id=artifact_id,
                        conversation_id=uuid.UUID(conv_id),
                        user_id=user.id,
                        filename="summary.md",
                        ext=".md",
                        mime_type="text/markdown",
                        category="document",
                        size_bytes=42,
                        storage_key=f"whitz/uploads/{user.id}/{conv_id}/{artifact_id}/summary.md",
                        status="ready",
                        source="assistant",
                    )
                )
                await inner_db.commit()
            yield ("message.delta", {"delta": "已完成。"})
            yield ("run.completed", {"output": "已完成。", "usage": {"total_tokens": 100}})

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(chat_routes, "AgentClient", MockLateArtifactAgent)
    monkeypatch.setattr(chat_stream, "AgentClient", MockLateArtifactAgent)

    send_headers = await _issue_send_headers(client, reg["access_token"], conv_id)
    resp = await client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"content": "生成 summary.md"},
        headers=send_headers,
    )
    assert resp.status_code == 200, resp.text
    events = _parse_sse_events(resp.text)
    file_ev = next(data for name, data in events if name == "workspace.file_created")
    completed_ev = next(data for name, data in events if name == "run.completed")

    assert file_ev["id"] == str(artifact_id)
    assert file_ev["file"]["id"] == str(artifact_id)
    assert completed_ev["artifacts"][0]["id"] == str(artifact_id)

    detail = (await client.get(f"/api/conversations/{conv_id}", headers=headers)).json()
    asst_msg = next(m for m in detail["messages"] if m["role"] == "assistant")
    assert asst_msg["tool_payload"]["artifacts"][0]["id"] == str(artifact_id)
    assert asst_msg["tool_payload"]["artifacts"][0]["message_id"] == asst_msg["id"]

    legacy_fid = str(uuid.uuid4())
    conv_obj = await db.get(Conversation, uuid.UUID(conv_id))
    legacy_msg = Message(
        conversation_id=uuid.UUID(conv_id),
        role="assistant",
        content="",
        status="streaming",
        tool_payload={"artifacts": [{"file_id": legacy_fid, "filename": "legacy.txt"}]},
    )
    pipeline = chat_stream.ChatPipeline(db, MockLateArtifactAgent("p", "k"), conv_obj, legacy_msg, "run-leg")
    assert pipeline.artifacts[0]["id"] == legacy_fid
    assert legacy_fid in pipeline.seen_artifact_ids


async def test_regenerate_and_edit_truncate_preserve_credits_and_rotate_thread(
    register, client, db, engine, monkeypatch
):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(chat_stream, "SessionLocal", session_factory)

    reg = await register(email="regen@test.local", display_name="RegenUser")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "regen@test.local"))).scalar_one()

    conv = (await client.post("/api/conversations", json={"title": "重构对话"}, headers=headers)).json()
    conv_id = conv["id"]

    t0 = datetime.now(timezone.utc) - timedelta(minutes=10)
    u1 = Message(conversation_id=uuid.UUID(conv_id), role="user", content="第一问", status="completed", created_at=t0)
    a1 = Message(
        conversation_id=uuid.UUID(conv_id),
        role="assistant",
        content="第一答",
        status="completed",
        run_id="run-1",
        created_at=t0 + timedelta(seconds=1),
    )
    u2 = Message(
        conversation_id=uuid.UUID(conv_id),
        role="user",
        content="第二问",
        status="completed",
        created_at=t0 + timedelta(seconds=2),
    )
    a2 = Message(
        conversation_id=uuid.UUID(conv_id),
        role="assistant",
        content="第二答（待重新生成）",
        status="completed",
        run_id="run-2",
        created_at=t0 + timedelta(seconds=3),
    )
    tool2 = Message(
        conversation_id=uuid.UUID(conv_id),
        role="tool",
        tool_name="web_search",
        status="completed",
        run_id="run-2",
        created_at=t0 + timedelta(seconds=4),
    )
    db.add_all([u1, a1, u2, a2, tool2])
    await db.commit()

    db.add(
        CreditLedger(
            user_id=user.id,
            tokens=-5000,
            kind="consume",
            tier="free",
            conversation_id=uuid.UUID(conv_id),
            message_id=a2.id,
        )
    )
    await db.commit()

    deleted_threads: list[str] = []
    run_calls: list[dict] = []

    class MockActionAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            pass

        async def health(self) -> bool:
            return True

        async def delete_thread(self, thread_id: str) -> None:
            deleted_threads.append(thread_id)

        async def create_run(self, **kwargs) -> dict:
            run_calls.append(kwargs)
            return {"run_id": f"run-new-{len(run_calls)}"}

        async def stream_events(self, run_id: str, *, last_event_id: str | None = None):
            yield ("message.delta", {"delta": f"新回复({run_id})"})
            yield ("run.completed", {"output": f"新回复({run_id})", "usage": {"total_tokens": 5000}})

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(chat_routes, "AgentClient", MockActionAgent)
    monkeypatch.setattr(chat_stream, "AgentClient", MockActionAgent)

    # Wrong role -> 400
    bad_regen_headers = await _issue_send_headers(client, reg["access_token"], conv_id)
    bad_regen = await client.post(
        f"/api/conversations/{conv_id}/messages/{u2.id}/regenerate",
        headers=bad_regen_headers,
    )
    assert bad_regen.status_code == 400

    # Regenerate a2
    conv_before = await db.get(Conversation, uuid.UUID(conv_id))
    orig_thread = conv_before.thread_id
    regen_headers = await _issue_send_headers(client, reg["access_token"], conv_id)
    regen_resp = await client.post(
        f"/api/conversations/{conv_id}/messages/{a2.id}/regenerate",
        headers=regen_headers,
    )
    assert regen_resp.status_code == 200, regen_resp.text
    assert len(deleted_threads) == 1 and deleted_threads[0] == orig_thread
    assert run_calls[0]["thread_id"] != orig_thread
    assert run_calls[0]["input_text"] == "第二问"
    assert run_calls[0]["conversation_history"] == [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
    ]

    detail1 = (await client.get(f"/api/conversations/{conv_id}", headers=headers)).json()
    msgs1 = detail1["messages"]
    assert len(msgs1) == 4
    assert msgs1[-1]["content"] == "新回复(run-new-1)"
    assert msgs1[-1]["id"] != str(a2.id)

    ledger_count = len(
        (await db.execute(select(CreditLedger).where(CreditLedger.user_id == user.id))).scalars().all()
    )
    assert ledger_count == 2

    # Edit u1 -> truncates u1, a1, u2, new_a2 and rotates thread again
    edit_headers = await _issue_send_headers(client, reg["access_token"], conv_id)
    edit_resp = await client.post(
        f"/api/conversations/{conv_id}/messages/{u1.id}/edit",
        json={"content": "修改后的第一问", "skill_names": ["some-skill"], "model_route": "fast"},
        headers=edit_headers,
    )
    assert edit_resp.status_code == 200, edit_resp.text
    assert len(deleted_threads) == 2
    assert run_calls[1]["thread_id"] != run_calls[0]["thread_id"]
    assert run_calls[1]["input_text"] == "修改后的第一问"
    assert run_calls[1]["model_route"] == "fast"
    assert run_calls[1]["conversation_history"] is None

    detail2 = (await client.get(f"/api/conversations/{conv_id}", headers=headers)).json()
    msgs2 = detail2["messages"]
    assert len(msgs2) == 2
    assert msgs2[0]["content"] == "修改后的第一问"
    assert msgs2[1]["content"] == "新回复(run-new-2)"

    conv_obj = await db.get(Conversation, uuid.UUID(conv_id))
    conv_obj.active_run_id = "busy-run"
    await db.commit()
    busy_headers = await _issue_send_headers(client, reg["access_token"], conv_id)
    busy_resp = await client.post(
        f"/api/conversations/{conv_id}/messages/{msgs2[1]['id']}/regenerate",
        headers=busy_headers,
    )
    assert busy_resp.status_code == 409


async def test_agent_status_and_topology_endpoints(register, client, monkeypatch):
    reg = await register(email="topo@test.local", display_name="TopoUser")
    headers = auth_header(reg["access_token"])

    class MockTopoAgent:
        def __init__(self, namespace: str | None = None, api_key: str | None = None) -> None:
            pass

        async def health_info(self) -> dict:
            return {"ready": True, "status": "ok", "sandbox_mode": "docker"}

        async def topology(self) -> dict:
            return {
                "entry": "context_loader",
                "nodes": [{"id": "context_loader", "label": "Loader"}, {"id": "agent", "label": "Agent"}],
                "edges": [{"source": "context_loader", "target": "agent"}],
            }

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(agent_routes, "AgentClient", MockTopoAgent)

    st = await client.get("/api/agent/status", headers=headers)
    assert st.status_code == 200
    assert st.json()["ready"] is True
    assert st.json()["engine"] == "langgraph"
    assert st.json()["sandbox_mode"] == "docker"

    topo = await client.get("/api/agent/topology", headers=headers)
    assert topo.status_code == 200
    assert topo.json()["entry"] == "context_loader"
    assert len(topo.json()["nodes"]) == 2
