import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    AiPostDailyRun,
    AiPostPendingInteraction,
    CreditLedger,
    MemoryEntry,
    Post,
    PostComment,
    UsageDaily,
    User,
)
from app.services import memory_service, posts_service, web_search
from tests.conftest import auth_header


def test_compute_daily_post_count_formula():
    # 0 memory -> always 0 across all tiers
    for tier in ("free", "plus", "pro"):
        assert posts_service.compute_daily_post_count(tier, 0, 0) == 0
        assert posts_service.compute_daily_post_count(tier, 0, 3) == 0
        assert posts_service.compute_daily_post_count(tier, 5, 0) == 0

    # 1 entry / 1 category -> 1 across all tiers (never exceeds entry count)
    assert posts_service.compute_daily_post_count("free", 1, 1) == 1
    assert posts_service.compute_daily_post_count("plus", 1, 1) == 1
    assert posts_service.compute_daily_post_count("pro", 1, 1) == 1

    # More categories -> more posts; paid tiers > free
    free_3c = posts_service.compute_daily_post_count("free", 6, 3)
    plus_3c = posts_service.compute_daily_post_count("plus", 6, 3)
    pro_3c = posts_service.compute_daily_post_count("pro", 6, 3)
    assert free_3c == 1
    assert plus_3c == 3
    assert pro_3c == 3

    # High categories + volume bonus + tier caps (Free<=2, Plus<=5, Pro<=8)
    assert posts_service.compute_daily_post_count("free", 25, 6) == 2
    assert posts_service.compute_daily_post_count("plus", 25, 6) == 5
    assert posts_service.compute_daily_post_count("pro", 25, 6) == 8
    assert posts_service.compute_daily_post_count("pro", 15, 5) == 7


async def test_default_disabled_and_opt_in_toggle(register, client, db, engine):
    reg = await register(email="post_optin@test.local", display_name="PostOptIn")
    headers = auth_header(reg["access_token"])

    # Default must be False to avoid surprise credit consumption
    me = await client.get("/api/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["ai_posts_enabled"] is False
    assert me.json()["ai_posts_consented_at"] is None

    # Quota endpoint reflects disabled state and 0 memories -> 0 estimated
    q = await client.get("/api/posts/quota", headers=headers)
    assert q.status_code == 200
    assert q.json()["ai_posts_enabled"] is False
    assert q.json()["estimated_daily_count"] == 0

    # Scheduler does NOT claim disabled users
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    noon_utc = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)  # 12:00 Asia/Shanghai
    claimed = await posts_service.dispatch_daily_ai_posts(
        session_factory=session_factory, now=noon_utc, execute_inline=True
    )
    assert claimed == 0

    # Explicit opt-in enables feature and sets consented_at
    on_resp = await client.put("/api/users/me/ai-posts", json={"ai_posts_enabled": True}, headers=headers)
    assert on_resp.status_code == 200
    assert on_resp.json()["ai_posts_enabled"] is True
    assert on_resp.json()["ai_posts_consented_at"] is not None

    # Can toggle back off
    off_resp = await client.put("/api/users/me/ai-posts", json={"ai_posts_enabled": False}, headers=headers)
    assert off_resp.status_code == 200
    assert off_resp.json()["ai_posts_enabled"] is False


async def test_daily_ai_posts_zero_memory_skips_llm_and_search(register, client, db, engine, monkeypatch):
    reg = await register(email="post_zero@test.local", display_name="PostZero")
    headers = auth_header(reg["access_token"])
    user_id = uuid.UUID(reg["user"]["id"])

    await client.put("/api/users/me/ai-posts", json={"ai_posts_enabled": True}, headers=headers)

    called = {"llm": 0, "search": 0}

    async def _fail_search(*args, **kwargs):
        called["search"] += 1
        return []

    async def _fail_llm(*args, **kwargs):
        called["llm"] += 1
        return [], 0

    monkeypatch.setattr(web_search, "search_web", _fail_search)
    monkeypatch.setattr(posts_service, "_call_llm_json", _fail_llm)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    noon_utc = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)
    claimed = await posts_service.dispatch_daily_ai_posts(
        session_factory=session_factory, now=noon_utc, execute_inline=True
    )
    assert claimed == 1
    assert called["search"] == 0
    assert called["llm"] == 0

    run_row = (
        await db.execute(select(AiPostDailyRun).where(AiPostDailyRun.user_id == user_id))
    ).scalar_one()
    assert run_row.status == "skipped_empty_memory"
    assert run_row.target_count == 0
    assert run_row.generated_count == 0

    posts = (await db.execute(select(Post).where(Post.user_id == user_id))).scalars().all()
    assert len(posts) == 0


