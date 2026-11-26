import smtplib
import uuid

from app.core.config import get_settings
from app.db.models import User
from app.services import email as email_service
from tests.conftest import auth_header


async def test_register_creates_user_and_profile(register, db):
    data = await register(email="alice@test.local", display_name="Alice")
    assert data["user"]["email"] == "alice@test.local"
    assert data["user"]["role"] == "user"
    assert data["user"]["email_verified_at"] is not None
    assert data["access_token"] and data["refresh_token"]
    user = await db.get(User, uuid.UUID(data["user"]["id"]))
    assert user.agent_namespace.startswith("u")
    assert len(user.agent_api_key) == 64
    assert user.email_verified_at is not None


async def test_register_requires_valid_email_code(client, sent_emails):
    resp = await client.post("/api/auth/email-code", json={"email": "new@test.local", "purpose": "register"})
    assert resp.status_code == 200
    assert sent_emails[-1]["to"] == "new@test.local"
    assert len(sent_emails[-1]["code"]) == 6

    bad = await client.post(
        "/api/auth/register",
        json={
            "email": "new@test.local",
            "code": "000000" if sent_emails[-1]["code"] != "000000" else "999999",
            "password": "Passw0rd!",
            "display_name": "NewUser",
        },
    )
    assert bad.status_code == 400


async def test_register_duplicate_email_conflict(register, client):
    await register(email="dup@test.local")
    code_resp = await client.post("/api/auth/email-code", json={"email": "dup@test.local", "purpose": "register"})
    assert code_resp.status_code == 409

    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "dup@test.local",
            "code": "123456",
            "password": "Passw0rd!",
            "display_name": "Dup",
        },
    )
    assert resp.status_code == 409


async def test_email_code_cooldown_and_smtp_failure_clears_cooldown(client, monkeypatch):
    resp1 = await client.post("/api/auth/email-code", json={"email": "cd@test.local", "purpose": "register"})
    assert resp1.status_code == 200

    resp2 = await client.post("/api/auth/email-code", json={"email": "cd@test.local", "purpose": "register"})
    assert resp2.status_code == 429

    async def _fail_send(*args, **kwargs):
        raise email_service.EmailDeliveryError("发送失败")

    monkeypatch.setattr(email_service, "send_email", _fail_send)
    fail = await client.post("/api/auth/email-code", json={"email": "cd2@test.local", "purpose": "register"})
    assert fail.status_code == 503

    # Cooldown must not linger when SMTP delivery failed.
    sent_again = []

    async def _ok_send(to_email, subject, text_body, html_body):
        sent_again.append(to_email)

    monkeypatch.setattr(email_service, "send_email", _ok_send)
    retry = await client.post("/api/auth/email-code", json={"email": "cd2@test.local", "purpose": "register"})
    assert retry.status_code == 200
    assert sent_again == ["cd2@test.local"]


async def test_login_success(register, client):
    await register(email="login@test.local", password="Passw0rd!", display_name="LoginUser")
    resp = await client.post("/api/auth/login", json={"email": "login@test.local", "password": "Passw0rd!"})
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "login@test.local"

    # Login with username (case-insensitive) using identifier or email field.
    by_name = await client.post("/api/auth/login", json={"identifier": "loginuser", "password": "Passw0rd!"})
    assert by_name.status_code == 200
    assert by_name.json()["user"]["email"] == "login@test.local"

    by_name_exact = await client.post("/api/auth/login", json={"identifier": "LoginUser", "password": "Passw0rd!"})
    assert by_name_exact.status_code == 200
    assert by_name_exact.json()["user"]["display_name"] == "LoginUser"


