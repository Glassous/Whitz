import uuid

from app.db.models import User
from app.services import provisioning
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
    # B's list is empty
    listing = await client.get("/api/conversations", headers=auth_header(b["access_token"]))
    assert listing.json() == []
    # A still sees it
    a_list = await client.get("/api/conversations", headers=auth_header(a["access_token"]))
    assert len(a_list.json()) == 1


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
    # parked marker written
    user = await db.get(User, uuid.UUID(vid))
    assert (provisioning.profile_dir(user.hermes_profile) / "gateway.parked").exists()
    # re-enable
    enable = await client.patch(
        f"/api/admin/users/{vid}", json={"is_active": True}, headers=auth_header(admin["access_token"])
    )
    assert enable.status_code == 200
    login2 = await client.post("/api/auth/login", json={"email": "victim@test.local", "password": "Passw0rd!"})
    assert login2.status_code == 200
    assert not (provisioning.profile_dir(user.hermes_profile) / "gateway.parked").exists()


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