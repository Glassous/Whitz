from __future__ import annotations

import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.api.schemas import CreditStatusOut, SkillOut, SkillPendingOut, UserCreditLedgerItemOut
from app.services import membership, pricing, schedule_calc, sessions_service, skills_service


def test_schedule_interval_preserves_seconds_no_shortening():
    now = datetime(2026, 6, 1, 10, 0, 45, 500000, tzinfo=timezone.utc)
    nxt = schedule_calc.compute_next_run_at("interval", {"every_minutes": 1}, "UTC", after_dt=now)
    assert nxt is not None
    # Previously replaced second=0 -> 10:01:00 (only 15s later!). Now strictly >= 60s later!
    delta = (nxt - now.replace(microsecond=0)).total_seconds()
    assert delta == 60.0


def test_skills_validate_url_blocks_non_github_and_ip():
    with pytest.raises(skills_service.SkillSsrfError):
        skills_service._validate_remote_url("http://github.com/org/repo")
    with pytest.raises(skills_service.SkillSsrfError):
        skills_service._validate_remote_url("https://127.0.0.1/org/repo")
    with pytest.raises(skills_service.SkillSsrfError):
        skills_service._validate_remote_url("https://evil.example.com/org/repo")
    assert (
        skills_service._validate_remote_url("https://github.com/org/repo")
        == "https://github.com/org/repo"
    )


def test_skills_validate_url_fail_closed_on_dns_error(monkeypatch):
    def boom(*a, **kw):
        raise OSError("dns failure")

    monkeypatch.setattr("socket.getaddrinfo", boom)
    with pytest.raises(skills_service.SkillSsrfError):
        skills_service._validate_remote_url("https://github.com/org/repo", resolve_dns=True)


def test_skill_out_and_pending_include_files_manifest():
    s = SkillOut(name="demo", files=["SKILL.md", "references/guide.md"])
    assert s.files == ["SKILL.md", "references/guide.md"]
    p = SkillPendingOut(id="p1", name="demo", content="# hi", files=["SKILL.md"])
    assert p.files == ["SKILL.md"]


def test_membership_credit_status_schema_includes_bonus_and_ledger():
    now = datetime.now(timezone.utc)
    item = UserCreditLedgerItemOut(
        id=1,
        created_at=now,
        tokens=50000,
        credits=10.0,
        kind="adjust",
        bucket="bonus",
        tier="free",
        note="活动赠送",
    )
    assert item.bucket == "bonus"
    assert item.credits == 10.0

    plan = membership.plan_payload(membership.plan_for("free"))
    cs = CreditStatusOut(
        tier="free",
        tier_label="Free",
        expires_at=None,
        anchor_at=now.isoformat(),
        tokens_per_credit=5000,
        weekly={"limit": 100, "used": 20.0, "remaining": 80.0, "reset_at": now.isoformat()},
        five_hour={"limit": 20, "used": 5.0, "remaining": 15.0, "reset_at": now.isoformat()},
        bonus_credits=50.0,
        remaining=65.0,
        overdrawn=False,
        plan=plan,
        plans=membership.plans_payload(),
    )
    assert cs.bonus_credits == 50.0
    assert cs.remaining == 65.0


@pytest.mark.asyncio
async def test_membership_bonus_credits_survive_rolling_window_reset(monkeypatch):
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    user = types.SimpleNamespace(
        id=uuid.uuid4(),
        membership_tier="free",
        membership_expires_at=None,
        credit_anchor_at=now - timedelta(days=10),
        created_at=now - timedelta(days=10),
    )

    async def fake_net_tokens(db, user_id, start, end=None, *, bucket="plan"):
        # Plan window used 10 credits (50,000 tokens)
        return -50000

    async def fake_bonus_tokens(db, user_id):
        # Admin granted 30 bonus credits (150,000 tokens) weeks ago
        return 150000

    monkeypatch.setattr(membership, "_net_tokens", fake_net_tokens)
    monkeypatch.setattr(membership, "_bonus_tokens", fake_bonus_tokens)

    info = await membership.status(None, user, now=now)
    # Free 5h limit is 20 -> 20 - 10 = 10 plan remaining; + 30 bonus = 40 total!
    assert info["five_hour"]["remaining"] == 10.0
    assert info["bonus_credits"] == 30.0
    assert info["remaining"] == 40.0


@pytest.mark.asyncio
async def test_pricing_custom_rates_cache_and_invalidation():
    pricing.invalidate_custom_rates_cache()
    calls = 0

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [
                types.SimpleNamespace(
                    id=uuid.uuid4(),
                    model_pattern="custom-model",
                    display_name="Custom",
                    input_usd_per_1m=1.0,
                    output_usd_per_1m=2.0,
                    is_active=True,
                    updated_at=None,
                )
            ]

    class FakeDb:
        async def execute(self, stmt):
            nonlocal calls
            calls += 1
            return FakeResult()

    db = FakeDb()
    r1 = await pricing.list_custom_rates(db)
    r2 = await pricing.list_custom_rates(db)
    assert calls == 1
    assert r1[0]["model_pattern"] == "custom-model"
    assert r2[0]["model_pattern"] == "custom-model"

    pricing.invalidate_custom_rates_cache()
    await pricing.list_custom_rates(db)
    assert calls == 2


@pytest.mark.asyncio
async def test_sessions_service_uses_batch_mget(monkeypatch):
    sid1, sid2 = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    fake_rows = [
        types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=sid1,
            family_id=sid1,
            user_agent="UA1",
            client_ip="1.1.1.1",
            last_used_at=now,
            created_at=now - timedelta(hours=1),
            expires_at=now + timedelta(days=7),
        ),
        types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=sid2,
            family_id=sid2,
            user_agent="UA2",
            client_ip="2.2.2.2",
            last_used_at=now - timedelta(minutes=10),
            created_at=now - timedelta(hours=2),
            expires_at=now + timedelta(days=7),
        ),
    ]

    class FakeRes:
        def scalars(self):
            return self

        def all(self):
            return fake_rows

    class FakeDb:
        async def execute(self, stmt):
            return FakeRes()

    batch_called = 0

    async def fake_are_revoked(sids):
        nonlocal batch_called
        batch_called += 1
        return {sid1: False, sid2: True}

    monkeypatch.setattr(sessions_service, "are_sessions_revoked", fake_are_revoked)

    out = await sessions_service.list_user_active_sessions(
        FakeDb(),
        uuid.uuid4(),
        current_session_id=sid1,
    )
    assert batch_called == 1
    assert len(out) == 1
    assert out[0].session_id == sid1
    assert out[0].is_current is True
