from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.schemas import EmailCodeRequest
from app.core import security
from app.services import llm_gateway, ops_service, posts_service, rag_jobs, realtime_bus


@pytest.mark.asyncio
async def test_realtime_multiplexer_fanout_and_cleanup():
    uid = uuid.uuid4()
    received_a: list[tuple[str, dict]] = []
    received_b: list[tuple[str, dict]] = []

    from contextlib import aclosing

    async def _consume(out: list[tuple[str, dict]]):
        async with aclosing(realtime_bus.subscribe_user_events(uid)) as stream:
            async for ev, data in stream:
                out.append((ev, data))
                if len(out) >= 2:
                    return

    t1 = asyncio.create_task(_consume(received_a))
    t2 = asyncio.create_task(_consume(received_b))
    await asyncio.sleep(0.05)

    await realtime_bus.publish_user_event(uid, "library.updated", {"action": "added", "file_id": "f1"})
    await realtime_bus.publish_user_event(uid, "title.updated", {"title": "New"})

    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)
    assert received_a == [
        ("library.updated", {"action": "added", "file_id": "f1"}),
        ("title.updated", {"title": "New"}),
    ]
    assert received_b == received_a
    # Cleanup verified
    assert str(uid) not in realtime_bus._LOCAL_SUBSCRIBERS


def test_llm_gateway_sse_line_parsing_accurate_chars_and_usage():
    tok, ch = llm_gateway._parse_sse_data_line(
        b'data: {"choices":[{"delta":{"content":"hello world","reasoning_content":"think"}}]}\n'
    )
    assert tok == 0
    assert ch == len("hello world") + len("think")

    tok2, ch2 = llm_gateway._parse_sse_data_line(
        b'data: {"choices":[],"usage":{"prompt_tokens":120,"completion_tokens":45,"total_tokens":165}}\n'
    )
    assert tok2 == 165
    assert ch2 == 0

    assert llm_gateway._parse_sse_data_line(b"data: [DONE]\n") == (0, 0)
    assert llm_gateway._parse_sse_data_line(b": keepalive\n") == (0, 0)


@pytest.mark.asyncio
async def test_llm_gateway_stream_does_not_bill_on_upstream_error(monkeypatch):
    settled: list[int] = []

    async def _fake_settle(uid, tokens):
        settled.append(tokens)

    class _FakeResp:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aread(self):
            return b"upstream error"

    class _FakeClient:
        def stream(self, *args, **kwargs):
            return _FakeResp()

    monkeypatch.setattr(llm_gateway, "_settle", _fake_settle)
    monkeypatch.setattr(llm_gateway, "client", lambda: _FakeClient())

    user = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(Exception):
        async for _ in llm_gateway.proxy_stream(user, {"messages": [{"role": "user", "content": "hi"}]}):
            pass
    assert settled == []


def test_posts_composite_cursor_roundtrip_and_legacy_compat():
    ts = datetime(2026, 11, 26, 8, 30, 0, tzinfo=timezone.utc)
    pid = uuid.uuid4()
    encoded = posts_service.encode_post_cursor(ts, pid)
    dec_ts, dec_id = posts_service.decode_post_cursor(encoded)
    assert dec_ts == ts
    assert dec_id == pid

    # Legacy ISO-only cursor still works
    leg_ts, leg_id = posts_service.decode_post_cursor(ts.isoformat())
    assert leg_ts == ts
    assert leg_id is None


def test_rag_backfill_scope_normalization():
    assert rag_jobs.normalize_backfill_scope("file_chunks") == {"file_chunks"}
    assert rag_jobs.normalize_backfill_scope("files") == {"file_chunks"}
    assert rag_jobs.normalize_backfill_scope("memory_entries") == {"memory_entries"}
    assert rag_jobs.normalize_backfill_scope("memories") == {"memory_entries"}
    assert rag_jobs.normalize_backfill_scope("conversation_digests") == {"conversation_digests"}
    assert rag_jobs.normalize_backfill_scope("conversation_episodes") == {"conversation_episodes"}
    assert rag_jobs.normalize_backfill_scope("message_chunks") == {"message_chunks"}
    assert rag_jobs.normalize_backfill_scope("chats") == {
        "conversation_digests",
        "conversation_episodes",
        "message_chunks",
    }
    assert len(rag_jobs.normalize_backfill_scope("all")) == 5


@pytest.mark.asyncio
async def test_webhook_ssrf_blocks_private_and_loopback():
    assert await ops_service.dispatch_webhook("http://127.0.0.1:8000/hook", {"rule_name": "r"}) == "blocked_ssrf"
    assert await ops_service.dispatch_webhook("http://localhost/hook", {"rule_name": "r"}) == "blocked_ssrf"
    assert await ops_service.dispatch_webhook("http://169.254.169.254/latest/meta-data", {"rule_name": "r"}) == "blocked_ssrf"
    assert await ops_service.dispatch_webhook("file:///etc/passwd", {"rule_name": "r"}) == "blocked_ssrf"


@pytest.mark.asyncio
async def test_async_argon2_and_client_ip_proxy_resolution():
    hashed = await security.hash_password_async("SuperSecret123!")
    assert await security.verify_password_async("SuperSecret123!", hashed) is True
    assert await security.verify_password_async("WrongPass!", hashed) is False

    req = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"x-forwarded-for": "203.0.113.42, 10.0.0.1"},
    )
    assert security.get_client_ip(req) == "203.0.113.42"

    untrusted_req = SimpleNamespace(
        client=SimpleNamespace(host="198.51.100.7"),
        headers={"x-forwarded-for": "203.0.113.42"},
    )
    assert security.get_client_ip(untrusted_req) == "198.51.100.7"


def test_email_code_request_normalizes_desktop_reset_alias():
    req = EmailCodeRequest(email="dev@example.com", purpose="reset")
    assert req.purpose == "reset_password"
