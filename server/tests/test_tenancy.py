import uuid

from app.db.models import Message, User
from tests.conftest import auth_header


async def _create_conv(client, token, title="测试会话"):
    resp = await client.post("/api/conversations", json={"title": title}, headers=auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_conversation_crud(register, client):
    data = await register(email="crud@test.local")
    token = data["access_token"]
    conv = await _create_conv(client, token, title="我的会话")
    assert conv["title"] == "我的会话"

    listing = await client.get("/api/conversations", headers=auth_header(token))
    assert listing.status_code == 200
    assert any(c["id"] == conv["id"] for c in listing.json())

    detail = await client.get(f"/api/conversations/{conv['id']}", headers=auth_header(token))
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    rename = await client.patch(
        f"/api/conversations/{conv['id']}", json={"title": "改名"}, headers=auth_header(token)
    )
    assert rename.status_code == 200
    assert rename.json()["title"] == "改名"

    delete = await client.delete(f"/api/conversations/{conv['id']}", headers=auth_header(token))
    assert delete.status_code == 204
    gone = await client.get(f"/api/conversations/{conv['id']}", headers=auth_header(token))
    assert gone.status_code == 404


async def test_conversation_tenant_isolation(register, client):
    a = await register(email="owner@test.local")
    b = await register(email="intruder@test.local")
    conv = await _create_conv(client, a["access_token"])

    # B cannot read A's conversation
    read = await client.get(f"/api/conversations/{conv['id']}", headers=auth_header(b["access_token"]))
    assert read.status_code == 404
    # B cannot rename or delete it
    patch = await client.patch(
        f"/api/conversations/{conv['id']}", json={"title": "x"}, headers=auth_header(b["access_token"])
    )
    assert patch.status_code == 404
    delete = await client.delete(f"/api/conversations/{conv['id']}", headers=auth_header(b["access_token"]))
    assert delete.status_code == 404
    # B's list only contains B's own auto-created main chat (no side chats, never A's)
    listing = await client.get("/api/conversations", headers=auth_header(b["access_token"]))
    b_convs = listing.json()
    assert len(b_convs) == 1
    assert b_convs[0]["kind"] == "main"
    assert all(c["id"] != conv["id"] for c in b_convs)
    # A sees their main chat + the created side chat
    a_list = await client.get("/api/conversations", headers=auth_header(a["access_token"]))
    a_convs = a_list.json()
    assert len(a_convs) == 2
    assert a_convs[0]["kind"] == "main"
    assert any(c["id"] == conv["id"] and c["kind"] == "side" for c in a_convs)


async def test_admin_requires_admin(register, client):
    data = await register(email="plain@test.local")
    resp = await client.get("/api/admin/users", headers=auth_header(data["access_token"]))
    assert resp.status_code == 403


async def test_admin_list_users(admin, register, client):
    await register(email="listed@test.local")
    resp = await client.get("/api/admin/users", headers=auth_header(admin["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    emails = {u["email"] for u in body["items"]}
    assert {"admin@test.local", "listed@test.local"} <= emails


async def test_admin_disable_and_enable(admin, register, client, db):
    victim = await register(email="victim@test.local")
    vid = victim["user"]["id"]
    disable = await client.patch(
        f"/api/admin/users/{vid}", json={"is_active": False}, headers=auth_header(admin["access_token"])
    )
    assert disable.status_code == 200
    assert disable.json()["is_active"] is False
    # disabled user cannot log in
    login = await client.post("/api/auth/login", json={"email": "victim@test.local", "password": "Passw0rd!"})
    assert login.status_code == 403
    user = await db.get(User, uuid.UUID(vid))
    assert user.is_active is False
    # re-enable
    enable = await client.patch(
        f"/api/admin/users/{vid}", json={"is_active": True}, headers=auth_header(admin["access_token"])
    )
    assert enable.status_code == 200
    login2 = await client.post("/api/auth/login", json={"email": "victim@test.local", "password": "Passw0rd!"})
    assert login2.status_code == 200


async def test_admin_cannot_disable_self(admin, client):
    resp = await client.patch(
        f"/api/admin/users/{admin['user']['id']}",
        json={"is_active": False},
        headers=auth_header(admin["access_token"]),
    )
    assert resp.status_code == 400


async def test_admin_cannot_demote_self(admin, client):
    resp = await client.patch(
        f"/api/admin/users/{admin['user']['id']}",
        json={"role": "user"},
        headers=auth_header(admin["access_token"]),
    )
    assert resp.status_code == 400


async def test_admin_promote_user(admin, register, client):
    data = await register(email="promo@test.local")
    resp = await client.patch(
        f"/api/admin/users/{data['user']['id']}",
        json={"role": "admin"},
        headers=auth_header(admin["access_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
    # promoted user can now access admin endpoint
    access = await client.get("/api/admin/users", headers=auth_header(data["access_token"]))
    assert access.status_code == 200


async def test_conversation_search(register, client, db):
    a = await register(email="search-a@test.local")
    b = await register(email="search-b@test.local")
    conv1 = await _create_conv(client, a["access_token"], title="架构讨论")
    conv2 = await _create_conv(client, a["access_token"], title="Python 性能优化清单")
    conv_b = await _create_conv(client, b["access_token"], title="他人隐私")

    long_prefix = "这是一段很长的背景说明文字，用于测试搜索正文返回前后文摘要的截断效果。" * 2
    long_suffix = "后续补充了更多细节内容，确保关键词后面的上下文也能完整展示出来。" * 3
    db.add_all(
        [
            Message(
                conversation_id=uuid.UUID(conv1["id"]),
                role="user",
                content=f"{long_prefix}这里提到了异步队列与 Redis 缓存策略，{long_suffix}",
            ),
            Message(
                conversation_id=uuid.UUID(conv1["id"]),
                role="tool",
                content="Redis internal tool payload should be ignored",
            ),
            Message(
                conversation_id=uuid.UUID(conv2["id"]),
                role="assistant",
                content="可以使用 cProfile 分析热点函数，包含 100% 实测数据。",
            ),
            Message(
                conversation_id=uuid.UUID(conv_b["id"]),
                role="user",
                content="他人对话中的 Redis 关键词不应泄露",
            ),
        ]
    )
    await db.commit()

    # Body search returns message hit with context snippet and ignores tool messages & other users
    r1 = await client.get(
        "/api/conversations/search",
        params={"q": "Redis"},
        headers=auth_header(a["access_token"]),
    )
    assert r1.status_code == 200, r1.text
    hits1 = r1.json()
    assert len(hits1) == 1
    assert hits1[0]["conversation_id"] == conv1["id"]
    assert hits1[0]["match_in"] == "message"
    assert hits1[0]["role"] == "user"
    assert "Redis" in hits1[0]["snippet"]
    assert hits1[0]["snippet"].startswith("…") and hits1[0]["snippet"].endswith("…")

    # Title match when body does not match
    r2 = await client.get(
        "/api/conversations/search",
        params={"q": "性能优化"},
        headers=auth_header(a["access_token"]),
    )
    assert r2.status_code == 200
    hits2 = r2.json()
    assert len(hits2) == 1
    assert hits2[0]["conversation_id"] == conv2["id"]
    assert hits2[0]["match_in"] == "title"
    assert hits2[0]["snippet"] == ""

    # Wildcard escaping: literal '%' only matches message containing '%'
    r3 = await client.get(
        "/api/conversations/search",
        params={"q": "100%"},
        headers=auth_header(a["access_token"]),
    )
    assert r3.status_code == 200
    hits3 = r3.json()
    assert len(hits3) == 1
    assert hits3[0]["conversation_id"] == conv2["id"]