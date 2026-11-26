from app.services.chat.event_normalizer import normalize_control_payload, normalize_passthrough_event


def test_control_payload_approval_with_detail():
    out = normalize_control_payload(
        "approval.request",
        {
            "request_id": "r1",
            "tool": "execute_code",
            "preview": "print(1)",
            "execution_generation": 3,
            "detail": {"code": "print(1)", "language": "python", "reason": "needs approval"},
        },
    )
    assert out["kind"] == "approval"
    assert out["request_id"] == "r1"
    assert out["code"] == "print(1)"
    assert out["language"] == "python"
    assert out["description"] == "needs approval"
    assert out["execution_generation"] == 3


def test_control_payload_clarify_falls_back_to_prompt_id_and_payload_detail():
    out = normalize_control_payload("clarify.request", {"prompt_id": "p9", "description": "which one?"})
    assert out["kind"] == "clarify"
    assert out["request_id"] == "p9"
    assert out["description"] == "which one?"
    assert "code" not in out


def test_control_payload_missing_request_id():
    assert normalize_control_payload("approval.request", {})["request_id"] == ""


def test_thinking_and_reasoning_delta_map_to_reasoning():
    for name in ("thinking.delta", "reasoning.delta"):
        ev, data = normalize_passthrough_event(name, {"delta": "hm", "step": 2, "title": None})
        assert ev == "reasoning.delta"
        assert data == {"text": "hm", "step": 2, "title": ""}


def test_message_delta_prefers_delta_then_text():
    assert normalize_passthrough_event("message.delta", {"delta": "a", "text": "b"}) == ("message.delta", {"text": "a"})
    assert normalize_passthrough_event("message.delta", {"text": "b"}) == ("message.delta", {"text": "b"})
    assert normalize_passthrough_event("message.delta", {}) == ("message.delta", {"text": ""})


def test_message_interim_becomes_commentary():
    ev, data = normalize_passthrough_event("message.interim", {"text": "t", "already_streamed": 1})
    assert ev == "commentary"
    assert data["text"] == "t"
    assert data["already_streamed"] is True


def test_tool_events_get_default_metadata_without_overriding():
    ev, data = normalize_passthrough_event("tool.started", {"tool": "web_search", "label": "custom"})
    assert ev == "tool.started"
    assert data["label"] == "custom"
    assert "ui_kind" in data and "summary" in data


def test_run_snapshot_injects_assistant_info_and_pending_control():
    ev, data = normalize_passthrough_event(
        "run.snapshot",
        {"pending_controls": [{"kind": "approval", "request_id": "r2"}]},
        assistant_id_str="a1",
        assistant_created_at="2026-01-01T00:00:00Z",
    )
    assert ev == "run.snapshot"
    assert data["assistant_message_id"] == "a1"
    assert data["created_at"] == "2026-01-01T00:00:00Z"
    assert data["pending_control"]["kind"] == "approval"
    assert data["pending_control"]["request_id"] == "r2"


def test_run_snapshot_does_not_override_existing_values():
    _, data = normalize_passthrough_event(
        "run.snapshot", {"assistant_message_id": "keep"}, assistant_id_str="other"
    )
    assert data["assistant_message_id"] == "keep"


def test_unknown_event_passes_through_copy():
    payload = {"x": 1}
    ev, data = normalize_passthrough_event("custom.event", payload)
    assert ev == "custom.event"
    assert data == payload and data is not payload
