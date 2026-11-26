from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from app.services import limits
from app.services.chat import (
    finalize_plan_status,
    get_tool_meta,
    merge_citations,
    normalize_control_payload,
    normalize_passthrough_event,
    summarize_tool_call,
)


def test_tool_meta_and_human_summaries():
    label, kind = get_tool_meta("web_search")
    assert label == "联网搜索" and kind == "search"

    # Legacy MCP prefix stripping
    label2, kind2 = get_tool_meta("mcp__whitz_files__write_workspace_file")
    assert label2 == "写入工作区文件" and kind2 == "file_write"

    assert "命中 3 条" in summarize_tool_call(
        "knowledge_search",
        {"query": "LangGraph"},
        '{"results":[1,2,3]}',
    )
    assert "退出码 0" in summarize_tool_call(
        "execute_code",
        {"language": "python"},
        '{"exit_code": 0}',
    )
    assert "失败" in summarize_tool_call("web_extract", {"url": "https://x.test"}, None, "timeout")


def test_merge_citations_preserves_prefetch_across_stages():
    prefetch = [
        {"citation_id": "S1", "source_type": "file", "source_id": "f1", "locator": "p1", "score": 0.8},
        {"citation_id": "S2", "source_type": "memory", "source_id": "m1", "locator": "mem", "score": 0.7},
    ]
    mid_run = [
        {"citation_id": "S3", "source_type": "file", "source_id": "f2", "locator": "p3", "score": 0.9},
        {"citation_id": "S1", "source_type": "file", "source_id": "f1", "locator": "p1", "score": 0.85},
    ]
    merged = merge_citations(prefetch, mid_run)
    assert [c["citation_id"] for c in merged] == ["S1", "S2", "S3"]
    assert merged[0]["score"] == 0.85


def test_finalize_plan_status_closes_dangling_in_progress():
    plan = {
        "items": [
            {"id": "1", "content": "检索资料", "status": "completed"},
            {"id": "2", "content": "撰写报告", "status": "in_progress"},
            {"id": "3", "content": "补充图表", "status": "pending"},
        ]
    }
    done = finalize_plan_status(plan, "completed")
    assert done["items"][1]["status"] == "completed"
    assert done["items"][2]["status"] == "pending"

    failed = finalize_plan_status(plan, "failed")
    assert failed["items"][1]["status"] == "cancelled"


def test_path_c_passthrough_normalizer_matches_canonical_schema():
    ev, data = normalize_passthrough_event("thinking.delta", {"delta": "分析中", "step": 2})
    assert ev == "reasoning.delta"
    assert data == {"text": "分析中", "step": 2, "title": ""}

    ev2, data2 = normalize_passthrough_event("message.interim", {"text": "准备查文件", "already_streamed": True})
    assert ev2 == "commentary"
    assert data2["already_streamed"] is True

    ev3, data3 = normalize_passthrough_event(
        "approval.request",
        {"request_id": "r1", "execution_generation": 1, "tool": "execute_code", "detail": {"code": "print(1)", "language": "python", "reason": "计算"}},
    )
    assert ev3 == "approval.request"
    assert data3["code"] == "print(1)"
    assert data3["description"] == "计算"

    ev4, data4 = normalize_passthrough_event(
        "run.snapshot",
        {"status": "waiting_for_approval", "pending_controls": [{"kind": "approval", "request_id": "r1", "tool": "execute_code", "detail": {"code": "x=1"}}]},
        assistant_id_str="a1",
    )
    assert ev4 == "run.snapshot"
    assert data4["assistant_message_id"] == "a1"
    assert data4["pending_control"]["code"] == "x=1"


@pytest.mark.asyncio
async def test_limits_acquire_and_release_slots():
    uid = uuid.uuid4()
    s1 = await limits.acquire_run(uid, per_user=2)
    s2 = await limits.acquire_run(uid, per_user=2)
    s3 = await limits.acquire_run(uid, per_user=2)
    assert s1 is not None and s2 is not None and s3 is None
    await limits.release_run(uid, s1)
    s4 = await limits.acquire_run(uid, per_user=2)
    assert s4 is not None
    await limits.release_run(uid, s2)
    await limits.release_run(uid, s4)


def test_alembic_0024_migration_loads_cleanly():
    mig_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0024_refactor_indexes_and_telemetry.py"
    spec = importlib.util.spec_from_file_location("mig_0024", mig_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0024"
    assert mod.down_revision == "0023"
    assert callable(mod.upgrade) and callable(mod.downgrade)
