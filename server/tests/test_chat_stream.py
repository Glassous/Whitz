import json

from app.services.chat_stream import _find_todos, parse_todos, sse


def test_sse_keeps_unicode():
    ev = sse("message.delta", {"text": "你好"})
    assert ev["event"] == "message.delta"
    assert "你好" in ev["data"]
    assert json.loads(ev["data"]) == {"text": "你好"}


def test_parse_todos_plain_list():
    items = parse_todos([{"id": "1", "content": "步骤一", "status": "pending"}])
    assert items == [{"id": "1", "content": "步骤一", "status": "pending", "parent": None}]


def test_parse_todos_nested_dict():
    preview = {"todos": [{"id": "1", "title": "搜索", "status": "in_progress"}]}
    items = parse_todos(preview)
    assert items[0]["content"] == "搜索"
    assert items[0]["status"] == "in_progress"


def test_parse_todos_json_string():
    raw = json.dumps({"items": [{"id": "1", "text": "整理", "status": "completed"}]})
    items = parse_todos(raw)
    assert items[0]["content"] == "整理"
    assert items[0]["status"] == "completed"


def test_parse_todos_defaults_and_parent():
    items = parse_todos([
        {"id": "1", "content": "父任务", "status": "in_progress"},
        {"id": "2", "task": "子任务", "parent": "1"},
    ])
    assert items[1]["content"] == "子任务"
    assert items[1]["status"] == "pending"
    assert items[1]["parent"] == "1"


def test_parse_todos_invalid_returns_none():
    assert parse_todos(None) is None
    assert parse_todos("not json") is None
    assert parse_todos('{"todos": [{"id":"1","content":"trunc') is None  # truncated preview
    assert parse_todos(123) is None


def test_find_todos_deep_recursion():
    obj = {"result": {"data": {"steps": [{"id": "1", "content": "deep", "status": "pending"}]}}}
    found = _find_todos(obj)
    assert found[0]["content"] == "deep"


def test_find_todos_ignores_non_todo_lists():
    assert _find_todos({"values": [1, 2, 3]}) is None
    assert _find_todos([{"foo": "bar"}]) is None