from tests.conftest import auth_header


async def test_admin_audit_logs(admin, register, client):
    await register(email="audited@test.local")
    resp = await client.get("/api/admin/audit-logs", headers=auth_header(admin["access_token"]))
    assert resp.status_code == 200
    body = resp.json()
    actions = {item["action"] for item in body["items"]}
    assert "auth.register" in actions
    assert body["total"] >= 1


async def test_audit_severity_filter(admin, client):
    await client.post("/api/auth/login", json={"email": "ghost@test.local", "password": "Passw0rd!"})
    resp = await client.get(
        "/api/admin/audit-logs?severity=warning", headers=auth_header(admin["access_token"])
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert all(item["severity"] == "warning" for item in items)
    assert any(item["action"] == "auth.login_failed" for item in items)


async def test_audit_requires_admin(register, client):
    data = await register(email="notadmin@test.local")
    resp = await client.get("/api/admin/audit-logs", headers=auth_header(data["access_token"]))
    assert resp.status_code == 403
