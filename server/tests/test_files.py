import io
import uuid

import openpyxl
import pytest
from docx import Document

from app.core.config import get_settings
from app.services import cos, file_parser, file_types
from tests.conftest import auth_header


@pytest.fixture
def cos_env(monkeypatch):
    monkeypatch.setenv("COS_SECRET_ID", "AKIDtest")
    monkeypatch.setenv("COS_SECRET_KEY", "SecretTest")
    monkeypatch.setenv("COS_BUCKET", "whitz-1250000000")
    monkeypatch.setenv("COS_REGION", "ap-shanghai")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_file_type_validation():
    ok = file_types.validate_upload_request("目录/../季度报表.xlsx", "", 2048, 20 * 1024 * 1024)
    assert ok.filename == "季度报表.xlsx"
    assert ok.ext == ".xlsx"
    assert ok.category == "spreadsheet"

    # Markdown files often arrive with empty or octet-stream MIME from browsers
    md = file_types.validate_upload_request("README.md", "application/octet-stream", 100, 20 * 1024 * 1024)
    assert md.mime_type == "text/markdown"

    for bad_name, bad_mime in [
        ("malware.exe", "application/x-msdownload"),
        ("archive.zip", "application/zip"),
        ("movie.mp4", "video/mp4"),
        ("vector.svg", "image/svg+xml"),
        ("fake.txt", "video/mp4"),
    ]:
        with pytest.raises(file_types.FileValidationError):
            file_types.validate_upload_request(bad_name, bad_mime, 100, 20 * 1024 * 1024)

    with pytest.raises(file_types.FileValidationError):
        file_types.validate_upload_request("huge.pdf", "application/pdf", 25 * 1024 * 1024, 20 * 1024 * 1024)


