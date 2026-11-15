import uuid

from app.db.models import User
from app.services import provisioning
from tests.conftest import auth_header


async def test_register_creates_user_and_profile(register, db):
    data = await register(email="alice@test.local", display_name="Alice")
    assert data["user"]["email"] == "alice@test.local"
    assert data["user"]["role"] == "user"
    assert data["access_token"] and data["refresh_token"]
    user = await db.get(User, uuid.UUID(data["user"]["id"]))
    assert user.hermes_profile.startswith("u")
    assert (provisioning.profile_dir(user.hermes_profile) / "config.yaml").exists()


async def test_register_duplicate_email_conflict(register, client):
    await register(email="dup@test.local")
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "dup@test.local",
            "password": "Passw0rd!",
            "display_name": "Dup",
            "security_questions": [
                {"question": "Q1?", "answer": "a"},
                {"question": "Q2?", "answer": "b"},
            ],
        },
    )
    assert resp.status_code == 409


async def test_register_requires_two_questions(client):
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "bad@test.local",
            "password": "Passw0rd!",
            "display_name": "Bad",
            "security_questions": [{"question": "Q1?", "answer": "a"}],
        },
    )
    assert resp.status_code == 422


async def test_login_success(register, client):
    await register(email="login@test.local", password="Passw0rd!")
    resp = await client.post("/api/auth/login", json={"email": "login@test.local", "password": "Passw0rd!"})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "login@test.local"


async def test_login_wrong_password(register, client):
    await register(email="wp@test.local", password="Passw0rd!")
    resp = await client.post("/api/auth/login", json={"email": "wp@test.local", "password": "bad"})
    assert resp.status_code == 401


async def test_login_unknown_email(client):
    resp = await client.post("/api/auth/login", json={"email": "nobody@test.local", "password": "Passw0rd!"})
    assert resp.status_code == 401


async def test_refresh_rotation(register, client):
    data = await register(email="refresh@test.local")
    old_refresh = data["refresh_token"]
    resp = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    new = resp.json()
    assert new["refresh_token"] != old_refresh
    # old refresh token is revoked
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401


async def test_logout_revokes_refresh(register, client):
    data = await register(email="logout@test.local")
    resp = await client.post("/api/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 204
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert reuse.status_code == 401


async def test_security_questions(register, client):
    await register(email="sq@test.local")
    resp = await client.get("/api/auth/security-questions", params={"email": "sq@test.local"})
    assert resp.status_code == 200
    questions = resp.json()
    assert len(questions) == 2
    assert {q["position"] for q in questions} == {0, 1}


async def test_security_questions_unknown_email(client):
    resp = await client.get("/api/auth/security-questions", params={"email": "ghost@test.local"})
    assert resp.status_code == 404


async def test_reset_password_success(register, client):
    data = await register(email="reset@test.local", password="OldPassw0rd!")
    resp = await client.post(
        "/api/auth/reset-password",
        json={"email": "reset@test.local", "answers": ["alpha", "beta"], "new_password": "NewPassw0rd!"},
    )
    assert resp.status_code == 204
    # old password no longer works
    old = await client.post("/api/auth/login", json={"email": "reset@test.local", "password": "OldPassw0rd!"})
    assert old.status_code == 401
    # new password works
    new = await client.post("/api/auth/login", json={"email": "reset@test.local", "password": "NewPassw0rd!"})
    assert new.status_code == 200
    # previous refresh token revoked
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert reuse.status_code == 401


async def test_reset_wrong_answer(register, client):
    await register(email="wa@test.local")
    resp = await client.post(
        "/api/auth/reset-password",
        json={"email": "wa@test.local", "answers": ["wrong", "beta"], "new_password": "NewPassw0rd!"},
    )
    assert resp.status_code == 400


async def test_reset_lockout_after_five_failures(register, client):
    await register(email="lock@test.local")
    payload = {"email": "lock@test.local", "answers": ["no", "no"], "new_password": "NewPassw0rd!"}
    for _ in range(5):
        resp = await client.post("/api/auth/reset-password", json=payload)
        assert resp.status_code == 400
    # sixth attempt is locked, even with correct answers
    locked = await client.post(
        "/api/auth/reset-password",
        json={"email": "lock@test.local", "answers": ["alpha", "beta"], "new_password": "NewPassw0rd!"},
    )
    assert locked.status_code == 429


async def test_me_requires_auth(client):
    resp = await client.get("/api/users/me")
    assert resp.status_code == 401


async def test_me_returns_user(register, client):
    data = await register(email="me@test.local", display_name="Me")
    resp = await client.get("/api/users/me", headers=auth_header(data["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@test.local"