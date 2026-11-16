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
    assert body["limits"]["max_concurrent_runs"] > 0
    assert [plan["tier"] for plan in body["plans"]] == ["free", "plus", "pro"]
    assert body["membership"]["free"] >= 2
    assert body["credits_today"]["tokens_per_credit"] == 1000
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


async def test_admin_user_list_includes_credit_summary(admin, register, client):
    await register(email="summary@test.local")
    resp = await client.get("/api/admin/users?page_size=100", headers=auth_header(admin["access_token"]))
    assert resp.status_code == 200, resp.text
    item = next(row for row in resp.json()["items"] if row["email"] == "summary@test.local")
    assert item["membership_tier"] == "free"
    assert item["credits"]["weekly_limit"] == 100
    assert item["credits"]["five_hour_limit"] == 20
    assert item["credits"]["remaining"] == 20.0


async def test_admin_updates_membership_and_credits(admin, register, client):
    data = await register(email="adjust@test.local")
    user_id = data["user"]["id"]
    headers = auth_header(admin["access_token"])

    resp = await client.patch(
        f"/api/admin/users/{user_id}/membership", json={"tier": "pro"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tier"] == "pro"
    assert body["weekly"]["limit"] == 1250
    assert body["five_hour"]["limit"] is None
    assert body["expires_at"]

    resp = await client.post(
        f"/api/admin/users/{user_id}/credits",
        json={"credits": 200, "note": "客服补偿"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["remaining"] == 1450.0

    resp = await client.patch(
        f"/api/admin/users/{user_id}/membership", json={"tier": "free"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tier"] == "free"
    assert resp.json()["expires_at"] is None
