import json
import uuid

import pytest
from sqlalchemy import select

from app.api.schemas import EditMessageRequest, SendMessageRequest
from app.core.config import get_settings
from app.db.models import ConversationFile, Message, User
from app.services import cos, cross_chat_memory, file_cache, file_parser
from tests.conftest import auth_header

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfeA\x89\x18\x0b\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_send_message_allows_file_only_without_text():
    fid = uuid.uuid4()
    req = SendMessageRequest(content="", file_ids=[fid])
    assert req.content == ""
    assert req.file_ids == [fid]

    edit_req = EditMessageRequest(content="   ", file_ids=[fid])
    assert edit_req.file_ids == [fid]

    with pytest.raises(ValueError):
        SendMessageRequest(content="   ", file_ids=[])


def test_history_preserves_attachments_on_file_only_turns():
    fid = str(uuid.uuid4())
    msg = Message(
        conversation_id=uuid.uuid4(),
        role="user",
        content="",
        tool_payload={
            "attachments": [
                {"id": fid, "filename": "chart.png", "ext": ".png", "category": "image", "size_bytes": 1234}
            ]
        },
        status="completed",
    )
    rendered = cross_chat_memory.format_history_message_content(msg)
    assert "chart.png" in rendered
    assert fid in rendered


def test_normalize_image_keeps_small_original_uncompressed():
    out_bytes, out_mime, _w, _h, compressed = file_parser.normalize_image_for_base64(
        _TINY_PNG,
        mime_type="image/png",
        max_raw_bytes=5 * 1024 * 1024,
    )
    assert out_bytes == _TINY_PNG
    assert out_mime == "image/png"
    assert compressed is False


def test_sniff_file_header_validates_magic_bytes():
    assert file_parser.sniff_file_header(_TINY_PNG[:16], ext=".png", category="image") is None
    assert file_parser.sniff_file_header(b"not-an-image", ext=".png", category="image") is not None
    assert file_parser.sniff_file_header(b"%PDF-1.7\n...", ext=".pdf", category="document") is None
    assert file_parser.sniff_file_header(b"<html>fake</html>", ext=".pdf", category="document") is not None


def test_parsed_file_cache_and_outline_and_injection():
    cache = file_cache.ParsedFileCache(max_bytes=64 * 1024, ttl_seconds=60.0)
    raw = "# 架构总览\n第2行内容\n## 核心模块\ndef run_pipeline():\n    return 42\n".encode("utf-8")
    parsed_dict = file_parser.parse_file_for_cache(raw, filename="design.md", ext=".md", mime_type="text/markdown")
    entry = file_cache.ParsedFileData(
        format=parsed_dict["format"],
        ext=parsed_dict["ext"],
        mime_type=parsed_dict["mime_type"],
        size_bytes=len(raw),
        approx_bytes=parsed_dict["approx_bytes"],
        lines=parsed_dict["lines"],
        outline=parsed_dict["outline"],
    )
    fid = uuid.uuid4()
    key = cache.build_key(fid, "etag-v1")
    cache.set(key, entry)
    hit = cache.get(key)
    assert hit is not None
    sliced = file_parser.read_from_parsed(hit, start_line=1, max_lines=3)
    assert sliced["total_lines"] == 5
    assert sliced["has_more"] is True
    assert sliced["next_start_line"] == 4

    full_txt, est_tokens, stats = file_parser.extract_full_text_for_injection(hit, max_tokens=2000)
    assert full_txt is not None and "run_pipeline" in full_txt
    assert est_tokens > 0 and stats["total_lines"] == 5

    # Exceeding budget returns None so caller switches to outline_rag
    too_big, _, _ = file_parser.extract_full_text_for_injection(hit, max_tokens=2)
    assert too_big is None
    outline = file_parser.format_outline_text(hit, filename="design.md")
    assert "架构总览" in outline

    hits = file_parser.search_parsed_content(hit, query="run_pipeline")
    assert len(hits) == 1 and hits[0]["location"] == "第 4 行"

    cache.invalidate_file(fid)
    assert cache.get(key) is None


