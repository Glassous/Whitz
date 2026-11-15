import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services import chat_tickets, limits, usage


def make_request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


async def test_ticket_is_single_use_and_bound():
    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    issued = await chat_tickets.issue(user_id, conv_id, "send", "nonce-123456", "127.0.0.1")
    headers = {
        chat_tickets.TICKET_HEADER: issued["ticket"],
        chat_tickets.NONCE_HEADER: "nonce-123456",
    }
    await chat_tickets.require(make_request(headers), user_id, conv_id, "send")

    with pytest.raises(HTTPException) as exc:
        await chat_tickets.require(make_request(headers), user_id, conv_id, "send")
    assert exc.value.status_code == 403


async def test_ticket_rejects_wrong_nonce():
    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    issued = await chat_tickets.issue(user_id, conv_id, "stop", "nonce-abcdef", None)
    headers = {
        chat_tickets.TICKET_HEADER: issued["ticket"],
        chat_tickets.NONCE_HEADER: "nonce-other",
    }
    with pytest.raises(HTTPException) as exc:
        await chat_tickets.require(make_request(headers), user_id, conv_id, "stop")
    assert exc.value.status_code == 403


async def test_run_slots_limit_per_user_and_release():
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    user_c = uuid.uuid4()
    slot_a = await limits.acquire_run(user_a)
    assert slot_a
    assert await limits.acquire_run(user_a) is None
    slot_b = await limits.acquire_run(user_b)
    assert slot_b
    # Two global run slots are used at this point.
    assert await limits.acquire_run(user_c) is None
    await limits.release_run(user_a, slot_a)
    slot_c = await limits.acquire_run(user_c)
    assert slot_c
    await limits.release_run(user_b, slot_b)
    await limits.release_run(user_c, slot_c)


def test_tokens_from_usage():
    assert usage.tokens_from_usage({"total_tokens": 42}) == 42
    assert usage.tokens_from_usage({"prompt_tokens": 10, "completion_tokens": 5}) == 15
    assert usage.tokens_from_usage({"input_tokens": 7, "output_tokens": 3}) == 10
    assert usage.tokens_from_usage(None) == 0
