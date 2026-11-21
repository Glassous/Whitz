import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api.routes import admin as admin_routes
from app.core.config import get_settings
from app.core.security import decode_access_claims, is_session_revoked
from app.db.models import (
    AuditLog,
    Conversation,
    ConversationFile,
    CreditLedger,
    Message,
    RefreshToken,
    UsageDaily,
    User,
)
from app.services import membership
from app.services.agent_client import AgentError
from tests.conftest import auth_header


async def test_admin_analytics_requires_admin(register, client):
    user = await register(email="plain-analytics@test.local")
    headers = auth_header(user["access_token"])
    uid = user["user"]["id"]
    fake_id = str(uuid.uuid4())

    for method, path in [
        ("GET", "/api/admin/analytics"),
        ("GET", "/api/admin/monitor"),
        ("POST", f"/api/admin/conversations/{fake_id}/stop"),
        ("GET", f"/api/admin/users/{uid}"),
        ("GET", f"/api/admin/users/{uid}/ledger"),
        ("GET", f"/api/admin/users/{uid}/sessions"),
        ("DELETE", f"/api/admin/users/{uid}/sessions/{fake_id}"),
        ("GET", f"/api/admin/invite-codes/{fake_id}/redemptions"),
    ]:
        resp = await client.request(method, path, headers=headers)
        assert resp.status_code == 403, f"{method} {path} returned {resp.status_code}"


