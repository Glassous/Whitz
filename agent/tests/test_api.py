from __future__ import annotations

import json

import httpx
import pytest

from app.api import create_app
from app.core.config import AgentSettings
from app.runner import events_key, load_run_meta, publish_event, save_run_meta
from tests.conftest import FakeArqPool, FakePGPool, FakeRedis


@pytest.mark.asyncio
async def test_control_api_auth_runs_resume_cancel_events_and_delete():
    redis = FakeRedis()
    arq = FakeArqPool()
    pg = FakePGPool(responder=lambda sql, params: [(1,)])
    settings = AgentSettings(agent_internal_token="secret-token", internal_mcp_base_url="")
    app = create_app(redis_client=redis, arq_pool=arq, pg_pool=pg, settings_override=settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Health is accessible without token
            h = await client.get("/health")
            assert h.status_code == 200
            assert h.json()["ok"] is True

            # Auth required on /v1/*
            unauth = await client.get("/v1/graph/topology")
            assert unauth.status_code == 401

            headers = {"X-Agent-Token": "secret-token"}
            topo = await client.get("/v1/graph/topology", headers=headers)
            assert topo.status_code == 200
            assert len(topo.json()["nodes"]) == 6

            # Create run + idempotency
            req_body = {
                "thread_id": "thread-api-1",
                "conversation_id": "conv-1",
                "user_id": "user-1",
                "input": "Hello",
                "model_route": "auto",
            }
            r1 = await client.post(
                "/v1/runs",
                json=req_body,
                headers={**headers, "Idempotency-Key": "idem-1"},
            )
            assert r1.status_code == 201
            run_id = r1.json()["run_id"]
            assert len(arq.jobs) == 1

            r2 = await client.post(
                "/v1/runs",
                json=req_body,
                headers={**headers, "Idempotency-Key": "idem-1"},
            )
            assert r2.json()["run_id"] == run_id
            assert len(arq.jobs) == 1

            # Get run
            g = await client.get(f"/v1/runs/{run_id}", headers=headers)
            assert g.status_code == 200
            assert g.json()["status"] == "queued"

            # Put run into waiting state and test generation conflict + resume
            meta = await load_run_meta(redis, run_id)
            meta["status"] = "waiting_for_approval"
            meta["execution_generation"] = 1
            await save_run_meta(redis, run_id, meta)

            stale = await client.post(
                f"/v1/runs/{run_id}/resume",
                json={"choice": "once", "execution_generation": 99},
                headers=headers,
            )
            assert stale.status_code == 409

            resumed = await client.post(
                f"/v1/runs/{run_id}/resume",
                json={"choice": "once", "execution_generation": 1},
                headers=headers,
            )
            assert resumed.status_code == 200
            assert arq.jobs[-1][0] == "resume_run_job"

            # Publish events & test SSE stream with Last-Event-ID
            id1 = await publish_event(redis, run_id, "run.started", {"run_id": run_id})
            await publish_event(redis, run_id, "message.delta", {"text": "Hi"})
            await publish_event(redis, run_id, "run.completed", {"output": "Hi"})

            sse_resp = await client.get(
                f"/v1/runs/{run_id}/events",
                headers={**headers, "Last-Event-ID": id1},
            )
            assert sse_resp.status_code == 200
            body_text = sse_resp.text
            assert "event: message.delta" in body_text
            assert "event: run.completed" in body_text
            assert "event: run.started" not in body_text

            # Cancel run
            c = await client.post(f"/v1/runs/{run_id}/cancel", headers=headers)
            assert c.status_code == 200
            assert await redis.get(f"run:{run_id}:cancel") == "1"

            # Delete thread
            d = await client.delete("/v1/threads/thread-api-1", headers=headers)
            assert d.status_code == 204
