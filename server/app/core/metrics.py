from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS_TOTAL = Counter(
    "whitz_server_http_requests_total",
    "Total HTTP requests handled by Whitz server",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "whitz_server_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
ACTIVE_SSE_STREAMS = Gauge(
    "whitz_server_active_sse_streams",
    "Current number of active SSE chat streams",
)
AGENT_RUNS_TOTAL = Counter(
    "whitz_agent_runs_total",
    "Total completed/failed/interrupted agent runs",
    ["route", "status"],
)
AGENT_RUN_DURATION_SECONDS = Histogram(
    "whitz_agent_run_duration_seconds",
    "End-to-end agent run duration in seconds",
    ["route", "status"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 45.0, 90.0, 180.0, 300.0),
)
AGENT_TOKENS_TOTAL = Counter(
    "whitz_agent_tokens_total",
    "Total LLM tokens consumed by agent runs",
    ["route", "kind"],
)
TOOL_CALLS_TOTAL = Counter(
    "whitz_agent_tool_calls_total",
    "Total tool invocations by tool name and outcome",
    ["tool", "outcome"],
)


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


async def metrics_middleware(request: Request, call_next: Callable):
    if request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    status_code = "500"
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
        return response
    finally:
        elapsed = max(0.0, time.perf_counter() - start)
        route = _route_label(request)
        method = request.method
        HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=status_code).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(elapsed)


def render_prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_run_metrics(
    *,
    route: str,
    status: str,
    duration_ms: int | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    tools_summary: list[dict] | None = None,
) -> None:
    r = (route or "auto").strip() or "auto"
    s = (status or "completed").strip() or "completed"
    AGENT_RUNS_TOTAL.labels(route=r, status=s).inc()
    if duration_ms is not None and duration_ms >= 0:
        AGENT_RUN_DURATION_SECONDS.labels(route=r, status=s).observe(duration_ms / 1000.0)
    if prompt_tokens > 0:
        AGENT_TOKENS_TOTAL.labels(route=r, kind="prompt").inc(prompt_tokens)
    if completion_tokens > 0:
        AGENT_TOKENS_TOTAL.labels(route=r, kind="completion").inc(completion_tokens)
    if tools_summary:
        for item in tools_summary:
            name = str(item.get("name") or "unknown")
            calls = int(item.get("calls") or 0)
            errors = int(item.get("errors") or 0)
            ok = max(0, calls - errors)
            if ok > 0:
                TOOL_CALLS_TOTAL.labels(tool=name, outcome="success").inc(ok)
            if errors > 0:
                TOOL_CALLS_TOTAL.labels(tool=name, outcome="error").inc(errors)
