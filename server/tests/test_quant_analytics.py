import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import RunTelemetry, UsageDaily
from tests.conftest import auth_header


async def test_quant_summary_models_retention_and_evals(admin, register, client, db):
    headers = auth_header(admin["access_token"])
    now = datetime.now(timezone.utc)
    today = now.date()

    u1 = await register(email="quant1@test.local")
    u1_id = uuid.UUID(u1["user"]["id"])

    db.add(
        UsageDaily(
            user_id=u1_id,
            day=today,
            messages=6,
            tokens=3000,
            runs=3,
        )
    )
    db.add_all(
        [
            RunTelemetry(
                run_id=f"q-1-{uuid.uuid4().hex}",
                user_id=u1_id,
                model_route="fast",
                model_name="gpt-4o-mini",
                status="completed",
                ttft_ms=120,
                duration_ms=1000,
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300,
                tool_calls_count=1,
                tool_errors_count=0,
                tools_summary=[{"name": "web_search", "calls": 1, "errors": 0, "total_duration_ms": 400}],
                skills_used=["deep-research"],
                created_at=now,
            ),
            RunTelemetry(
                run_id=f"q-2-{uuid.uuid4().hex}",
                user_id=u1_id,
                model_route="reasoning",
                model_name="o3-mini",
                status="completed",
                ttft_ms=300,
                duration_ms=3000,
                prompt_tokens=600,
                completion_tokens=400,
                total_tokens=1000,
                tool_calls_count=2,
                tool_errors_count=1,
                tools_summary=[{"name": "web_search", "calls": 2, "errors": 1, "total_duration_ms": 1000}],
                skills_used=["data-analysis"],
                created_at=now - timedelta(days=1),
            ),
        ]
    )
    await db.commit()

    sum_resp = await client.get("/api/admin/quant/summary?days=7", headers=headers)
    assert sum_resp.status_code == 200
    s = sum_resp.json()
    assert s["runs"]["total"] == 2
    assert s["runs"]["completed"] == 2
    assert s["runs"]["success_rate_pct"] == 100.0
    assert s["runs"]["total_tokens"] == 1300
    assert s["latency"]["p50_ms"] == 2000.0
    assert len(s["daily_latency"]) == 7

    mt_resp = await client.get("/api/admin/quant/models-tools?days=7", headers=headers)
    assert mt_resp.status_code == 200
    mt = mt_resp.json()
    assert len(mt["routes"]) == 2
    assert mt["tools"][0]["name"] == "web_search"
    assert mt["tools"][0]["calls"] == 3
    assert mt["tools"][0]["errors"] == 1
    assert len(mt["skills"]) == 2

    ret_resp = await client.get("/api/admin/quant/retention?days=14", headers=headers)
    assert ret_resp.status_code == 200
    ret = ret_resp.json()
    assert len(ret["funnel"]) == 4
    assert ret["funnel"][0]["count"] >= 2

    eval_run = await client.post("/api/admin/quant/evals/run", headers=headers)
    assert eval_run.status_code == 201
    assert eval_run.json()["total"] == 5
    assert eval_run.json()["pass_rate"] == 1.0

    eval_list = await client.get("/api/admin/quant/evals", headers=headers)
    assert eval_list.status_code == 200
    assert len(eval_list.json()["items"]) == 1