async def test_admin_analytics_fills_gaps_top_users_files_and_summary(admin, register, client, db):
    now = datetime.now(timezone.utc)
    today = now.date()
    day_2_ago = today - timedelta(days=2)
    day_6_ago = today - timedelta(days=6)
    out_of_window = today - timedelta(days=12)

    u1_data = await register(email="top1@test.local", display_name="TopOne")
    u2_data = await register(email="top2@test.local", display_name="TopTwo")
    u3_data = await register(email="expired-plus@test.local", display_name="ExpiredPlus")
    u1_id = uuid.UUID(u1_data["user"]["id"])
    u2_id = uuid.UUID(u2_data["user"]["id"])
    u3_id = uuid.UUID(u3_data["user"]["id"])

    # Set u1 created_at 2 days ago, u2 6 days ago, u3 12 days ago + expired plus membership
    u1 = await db.get(User, u1_id)
    u2 = await db.get(User, u2_id)
    u3 = await db.get(User, u3_id)
    assert u1 and u2 and u3
    u1.created_at = datetime.combine(day_2_ago, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
    u2.created_at = datetime.combine(day_6_ago, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=8)
    u2.membership_tier = "pro"
    u2.membership_expires_at = now + timedelta(days=10)
    u3.created_at = datetime.combine(out_of_window, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=5)
    u3.membership_tier = "plus"
    u3.membership_expires_at = now - timedelta(minutes=5)

    # Seed extra users so we verify top_users limit=10
    extra_users: list[User] = []
    for idx in range(10):
        reg = await register(email=f"extra{idx}@test.local", display_name=f"Extra{idx}")
        extra_users.append(await db.get(User, uuid.UUID(reg["user"]["id"])))

    # Seed UsageDaily: u1 active on two separate days (must count once in summary.active_users!)
    db.add_all(
        [
            UsageDaily(user_id=u1_id, day=today, messages=4, tokens=15000, runs=2),
            UsageDaily(user_id=u1_id, day=day_2_ago, messages=3, tokens=10000, runs=2),
            UsageDaily(user_id=u2_id, day=day_6_ago, messages=2, tokens=5000, runs=1),
            # Out of 7-day window row should be excluded from 7-day query
            UsageDaily(user_id=u3_id, day=out_of_window, messages=99, tokens=999000, runs=99),
        ]
    )
    for idx, eu in enumerate(extra_users):
        db.add(UsageDaily(user_id=eu.id, day=today, messages=1, tokens=(idx + 1) * 500, runs=1))

    # Seed CreditLedger consumption and an admin adjustment (adjustment must not count as consumed credits)
    db.add_all(
        [
            CreditLedger(
                user_id=u1_id,
                tokens=-15000,
                kind="consume",
                tier="free",
                created_at=now,
            ),
            CreditLedger(
                user_id=u1_id,
                tokens=-10000,
                kind="consume",
                tier="free",
                created_at=datetime.combine(day_2_ago, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12),
            ),
            CreditLedger(
                user_id=u2_id,
                tokens=-5000,
                kind="consume",
                tier="pro",
                created_at=datetime.combine(day_6_ago, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=9),
            ),
            CreditLedger(
                user_id=u1_id,
                tokens=500000,
                kind="adjust",
                tier="free",
                created_at=now,
                note="manual grant",
            ),
            CreditLedger(
                user_id=u3_id,
                tokens=-50000,
                kind="consume",
                tier="plus",
                created_at=datetime.combine(out_of_window, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=2),
            ),
        ]
    )

    # Seed files for file_stats
    conv = Conversation(user_id=u1_id, thread_id="sess-f1", title="Files")
    db.add(conv)
    await db.flush()
    db.add_all(
        [
            ConversationFile(
                conversation_id=conv.id,
                user_id=u1_id,
                filename="doc.pdf",
                ext=".pdf",
                mime_type="application/pdf",
                category="document",
                size_bytes=1000,
                storage_key=f"k/{uuid.uuid4()}",
                status="ready",
                source="user",
                is_global=False,
            ),
            ConversationFile(
                conversation_id=None,
                user_id=u1_id,
                filename="global.md",
                ext=".md",
                mime_type="text/markdown",
                category="text",
                size_bytes=250,
                storage_key=f"k/{uuid.uuid4()}",
                status="ready",
                source="user",
                is_global=True,
            ),
            ConversationFile(
                conversation_id=conv.id,
                user_id=u1_id,
                filename="artifact.html",
                ext=".html",
                mime_type="text/html",
                category="text",
                size_bytes=500,
                storage_key=f"k/{uuid.uuid4()}",
                status="ready",
                source="assistant",
                is_global=False,
            ),
            ConversationFile(
                conversation_id=conv.id,
                user_id=u1_id,
                filename="pending.txt",
                ext=".txt",
                mime_type="text/plain",
                category="text",
                size_bytes=9999,
                storage_key=f"k/{uuid.uuid4()}",
                status="pending",
                source="user",
                is_global=False,
            ),
            ConversationFile(
                conversation_id=conv.id,
                user_id=u1_id,
                filename="failed.txt",
                ext=".txt",
                mime_type="text/plain",
                category="text",
                size_bytes=8888,
                storage_key=f"k/{uuid.uuid4()}",
                status="failed",
                source="user",
                is_global=False,
            ),
        ]
    )
    await db.commit()

    # Check bounds validation
    bad_low = await client.get("/api/admin/analytics?days=6", headers=auth_header(admin["access_token"]))
    assert bad_low.status_code == 422
    bad_high = await client.get("/api/admin/analytics?days=91", headers=auth_header(admin["access_token"]))
    assert bad_high.status_code == 422

    resp = await client.get("/api/admin/analytics?days=7", headers=auth_header(admin["access_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["days"] == 7
    assert body["start_day"] == day_6_ago.isoformat()
    assert body["end_day"] == today.isoformat()
    assert body["tokens_per_credit"] == 5000

    daily = body["daily"]
    assert len(daily) == 7
    assert [d["day"] for d in daily] == [
        (day_6_ago + timedelta(days=i)).isoformat() for i in range(7)
    ]

    by_day = {d["day"]: d for d in daily}
    # Gap day (e.g. yesterday) has zeros
    gap = by_day[(today - timedelta(days=1)).isoformat()]
    assert gap == {
        "day": (today - timedelta(days=1)).isoformat(),
        "messages": 0,
        "tokens": 0,
        "credits": 0.0,
        "runs": 0,
        "new_users": 0,
        "active_users": 0,
    }

    assert by_day[day_6_ago.isoformat()]["tokens"] == 5000
    assert by_day[day_6_ago.isoformat()]["credits"] == 1.0
    assert by_day[day_6_ago.isoformat()]["new_users"] == 1
    assert by_day[day_6_ago.isoformat()]["active_users"] == 1

    assert by_day[day_2_ago.isoformat()]["tokens"] == 10000
    assert by_day[day_2_ago.isoformat()]["credits"] == 2.0
    assert by_day[day_2_ago.isoformat()]["new_users"] == 1
    assert by_day[day_2_ago.isoformat()]["active_users"] == 1

    assert by_day[today.isoformat()]["tokens"] == 15000 + sum((i + 1) * 500 for i in range(10))
    assert by_day[today.isoformat()]["credits"] == 3.0
    assert by_day[today.isoformat()]["active_users"] == 11

    # Summary: u1 + u2 + 10 extra users = 12 distinct active users (not 13!)
    extra_tokens = sum((i + 1) * 500 for i in range(10))
    assert body["summary"]["total_messages"] == 4 + 3 + 2 + 10
    assert body["summary"]["total_tokens"] == 15000 + 10000 + 5000 + extra_tokens
    assert body["summary"]["total_credits"] == 6.0
    assert body["summary"]["total_runs"] == 2 + 2 + 1 + 10
    assert body["summary"]["active_users"] == 12
    # new_users in window = u1 (2d ago) + u2 (6d ago) + admin (today) + 10 extra (today) = 13 (u3 was 12d ago)
    assert body["summary"]["total_new_users"] == 13

    # Top users: max 10, sorted descending by tokens
    top_users = body["top_users"]
    assert len(top_users) == 10
    assert top_users[0]["email"] == "top1@test.local"
    assert top_users[0]["tokens"] == 25000
    assert top_users[0]["credits"] == 5.0
    assert top_users[0]["messages"] == 7
    assert top_users[0]["runs"] == 4
    # Second is either top2 or extra9 (both 5000 tokens); verify sorted order
    assert top_users[1]["tokens"] == 5000
    assert all(top_users[i]["tokens"] >= top_users[i + 1]["tokens"] for i in range(len(top_users) - 1))

    # Expired plus user normalized to free
    dist = body["membership_distribution"]
    assert dist["pro"] == 1
    assert dist["plus"] == 0
    assert dist["free"] == 1 + 1 + 1 + 10  # admin + u1 + expired u3 + 10 extras

    assert body["file_stats"] == {
        "total_files": 3,
        "total_bytes": 1750,
        "global_files": 1,
        "assistant_files": 1,
        "pending_files": 1,
    }


async def test_admin_monitor_and_force_stop_run(admin, register, client, db, monkeypatch):
    now = datetime.now(timezone.utc)
    u1_data = await register(email="runner@test.local", display_name="Runner")
    u1_id = uuid.UUID(u1_data["user"]["id"])

    # Create active normal run, stalled run, and idle conversation
    c_live = Conversation(
        user_id=u1_id,
        thread_id="s-live",
        title="Live Task",
        active_run_id="run-live",
        active_run_status="running",
        last_message_at=now - timedelta(seconds=15),
    )
    c_stalled = Conversation(
        user_id=u1_id,
        thread_id="s-stalled",
        title="Stalled Task",
        active_run_id="run-stalled",
        active_run_status="waiting_for_approval",
        last_message_at=now - timedelta(seconds=750),
    )
    c_idle = Conversation(
        user_id=u1_id,
        thread_id="s-idle",
        title="Idle Task",
        active_run_id=None,
        active_run_status=None,
        last_message_at=now - timedelta(minutes=5),
    )
    db.add_all([c_live, c_stalled, c_idle])
    await db.flush()

    m_stalled = Message(
        conversation_id=c_stalled.id,
        role="assistant",
        content="partial",
        status="waiting",
        run_id="run-stalled",
        created_at=now - timedelta(seconds=750),
    )
    m_live = Message(
        conversation_id=c_live.id,
        role="assistant",
        content="working",
        status="streaming",
        run_id="run-live",
        created_at=now - timedelta(seconds=15),
    )
    db.add_all([m_stalled, m_live])

    # Seed 22 failed assistant messages (only last 20 returned) + 1 failed user msg (ignored)
    for idx in range(22):
        db.add(
            Message(
                conversation_id=c_idle.id,
                role="assistant",
                content=f"fail-{idx}",
                status="failed",
                created_at=now - timedelta(minutes=idx + 1),
            )
        )
    db.add(
        Message(
            conversation_id=c_idle.id,
            role="user",
            content="user-msg",
            status="failed",
            created_at=now,
        )
    )

    # Seed AuditLog failures (including older >24h entry and success entry)
    db.add_all(
        [
            AuditLog(
                actor_email="attacker@test.local",
                action="chat.rate_limited",
                outcome="failure",
                severity="warning",
                created_at=now - timedelta(hours=2),
            ),
            AuditLog(
                actor_email="attacker@test.local",
                action="auth.login_failed",
                outcome="failure",
                severity="warning",
                created_at=now - timedelta(minutes=10),
            ),
            AuditLog(
                actor_email="runner@test.local",
                action="chat.credits_exhausted",
                outcome="failure",
                severity="warning",
                created_at=now - timedelta(hours=1),
            ),
            AuditLog(
                actor_email="old@test.local",
                action="auth.login_failed",
                outcome="failure",
                severity="warning",
                created_at=now - timedelta(hours=30),
            ),
            AuditLog(
                actor_email="ok@test.local",
                action="auth.login",
                outcome="success",
                severity="info",
                created_at=now - timedelta(minutes=5),
            ),
        ]
    )
    await db.commit()

    stopped_calls: list[tuple[str, str]] = []

    class MockAgentMonitor:
        def __init__(self, namespace: str, api_key: str) -> None:
            self.namespace = namespace
            self.api_key = api_key

        async def health_info(self) -> dict:
            return {"ready": True, "status": "ok", "redis": True, "postgres": True, "sandbox_mode": "disabled"}

        async def health(self) -> bool:
            return True

        async def cancel_run(self, run_id: str) -> dict:
            stopped_calls.append((self.namespace, run_id))
            if run_id == "run-live":
                raise AgentError(503, "agent_unreachable")
            return {"status": "cancelled"}

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(admin_routes, "AgentClient", MockAgentMonitor)
    with monkeypatch.context() as mp:
        mp.setenv("SMTP_HOST", "smtp.test.local")
        mp.setenv("SMTP_USERNAME", "noreply@test.local")
        mp.setenv("SMTP_PASSWORD", "secret")
        get_settings.cache_clear()
        try:
            resp = await client.get("/api/admin/monitor", headers=auth_header(admin["access_token"]))
            assert resp.status_code == 200, resp.text
            mon = resp.json()
        finally:
            get_settings.cache_clear()
    get_settings.cache_clear()

    assert mon["services"] == {
        "postgres": True,
        "redis": True,
        "agent": True,
        "worker": True,
        "pgvector": False,
        "sandbox": False,
        "sandbox_mode": "disabled",
        "cos_configured": False,
        "smtp_configured": True,
    }

    # Verify agent=False and custom run_max_seconds threshold marks shorter runs as stalled
    class UnhealthyAgentMonitor(MockAgentMonitor):
        async def health_info(self) -> dict:
            return {"ready": False, "status": "unreachable"}

        async def health(self) -> bool:
            return False

    monkeypatch.setattr(admin_routes, "AgentClient", UnhealthyAgentMonitor)
    with monkeypatch.context() as mp:
        mp.setenv("RUN_MAX_SECONDS", "10")
        get_settings.cache_clear()
        try:
            mon_low = await client.get("/api/admin/monitor", headers=auth_header(admin["access_token"]))
            assert mon_low.status_code == 200
            mon_low_body = mon_low.json()
            assert mon_low_body["services"]["agent"] is False
            assert mon_low_body["services"]["worker"] is False
            assert mon_low_body["services"]["smtp_configured"] is False
            low_runs = {r["active_run_id"]: r for r in mon_low_body["active_runs"]}
            assert low_runs["run-live"]["is_stalled"] is True
        finally:
            get_settings.cache_clear()
    get_settings.cache_clear()
    monkeypatch.setattr(admin_routes, "AgentClient", MockAgentMonitor)

    runs = mon["active_runs"]
    assert len(runs) == 2
    by_run_id = {r["active_run_id"]: r for r in runs}
    assert by_run_id["run-stalled"]["is_stalled"] is True
    assert by_run_id["run-stalled"]["duration_seconds"] >= 749
    assert by_run_id["run-stalled"]["user_email"] == "runner@test.local"
    assert by_run_id["run-live"]["is_stalled"] is False

    spikes = {s["action"]: s for s in mon["failure_spikes_24h"]}
    assert set(spikes.keys()) == {"auth.login_failed", "chat.rate_limited", "chat.credits_exhausted"}
    assert spikes["auth.login_failed"]["count"] == 1  # >24h entry excluded

    actors = {a["actor_email"]: a for a in mon["top_failing_actors_24h"]}
    assert actors["attacker@test.local"]["count"] == 2
    assert actors["attacker@test.local"]["latest_action"] == "auth.login_failed"
    assert actors["runner@test.local"]["count"] == 1
    assert "old@test.local" not in actors

    assert mon["failed_messages_24h"] == 22
    assert len(mon["recent_failed_messages"]) == 20
    assert all(m["status"] == "failed" for m in mon["recent_failed_messages"])
    assert all(m["user_email"] == "runner@test.local" for m in mon["recent_failed_messages"])

    c_stalled_id = c_stalled.id
    c_live_id = c_live.id
    m_stalled_id = m_stalled.id
    m_live_id = m_live.id

    # Force stop stalled run (Agent succeeds)
    stop_stalled = await client.post(
        f"/api/admin/conversations/{c_stalled_id}/stop",
        headers=auth_header(admin["access_token"]),
    )
    assert stop_stalled.status_code == 200, stop_stalled.text
    assert stop_stalled.json()["agent_stopped"] is True
    assert stop_stalled.json()["status"] == "cancelled"

    # Stopping an already-idle conversation returns 409
    stop_again = await client.post(
        f"/api/admin/conversations/{c_stalled_id}/stop",
        headers=auth_header(admin["access_token"]),
    )
    assert stop_again.status_code == 409

    # Missing conversation returns 404
    stop_missing = await client.post(
        f"/api/admin/conversations/{uuid.uuid4()}/stop",
        headers=auth_header(admin["access_token"]),
    )
    assert stop_missing.status_code == 404

    # Force stop live run even when AgentClient.cancel_run fails (best-effort)
    stop_live = await client.post(
        f"/api/admin/conversations/{c_live_id}/stop",
        headers=auth_header(admin["access_token"]),
    )
    assert stop_live.status_code == 200, stop_live.text
    assert stop_live.json()["agent_stopped"] is False

    db.expire_all()
    refreshed_stalled = await db.get(Conversation, c_stalled_id)
    refreshed_live = await db.get(Conversation, c_live_id)
    refreshed_m_stalled = await db.get(Message, m_stalled_id)
    refreshed_m_live = await db.get(Message, m_live_id)
    assert refreshed_stalled.active_run_id is None
    assert refreshed_stalled.active_run_status is None
    assert refreshed_live.active_run_id is None
    assert refreshed_live.active_run_status is None
    assert refreshed_m_stalled.status == "cancelled"
    assert refreshed_m_live.status == "cancelled"
    assert len(stopped_calls) == 2

    audits = (
        await db.execute(select(AuditLog).where(AuditLog.action == "admin.run_force_stop"))
    ).scalars().all()
    assert len(audits) == 2


async def test_admin_user_detail_ledger_sessions_and_revoke(admin, register, client, db):
    # Register user (session 1) then login again (session 2)
    reg = await register(email="detail@test.local", password="Passw0rd!", display_name="DetailUser")
    login_resp = await client.post(
        "/api/auth/login",
        json={"email": "detail@test.local", "password": "Passw0rd!"},
        headers={"User-Agent": "TestBrowser/2.0"},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()

    # Rotate session 1 refresh token so session 1 has 2 RefreshToken rows (1 revoked, 1 active)
    refresh_resp = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": reg["refresh_token"]},
    )
    assert refresh_resp.status_code == 200
    s1_access = refresh_resp.json()["access_token"]
    s2_access = login_data["access_token"]
    s1_claims = decode_access_claims(s1_access)
    s2_claims = decode_access_claims(s2_access)
    assert s1_claims and s1_claims.session_id
    assert s2_claims and s2_claims.session_id
    assert s1_claims.session_id != s2_claims.session_id

    user_id = uuid.UUID(reg["user"]["id"])
    admin_id = uuid.UUID(admin["user"]["id"])

    # Enable privacy/memory flags and seed conversations, messages, files, usage, and ledger
    user = await db.get(User, user_id)
    assert user is not None
    now = datetime.now(timezone.utc)
    user.profile_context_enabled = True
    user.profile_context_consented_at = now
    user.memory_enabled = True
    user.memory_consented_at = now
    user.memory_require_confirm = False

    conv = Conversation(user_id=user_id, thread_id="s-det", title="Detail Conv")
    db.add(conv)
    await db.flush()
    db.add_all(
        [
            Message(conversation_id=conv.id, role="user", content="hi", status="completed"),
            Message(conversation_id=conv.id, role="assistant", content="hello", status="completed"),
            ConversationFile(
                conversation_id=conv.id,
                user_id=user_id,
                filename="a.txt",
                ext=".txt",
                mime_type="text/plain",
                category="text",
                size_bytes=123,
                storage_key=f"k/{uuid.uuid4()}",
                status="ready",
            ),
            ConversationFile(
                conversation_id=conv.id,
                user_id=user_id,
                filename="pending.txt",
                ext=".txt",
                mime_type="text/plain",
                category="text",
                size_bytes=456,
                storage_key=f"k/{uuid.uuid4()}",
                status="pending",
            ),
            UsageDaily(user_id=user_id, day=now.date(), messages=10, tokens=25000, runs=5),
        ]
    )

    # Seed 25 ledger items (15 consume, 10 adjust)
    for i in range(15):
        db.add(
            CreditLedger(
                user_id=user_id,
                tokens=-2500,
                kind="consume",
                tier="free",
                created_at=now - timedelta(minutes=i + 10),
            )
        )
    for i in range(10):
        db.add(
            CreditLedger(
                user_id=user_id,
                tokens=10000,
                kind="adjust",
                tier="free",
                actor_user_id=admin_id,
                note=f"adj-{i}",
                created_at=now - timedelta(minutes=i),
            )
        )
    await db.commit()

    # Invite code redemption for this user
    code_resp = await client.post(
        "/api/admin/invite-codes",
        json={"tier": "plus", "duration_days": 30, "max_uses": 3},
        headers=auth_header(admin["access_token"]),
    )
    assert code_resp.status_code == 201
    code_obj = code_resp.json()
    redeem_resp = await client.post(
        "/api/users/me/redeem",
        json={"code": code_obj["code"]},
        headers=auth_header(s2_access),
    )
    assert redeem_resp.status_code == 200

    # 404 check
    missing_user = await client.get(
        f"/api/admin/users/{uuid.uuid4()}", headers=auth_header(admin["access_token"])
    )
    assert missing_user.status_code == 404

    detail_resp = await client.get(
        f"/api/admin/users/{user_id}", headers=auth_header(admin["access_token"])
    )
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()

    assert detail["email"] == "detail@test.local"
    assert detail["profile_context_enabled"] is True
    assert detail["memory_enabled"] is True
    assert detail["memory_require_confirm"] is False
    # Auto-created Main Chat on registration + 1 seeded side conversation = 2
    assert detail["conversation_count"] == 2
    assert detail["message_count"] == 2
    assert detail["file_count"] == 1
    assert detail["total_tokens"] == 25000
    assert detail["total_messages"] == 10
    assert detail["total_runs"] == 5
    assert detail["membership_tier"] == "plus"
    assert detail["credits"]["tier"] == "plus"
    assert len(detail["active_sessions"]) == 2
    assert len(detail["recent_ledger"]) == 20
    assert detail["recent_ledger"][0]["kind"] == "adjust"
    assert detail["recent_ledger"][0]["credits"] == 2.0
    assert detail["recent_ledger"][0]["actor_email"] == "admin@test.local"
    assert len(detail["invite_redemptions"]) == 1
    assert detail["invite_redemptions"][0]["code"] == code_obj["code"]
    assert detail["invite_redemptions"][0]["user_email"] == "detail@test.local"

    # Paginated ledger & kind filter
    ledger_page1 = await client.get(
        f"/api/admin/users/{user_id}/ledger?page=1&page_size=6",
        headers=auth_header(admin["access_token"]),
    )
    assert ledger_page1.status_code == 200
    assert ledger_page1.json()["total"] == 25
    assert len(ledger_page1.json()["items"]) == 6

    ledger_consume = await client.get(
        f"/api/admin/users/{user_id}/ledger?kind=consume&page=1&page_size=20",
        headers=auth_header(admin["access_token"]),
    )
    assert ledger_consume.status_code == 200
    consume_body = ledger_consume.json()
    assert consume_body["total"] == 15
    assert all(item["kind"] == "consume" and item["credits"] == -0.5 for item in consume_body["items"])

    ledger_adjust = await client.get(
        f"/api/admin/users/{user_id}/ledger?kind=adjust",
        headers=auth_header(admin["access_token"]),
    )
    assert ledger_adjust.status_code == 200
    assert ledger_adjust.json()["total"] == 10
    assert all(
        item["kind"] == "adjust" and item["credits"] == 2.0 and item["actor_email"] == "admin@test.local"
        for item in ledger_adjust.json()["items"]
    )

    # Sessions endpoint
    sessions_resp = await client.get(
        f"/api/admin/users/{user_id}/sessions",
        headers=auth_header(admin["access_token"]),
    )
    assert sessions_resp.status_code == 200
    session_ids = {s["session_id"] for s in sessions_resp.json()}
    assert session_ids == {str(s1_claims.session_id), str(s2_claims.session_id)}

    # Cross-user session revoke fails with 404 and does NOT revoke victim's session
    other_user = await register(email="other-sess@test.local")
    cross_revoke = await client.delete(
        f"/api/admin/users/{other_user['user']['id']}/sessions/{s1_claims.session_id}",
        headers=auth_header(admin["access_token"]),
    )
    assert cross_revoke.status_code == 404
    assert not await is_session_revoked(s1_claims.session_id)

    # Revoke session 1 legitimately
    revoke_resp = await client.delete(
        f"/api/admin/users/{user_id}/sessions/{s1_claims.session_id}",
        headers=auth_header(admin["access_token"]),
    )
    assert revoke_resp.status_code == 204
    assert await is_session_revoked(s1_claims.session_id)

    # Session 1 access token is immediately rejected, while session 2 still works
    me_s1 = await client.get("/api/users/me", headers=auth_header(s1_access))
    assert me_s1.status_code == 401
    me_s2 = await client.get("/api/users/me", headers=auth_header(s2_access))
    assert me_s2.status_code == 200

    # Refresh token for session 1 is marked revoked in DB
    s1_tokens = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.session_id == s1_claims.session_id
            )
        )
    ).scalars().all()
    assert s1_tokens and all(tok.revoked_at is not None for tok in s1_tokens)

    # Only session 2 remains in active sessions list
    sessions_after = await client.get(
        f"/api/admin/users/{user_id}/sessions",
        headers=auth_header(admin["access_token"]),
    )
    assert [s["session_id"] for s in sessions_after.json()] == [str(s2_claims.session_id)]

    # Audit log recorded admin.session_revoke
    revoke_audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "admin.session_revoke"))
    ).scalars().first()
    assert revoke_audit is not None
    assert revoke_audit.metadata_["revoked_session_id"] == str(s1_claims.session_id)


