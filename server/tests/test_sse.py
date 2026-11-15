from app.services.sse import iter_sse


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


async def collect(lines):
    return [ev async for ev in iter_sse(FakeResponse(lines))]


async def test_skips_comments_and_keepalive():
    events = await collect([": keepalive", "event: message.delta", 'data: {"text":"hi"}', ""])
    assert events == [("message.delta", {"text": "hi"})]


async def test_payload_type_field_wins_over_event():
    events = await collect(["event: ignored", 'data: {"type":"run.completed","output":"done"}', ""])
    assert events == [("run.completed", {"type": "run.completed", "output": "done"})]


async def test_multiline_data_joined():
    events = await collect(["event: x", 'data: {"a":', 'data: 1}', ""])
    assert events == [("x", {"a": 1})]


async def test_non_dict_payload_wrapped():
    events = await collect(["event: x", "data: 42", ""])
    assert events == [("x", {"value": 42})]


async def test_invalid_json_becomes_raw():
    events = await collect(["event: x", "data: not-json", ""])
    assert events == [("x", {"raw": "not-json"})]


async def test_trailing_data_without_blank_line_flushed():
    events = await collect(["event: x", 'data: {"k":"v"}'])
    assert events == [("x", {"k": "v"})]


async def test_multiple_events():
    events = await collect([
        'data: {"type":"message.delta","text":"a"}', "",
        ": ping", "",
        'data: {"type":"run.completed"}', "",
    ])
    assert [name for name, _ in events] == ["message.delta", "run.completed"]