@pytest.mark.asyncio
async def test_internal_hydration_builders_url_first_and_inline_full_unit(monkeypatch):
    from app.api.routes import internal_files

    monkeypatch.setenv("COS_SECRET_ID", "AKIDtest")
    monkeypatch.setenv("COS_SECRET_KEY", "SecretTest")
    monkeypatch.setenv("COS_BUCKET", "whitz-1250000000")
    monkeypatch.setenv("COS_REGION", "ap-shanghai")
    get_settings.cache_clear()
    settings = get_settings()
    file_cache.get_file_cache().clear()

    img_row = ConversationFile(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        filename="screen.png",
        ext=".png",
        mime_type="image/png",
        category="image",
        size_bytes=len(_TINY_PNG),
        storage_key="whitz/uploads/u/c/f/screen.png",
        etag="etag-1",
        status="ready",
    )
    doc_row = ConversationFile(
        id=uuid.uuid4(),
        user_id=img_row.user_id,
        filename="app.py",
        ext=".py",
        mime_type="text/x-python",
        category="code",
        size_bytes=50,
        storage_key="whitz/uploads/u/c/f/app.py",
        etag="etag-2",
        status="ready",
    )

    downloads = {"count": 0}

    async def _fake_get(key: str, *, max_bytes: int, settings=None) -> bytes:
        downloads["count"] += 1
        if key.endswith("screen.png"):
            return _TINY_PNG
        return b"def hello():\n    return 'world'\n"

    monkeypatch.setattr(cos, "get_object_bytes", _fake_get)

    # Image url_first: ZERO downloads, clean presigned COS URL
    img_url_res = await internal_files._build_image_payload(img_row, mode="url_first", settings=settings)
    assert img_url_res["delivery"] == "native_image_url"
    assert img_url_res["image_url"].startswith("https://whitz-1250000000.cos.ap-shanghai.myqcloud.com/")
    assert "response-content-disposition" not in img_url_res["image_url"]
    assert downloads["count"] == 0

    # Image base64 fallback: downloads once, keeps uncompressed original
    img_b64_res = await internal_files._build_image_payload(img_row, mode="base64", settings=settings)
    assert img_b64_res["delivery"] == "native_image_base64"
    assert img_b64_res["image_url"].startswith("data:image/png;base64,")
    assert img_b64_res["compressed"] is False
    assert downloads["count"] == 1

    # Small code doc: inline_full on first call, cache hit on second call
    doc_res, used_tok = await internal_files._build_document_payload(
        doc_row,
        allow_native_pdf=True,
        remaining_token_budget=8000,
        single_file_max_tokens=4000,
        settings=settings,
    )
    assert doc_res["delivery"] == "inline_full"
    assert "return 'world'" in doc_res["content"]
    assert used_tok > 0
    assert downloads["count"] == 2

    # Second call hits ParsedFileCache (zero extra COS download!)
    doc_res2, _ = await internal_files._build_document_payload(
        doc_row,
        allow_native_pdf=True,
        remaining_token_budget=8000,
        single_file_max_tokens=4000,
        settings=settings,
    )
    assert doc_res2["delivery"] == "inline_full"
    assert downloads["count"] == 2

    # Tight budget triggers outline_rag cleanly
    doc_outline, used_zero = await internal_files._build_document_payload(
        doc_row,
        allow_native_pdf=True,
        remaining_token_budget=1,
        single_file_max_tokens=1,
        settings=settings,
    )
    assert doc_outline["delivery"] == "outline_rag"
    assert "hello" in doc_outline["outline"]
    assert used_zero == 0

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_internal_prepare_turn_cache_links_and_visual_mcp(client, register, db, monkeypatch):
    monkeypatch.setenv("COS_SECRET_ID", "AKIDtest")
    monkeypatch.setenv("COS_SECRET_KEY", "SecretTest")
    monkeypatch.setenv("COS_BUCKET", "whitz-1250000000")
    monkeypatch.setenv("COS_REGION", "ap-shanghai")
    get_settings.cache_clear()
    file_cache.get_file_cache().clear()

    u_auth = await register(email="mm@test.local", display_name="MMUser")
    user = (await db.execute(select(User).where(User.email == "mm@test.local"))).scalar_one()
    hdr = auth_header(u_auth["access_token"])

    conv_resp = await client.post("/api/conversations", json={"title": "MM Chat"}, headers=hdr)
    conv_id = conv_resp.json()["id"]
    other_conv_resp = await client.post("/api/conversations", json={"title": "Lib Source"}, headers=hdr)
    other_conv_id = other_conv_resp.json()["id"]

    img_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    lib_id = uuid.uuid4()
    db.add_all(
        [
            ConversationFile(
                id=img_id,
                conversation_id=uuid.UUID(conv_id),
                user_id=user.id,
                filename="photo.png",
                ext=".png",
                mime_type="image/png",
                category="image",
                size_bytes=len(_TINY_PNG),
                storage_key=f"whitz/uploads/{user.id}/{conv_id}/{img_id}/photo.png",
                etag="etag-img-1",
                status="ready",
            ),
            ConversationFile(
                id=doc_id,
                conversation_id=uuid.UUID(conv_id),
                user_id=user.id,
                filename="notes.md",
                ext=".md",
                mime_type="text/markdown",
                category="document",
                size_bytes=80,
                storage_key=f"whitz/uploads/{user.id}/{conv_id}/{doc_id}/notes.md",
                etag="etag-doc-1",
                status="ready",
            ),
            ConversationFile(
                id=lib_id,
                conversation_id=uuid.UUID(other_conv_id),
                user_id=user.id,
                filename="shared_spec.txt",
                ext=".txt",
                mime_type="text/plain",
                category="document",
                size_bytes=40,
                storage_key=f"whitz/uploads/{user.id}/{other_conv_id}/{lib_id}/shared_spec.txt",
                etag="etag-lib-1",
                status="ready",
            ),
        ]
    )
    await db.commit()

    download_calls: dict[str, int] = {}

    async def _fake_get_bytes(key: str, *, max_bytes: int, settings=None) -> bytes:
        download_calls[key] = download_calls.get(key, 0) + 1
        if key.endswith("photo.png"):
            return _TINY_PNG
        if key.endswith("notes.md"):
            return "# 标题一\n第一行内容\n## 标题二\n第二行关键数据 42\n".encode("utf-8")
        return "跨会话共享规格内容".encode("utf-8")

    monkeypatch.setattr(cos, "get_object_bytes", _fake_get_bytes)

    internal_hdr = {
        "Authorization": f"Bearer {user.agent_api_key}",
        "X-Whitz-Namespace": user.agent_namespace,
    }

    # 1. prepare-turn: image uses clean COS URL without downloading bytes; small doc uses inline_full
    prep = await client.post(
        "/api/internal/files/prepare-turn",
        json={"conversation_id": conv_id, "file_ids": [str(img_id), str(doc_id)], "prefer_image_mode": "url_first"},
        headers=internal_hdr,
    )
    assert prep.status_code == 200
    items = prep.json()["items"]
    assert len(items) == 2
    assert items[0]["delivery"] == "native_image_url"
    assert items[0]["image_url"].startswith("https://")
    assert "response-content-disposition" not in items[0]["image_url"]
    assert download_calls.get(f"whitz/uploads/{user.id}/{conv_id}/{img_id}/photo.png", 0) == 0

    assert items[1]["delivery"] == "inline_full"
    assert "第二行关键数据 42" in items[1]["content"]

    # 2. On-demand base64 fallback returns original uncompressed data URI
    fb = await client.get(f"/api/internal/files/{img_id}/media?mode=base64", headers=internal_hdr)
    assert fb.status_code == 200
    fb_data = fb.json()
    assert fb_data["delivery"] == "native_image_base64"
    assert fb_data["image_url"].startswith("data:image/png;base64,")
    assert fb_data["compressed"] is False

    # 3. Repeated paginated read_workspace_file hits parsed cache (only 1 COS download total for notes.md!)
    doc_key = f"whitz/uploads/{user.id}/{conv_id}/{doc_id}/notes.md"
    assert download_calls[doc_key] == 1
    for start_line in (1, 3):
        r = await client.post(
            "/api/internal/mcp/files",
            json={
                "jsonrpc": "2.0",
                "id": start_line,
                "method": "tools/call",
                "params": {
                    "name": "read_workspace_file",
                    "arguments": {"conversation_id": conv_id, "filename": "notes.md", "start_line": start_line, "max_lines": 2},
                },
            },
            headers=internal_hdr,
        )
        assert r.status_code == 200
        assert r.json()["result"]["isError"] is False
    assert download_calls[doc_key] == 1  # Zero extra COS downloads!

    # 4. inspect_workspace_file returns Markdown headings & line count from cache
    insp = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": "inspect_workspace_file", "arguments": {"conversation_id": conv_id, "file_id": str(doc_id)}},
        },
        headers=internal_hdr,
    )
    insp_payload = json.loads(insp.json()["result"]["content"][0]["text"])
    assert insp_payload["outline"]["total_lines"] == 4
    assert any("标题一" in h for h in insp_payload["outline"]["headings"])
    assert download_calls[doc_key] == 1

    # 5. MCP read_workspace_file on image returns lightweight visual attachment metadata (NO raw base64 blob!)
    img_read = await client.post(
        "/api/internal/mcp/files",
        json={
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {"name": "read_workspace_file", "arguments": {"conversation_id": conv_id, "file_id": str(img_id)}},
        },
        headers=internal_hdr,
    )
    img_payload = json.loads(img_read.json()["result"]["content"][0]["text"])
    assert img_payload["whitz_visual_attachment"] is True
    assert img_payload["image_url"].startswith("https://")
    assert "image_base64" not in img_payload

    # 6. Persistent attach from library survives GET /conversations/{id}/files & detaches cleanly
    att = await client.post(
        f"/api/conversations/{conv_id}/files/attach",
        json={"file_ids": [str(lib_id)]},
        headers=hdr,
    )
    assert att.status_code == 200
    listed_after_attach = await client.get(f"/api/conversations/{conv_id}/files", headers=hdr)
    assert any(item["id"] == str(lib_id) for item in listed_after_attach.json())

    det = await client.delete(f"/api/conversations/{conv_id}/files/{lib_id}", headers=hdr)
    assert det.status_code == 204
    listed_after_detach = await client.get(f"/api/conversations/{conv_id}/files", headers=hdr)
    assert all(item["id"] != str(lib_id) for item in listed_after_detach.json())

    get_settings.cache_clear()