async def test_username_globally_unique_and_updatable(register, client, sent_emails):
    first = await register(email="u1@test.local", password="Passw0rd!", display_name="UniqueAlice")
    await register(email="u2@test.local", password="Passw0rd!", display_name="UniqueBob")

    # Registering with a colliding username (different case) must fail with 409.
    code_resp = await client.post("/api/auth/email-code", json={"email": "u3@test.local", "purpose": "register"})
    assert code_resp.status_code == 200
    dup = await client.post(
        "/api/auth/register",
        json={
            "email": "u3@test.local",
            "code": sent_emails[-1]["code"],
            "password": "Passw0rd!",
            "display_name": "uniquealice",
        },
    )
    assert dup.status_code == 409

    # Registering with '@' in username is rejected.
    bad_at = await client.post(
        "/api/auth/register",
        json={
            "email": "u3@test.local",
            "code": sent_emails[-1]["code"],
            "password": "Passw0rd!",
            "display_name": "alice@test",
        },
    )
    assert bad_at.status_code == 422

    # Updating profile to another user's username fails with 409.
    conflict = await client.patch(
        "/api/users/me",
        json={"display_name": "uniquebob"},
        headers=auth_header(first["access_token"]),
    )
    assert conflict.status_code == 409

    # Updating own username to a new unique name succeeds and updates login identifier.
    renamed = await client.patch(
        "/api/users/me",
        json={"display_name": "AliceRenamed"},
        headers=auth_header(first["access_token"]),
    )
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "AliceRenamed"

    old_login = await client.post("/api/auth/login", json={"identifier": "UniqueAlice", "password": "Passw0rd!"})
    assert old_login.status_code == 401
    new_login = await client.post("/api/auth/login", json={"identifier": "alicerenamed", "password": "Passw0rd!"})
    assert new_login.status_code == 200
    assert new_login.json()["user"]["email"] == "u1@test.local"


