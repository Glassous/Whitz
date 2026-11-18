import base64
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services import desktop_policy
from cryptography.hazmat.primitives import serialization

from tests.conftest import auth_header


def _settings(private_key: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        desktop_policy_private_key=private_key or "",
        desktop_policy_key_id="test-key",
        desktop_policy_ttl_minutes=60,
        desktop_work_mode_enabled=True,
        desktop_work_disabled_reason="",
        desktop_min_app_version="0.1.0",
        desktop_latest_app_version="0.1.0",
        desktop_llm_model_alias="whitz-default",
    )


def test_policy_envelope_is_signed(monkeypatch):
    key = Ed25519PrivateKey.generate()
    seed = base64.b64encode(
        key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    monkeypatch.setattr(desktop_policy, "get_settings", lambda: _settings(seed))

    envelope = desktop_policy.build_envelope()
    assert envelope["signature"]
    raw = envelope["payload"].encode("utf-8")
    key.public_key().verify(base64.b64decode(envelope["signature"]), raw)

    payload = json.loads(envelope["payload"])
    assert payload["work_mode"]["enabled"] is True
    assert payload["llm"]["model_alias"] == "whitz-default"
    assert payload["version"] > 0


def test_policy_without_key_is_unsigned(monkeypatch):
    monkeypatch.setattr(desktop_policy, "get_settings", lambda: _settings(None))
    envelope = desktop_policy.build_envelope()
    assert envelope["signature"] == ""
    assert json.loads(envelope["payload"])["work_mode"]["enabled"] is True


def test_policy_endpoint_public(client):
    resp = client.get("/api/desktop/policy")
    assert resp.status_code == 200
    body = resp.json()
    assert "payload" in body and "signature" in body
    assert json.loads(body["payload"])["desktop"]["min_app_version"]


@pytest.mark.asyncio
async def test_desktop_llm_key_lifecycle(client, register):
    data = await register(email="desktop@test.local")
    token = data["access_token"]

    issued = await client.post("/api/desktop/llm-key", headers=auth_header(token))
    assert issued.status_code == 201, issued.text
    key = issued.json()["key"]
    assert key.startswith("whitz-dk-")

    models = await client.get("/api/desktop/llm/v1/models", headers=auth_header(key))
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "whitz-default"

    revoked = await client.delete("/api/desktop/llm-key", headers=auth_header(token))
    assert revoked.status_code == 204

    after = await client.get("/api/desktop/llm/v1/models", headers=auth_header(key))
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_desktop_llm_rejects_unknown_key(client):
    resp = await client.get("/api/desktop/llm/v1/models", headers=auth_header("whitz-dk-unknown"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_chat_completions_requires_desktop_key(client, register):
    data = await register(email="desktop2@test.local")
    resp = await client.post(
        "/api/desktop/llm/v1/chat/completions",
        headers=auth_header(data["access_token"]),
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sanitize_body_pins_model_and_caps_tokens(monkeypatch):
    from app.services import llm_gateway

    monkeypatch.setattr(
        llm_gateway,
        "get_settings",
        lambda: SimpleNamespace(
            desktop_llm_max_tokens=128,
            desktop_llm_model_alias="whitz-default",
            desktop_llm_upstream_model="",
            llm_model="upstream-model",
        ),
    )
    body = llm_gateway.sanitize_body({"model": "gpt-4.1", "max_tokens": 9999, "messages": []})
    assert body["model"] == "upstream-model"
    assert body["max_tokens"] == 128
