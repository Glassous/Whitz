import json
import uuid
from datetime import datetime, timedelta, timezone

from app.db.models import (
    Conversation,
    Message,
    ScheduledTask,
    ScheduledTaskPendingProposal,
    ScheduledTaskRun,
)
from app.services import ops_service
from tests.conftest import auth_header


async def test_dashboards_require_admin(register, client):
    user = await register(email="plain-dash@test.local")
    headers = auth_header(user["access_token"])

    for path in (
        "/api/admin/dashboards/schedules",
        "/api/admin/dashboards/http-tools",
        "/api/admin/dashboards/web-search",
        "/api/admin/dashboards/export",
    ):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 403, f"GET {path} returned {resp.status_code}"


async def test_schedules_http_tools_web_search_dashboards_and_alerts(admin, register, client, db, monkeypatch):
    headers = auth_header(admin["access_token"])
    now = datetime.now(timezone.utc)

    u1 = await register(email="dash-user@test.local", display_name="DashUser")
    u1_id = uuid.UUID(u1["user"]["id"])

    conv = Conversation(user_id=u1_id, title="测试会话", kind="side")
    db.add(conv)
    await db.flush()

    # 1. Seed Scheduled Tasks + Pending Proposal + ScheduledTaskRuns
    t_active = ScheduledTask(
        user_id=u1_id,
        conversation_id=conv.id,
        name="每日巡检任务",
        prompt="检查接口健康度",
        schedule_type="daily",
        schedule_config={"hour": 9, "minute": 0},
        timezone="Asia/Shanghai",
        target_mode="dedicated",
        enabled=True,
        status="active",
        run_count=3,
        consecutive_failures=0,
        last_run_at=now - timedelta(minutes=10),
        last_run_status="completed",
    )
    t_err = ScheduledTask(
        user_id=u1_id,
        conversation_id=conv.id,
        name="异常暂停任务",
        prompt="抓取失败示例",
        schedule_type="interval",
        schedule_config={"every_minutes": 60},
        timezone="Asia/Shanghai",
        target_mode="main",
        enabled=False,
        status="error",
        run_count=2,
        consecutive_failures=5,
        last_run_at=now - timedelta(minutes=5),
        last_run_status="failed",
        last_error="Upstream 502",
    )
    db.add_all([t_active, t_err])
    await db.flush()

    db.add(
        ScheduledTaskPendingProposal(
            user_id=u1_id,
            conversation_id=conv.id,
            action="create",
            payload={"name": "待审批任务", "schedule_type": "daily", "schedule_config": {"hour": 8, "minute": 0}},
            status="pending",
        )
    )
    db.add_all(
        [
            ScheduledTaskRun(
                task_id=t_active.id,
                user_id=u1_id,
                conversation_id=conv.id,
                trigger_type="scheduled",
                status="completed",
                scheduled_for=now - timedelta(hours=2),
                started_at=now - timedelta(hours=2) + timedelta(seconds=15),
                finished_at=now - timedelta(hours=2) + timedelta(seconds=20),
                tokens_used=400,
            ),
            ScheduledTaskRun(
                task_id=t_active.id,
                user_id=u1_id,
                conversation_id=conv.id,
                trigger_type="manual",
                status="completed",
                scheduled_for=now - timedelta(hours=1),
                started_at=now - timedelta(hours=1),
                finished_at=now - timedelta(hours=1) + timedelta(seconds=4),
                tokens_used=300,
            ),
            ScheduledTaskRun(
                task_id=t_err.id,
                user_id=u1_id,
                conversation_id=conv.id,
                trigger_type="scheduled",
                status="failed",
                scheduled_for=now - timedelta(minutes=30),
                started_at=now - timedelta(minutes=28),  # 120s delay (>60s)
                finished_at=now - timedelta(minutes=27, seconds=50),
                error="Upstream 502",
                tokens_used=100,
            ),
            ScheduledTaskRun(
                task_id=t_active.id,
                user_id=u1_id,
                conversation_id=conv.id,
                trigger_type="scheduled",
                status="cancelled",
                scheduled_for=now - timedelta(minutes=15),
                started_at=now - timedelta(minutes=15) + timedelta(seconds=5),
                finished_at=now - timedelta(minutes=14),
                tokens_used=0,
            ),
        ]
    )

    # 2. Seed Curl / http_request, web_extract, execute_code tool messages
    db.add_all(
        [
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="http_request",
                status="completed",
                tool_payload={
                    "args": {"url": "https://api.example.com/v1/health", "method": "GET"},
                    "result": json.dumps({"ok": True, "status_code": 200, "url": "https://api.example.com/v1/health", "elapsed_ms": 120, "bytes_read": 256}),
                    "duration_ms": 125,
                },
                created_at=now - timedelta(minutes=20),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="http_request",
                status="completed",
                tool_payload={
                    "args": {"url": "https://api.example.com/v1/items", "method": "POST"},
                    "result": json.dumps({"ok": True, "status_code": 201, "url": "https://api.example.com/v1/items", "elapsed_ms": 200, "bytes_read": 512}),
                    "duration_ms": 205,
                },
                created_at=now - timedelta(minutes=18),
            ),
            # Legacy 404 where status="completed" on message row, but ok=False in JSON result
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="http_request",
                status="completed",
                tool_payload={
                    "args": {"url": "https://api.example.com/v1/missing?api_key=SECRET_KEY_123", "method": "GET"},
                    "result": json.dumps({"ok": False, "status_code": 404, "url": "https://api.example.com/v1/missing?api_key=SECRET_KEY_123", "elapsed_ms": 80, "bytes_read": 64}),
                    "duration_ms": 82,
                },
                created_at=now - timedelta(minutes=16),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="http_request",
                status="failed",
                tool_payload={
                    "args": {"url": "https://bad.example.org/hook", "method": "DELETE"},
                    "result": json.dumps({"ok": False, "status_code": 500, "url": "https://bad.example.org/hook", "elapsed_ms": 300, "bytes_read": 100}),
                    "error": "HTTP 500 Internal Server Error",
                    "duration_ms": 310,
                },
                created_at=now - timedelta(minutes=14),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="http_request",
                status="failed",
                tool_payload={
                    "args": {"url": "http://127.0.0.1:8000/admin", "method": "GET"},
                    "result": json.dumps({"ok": False, "url": "http://127.0.0.1:8000/admin", "error": "仅允许请求合法的公网 HTTP/HTTPS 地址。"}),
                    "error": "仅允许请求合法的公网 HTTP/HTTPS 地址。",
                    "duration_ms": 5,
                },
                created_at=now - timedelta(minutes=12),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="web_extract",
                status="completed",
                tool_payload={
                    "args": {"url": "https://docs.example.com/guide"},
                    "result": json.dumps({"ok": True, "provider": "http", "fallback_from": "tavily", "url": "https://docs.example.com/guide", "content": "guide"}),
                    "duration_ms": 420,
                },
                created_at=now - timedelta(minutes=10),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="execute_code",
                status="completed",
                tool_payload={
                    "args": {"language": "python", "code": "print(42)"},
                    "result": json.dumps({"exit_code": 0, "language": "python", "mode": "docker"}),
                    "duration_ms": 350,
                },
                created_at=now - timedelta(minutes=9),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="execute_code",
                status="failed",
                tool_payload={
                    "args": {"language": "sh", "code": "curl -s https://api.example.com"},
                    "result": json.dumps({"exit_code": 6, "language": "sh", "mode": "docker", "stderr": "network disabled"}),
                    "error": "network disabled",
                    "duration_ms": 180,
                },
                created_at=now - timedelta(minutes=8),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="execute_code",
                status="failed",
                tool_payload={
                    "args": {"language": "python", "code": "import os"},
                    "result": json.dumps({"status": "denied", "message": "用户拒绝了代码执行审批。"}),
                    "error": "用户拒绝了代码执行审批。",
                    "duration_ms": 10,
                },
                created_at=now - timedelta(minutes=7),
            ),
        ]
    )

    # 3. Seed web_search tool messages
    db.add_all(
        [
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="web_search",
                status="completed",
                tool_payload={
                    "args": {"query": "FastAPI 最佳实践"},
                    "result": json.dumps({"ok": True, "provider": "tavily", "result_count": 3, "results": [{"title": "A"}, {"title": "B"}, {"title": "C"}]}),
                    "duration_ms": 600,
                },
                created_at=now - timedelta(minutes=25),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="web_search",
                status="completed",
                tool_payload={
                    "args": {"query": "LangGraph checkpoint"},
                    "result": json.dumps({"ok": True, "provider": "duckduckgo", "fallback_from": "tavily", "result_count": 1, "results": [{"title": "LG"}]}),
                    "duration_ms": 900,
                },
                created_at=now - timedelta(minutes=22),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="web_search",
                status="completed",
                tool_payload={
                    "args": {"query": "非常冷门的查询词"},
                    "result": json.dumps({"ok": True, "provider": "duckduckgo", "result_count": 0, "results": []}),
                    "duration_ms": 400,
                },
                created_at=now - timedelta(minutes=19),
            ),
            Message(
                conversation_id=conv.id,
                role="tool",
                tool_name="web_search",
                status="failed",
                tool_payload={
                    "args": {"query": "超时搜索测试"},
                    "result": json.dumps({"ok": False, "provider": "none", "result_count": 0, "results": [], "error": "ConnectTimeout"}),
                    "error": "ConnectTimeout",
                    "duration_ms": 15000,
                },
                created_at=now - timedelta(minutes=15),
            ),
        ]
    )
    await db.commit()

    # Verify Scheduled Tasks Dashboard
    sched_resp = await client.get("/api/admin/dashboards/schedules?days=7", headers=headers)
    assert sched_resp.status_code == 200
    sd = sched_resp.json()
    assert sd["tasks_summary"]["total"] == 2
    assert sd["tasks_summary"]["active"] == 1
    assert sd["tasks_summary"]["error"] == 1
    assert sd["tasks_summary"]["pending_proposals"] == 1
    assert sd["runs_summary"]["total"] == 4
    assert sd["runs_summary"]["completed"] == 2
    assert sd["runs_summary"]["failed"] == 1
    assert sd["runs_summary"]["cancelled"] == 1
    assert sd["runs_summary"]["success_rate_pct"] == 66.67
    assert sd["runs_summary"]["on_time_rate_pct"] == 66.67
    assert sd["runs_summary"]["total_tokens"] == 800
    assert len(sd["daily"]) == 7
    assert len(sd["recent_failures"]) == 1
    assert sd["recent_failures"][0]["error"] == "Upstream 502"

    # Verify Http / Curl / Sandbox Dashboard
    http_resp = await client.get("/api/admin/dashboards/http-tools?days=7", headers=headers)
    assert http_resp.status_code == 200
    hd = http_resp.json()
    hs = hd["http_request"]["summary"]
    assert hs["total"] == 5
    assert hs["succeeded"] == 2
    assert hs["failed"] == 3
    assert hs["success_rate_pct"] == 40.0
    assert hs["http_2xx"] == 2
    assert hs["http_4xx"] == 1
    assert hs["http_5xx"] == 1
    assert hs["network_errors"] == 1
    # Query string secret must NEVER leak into recent_failures
    for f in hd["http_request"]["recent_failures"]:
        assert "SECRET_KEY_123" not in f["url"]
    assert any(m["method"] == "POST" and m["success_rate_pct"] == 100.0 for m in hd["http_request"]["by_method"])
    assert hd["web_extract"]["summary"]["total"] == 1
    assert hd["web_extract"]["summary"]["fallback_count"] == 1
    cs = hd["execute_code"]["summary"]
    assert cs["total"] == 3
    assert cs["succeeded"] == 1
    assert cs["failed"] == 1
    assert cs["denied"] == 1
    assert cs["curl_command_count"] == 1

    # Verify Web Search Dashboard
    ws_resp = await client.get("/api/admin/dashboards/web-search?days=7", headers=headers)
    assert ws_resp.status_code == 200
    wd = ws_resp.json()
    wss = wd["summary"]
    assert wss["total"] == 4
    assert wss["succeeded"] == 3
    assert wss["failed"] == 1
    assert wss["success_rate_pct"] == 75.0
    assert wss["with_results"] == 2
    assert wss["empty_results"] == 1
    assert wss["hit_rate_pct"] == 66.67
    assert wss["fallback_count"] == 1
    assert len(wd["by_provider"]) == 3
    assert len(wd["recent_searches"]) == 4
    assert len(wd["recent_failures"]) == 2  # 1 failed + 1 zero-result

    # Verify CSV Export
    exp_resp = await client.get("/api/admin/dashboards/export?days=7&section=all", headers=headers)
    assert exp_resp.status_code == 200
    assert "text/csv" in exp_resp.headers["content-type"]
    csv_text = exp_resp.text
    assert "schedules" in csv_text
    assert "http_request" in csv_text
    assert "web_search" in csv_text

    # Verify Ops inspection automation strip & new alert rules
    insp_resp = await client.get("/api/admin/ops/inspection", headers=headers)
    assert insp_resp.status_code == 200
    insp = insp_resp.json()
    assert insp["automation"]["scheduled_runs_24h"] == 4
    assert insp["automation"]["http_request_calls_24h"] == 5
    assert insp["automation"]["web_search_calls_24h"] == 4
    assert "scheduled_task_failure_rate_pct" in insp["supported_metrics"]
    assert "web_search_error_rate_pct" in insp["supported_metrics"]
    assert "http_request_error_rate_pct" in insp["supported_metrics"]

    async def _fake_dispatch(url, payload):
        return "http_200"

    monkeypatch.setattr(ops_service, "dispatch_webhook", _fake_dispatch)
    rule_resp = await client.post(
        "/api/admin/ops/alerts/rules",
        headers=headers,
        json={
            "name": "Curl高失败率告警",
            "metric_key": "http_request_error_rate_pct",
            "operator": "gt",
            "threshold": 50.0,
            "window_minutes": 60,
            "cooldown_minutes": 30,
            "severity": "warning",
            "enabled": True,
        },
    )
    assert rule_resp.status_code == 201
    eval_resp = await client.post("/api/admin/ops/alerts/evaluate", headers=headers)
    assert eval_resp.status_code == 200
    assert eval_resp.json()["triggered"] == 1