async def test_invite_code_redemptions_and_reenable(admin, register, client, db):
    headers = auth_header(admin["access_token"])
    create_resp = await client.post(
        "/api/admin/invite-codes",
        json={"tier": "pro", "duration_days": 14, "max_uses": 5, "note": "VIP"},
        headers=headers,
    )
    assert create_resp.status_code == 201
    code = create_resp.json()

    # Disable then re-enable invite code
    disable_resp = await client.patch(
        f"/api/admin/invite-codes/{code['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["is_active"] is False

    u1 = await register(email="reenable1@test.local")
    u2 = await register(email="reenable2@test.local")
    fail_redeem = await client.post(
        "/api/users/me/redeem",
        json={"code": code["code"]},
        headers=auth_header(u1["access_token"]),
    )
    assert fail_redeem.status_code == 400

    enable_resp = await client.patch(
        f"/api/admin/invite-codes/{code['id']}",
        json={"is_active": True},
        headers=headers,
    )
    assert enable_resp.status_code == 200
    assert enable_resp.json()["is_active"] is True

    # Both users redeem the re-enabled code
    r1 = await client.post(
        "/api/users/me/redeem",
        json={"code": code["code"]},
        headers=auth_header(u1["access_token"]),
    )
    assert r1.status_code == 200, r1.text
    r2 = await client.post(
        "/api/users/me/redeem",
        json={"code": code["code"]},
        headers=auth_header(u2["access_token"]),
    )
    assert r2.status_code == 200, r2.text

    # Redemptions list joined with user_email and code
    red_resp = await client.get(
        f"/api/admin/invite-codes/{code['id']}/redemptions",
        headers=headers,
    )
    assert red_resp.status_code == 200, red_resp.text
    items = red_resp.json()
    assert len(items) == 2
    assert [item["user_email"] for item in items] == ["reenable2@test.local", "reenable1@test.local"]
    assert all(
        item["code"] == code["code"] and item["tier"] == "pro" and item["duration_days"] == 14
        for item in items
    )

    # 404 for unknown invite code
    missing = await client.get(f"/api/admin/invite-codes/{uuid.uuid4()}/redemptions", headers=headers)
    assert missing.status_code == 404

    enable_audit = (
        await db.execute(select(AuditLog).where(AuditLog.action == "invite.enable"))
    ).scalars().first()
    assert enable_audit is not None