async def test_extended_profile_fields_update_and_validation(register, client):
    data = await register(email="profile@test.local", display_name="ProfileUser")
    headers = auth_header(data["access_token"])

    # Invalid avatar URL and phone should be rejected.
    bad_avatar = await client.patch("/api/users/me", json={"avatar_url": "javascript:alert(1)"}, headers=headers)
    assert bad_avatar.status_code == 422
    bad_phone = await client.patch("/api/users/me", json={"phone": "abc"}, headers=headers)
    assert bad_phone.status_code == 422

    updated = await client.patch(
        "/api/users/me",
        json={
            "bio": "专注于 AI 工程化落地",
            "gender": "非二元",
            "birthday": "1998-06-14",
            "phone": "+86 138 0013 8000",
            "location": "上海",
            "occupation": "全栈工程师",
            "website": "https://whitz.dev",
            "preferred_language": "zh-CN",
            "timezone": "Asia/Shanghai",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["bio"] == "专注于 AI 工程化落地"
    assert body["gender"] == "非二元"
    assert body["birthday"] == "1998-06-14"
    assert body["phone"] == "+86 138 0013 8000"
    assert body["location"] == "上海"
    assert body["occupation"] == "全栈工程师"
    assert body["website"] == "https://whitz.dev"
    assert body["preferred_language"] == "zh-CN"
    assert body["timezone"] == "Asia/Shanghai"

    # Upload 1x1 PNG avatar via PUT /api/users/me/avatar, fetch it, then delete it.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    up = await client.put(
        "/api/users/me/avatar",
        json={"data_url": f"data:image/png;base64,{tiny_png_b64}"},
        headers=headers,
    )
    assert up.status_code == 200, up.text
    avatar_url = up.json()["avatar_url"]
    assert avatar_url and avatar_url.startswith("/api/users/")

    fetched = await client.get(avatar_url)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"

    deleted = await client.delete("/api/users/me/avatar", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["avatar_url"] is None

    me = await client.get("/api/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["occupation"] == "全栈工程师"
    assert me.json()["gender"] == "非二元"


async def test_avatar_upload_falls_back_when_data_dir_unwritable(monkeypatch, register, client):
    """APP_DATA_DIR 不可写时（容器卷属主不匹配）不能抛 500，应降级到临时目录。"""
    import shutil
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace

    from app.api.routes import users as users_routes

    workdir = Path(tempfile.mkdtemp(prefix="whitz-avatar-fallback-"))
    blocked = workdir / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    fallback_root = workdir / "tmp"
    fallback_root.mkdir()

    monkeypatch.setattr(users_routes, "get_settings", lambda: SimpleNamespace(app_data_path=blocked / "data"))
    monkeypatch.setattr(users_routes.tempfile, "gettempdir", lambda: str(fallback_root))
    users_routes._reset_avatars_dir_cache()
    try:
        data = await register(email="avatar-fallback@test.local", display_name="AvatarFallback")
        headers = auth_header(data["access_token"])
        tiny_png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        up = await client.put(
            "/api/users/me/avatar",
            json={"data_url": f"data:image/png;base64,{tiny_png_b64}"},
            headers=headers,
        )
        assert up.status_code == 200, up.text
        stored = fallback_root / "whitz-avatars" / f"{data['user']['id']}.png"
        assert stored.is_file()

        fetched = await client.get(up.json()["avatar_url"])
        assert fetched.status_code == 200
        assert fetched.headers["content-type"] == "image/png"
    finally:
        users_routes._reset_avatars_dir_cache()
        shutil.rmtree(workdir, ignore_errors=True)


async def test_login_with_email_code(register, client, sent_emails):
    await register(email="codelogin@test.local", password="Passw0rd!")

    unknown = await client.post("/api/auth/email-code", json={"email": "nobody@test.local", "purpose": "login"})
    assert unknown.status_code == 404

    send = await client.post("/api/auth/email-code", json={"email": "codelogin@test.local", "purpose": "login"})
    assert send.status_code == 200
    code = sent_emails[-1]["code"]

    bad = await client.post("/api/auth/login/code", json={"email": "codelogin@test.local", "code": "000001" if code != "000001" else "000002"})
    assert bad.status_code == 400

    ok = await client.post("/api/auth/login/code", json={"email": "codelogin@test.local", "code": code})
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == "codelogin@test.local"

    # Code is single-use.
    reuse = await client.post("/api/auth/login/code", json={"email": "codelogin@test.local", "code": code})
    assert reuse.status_code == 400


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
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401


async def test_logout_revokes_refresh(register, client):
    data = await register(email="logout@test.local")
    resp = await client.post("/api/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 204
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert reuse.status_code == 401


async def test_reset_password_with_email_code(register, client, sent_emails):
    data = await register(email="reset@test.local", password="OldPassw0rd!")

    unknown = await client.post(
        "/api/auth/email-code",
        json={"email": "ghost@test.local", "purpose": "reset_password"},
    )
    assert unknown.status_code == 404

    send = await client.post(
        "/api/auth/email-code",
        json={"email": "reset@test.local", "purpose": "reset_password"},
    )
    assert send.status_code == 200
    code = sent_emails[-1]["code"]

    resp = await client.post(
        "/api/auth/reset-password",
        json={"email": "reset@test.local", "code": code, "new_password": "NewPassw0rd!"},
    )
    assert resp.status_code == 204

    old = await client.post("/api/auth/login", json={"email": "reset@test.local", "password": "OldPassw0rd!"})
    assert old.status_code == 401
    new = await client.post("/api/auth/login", json={"email": "reset@test.local", "password": "NewPassw0rd!"})
    assert new.status_code == 200
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert reuse.status_code == 401


async def test_reset_code_invalidated_after_five_failures(register, client, sent_emails):
    await register(email="lock@test.local")
    send = await client.post(
        "/api/auth/email-code",
        json={"email": "lock@test.local", "purpose": "reset_password"},
    )
    assert send.status_code == 200
    valid_code = sent_emails[-1]["code"]
    wrong_code = "000000" if valid_code != "000000" else "999999"

    for _ in range(5):
        resp = await client.post(
            "/api/auth/reset-password",
            json={"email": "lock@test.local", "code": wrong_code, "new_password": "NewPassw0rd!"},
        )
        assert resp.status_code == 400

    # Even the previously valid code is now invalidated.
    after = await client.post(
        "/api/auth/reset-password",
        json={"email": "lock@test.local", "code": valid_code, "new_password": "NewPassw0rd!"},
    )
    assert after.status_code == 400


async def test_security_questions_endpoints_removed(register, client):
    data = await register(email="removed@test.local")
    get_sq = await client.get("/api/auth/security-questions", params={"email": "removed@test.local"})
    assert get_sq.status_code == 404
    put_sq = await client.put(
        "/api/users/me/security-questions",
        json={"password": "Passw0rd!", "security_questions": []},
        headers=auth_header(data["access_token"]),
    )
    assert put_sq.status_code == 404


async def test_me_requires_auth(client):
    resp = await client.get("/api/users/me")
    assert resp.status_code == 401


async def test_me_returns_user(register, client):
    data = await register(email="me@test.local", display_name="Me")
    resp = await client.get("/api/users/me", headers=auth_header(data["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@test.local"


async def test_refresh_from_cookie(register, client):
    data = await register(email="cookie@test.local")
    assert data["refresh_expires_in"] == 15 * 86400
    resp = await client.post("/api/auth/refresh", json={})
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    logout = await client.post("/api/auth/logout", json={})
    assert logout.status_code == 204
    reuse = await client.post("/api/auth/refresh", json={})
    assert reuse.status_code == 401


async def test_password_change_keeps_current_device_and_revokes_others(register, client):
    data = await register(email="rotate@test.local", password="Passw0rd!")
    other = await client.post(
        "/api/auth/login",
        json={"email": "rotate@test.local", "password": "Passw0rd!"},
        headers={"User-Agent": "OtherDevice/1.0"},
    )
    assert other.status_code == 200
    other_access = other.json()["access_token"]
    other_refresh = other.json()["refresh_token"]

    change = await client.put(
        "/api/users/me/password",
        json={"old_password": "Passw0rd!", "new_password": "NewPassw0rd!"},
        headers=auth_header(data["access_token"]),
    )
    assert change.status_code == 204

    # The device that changed the password stays signed in...
    current = await client.get("/api/users/me", headers=auth_header(data["access_token"]))
    assert current.status_code == 200
    # ...while every other device is revoked immediately.
    stale = await client.get("/api/users/me", headers=auth_header(other_access))
    assert stale.status_code == 401
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": other_refresh})
    assert reuse.status_code == 401


async def test_smtp_send_qq_ssl_handles_quit_disconnect(monkeypatch):
    # Use real send_email implementation for this unit test by restoring it from module reload or testing _send_sync
    events: list[tuple] = []

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout=None, context=None):
            events.append(("connect", host, port))

        def login(self, user, password):
            events.append(("login", user, password))

        def send_message(self, msg, from_addr=None, to_addrs=None):
            events.append(("send", from_addr, to_addrs, msg["Subject"]))

        def quit(self):
            events.append(("quit",))
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

        def close(self):
            events.append(("close",))

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setenv("SMTP_HOST", "smtp.qq.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USERNAME", "123456@qq.com")
    monkeypatch.setenv("SMTP_PASSWORD", "authcode12345678")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "")
    monkeypatch.setenv("SMTP_USE_SSL", "true")
    get_settings.cache_clear()
    try:
        from email.headerregistry import Address
        from email.message import EmailMessage

        settings = get_settings()
        msg = EmailMessage()
        msg["Subject"] = "Whitz 登录验证码"
        msg["From"] = Address(display_name="Whitz", addr_spec="123456@qq.com")
        msg["To"] = "user@qq.com"
        msg.set_content("验证码：123456")

        email_service._send_sync(msg, "123456@qq.com", "user@qq.com", settings)
        assert events == [
            ("connect", "smtp.qq.com", 465),
            ("login", "123456@qq.com", "authcode12345678"),
            ("send", "123456@qq.com", ["user@qq.com"], "Whitz 登录验证码"),
            ("quit",),
            ("close",),
        ]
    finally:
        get_settings.cache_clear()