def test_file_parsers_docx_xlsx_and_text():
    # DOCX
    doc = Document()
    doc.add_paragraph("第一段分析内容")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "数值"
    table.cell(1, 0).text = "营收"
    table.cell(1, 1).text = "120万"
    docx_buf = io.BytesIO()
    doc.save(docx_buf)
    parsed_docx = file_parser.read_file_content(
        docx_buf.getvalue(),
        ext=".docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert "第一段分析内容" in parsed_docx["content"]
    assert "营收 | 120万" in parsed_docx["content"]

    # XLSX
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Month", "Amount"])
    ws.append(["Jan", 500])
    xlsx_buf = io.BytesIO()
    wb.save(xlsx_buf)
    parsed_xlsx = file_parser.read_file_content(
        xlsx_buf.getvalue(),
        ext=".xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert parsed_xlsx["sheets"] == ["Sales"]
    assert "Jan\t500" in parsed_xlsx["content"]

    hits = file_parser.search_file_content(xlsx_buf.getvalue(), ext=".xlsx", query="jan")
    assert len(hits) == 1
    assert "Sales" in hits[0]["location"]


@pytest.mark.asyncio
async def test_conversation_file_workspace_lifecycle_and_isolation(client, register, cos_env, monkeypatch):
    u1 = await register(email="u1@test.local", display_name="User1")
    u2 = await register(email="u2@test.local", display_name="User2")
    h1 = auth_header(u1["access_token"])
    h2 = auth_header(u2["access_token"])

    conv_resp = await client.post("/api/conversations", json={"title": "文件测试"}, headers=h1)
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["id"]

    # Reject unsupported type
    bad = await client.post(
        f"/api/conversations/{conv_id}/files/presign",
        json={"filename": "payload.zip", "mime_type": "application/zip", "size_bytes": 100},
        headers=h1,
    )
    assert bad.status_code == 422

    # Presign valid file
    pre = await client.post(
        f"/api/conversations/{conv_id}/files/presign",
        json={"filename": "notes.md", "mime_type": "text/markdown", "size_bytes": 128},
        headers=h1,
    )
    assert pre.status_code == 200, pre.text
    pre_data = pre.json()
    file_id = pre_data["file_id"]
    assert "whitz-1250000000.cos.ap-shanghai.myqcloud.com" in pre_data["upload_url"]

    # Mock COS HEAD check
    async def _fake_head(key: str, settings=None):
        return {"content_length": 128, "etag": "abc123", "content_type": "text/markdown"}

    deleted_keys: list[str] = []

    async def _fake_delete_object(key: str, settings=None):
        deleted_keys.append(key)

    monkeypatch.setattr(cos, "head_object", _fake_head)
    monkeypatch.setattr(cos, "delete_object", _fake_delete_object)

    comp = await client.post(
        f"/api/conversations/{conv_id}/files/{file_id}/complete",
        json={"etag": "abc123"},
        headers=h1,
    )
    assert comp.status_code == 200, comp.text
    assert comp.json()["status"] == "ready"

    # List files
    listed = await client.get(f"/api/conversations/{conv_id}/files", headers=h1)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["filename"] == "notes.md"

    # Cross-user access denied
    other_list = await client.get(f"/api/conversations/{conv_id}/files", headers=h2)
    assert other_list.status_code == 404

    # Download URL
    dl = await client.get(f"/api/conversations/{conv_id}/files/{file_id}/download-url", headers=h1)
    assert dl.status_code == 200
    assert "q-signature=" in dl.json()["url"]

    # Remove from side-chat workspace detaches (stays in global library, COS object NOT deleted yet)
    dele = await client.delete(f"/api/conversations/{conv_id}/files/{file_id}", headers=h1)
    assert dele.status_code == 204
    assert len(deleted_keys) == 0

    listed_after = await client.get(f"/api/conversations/{conv_id}/files", headers=h1)
    assert listed_after.json() == []

    # Still exists in global Library until explicitly deleted from Library
    lib_before = await client.get("/api/library/files", headers=h1)
    assert lib_before.status_code == 200
    assert lib_before.json()["total"] == 1

    lib_del = await client.delete(f"/api/library/files/{file_id}", headers=h1)
    assert lib_del.status_code == 204
    assert len(deleted_keys) == 1

    lib_after = await client.get("/api/library/files", headers=h1)
    assert lib_after.json()["total"] == 0


def test_build_workspace_instructions_includes_ready_files():
    from app.db.models import ConversationFile
    from app.services.chat_stream import _build_workspace_instructions

    conv_id = uuid.uuid4()
    f1 = ConversationFile(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        user_id=uuid.uuid4(),
        filename="report.pdf",
        ext=".pdf",
        mime_type="application/pdf",
        category="document",
        size_bytes=4096,
        storage_key="k1",
        status="ready",
    )
    f2 = ConversationFile(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        user_id=f1.user_id,
        filename="data.csv",
        ext=".csv",
        mime_type="text/csv",
        category="spreadsheet",
        size_bytes=512,
        storage_key="k2",
        status="ready",
    )
    assert _build_workspace_instructions(conv_id, [], set()) is None
    text = _build_workspace_instructions(conv_id, [f1, f2], {f2.id})
    assert text is not None
    assert str(conv_id) in text
    assert "report.pdf" in text
    assert "data.csv [本轮新附带]" in text
    assert "read_workspace_file" in text


@pytest.mark.asyncio
async def test_pending_cleanup_preview_content_and_global_library(client, register, db, cos_env, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.db.models import ConversationFile, User

    u1 = await register(email="lib1@test.local", display_name="Lib1")
    u2 = await register(email="lib2@test.local", display_name="Lib2")
    h1 = auth_header(u1["access_token"])
    h2 = auth_header(u2["access_token"])
    user1 = (await db.execute(select(User).where(User.email == "lib1@test.local"))).scalar_one()

    conv1_id = (await client.post("/api/conversations", json={"title": "会话一"}, headers=h1)).json()["id"]
    conv2_id = (await client.post("/api/conversations", json={"title": "会话二"}, headers=h1)).json()["id"]

    # Insert an expired pending file and verify cleanup happens on list_files
    expired_id = uuid.uuid4()
    db.add(
        ConversationFile(
            id=expired_id,
            conversation_id=uuid.UUID(conv1_id),
            user_id=user1.id,
            filename="abandoned.txt",
            ext=".txt",
            mime_type="text/plain",
            category="document",
            size_bytes=10,
            storage_key=f"whitz/uploads/{user1.id}/{conv1_id}/{expired_id}/abandoned.txt",
            status="pending",
            expires_cleanup_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
    )
    ready_id = uuid.uuid4()
    db.add(
        ConversationFile(
            id=ready_id,
            conversation_id=uuid.UUID(conv1_id),
            user_id=user1.id,
            filename="page.html",
            ext=".html",
            mime_type="text/html",
            category="code",
            size_bytes=25,
            storage_key=f"whitz/uploads/{user1.id}/{conv1_id}/{ready_id}/page.html",
            status="ready",
            source="assistant",
        )
    )
    img_id = uuid.uuid4()
    db.add(
        ConversationFile(
            id=img_id,
            conversation_id=uuid.UUID(conv1_id),
            user_id=user1.id,
            filename="chart.png",
            ext=".png",
            mime_type="image/png",
            category="image",
            size_bytes=120,
            storage_key=f"whitz/uploads/{user1.id}/{conv1_id}/{img_id}/chart.png",
            status="ready",
        )
    )
    await db.commit()

    deleted_keys: list[str] = []

    async def _fake_delete_objects(keys, settings=None):
        deleted_keys.extend(keys)

    async def _fake_delete_object(key, settings=None):
        deleted_keys.append(key)

    async def _fake_get_bytes(key: str, *, max_bytes: int, settings=None) -> bytes:
        return b"<h1>Hello World</h1>"

    copied_puts: list[str] = []

    async def _fake_put_bytes(key: str, data: bytes, content_type: str, settings=None) -> str:
        copied_puts.append(key)
        return "etag-cloned"

    monkeypatch.setattr(cos, "delete_objects", _fake_delete_objects)
    monkeypatch.setattr(cos, "delete_object", _fake_delete_object)
    monkeypatch.setattr(cos, "get_object_bytes", _fake_get_bytes)
    monkeypatch.setattr(cos, "put_object_bytes", _fake_put_bytes)

    listed = await client.get(f"/api/conversations/{conv1_id}/files", headers=h1)
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    assert await db.get(ConversationFile, expired_id) is None

    # Preview URLs & thumb URLs attached
    img_item = next(f for f in listed.json() if f["id"] == str(img_id))
    assert img_item["preview_url"] and "q-signature=" in img_item["preview_url"]
    assert img_item["thumb_url"] is not None
    assert img_item["preview_expires_at"] is not None

    # In-panel preview-content returns UTF-8 HTML text
    preview = await client.get(f"/api/conversations/{conv1_id}/files/{ready_id}/preview-content", headers=h1)
    assert preview.status_code == 200
    assert preview.json()["format"] == "text"
    assert preview.json()["content"] == "<h1>Hello World</h1>"

    # Global Library listing & cross-user isolation
    lib = await client.get("/api/library/files", headers=h1)
    assert lib.status_code == 200
    assert lib.json()["total"] == 2
    assert {item["conversation_title"] for item in lib.json()["items"]} == {"会话一"}
    assert (await client.get("/api/library/files", headers=h2)).json()["total"] == 0

    # Mark page.html as global and rename
    patched = await client.patch(
        f"/api/library/files/{ready_id}",
        json={"is_global": True, "filename": "landing.html"},
        headers=h1,
    )
    assert patched.status_code == 200
    assert patched.json()["is_global"] is True
    assert patched.json()["filename"] == "landing.html"

    # Attach to conv2 references existing global library file without cloning duplicate COS objects
    attached = await client.post(
        f"/api/conversations/{conv2_id}/files/attach",
        json={"file_ids": [str(ready_id)]},
        headers=h1,
    )
    assert attached.status_code == 200, attached.text
    assert len(attached.json()) == 1
    assert attached.json()[0]["id"] == str(ready_id)
    assert len(copied_puts) == 0

    # Deleting conv1 preserves ALL files globally in Library (conversation_id -> None, is_global -> True)
    del_conv1 = await client.delete(f"/api/conversations/{conv1_id}", headers=h1)
    assert del_conv1.status_code == 204
    db.expire_all()
    survived = await db.get(ConversationFile, ready_id)
    assert survived is not None
    assert survived.conversation_id is None
    assert survived.is_global is True
    survived_img = await db.get(ConversationFile, img_id)
    assert survived_img is not None
    assert survived_img.conversation_id is None
    assert survived_img.is_global is True
    assert all(str(ready_id) not in k and str(img_id) not in k for k in deleted_keys)


@pytest.mark.asyncio
async def test_file_complete_indexes_chunks_and_syncs_global_flag(client, register, db, cos_env, monkeypatch):
    from sqlalchemy import select

    from app.db.models import FileChunk

    u1 = await register(email="chunker@test.local", display_name="ChunkUser")
    h1 = auth_header(u1["access_token"])
    conv_id = (await client.post("/api/conversations", json={"title": "RAG索引"}, headers=h1)).json()["id"]

    sample_text = ("第一段：LangGraph 状态图支持中断与恢复。\n" * 40).encode("utf-8")
    pre = await client.post(
        f"/api/conversations/{conv_id}/files/presign",
        json={"filename": "arch.md", "mime_type": "text/markdown", "size_bytes": len(sample_text)},
        headers=h1,
    )
    assert pre.status_code == 200
    file_id = pre.json()["file_id"]

    async def _fake_head(key: str, settings=None):
        return {"content_length": len(sample_text), "etag": "e1", "content_type": "text/markdown"}

    async def _fake_get(key: str, *, max_bytes: int, settings=None):
        return sample_text

    monkeypatch.setattr(cos, "head_object", _fake_head)
    monkeypatch.setattr(cos, "get_object_bytes", _fake_get)

    done = await client.post(f"/api/conversations/{conv_id}/files/{file_id}/complete", json={}, headers=h1)
    assert done.status_code == 200, done.text

    chunks = (
        await db.execute(
            select(FileChunk)
            .where(FileChunk.file_id == uuid.UUID(file_id))
            .order_by(FileChunk.chunk_index.asc())
        )
    ).scalars().all()
    assert len(chunks) >= 2
    assert chunks[0].is_global is True
    assert chunks[0].search_tsv is not None
    assert "LangGraph" in chunks[0].content

    patched = await client.patch(
        f"/api/library/files/{file_id}",
        json={"filename": "arch_v2.md"},
        headers=h1,
    )
    assert patched.status_code == 200
    assert patched.json()["filename"] == "arch_v2.md"
    db.expire_all()
    chunks_after = (
        await db.execute(select(FileChunk).where(FileChunk.file_id == uuid.UUID(file_id)))
    ).scalars().all()
    assert all(c.is_global is True for c in chunks_after)
