import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db.models import CreditLedger, User
from app.services import membership
from tests.conftest import auth_header


def test_window_bounds_roll_from_anchor():
    anchor = datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc)
    start, reset = membership.window_bounds(anchor, timedelta(days=7), anchor + timedelta(days=8))
    assert start == anchor + timedelta(days=7)
    assert reset == anchor + timedelta(days=14)

    start, reset = membership.window_bounds(anchor, timedelta(hours=5), anchor + timedelta(hours=7))
    assert start == anchor + timedelta(hours=5)
    assert reset == anchor + timedelta(hours=10)

    # Before the anchor the window clamps to the anchor itself.
    start, reset = membership.window_bounds(anchor, timedelta(days=7), anchor - timedelta(days=2))
    assert start == anchor
    assert reset == anchor + timedelta(days=7)


def test_plan_matrix():
    free = membership.plan_for("free")
    plus = membership.plan_for("plus")
    pro = membership.plan_for("pro")
    assert (free.weekly_credits, free.five_hour_credits) == (100, 20)
    assert (plus.weekly_credits, plus.five_hour_credits) == (500, 100)
    assert (pro.weekly_credits, pro.five_hour_credits) == (1250, None)
    assert len(membership.plans_payload()) == 3


def test_effective_tier_ignores_lapsed_membership():
    user = User(
        email="tier@test.local",
        password_hash="x",
        display_name="T",
        hermes_profile="p",
        hermes_api_key="k",
        membership_tier="plus",
        membership_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        credit_anchor_at=datetime.now(timezone.utc),
    )
    assert membership.effective_tier(user) == "free"
    user.membership_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    assert membership.effective_tier(user) == "plus"


async def test_status_and_exhaustion(register, db):
    data = await register(email="credits@test.local")
    user = await db.get(User, uuid.UUID(data["user"]["id"]))
    assert user is not None
    db.add(CreditLedger(user_id=user.id, tokens=-150_000, kind="consume"))
    await db.commit()

    info = await membership.status(db, user)
    assert info["tier"] == "free"
    assert info["weekly"]["used"] == 150.0
    assert info["five_hour"]["used"] == 150.0
    assert info["remaining"] == -130.0
    assert info["overdrawn"] is True
    assert await membership.credit_exhausted(db, user) is True


async def test_admin_grant_extends_quota(register, db):
    data = await register(email="grant@test.local")
    user = await db.get(User, uuid.UUID(data["user"]["id"]))
    assert user is not None
    db.add(CreditLedger(user_id=user.id, tokens=-15_000, kind="consume"))
    await db.commit()
    assert (await membership.status(db, user))["remaining"] == 5.0

    await membership.adjust(db, user, 20, note="test grant")
    info = await membership.status(db, user)
    assert info["remaining"] == 25.0
    assert info["weekly"]["used"] == 0.0
    assert info["five_hour"]["used"] == 0.0


async def test_settle_is_idempotent(register, db):
    data = await register(email="settle@test.local")
    user_id = uuid.UUID(data["user"]["id"])
    message_id = uuid.uuid4()

    assert await membership.settle(db, user_id, 5_000, message_id=message_id) is True
    assert await membership.settle(db, user_id, 5_000, message_id=message_id) is False

    total = await db.scalar(
        select(func.sum(CreditLedger.tokens)).where(CreditLedger.user_id == user_id)
    )
    assert total == -5_000


async def test_credits_endpoint(register, client):
    data = await register(email="endpoint@test.local")
    resp = await client.get("/api/users/me/credits", headers=auth_header(data["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tier"] == "free"
    assert body["tier_label"] == "Free"
    assert body["weekly"]["limit"] == 100
    assert body["five_hour"]["limit"] == 20
    assert body["tokens_per_credit"] == 1000
    assert body["remaining"] == 20.0
    assert body["overdrawn"] is False
    assert [plan["tier"] for plan in body["plans"]] == ["free", "plus", "pro"]


async def test_chat_blocked_when_credits_exhausted(register, client, db):
    data = await register(email="gated@test.local")
    token = data["access_token"]
    conv = (
        await client.post("/api/conversations", json={"title": "额度测试"}, headers=auth_header(token))
    ).json()
    nonce = "nonce-12345678"
    ticket = await client.post(
        f"/api/conversations/{conv['id']}/tickets",
        json={"action": "send", "nonce": nonce},
        headers=auth_header(token),
    )
    assert ticket.status_code == 200, ticket.text

    user = await db.get(User, uuid.UUID(data["user"]["id"]))
    assert user is not None
    db.add(CreditLedger(user_id=user.id, tokens=-200_000, kind="consume"))
    await db.commit()

    resp = await client.post(
        f"/api/conversations/{conv['id']}/messages",
        json={"content": "你好"},
        headers={
            **auth_header(token),
            "X-Chat-Ticket": ticket.json()["ticket"],
            "X-Chat-Nonce": nonce,
        },
    )
    assert resp.status_code == 402, resp.text
    assert "积分已用尽" in resp.json()["detail"]


async def test_expired_membership_normalizes_to_free(register, client, db):
    data = await register(email="expired@test.local")
    user = await db.get(User, uuid.UUID(data["user"]["id"]))
    assert user is not None
    user.membership_tier = "pro"
    user.membership_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    resp = await client.get("/api/users/me/credits", headers=auth_header(data["access_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["tier"] == "free"

    await db.refresh(user)
    assert user.membership_tier == "free"
    assert user.membership_expires_at is None
