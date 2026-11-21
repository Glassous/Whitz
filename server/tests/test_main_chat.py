from __future__ import annotations

import importlib.util
import pathlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Conversation, ConversationDigest, ConversationFile, FileChunk, Message, User
from app.main import create_app
from app.services import cos, cross_chat_memory as ccm
from tests.conftest import auth_header


# ---------------------------------------------------------------------------
# Pure Unit Tests (no external PostgreSQL required)
# ---------------------------------------------------------------------------


def test_models_schema_and_migration_0014():
    # User assistant columns & defaults
    assert User.__table__.columns["assistant_name"].default.arg == "Whitz"
    assert "assistant_avatar_url" in User.__table__.columns

    # Conversation kind, rolling summary, default title & unique main index
    assert Conversation.__table__.columns["kind"].default.arg == "side"
    assert Conversation.__table__.columns["title"].default.arg == "新旁聊"
    assert "rolling_summary" in Conversation.__table__.columns
    assert "summary_cursor_msg_id" in Conversation.__table__.columns
    index_names = {idx.name for idx in Conversation.__table__.indexes}
    assert "uq_conversations_user_main" in index_names

    # Global files default to True
    assert ConversationFile.__table__.columns["is_global"].default.arg is True
    assert FileChunk.__table__.columns["is_global"].default.arg is True

    # ConversationDigest table structure
    digest_cols = set(ConversationDigest.__table__.columns.keys())
    assert {"conversation_id", "user_id", "summary", "key_facts", "keywords", "message_count", "search_tsv", "embedding"} <= digest_cols

    # Alembic migration 0014 loads cleanly and chains from 0013
    mig_path = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0014_main_chat_and_global_files.py"
    spec = importlib.util.spec_from_file_location("mig_0014", mig_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0014"
    assert mod.down_revision == "0013"
    assert callable(mod.upgrade) and callable(mod.downgrade)


def test_fastapi_routes_registered_for_main_chat_assistant_and_library():
    app = create_app()
    paths = app.openapi()["paths"]

    assert "get" in paths.get("/api/conversations/main", {})
    assert "patch" in paths.get("/api/users/me/assistant", {})
    assert "put" in paths.get("/api/users/me/assistant/avatar", {})
    assert "delete" in paths.get("/api/users/me/assistant/avatar", {})
    assert "get" in paths.get("/api/users/{user_id}/assistant-avatar", {})
    assert "post" in paths.get("/api/library/files/presign", {})
    assert "post" in paths.get("/api/library/files/{file_id}/complete", {})


def test_cross_chat_memory_helpers_and_extractive_fallbacks():
    assert ccm.estimate_tokens("") == 0
    assert ccm.estimate_tokens("你好世界") >= 2
    assert ccm.estimate_tokens("hello world from whitz") >= 4
    assert ccm._cosine_sim([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert ccm._cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert ccm._cosine_sim(None, [1.0]) == 0.0

    # Extractive digest fallback
    msgs = [
        SimpleNamespace(role="user", content="帮我调研 PostgreSQL pgvector HNSW 索引参数", status="done"),
        SimpleNamespace(role="assistant", content="建议使用 m=16, ef_construction=64 并开启 vector_cosine_ops。", status="done"),
        SimpleNamespace(role="user", content="失败的消息", status="failed"),
    ]
    summary, facts, keywords = ccm._extractive_digest("向量索引调研", msgs)  # type: ignore[arg-type]
    assert "PostgreSQL" in summary
    assert "ef_construction=64" in summary
    assert len(facts) == 2
    assert len(keywords) >= 2

    # JSON parser accepts wrapped markdown fences and clips lengths
    parsed = ccm._parse_digest_json(
        '```json\n{"summary": "讨论了主聊天架构", "key_facts": ["每用户唯一主聊", "文件全局共享"], "keywords": ["主聊", "资料库"]}\n```'
    )
    assert parsed is not None
    assert parsed[0] == "讨论了主聊天架构"
    assert parsed[1] == ["每用户唯一主聊", "文件全局共享"]
    assert parsed[2] == ["主聊", "资料库"]

    # Extractive rolling summary stays strictly bounded under ROLLING_SUMMARY_MAX_CHARS
    long_msgs = [
        SimpleNamespace(role="user" if i % 2 == 0 else "assistant", content=f"第 {i} 轮讨论细节：" + ("内容" * 200), status="done")
        for i in range(40)
    ]
    rolled = ccm._extractive_rolling_summary("旧摘要：" + ("历史" * 1500), long_msgs)  # type: ignore[arg-type]
    assert len(rolled) <= ccm.ROLLING_SUMMARY_MAX_CHARS
    assert "第 39 轮讨论细节" in rolled


# ---------------------------------------------------------------------------
# Full Integration Tests (requires PostgreSQL test DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_chat_uniqueness_and_protection(client, register):
    reg = await register(email="mainchat@test.local", display_name="MainOwner")
    headers = auth_header(reg["access_token"])

    # Register auto-creates the unique main chat
    listed = (await client.get("/api/conversations", headers=headers)).json()
    assert len(listed) == 1
    assert listed[0]["kind"] == "main"
    assert listed[0]["title"] == "主要聊天"

    main_res = await client.get("/api/conversations/main", headers=headers)
    assert main_res.status_code == 200
    main_id = main_res.json()["id"]
    assert main_id == listed[0]["id"]

    # Main chat cannot be deleted or renamed/pinned
    assert (await client.delete(f"/api/conversations/{main_id}", headers=headers)).status_code == 400
    assert (await client.patch(f"/api/conversations/{main_id}", json={"title": "改名"}, headers=headers)).status_code == 400
    assert (await client.patch(f"/api/conversations/{main_id}", json={"is_pinned": True}, headers=headers)).status_code == 400

    # Creating a conversation always produces a side chat with default title "新旁聊"
    side = (await client.post("/api/conversations", json={}, headers=headers)).json()
    assert side["kind"] == "side"
    assert side["title"] == "新旁聊"

    listed2 = (await client.get("/api/conversations", headers=headers)).json()
    assert [c["kind"] for c in listed2] == ["main", "side"]


@pytest.mark.asyncio
async def test_assistant_profile_and_avatar_endpoints(client, register):
    reg = await register(email="assistant@test.local", display_name="Owner")
    headers = auth_header(reg["access_token"])
    user_id = reg["user"]["id"]

    assert reg["user"]["assistant_name"] == "Whitz"
    assert reg["user"]["assistant_avatar_url"] is None

    # Update nickname
    patched = await client.patch("/api/users/me/assistant", json={"assistant_name": "小智助手"}, headers=headers)
    assert patched.status_code == 200
    assert patched.json()["assistant_name"] == "小智助手"

    # Reject invalid image bytes
    bad_up = await client.put(
        "/api/users/me/assistant/avatar",
        files={"file": ("bad.png", b"not-a-png", "image/png")},
        headers=headers,
    )
    assert bad_up.status_code == 400

    # Upload minimal valid 1x1 PNG
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc`\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    up = await client.put(
        "/api/users/me/assistant/avatar",
        files={"file": ("avatar.png", png_1x1, "image/png")},
        headers=headers,
    )
    assert up.status_code == 200, up.text
    avatar_url = up.json()["assistant_avatar_url"]
    assert avatar_url and f"/api/users/{user_id}/assistant-avatar" in avatar_url

    fetched = await client.get(f"/api/users/{user_id}/assistant-avatar")
    assert fetched.status_code == 200
    assert fetched.content == png_1x1

    # Reset avatar back to default
    reset = await client.delete("/api/users/me/assistant/avatar", headers=headers)
    assert reset.status_code == 200
    assert reset.json()["assistant_avatar_url"] is None


@pytest.mark.asyncio
async def test_library_direct_upload_and_cross_chat_digest_and_compaction(client, register, db, monkeypatch):
    monkeypatch.setenv("COS_SECRET_ID", "AKIDtest")
    monkeypatch.setenv("COS_SECRET_KEY", "SecretTest")
    monkeypatch.setenv("COS_BUCKET", "whitz-1250000000")
    monkeypatch.setenv("COS_REGION", "ap-shanghai")
    get_settings.cache_clear()

    reg = await register(email="memory@test.local", display_name="MemUser")
    headers = auth_header(reg["access_token"])
    user = (await db.execute(select(User).where(User.email == "memory@test.local"))).scalar_one()

    # 1. Direct upload to Library (not tied to a conversation)
    sample = b"Whitz global knowledge file content for RAG."
    pre = await client.post(
        "/api/library/files/presign",
        json={"filename": "handbook.md", "mime_type": "text/markdown", "size_bytes": len(sample)},
        headers=headers,
    )
    assert pre.status_code == 200, pre.text
    file_id = pre.json()["file_id"]

    async def _fake_head(key: str, settings=None):
        return {"content_length": len(sample), "etag": "e-lib", "content_type": "text/markdown"}

    async def _fake_get(key: str, *, max_bytes: int, settings=None):
        return sample

    monkeypatch.setattr(cos, "head_object", _fake_head)
    monkeypatch.setattr(cos, "get_object_bytes", _fake_get)

    done = await client.post(f"/api/library/files/{file_id}/complete", json={"etag": "e-lib"}, headers=headers)
    assert done.status_code == 200, done.text
    assert done.json()["is_global"] is True
    assert done.json()["conversation_id"] is None

    # 2. Side chat digest refresh & Main chat cross-chat recall
    side = (await client.post("/api/conversations", json={"title": "Vim 配置调研"}, headers=headers)).json()
    side_id = uuid.UUID(side["id"])
    db.add(Message(conversation_id=side_id, role="user", content="怎么用 LazyVim 配置 Python LSP？", status="done"))
    db.add(Message(conversation_id=side_id, role="assistant", content="推荐启用 pyright 与 ruff 插件，并关闭格式化冲突。", status="done"))
    await db.commit()

    digest = await ccm.refresh_side_chat_digest(db, side_id, force=True)
    assert digest is not None
    assert "LazyVim" in digest.summary or "pyright" in digest.summary

    main_conv = await ccm.ensure_main_conversation(db, user)
    cross_ctx = await ccm.build_main_chat_memory_context(db, user, main_conv, "之前 LazyVim Python 插件怎么配的")
    assert cross_ctx is not None
    assert "Vim 配置调研" in cross_ctx

    # 3. Main chat rolling compaction triggers when message count exceeds threshold
    for i in range(ccm.COMPACT_TRIGGER_MESSAGES + 4):
        db.add(
            Message(
                conversation_id=main_conv.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"主聊历史第 {i} 条消息：记录关键项目决策 #{i}",
                status="done",
            )
        )
    await db.commit()

    compacted = await ccm.compact_main_conversation_if_needed(db, main_conv)
    assert compacted is True
    await db.refresh(main_conv)
    assert main_conv.rolling_summary
    assert main_conv.summary_cursor_msg_id is not None
    assert len(main_conv.rolling_summary) <= ccm.ROLLING_SUMMARY_MAX_CHARS
    get_settings.cache_clear()
