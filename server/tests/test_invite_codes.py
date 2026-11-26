import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import InviteCode
from tests.conftest import auth_header


async def _create_code(client, admin, **overrides) -> dict:
    payload = {"tier": "plus", "duration_days": 30, "max_uses": 1}
    payload.update(overrides)
    resp = await client.post(
        "/api/admin/invite-codes", json=payload, headers=auth_header(admin["access_token"])
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _redeem(client, user, code: str):
    return await client.post(
        "/api/users/me/redeem",
        json={"code": code},
        headers=auth_header(user["access_token"]),
    )


async def test_admin_creates_and_lists_codes(admin, client):
    row = await _create_code(client, admin, note="首批内测")
    assert row["code"].startswith("WZ-")
    assert row["tier"] == "plus"
    assert row["used_count"] == 0

    resp = await client.get("/api/admin/invite-codes", headers=auth_header(admin["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    assert any(item["code"] == row["code"] for item in body["items"])


async def test_redeem_upgrades_user(admin, register, client):
    row = await _create_code(client, admin)
    user = await register(email="plus@test.local")
    resp = await _redeem(client, user, row["code"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tier"] == "plus"
    from app.services.membership import PLANS

    assert body["weekly"]["limit"] == PLANS["plus"].weekly_credits
    assert body["five_hour"]["limit"] == PLANS["plus"].five_hour_credits
    expires = datetime.fromisoformat(body["expires_at"])
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(days=29) < delta < timedelta(days=31)

    resp = await client.get("/api/users/me", headers=auth_header(user["access_token"]))
    assert resp.json()["membership_tier"] == "plus"


async def test_same_tier_renewal_extends_expiry(admin, register, client):
    first = await _create_code(client, admin)
    second = await _create_code(client, admin)
    user = await register(email="renew@test.local")

    one = await _redeem(client, user, first["code"])
    assert one.status_code == 200, one.text
    first_expiry = datetime.fromisoformat(one.json()["expires_at"])

    two = await _redeem(client, user, second["code"])
    assert two.status_code == 200, two.text
    second_expiry = datetime.fromisoformat(two.json()["expires_at"])
    assert second_expiry - first_expiry == timedelta(days=30)


async def test_same_code_cannot_be_reused_by_one_user(admin, register, client):
    row = await _create_code(client, admin, max_uses=5)
    user = await register(email="reuse@test.local")
    assert (await _redeem(client, user, row["code"])).status_code == 200
    again = await _redeem(client, user, row["code"])
    assert again.status_code == 400
    assert "已使用" in again.json()["detail"]


async def test_downgrade_is_rejected(admin, register, client):
    pro = await _create_code(client, admin, tier="pro")
    plus = await _create_code(client, admin, tier="plus")
    user = await register(email="downgrade@test.local")
    assert (await _redeem(client, user, pro["code"])).status_code == 200
    resp = await _redeem(client, user, plus["code"])
    assert resp.status_code == 400
    assert "降级" in resp.json()["detail"]


async def test_max_uses_is_enforced(admin, register, client):
    row = await _create_code(client, admin, max_uses=1)
    first = await register(email="first@test.local")
    second = await register(email="second@test.local")
    assert (await _redeem(client, first, row["code"])).status_code == 200
    resp = await _redeem(client, second, row["code"])
    assert resp.status_code == 400
    assert "用完" in resp.json()["detail"]


async def test_disabled_code_is_rejected(admin, register, client):
    row = await _create_code(client, admin)
    resp = await client.patch(
        f"/api/admin/invite-codes/{row['id']}",
        json={"is_active": False},
        headers=auth_header(admin["access_token"]),
    )
    assert resp.status_code == 200, resp.text
    user = await register(email="disabled@test.local")
    redeem = await _redeem(client, user, row["code"])
    assert redeem.status_code == 400
    assert "停用" in redeem.json()["detail"]


async def test_expired_code_is_rejected(admin, register, client, db):
    row = await _create_code(client, admin, expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    stored = await db.get(InviteCode, uuid.UUID(row["id"]))
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    user = await register(email="expired-code@test.local")
    resp = await _redeem(client, user, row["code"])
    assert resp.status_code == 400
    assert "过期" in resp.json()["detail"]


async def test_admin_rejects_past_expiry(admin, client):
    resp = await client.post(
        "/api/admin/invite-codes",
        json={
            "tier": "plus",
            "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        },
        headers=auth_header(admin["access_token"]),
    )
    assert resp.status_code == 400


async def test_unknown_code_is_rejected(register, client):
    user = await register(email="unknown@test.local")
    resp = await _redeem(client, user, "WZ-AAAA-BBBB-CCCC-DDDD")
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"]
