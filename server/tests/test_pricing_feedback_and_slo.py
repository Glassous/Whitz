import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import Conversation, Message, RunTelemetry
from tests.conftest import auth_header


async def test_settings_feedback_reactions_pricing_and_slo(admin, register, client, db):
    admin_headers = auth_header(admin["access_token"])
    u = await register(email="fb@test.local")
    u_headers = auth_header(u["access_token"])
    u_id = uuid.UUID(u["user"]["id"])

    # 1. Settings: toggle AI positive reactions & submit product feedback
    pref_resp = await client.put(
        "/api/users/me/ai-reactions",
        json={"ai_reactions_enabled": False},
        headers=u_headers,
    )
    assert pref_resp.status_code == 200
    assert pref_resp.json()["ai_reactions_enabled"] is False

    fb_create = await client.post(
        "/api/users/me/feedback",
        json={"rating": 5, "category": "quality", "content": "推理链和工具调用非常稳定！"},
        headers=u_headers,
    )
    assert fb_create.status_code == 201
    fb_id = fb_create.json()["id"]

    fb_mine = await client.get("/api/users/me/feedback", headers=u_headers)
    assert fb_mine.status_code == 200
    assert len(fb_mine.json()) == 1

    # 2. Message reactions (multi-emoji on assistant message)
    conv = Conversation(user_id=u_id, kind="side", title="测试评价对话", thread_id=uuid.uuid4().hex)
    db.add(conv)
    await db.flush()
    msg_asst = Message(conversation_id=conv.id, role="assistant", content="这里是回答内容", status="completed")
    db.add(msg_asst)
    await db.commit()

    react_resp = await client.post(
        f"/api/conversations/{conv.id}/messages/{msg_asst.id}/reactions",
        json={"reaction": "love"},
        headers=u_headers,
    )
    assert react_resp.status_code == 200
    assert react_resp.json()["reaction"] == "love"

    conv_detail = await client.get(f"/api/conversations/{conv.id}", headers=u_headers)
    assert conv_detail.status_code == 200
    asst_items = [m for m in conv_detail.json()["messages"] if m["id"] == str(msg_asst.id)]
    assert asst_items[0]["reactions"][0]["reaction"] == "love"

    # 3. Admin Quant Pricing, Feedback, Golden Eval & Ops SLO
    price_put = await client.put(
        "/api/admin/quant/pricing",
        json={
            "model_pattern": "custom-fast",
            "display_name": "Custom Fast",
            "input_usd_per_1m": 0.2,
            "output_usd_per_1m": 0.8,
        },
        headers=admin_headers,
    )
    assert price_put.status_code == 200

    db.add(
        RunTelemetry(
            run_id=f"finops-{uuid.uuid4().hex}",
            user_id=u_id,
            model_route="fast",
            model_name="custom-fast-v1",
            status="completed",
            ttft_ms=110,
            duration_ms=900,
            prompt_tokens=100000,
            completion_tokens=50000,
            total_tokens=150000,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    await db.commit()

    recalc = await client.post("/api/admin/quant/pricing/recalculate?days=30", headers=admin_headers)
    assert recalc.status_code == 200
    assert recalc.json()["updated_rows"] >= 1

    quant_sum = await client.get("/api/admin/quant/summary?days=7", headers=admin_headers)
    assert quant_sum.status_code == 200
    qs = quant_sum.json()
    assert qs["finops"]["total_cost_usd"] > 0
    assert qs["finops"]["routing_savings_usd"] > 0
    assert qs["quality"]["csat_pct"] == 100.0

    quant_fb = await client.get("/api/admin/quant/feedback?days=30", headers=admin_headers)
    assert quant_fb.status_code == 200
    assert quant_fb.json()["reactions"]["user_breakdown"]["love"] == 1
    assert quant_fb.json()["product_feedback"]["total"] == 1

    fb_upd = await client.patch(
        f"/api/admin/quant/feedback/{fb_id}",
        json={"status": "resolved", "admin_note": "感谢反馈，已纳入迭代！"},
        headers=admin_headers,
    )
    assert fb_upd.status_code == 200
    assert fb_upd.json()["status"] == "resolved"

    golden_eval = await client.post("/api/admin/quant/evals/run?dataset=golden", headers=admin_headers)
    assert golden_eval.status_code == 201
    assert golden_eval.json()["total"] >= 5

    slo_resp = await client.get("/api/admin/ops/slo", headers=admin_headers)
    assert slo_resp.status_code == 200
    assert "burn_rate_1h" in slo_resp.json()["slo"]
    assert len(slo_resp.json()["anomalies"]) == 4
