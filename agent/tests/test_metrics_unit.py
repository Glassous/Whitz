from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import metrics


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(metrics.metrics_middleware)

    @app.get("/items/{item_id}")
    async def item(item_id: int):
        return {"id": item_id}

    @app.get("/metrics")
    async def prom():
        return metrics.render_prometheus_metrics()

    return app


def _count(route: str, status: str) -> float:
    return metrics.AGENT_HTTP_REQUESTS_TOTAL.labels(method="GET", route=route, status=status)._value.get()


def test_middleware_records_templated_route_not_raw_path():
    client = TestClient(_app())
    before = _count("/items/{item_id}", "200")
    assert client.get("/items/1").status_code == 200
    assert client.get("/items/2").status_code == 200
    assert _count("/items/{item_id}", "200") == before + 2


def test_unmatched_route_uses_raw_path():
    client = TestClient(_app())
    before = _count("/nope", "404")
    assert client.get("/nope").status_code == 404
    assert _count("/nope", "404") == before + 1


def test_metrics_endpoint_not_self_counted_and_renders_names():
    client = TestClient(_app())
    before = _count("/metrics", "200")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "whitz_agent_http_requests_total" in resp.text
    assert _count("/metrics", "200") == before
