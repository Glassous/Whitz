from tests.conftest import auth_header


async def test_user_sessions_list_and_single_revoke(register, client):
    reg = await register(email="sess@test.local", password="Passw0rd!", display_name="SessUser")
    access1 = reg["access_token"]
    refresh1 = reg["refresh_token"]

    # Second login creates a second active device/session
    login2 = await client.post(
        "/api/auth/login",
        json={"email": "sess@test.local", "password": "Passw0rd!"},
        headers={"User-Agent": "MobileSafari/17.0"},
    )
    assert login2.status_code == 200
    access2 = login2.json()["access_token"]
    refresh2 = login2.json()["refresh_token"]

    # Refresh token rotation on session 1 preserves session_id
    rot = await client.post("/api/auth/refresh", json={"refresh_token": refresh1})
    assert rot.status_code == 200
    access1_new = rot.json()["access_token"]

    sessions_resp = await client.get("/api/users/me/sessions", headers=auth_header(access1_new))
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json()
    assert len(sessions) == 2

    current = [s for s in sessions if s["is_current"]]
    others = [s for s in sessions if not s["is_current"]]
    assert len(current) == 1
    assert len(others) == 1
    assert others[0]["user_agent"] == "MobileSafari/17.0"

    # Revoke the other session
    del_resp = await client.delete(
        f"/api/users/me/sessions/{others[0]['session_id']}",
        headers=auth_header(access1_new),
    )
    assert del_resp.status_code == 204

    # Access token 2 is immediately rejected via Redis revocation check in get_current_user
    blocked_access = await client.get("/api/users/me", headers=auth_header(access2))
    assert blocked_access.status_code == 401

    # Refresh token 2 is also rejected in DB
    blocked_refresh = await client.post("/api/auth/refresh", json={"refresh_token": refresh2})
    assert blocked_refresh.status_code == 401

    # Current session 1 still works
    ok_me = await client.get("/api/users/me", headers=auth_header(access1_new))
    assert ok_me.status_code == 200
    remaining = (await client.get("/api/users/me/sessions", headers=auth_header(access1_new))).json()
    assert len(remaining) == 1
    assert remaining[0]["is_current"] is True


async def test_user_sessions_revoke_all_exclude_current_and_include_current(register, client):
    reg = await register(email="sessall@test.local", password="Passw0rd!", display_name="SessAll")
    access1 = reg["access_token"]

    login2 = await client.post(
        "/api/auth/login",
        json={"email": "sessall@test.local", "password": "Passw0rd!"},
    )
    access2 = login2.json()["access_token"]
    login3 = await client.post(
        "/api/auth/login",
        json={"email": "sessall@test.local", "password": "Passw0rd!"},
    )
    access3 = login3.json()["access_token"]

    # Revoke all except current
    rev_others = await client.delete(
        "/api/users/me/sessions?exclude_current=true",
        headers=auth_header(access1),
    )
    assert rev_others.status_code == 204
    assert (await client.get("/api/users/me", headers=auth_header(access1))).status_code == 200
    assert (await client.get("/api/users/me", headers=auth_header(access2))).status_code == 401
    assert (await client.get("/api/users/me", headers=auth_header(access3))).status_code == 401

    # Revoke all including current
    rev_all = await client.delete(
        "/api/users/me/sessions?exclude_current=false",
        headers=auth_header(access1),
    )
    assert rev_all.status_code == 204
    assert (await client.get("/api/users/me", headers=auth_header(access1))).status_code == 401
