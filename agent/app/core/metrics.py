from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

AGENT_HTTP_REQUESTS_TOTAL = Counter(
    "whitz_agent_http_requests_total",
    "Total HTTP requests handled by Whitz agent API",
    ["method", "route", "status"],
)
AGENT_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "whitz_agent_http_request_duration_seconds",
    "Agent API HTTP latency in seconds",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
AGENT_RUNS_ENQUEUED_TOTAL = Counter(
    "whitz_agent_runs_enqueued_total",
    "Total agent runs enqueued to ARQ",
    ["route"],
)
AGENT_ARQ_QUEUE_DEPTH = Gauge(
    "whitz_agent_arq_queue_depth",
    "Current ARQ queue depth observed on agent API",
)
AGENT_GUARDRAIL_TRIGGERS_TOTAL = Counter(
    "whitz_agent_guardrail_triggers_total",
    "Total security guardrail triggers by stage, action, and category",
    ["stage", "action", "category"],
)
AGENT_PII_REDACTED_TOTAL = Counter(
    "whitz_agent_pii_redacted_total",
    "Total PII/secret entities redacted before LLM calls",
    ["entity_type"],
)
AGENT_SEMANTIC_CACHE_REQUESTS_TOTAL = Counter(
    "whitz_agent_semantic_cache_requests_total",
    "Total semantic cache lookups by outcome",
    ["result"],
)
AGENT_SEMANTIC_CACHE_TOKENS_SAVED_TOTAL = Counter(
    "whitz_agent_semantic_cache_tokens_saved_total",
    "Estimated LLM tokens saved by semantic cache hits",
)
AGENT_SEMANTIC_CACHE_LOOKUP_SECONDS = Histogram(
    "whitz_agent_semantic_cache_lookup_seconds",
    "Semantic cache lookup latency in seconds",
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
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
        AGENT_HTTP_REQUESTS_TOTAL.labels(method=request.method, route=route, status=status_code).inc()
        AGENT_HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, route=route).observe(elapsed)


def render_prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