async def test_daily_ai_posts_web_grounded_credits_and_idempotency(register, client, db, engine, monkeypatch):
    reg = await register(email="post_plus@test.local", display_name="PostPlus")
    headers = auth_header(reg["access_token"])
    user_id = uuid.UUID(reg["user"]["id"])

    # Upgrade to Plus and enable ai_posts
    user = await db.get(User, user_id)
    assert user is not None
    user.membership_tier = "plus"
    user.membership_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    await db.commit()
    await client.put("/api/users/me/ai-posts", json={"ai_posts_enabled": True}, headers=headers)

    # Seed memories across 3 active collections (Plus + 3 categories + 6 entries => 3 daily posts)
    await memory_service.add_entry(db, user_id, "memory", "关注 AI Agent 架构演进", title="Agent 架构")
    await memory_service.add_entry(db, user_id, "memory", "喜欢极简风格界面设计", title="设计偏好")
    await memory_service.add_entry(db, user_id, "user", "平时喜欢手冲咖啡和徒步", title="生活兴趣")
    await memory_service.add_entry(db, user_id, "user", "偏好高信息密度的深度长文", title="阅读习惯")
    await memory_service.add_entry(db, user_id, "projects", "正在开发 Whitz 多端 AI 助手", title="Whitz 项目")
    await memory_service.add_entry(db, user_id, "projects", "重点打磨长期记忆与 RAG 检索", title="RAG 方向")

    q = await client.get("/api/posts/quota", headers=headers)
    assert q.status_code == 200
    assert q.json()["active_collection_count"] == 3
    assert q.json()["memory_entry_count"] == 6
    assert q.json()["estimated_daily_count"] == 3

    search_queries: list[str] = []

    async def _fake_search(query: str, *, max_results: int = 4, freshness: str = "oneWeek"):
        search_queries.append(query)
        return [
            {
                "title": f"{query} 最新进展",
                "url": f"https://example.com/news/{len(search_queries)}",
                "snippet": f"关于 {query} 的本周重要动态摘要。",
                "site_name": "TechDaily",
                "published_at": "2026-11-25",
            }
        ]

    llm_calls = {"n": 0}

    async def _fake_llm_json(messages, *, temperature=0.7, max_tokens=2400):
        llm_calls["n"] += 1
        if llm_calls["n"] == 1:
            return (
                [
                    {
                        "collection_slug": "projects",
                        "post_kind": "opinion",
                        "topic": "Agent 长期记忆新范式",
                        "angle": "结合 Whitz 架构发表观点",
                        "search_query": "AI Agent 长期记忆 2026",
                    },
                    {
                        "collection_slug": "user",
                        "post_kind": "digest",
                        "topic": "手冲咖啡产季风味速递",
                        "angle": "整理最新产区资讯",
                        "search_query": "手冲咖啡 2026 新产季",
                    },
                    {
                        "collection_slug": "memory",
                        "post_kind": "insight",
                        "topic": "极简界面与信息密度平衡",
                        "angle": "设计观察",
                        "search_query": "极简 UI 信息密度 设计趋势",
                    },
                ],
                600,
            )
        return (
            [
                {
                    "title": "对 Agent 长期记忆架构的一点新想法",
                    "content": "结合本周社区讨论与你的 Whitz 项目，多记忆集分层检索正在成为主流。",
                    "tags": ["Agent", "记忆"],
                    "post_kind": "opinion",
                    "collection_slug": "projects",
                },
                {
                    "title": "这周手冲咖啡圈的新产季风味速递",
                    "content": "帮你翻到了本周几家烘焙商的新豆单，埃塞水洗表现很亮眼。",
                    "tags": ["咖啡", "生活"],
                    "post_kind": "digest",
                    "collection_slug": "user",
                },
                {
                    "title": "极简界面如何兼顾高信息密度",
                    "content": "最近看到几个很克制的交互案例，和你偏好的高密度阅读风格很契合。",
                    "tags": ["设计"],
                    "post_kind": "insight",
                    "collection_slug": "memory",
                },
            ],
            1400,
        )

    monkeypatch.setattr(web_search, "search_web", _fake_search)
    monkeypatch.setattr(posts_service, "_call_llm_json", _fake_llm_json)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    noon_utc = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)
    claimed = await posts_service.dispatch_daily_ai_posts(
        session_factory=session_factory, now=noon_utc, execute_inline=True
    )
    assert claimed == 1
    assert len(search_queries) == 3
    assert llm_calls["n"] == 2

    # Verify posts stored with web_sources and collection metadata
    feed = await client.get("/api/posts", headers=headers)
    assert feed.status_code == 200
    items = feed.json()["items"]
    assert len(items) == 3
    assert all(it["author_type"] == "ai" for it in items)
    assert all(len(it["web_sources"]) == 1 for it in items)
    assert {it["post_kind"] for it in items} == {"opinion", "digest", "insight"}

    # Verify credits & daily usage settled (600 + 1400 = 2000 tokens)
    ledger_rows = (
        await db.execute(select(CreditLedger).where(CreditLedger.user_id == user_id))
    ).scalars().all()
    assert sum(r.tokens for r in ledger_rows) == -2000
    usage_rows = (await db.execute(select(UsageDaily).where(UsageDaily.user_id == user_id))).scalars().all()
    assert sum(r.tokens for r in usage_rows) == 2000

    # Idempotency: re-running same day claims 0 users and creates no duplicates
    claimed_again = await posts_service.dispatch_daily_ai_posts(
        session_factory=session_factory, now=noon_utc + timedelta(hours=2), execute_inline=True
    )
    assert claimed_again == 0
    feed_again = await client.get("/api/posts", headers=headers)
    assert len(feed_again.json()["items"]) == 3


