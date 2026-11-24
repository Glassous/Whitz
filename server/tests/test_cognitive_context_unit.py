from __future__ import annotations

from app.services import cross_chat_memory as ccm


def test_working_state_patch_adds_updates_and_evicts_completed_goals() -> None:
    initial = {
        "active_goals": [
            {"title": "重构 RAG 引擎", "status": "in_progress"},
            {"title": "设计主聊天上下文方案", "status": "in_progress"},
        ],
        "recent_decisions": [{"decision": "使用 shared/whitz_rag 共享包", "date": "2026-11-24"}],
        "open_questions": ["是否暴露 Working State UI？"],
        "key_entities": {"db": "pgvector 17"},
    }
    patch = {
        "completed_goals": ["重构 RAG 引擎"],
        "active_goals": [{"title": "上线 L2 情景档案", "status": "in_progress"}],
        "recent_decisions": [{"decision": "采用四层认知上下文金字塔", "reason": "避免滚动摘要失真"}],
        "resolved_questions": ["是否暴露 Working State UI？"],
        "open_questions": ["L0 置顶预算是否需要按会员等级调整？"],
        "key_entities": {"cache": "Redis 7"},
    }
    updated = ccm.apply_working_state_patch(initial, patch)
    goal_titles = [g["title"] for g in updated["active_goals"]]
    assert "重构 RAG 引擎" not in goal_titles
    assert "设计主聊天上下文方案" in goal_titles
    assert "上线 L2 情景档案" in goal_titles

    # Newest decision prepended first
    assert updated["recent_decisions"][0]["decision"] == "采用四层认知上下文金字塔"
    assert len(updated["recent_decisions"]) == 2
    assert updated["open_questions"] == ["L0 置顶预算是否需要按会员等级调整？"]
    assert updated["key_entities"]["db"] == "pgvector 17"
    assert updated["key_entities"]["cache"] == "Redis 7"


def test_format_working_state_prompt_and_legacy_fallback() -> None:
    ws = {
        "active_goals": [{"title": "完成验收测试", "status": "in_progress", "updated": "2026-11-24"}],
        "recent_decisions": [{"decision": "主聊与旁聊统一接入 Episode 归档", "date": "2026-11-24", "reason": "零黑洞"}],
        "open_questions": [],
        "key_entities": {"port": "5434"},
    }
    rendered = ccm.format_working_state_prompt(ws)
    assert "### 进行中目标与待办" in rendered
    assert "完成验收测试" in rendered
    assert "### 近期已拍板决策" in rendered
    assert "port: 5434" in rendered

    # Fallback to legacy rolling_summary when structured state is absent
    legacy = ccm.format_working_state_prompt(None, rolling_summary="旧版滚动摘要内容")
    assert legacy == "旧版滚动摘要内容"


def test_low_signal_turn_filter() -> None:
    assert ccm._is_low_signal_turn("好的", "不客气，有问题随时叫我。") is True
    assert ccm._is_low_signal_turn("谢谢！", "好的，随时为您服务。") is True
    assert ccm._is_low_signal_turn(
        "请确认 Redis 缓存穿透方案",
        "建议使用布隆过滤器加空值短 TTL（60s）并结合分布式互斥锁重建缓存。",
    ) is False
    # Short user message with substantial code block answer must NOT be filtered
    assert ccm._is_low_signal_turn("继续", "```python\ndef solve():\n    return 42\n```\n这是完整的实现代码与说明。") is False


def test_parse_episode_and_state_json() -> None:
    raw = (
        '```json\n'
        '{"episode":{"topic":"主聊天上下文架构设计","summary":"讨论了主聊长上下文与RAG分工，确立L0-L3四层架构。",'
        '"key_facts":["L0常驻<=10条","L2不可变归档"],"entities":["conversation_episodes","working_state"]},'
        '"working_state_patch":{"active_goals":[{"title":"实现L2归档","status":"in_progress"}]}}\n'
        '```'
    )
    parsed = ccm._parse_episode_and_state_json(raw)
    assert parsed is not None
    ep, patch = parsed
    assert ep["topic"] == "主聊天上下文架构设计"
    assert "conversation_episodes" in ep["entities"]
    assert patch["active_goals"][0]["title"] == "实现L2归档"
