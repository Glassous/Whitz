from tests.conftest import auth_header


async def test_admin_overview(admin, register, client):
    await register(email="member@test.local")
    resp = await client.get("/api/admin/overview", headers=auth_header(admin["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["users"]["total"] >= 2
    assert body["users"]["active"] >= 2
    assert body["users"]["admins"] >= 1
    assert body["usage_today"]["day"]
    assert body["limits"]["daily_message_limit"] > 0
    assert body["generated_at"]


async def test_admin_overview_requires_admin(register, client):
    data = await register(email="plain@test.local")
    resp = await client.get("/api/admin/overview", headers=auth_header(data["access_token"]))
    assert resp.status_code == 403


async def test_admin_user_filters(admin, register, client):
    await register(email="filtered@test.local")
    resp = await client.get(
        "/api/admin/users?role=admin", headers=auth_header(admin["access_token"])
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items
    assert all(item["role"] == "admin" for item in items)

    resp = await client.get(
        "/api/admin/users?is_active=false", headers=auth_header(admin["access_token"])
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_admin_audit_outcome_filter(admin, client):
    await client.post("/api/auth/login", json={"email": "ghost@test.local", "password": "Passw0rd!"})
    resp = await client.get(
        "/api/admin/audit-logs?outcome=failure", headers=auth_header(admin["access_token"])
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items
    assert all(item["outcome"] == "failure" for item in items)
