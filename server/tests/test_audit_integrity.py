from sqlalchemy import select, update

from app.db.models import AuditLog
from app.services import audit
from tests.conftest import auth_header


async def test_audit_hash_chain_verify_and_tamper_detection(admin, register, client, db):
    headers = auth_header(admin["access_token"])
    u = await register(email="tamper@test.local")

    # Trigger an admin mutation that records structured Before/After diff
    upd = await client.patch(
        f"/api/admin/users/{u['user']['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert upd.status_code == 200

    verify_ok = await client.get("/api/admin/audit-logs/verify?limit=200", headers=headers)
    assert verify_ok.status_code == 200
    vbody = verify_ok.json()
    assert vbody["valid"] is True
    assert vbody["hashed_count"] >= 1

    logs_resp = await client.get("/api/admin/audit-logs?action_prefix=admin.&min_risk=50", headers=headers)
    assert logs_resp.status_code == 200
    items = logs_resp.json()["items"]
    assert items
    latest = items[0]
    assert latest["risk_score"] >= 60
    assert latest["diff"]["before"]["is_active"] is True
    assert latest["diff"]["after"]["is_active"] is False
    assert latest["record_hash"]

    # Trace by request_id
    if latest["request_id"]:
        trace_resp = await client.get(f"/api/admin/audit-logs/trace/{latest['request_id']}", headers=headers)
        assert trace_resp.status_code == 200
        assert trace_resp.json()["count"] >= 1

    # Analytics & Masked Export
    ana_resp = await client.get("/api/admin/audit-logs/analytics?days=7", headers=headers)
    assert ana_resp.status_code == 200
    assert ana_resp.json()["summary"]["total_events"] >= 1

    exp_resp = await client.get("/api/admin/audit-logs/export?format=csv&mask_pii=true", headers=headers)
    assert exp_resp.status_code == 200
    assert "actor_email" in exp_resp.text

    # Simulate direct DB tampering and confirm verify detects exact broken row
    target_row = (
        await db.execute(select(AuditLog).where(AuditLog.id == latest["id"]))
    ).scalar_one()
    await db.execute(
        update(AuditLog).where(AuditLog.id == target_row.id).values(outcome="failure")
    )
    await db.commit()

    verify_bad = await client.get("/api/admin/audit-logs/verify?limit=200", headers=headers)
    assert verify_bad.status_code == 200
    assert verify_bad.json()["valid"] is False
    assert verify_bad.json()["broken_at_id"] == target_row.id
