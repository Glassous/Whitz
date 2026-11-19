import uuid
from datetime import datetime, timezone

import httpx

from app.db.models import RunTelemetry
from app.services import ops_service
from tests.conftest import auth_header


async def test_prometheus_metrics_endpoint(client):
    await client.get("/api/health")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "whitz_server_http_requests_total" in resp.text


async def test_ops_and_quant_require_admin(register, client):
    user = await register(email="plain-ops@test.local")
    headers = auth_header(user["access_token"])

    for method, path in [
        ("GET", "/api/admin/ops/inspection"),
        ("GET", "/api/admin/ops/alerts"),
        ("POST", "/api/admin/ops/alerts/evaluate"),
        ("GET", "/api/admin/quant/summary"),
        ("GET", "/api/admin/quant/models-tools"),
        ("GET", "/api/admin/quant/retention"),
        ("GET", "/api/admin/quant/evals"),
        ("POST", "/api/admin/quant/evals/run"),
    ]:
        resp = await client.request(method, path, headers=headers)
        assert resp.status_code == 403, f"{method} {path} returned {resp.status_code}"


async def test_ops_inspection_and_alert_lifecycle(admin, register, client, db, monkeypatch):
    headers = auth_header(admin["access_token"])

    insp = await client.get("/api/admin/ops/inspection", headers=headers)
    assert insp.status_code == 200
    body = insp.json()
    assert body["postgres"]["ok"] is True
    assert "redis" in body
    assert "runtime" in body
    assert "agent_error_rate_pct" in body["supported_metrics"]

    webhook_calls: list[dict] = []

    async def _fake_dispatch(url, payload):
        webhook_calls.append({"url": url, "json": payload})
        return "http_200"

    monkeypatch.setattr(ops_service, "dispatch_webhook", _fake_dispatch)

    # Create alert rule for error rate > 20%
    create_resp = await client.post(
        "/api/admin/ops/alerts/rules",
        headers=headers,
        json={
            "name": "高失败率测试",
            "metric_key": "agent_error_rate_pct",
            "operator": "gt",
            "threshold": 20.0,
            "window_minutes": 60,
            "cooldown_minutes": 30,
            "severity": "critical",
            "webhook_url": "https://webhook.test/hook",
            "enabled": True,
        },
    )
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["id"]

    # Test webhook
    test_resp = await client.post(f"/api/admin/ops/alerts/rules/{rule_id}/test", headers=headers)
    assert test_resp.status_code == 200
    assert test_resp.json()["ok"] is True
    assert len(webhook_calls) == 1

    # Seed 2 failed runs out of 2 => 100% error rate
    u = await register(email="ops-user@test.local")
    uid = uuid.UUID(u["user"]["id"])
    db.add_all(
        [
            RunTelemetry(
                run_id=f"ops-r1-{uuid.uuid4().hex}",
                user_id=uid,
                model_route="auto",
                status="failed",
                duration_ms=1200,
                created_at=datetime.now(timezone.utc),
            ),
            RunTelemetry(
                run_id=f"ops-r2-{uuid.uuid4().hex}",
                user_id=uid,
                model_route="fast",
                status="failed",
                duration_ms=800,
                created_at=datetime.now(timezone.utc),
            ),
        ]
    )
    await db.commit()

    eval_resp = await client.post("/api/admin/ops/alerts/evaluate", headers=headers)
    assert eval_resp.status_code == 200
    assert eval_resp.json()["triggered"] == 1
    assert len(webhook_calls) == 2

    alerts_resp = await client.get("/api/admin/ops/alerts", headers=headers)
    assert alerts_resp.status_code == 200
    events = alerts_resp.json()["events"]
    assert len(events) == 1
    event_id = events[0]["id"]
    assert events[0]["status"] == "firing"

    ack_resp = await client.post(f"/api/admin/ops/alerts/{event_id}/ack", headers=headers)
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "acked"

    del_resp = await client.delete(f"/api/admin/ops/alerts/rules/{rule_id}", headers=headers)
    assert del_resp.status_code == 204