async def test_user_post_memory_ingestion_and_delayed_ai_engagement(register, client, db, engine, monkeypatch):
    reg = await register(email="post_engage@test.local", display_name="PostEngage")
    headers = auth_header(reg["access_token"])
    user_id = uuid.UUID(reg["user"]["id"])

    await client.put("/api/users/me/ai-posts", json={"ai_posts_enabled": True}, headers=headers)

    # 1. User creates a private post -> auto-ingested into long-term memory + delayed AI engagement queued
    create_resp = await client.post(
        "/api/posts",
        json={
            "title": "周末计划",
            "content": "打算这周末去爬山，顺便测试一下新的便携咖啡壶。",
            "tags": ["徒步", "咖啡"],
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    post_data = create_resp.json()
    post_id = uuid.UUID(post_data["id"])
    assert post_data["author_type"] == "user"
    assert post_data["memory_entry_id"] is not None

    # Verify MemoryEntry created with source="post"
    mem_row = await db.get(MemoryEntry, uuid.UUID(post_data["memory_entry_id"]))
    assert mem_row is not None
    assert mem_row.source == "post"
    assert "便携咖啡壶" in mem_row.content

    # Verify delayed interaction queued in the future (NOT instant)
    pending_jobs = (
        await db.execute(
            select(AiPostPendingInteraction).where(
                AiPostPendingInteraction.post_id == post_id,
                AiPostPendingInteraction.kind == "user_post_engage",
            )
        )
    ).scalars().all()
    assert len(pending_jobs) == 1
    assert pending_jobs[0].status == "pending"
    assert pending_jobs[0].scheduled_for > datetime.now(timezone.utc)

    async def _fake_engage_llm(messages, *, temperature=0.7, max_tokens=450):
        sys_text = messages[0]["content"]
        if "刷到了它" in sys_text:
            return {"should_like": True, "comment": "爬山配手冲太惬意了！记得带保温杯装热水。"}, 320
        return {"should_like_comment": True, "reply": "好主意，拍几张山顶风景回来分享！"}, 280

    monkeypatch.setattr(posts_service, "_call_llm_json", _fake_engage_llm)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Not due yet -> 0 claimed
    early_claimed = await posts_service.dispatch_due_interactions(
        session_factory=session_factory,
        now=datetime.now(timezone.utc),
        execute_inline=True,
    )
    assert early_claimed == 0

    # Fast-forward time -> due interaction executes AI like + AI comment + credit settlement
    future = datetime.now(timezone.utc) + timedelta(minutes=15)
    due_claimed = await posts_service.dispatch_due_interactions(
        session_factory=session_factory,
        now=future,
        execute_inline=True,
    )
    assert due_claimed == 1

    detail = (await client.get(f"/api/posts/{post_id}", headers=headers)).json()
    assert detail["ai_liked"] is True
    assert len(detail["comments"]) == 1
    ai_comment_id = detail["comments"][0]["id"]
    assert detail["comments"][0]["author_type"] == "ai"
    assert "手冲" in detail["comments"][0]["content"]

    # 2. User replies to the AI comment -> queues delayed comment_reply
    reply_resp = await client.post(
        f"/api/posts/{post_id}/comments",
        json={
            "content": "哈哈对，已经把保温杯放进背包了！",
            "reply_to_id": ai_comment_id,
            "trigger_ai_reply": True,
        },
        headers=headers,
    )
    assert reply_resp.status_code == 201
    reply_payload = reply_resp.json()
    assert reply_payload["ai_reply_scheduled"] is True
    user_comment_id = reply_payload["comment"]["id"]
    assert reply_payload["comment"]["reply_to_id"] == ai_comment_id
    assert reply_payload["comment"]["reply_to_author_type"] == "ai"

    # Execute delayed AI reply
    due_reply = await posts_service.dispatch_due_interactions(
        session_factory=session_factory,
        now=datetime.now(timezone.utc) + timedelta(minutes=10),
        execute_inline=True,
    )
    assert due_reply == 1

    detail_after = (await client.get(f"/api/posts/{post_id}", headers=headers)).json()
    assert len(detail_after["comments"]) == 3
    user_c = next(c for c in detail_after["comments"] if c["id"] == user_comment_id)
    ai_reply_c = detail_after["comments"][2]
    assert user_c["ai_liked"] is True
    assert ai_reply_c["author_type"] == "ai"
    assert ai_reply_c["reply_to_id"] == user_comment_id

    # Verify credits deducted for both engagements (320 + 280 = 600 tokens)
    ledger_rows = (
        await db.execute(select(CreditLedger).where(CreditLedger.user_id == user_id))
    ).scalars().all()
    assert sum(r.tokens for r in ledger_rows) == -600


async def test_posts_privacy_isolation_and_interactions(register, client):
    reg_a = await register(email="post_owner@test.local", display_name="PostOwner")
    reg_b = await register(email="post_other@test.local", display_name="PostOther")
    headers_a = auth_header(reg_a["access_token"])
    headers_b = auth_header(reg_b["access_token"])

    created = (
        await client.post(
            "/api/posts",
            json={"title": "私密思考", "content": "这条动态只有我能看到。"},
            headers=headers_a,
        )
    ).json()
    pid = created["id"]

    # Owner interactions: like, bookmark, discuss
    liked = (await client.post(f"/api/posts/{pid}/like", headers=headers_a)).json()
    assert liked["is_liked"] is True
    bookmarked = (await client.post(f"/api/posts/{pid}/bookmark", headers=headers_a)).json()
    assert bookmarked["is_bookmarked"] is True
    discuss = (await client.post(f"/api/posts/{pid}/discuss", headers=headers_a)).json()
    assert discuss["conversation_id"]
    assert "私密思考" in discuss["prefill_prompt"]

    # User B cannot see or touch User A's post
    feed_b = (await client.get("/api/posts", headers=headers_b)).json()
    assert feed_b["items"] == []
    assert (await client.get(f"/api/posts/{pid}", headers=headers_b)).status_code == 404
    assert (await client.post(f"/api/posts/{pid}/like", headers=headers_b)).status_code == 404
    assert (await client.post(f"/api/posts/{pid}/bookmark", headers=headers_b)).status_code == 404
    assert (
        await client.post(f"/api/posts/{pid}/comments", json={"content": "偷窥"}, headers=headers_b)
    ).status_code == 404
    assert (await client.post(f"/api/posts/{pid}/discuss", headers=headers_b)).status_code == 404
    assert (await client.delete(f"/api/posts/{pid}", headers=headers_b)).status_code == 404

    # Owner can delete
    assert (await client.delete(f"/api/posts/{pid}", headers=headers_a)).status_code == 204
