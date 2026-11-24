from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from whitz_rag.retriever import DbAdapter, UnifiedKnowledgeRetriever, _to_psycopg_positional
from whitz_rag.types import EvidenceItem, RagScope

from app.rag.citations import CitationRegistry
from app.rag.query_rewriter import build_query_plan


class _FakePgCursor:
    def __init__(self, handler) -> None:
        self._handler = handler
        self._rows: list[Any] = []

    async def __aenter__(self) -> "_FakePgCursor":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._rows = list(self._handler(sql, params))

    async def fetchall(self) -> list[Any]:
        return self._rows


class _FakePgConn:
    def __init__(self, handler) -> None:
        self._handler = handler

    async def __aenter__(self) -> "_FakePgConn":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def cursor(self) -> _FakePgCursor:
        return _FakePgCursor(self._handler)


class _FakePgPool:
    def __init__(self, handler) -> None:
        self._handler = handler

    def connection(self) -> _FakePgConn:
        return _FakePgConn(self._handler)


class _StubEmbeddingClient:
    def __init__(self, vec: list[float] | None = None) -> None:
        self._vec = vec
        self.is_configured = vec is not None
        self.dimensions = len(vec) if vec else 4
        self.model_tag = "stub-embed:4"

    async def embed_query(self, text: str) -> list[float] | None:
        return self._vec


def test_to_psycopg_query_preserves_postgres_casts() -> None:
    sql = (
        "SELECT id, 1 - (embedding <=> :vec::vector) AS sim "
        "FROM file_chunks WHERE user_id = :uid AND file_id = ANY(:fids::uuid[]) AND q = :uid"
    )
    out_sql, params = _to_psycopg_positional(sql, {"vec": "[0.1,0.2]", "uid": "u-1", "fids": ["f-1"]})
    assert "%s::vector" in out_sql
    assert "%s::uuid[]" in out_sql
    assert "user_id = %s" in out_sql
    assert "q = %s" in out_sql
    assert params == ("[0.1,0.2]", "u-1", ["f-1"], "u-1")


@pytest.mark.asyncio
async def test_search_files_scope_boost_and_neighbor_window_expansion() -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    conv_cur = "22222222-2222-2222-2222-222222222222"
    conv_other = "33333333-3333-3333-3333-333333333333"
    f_global = "44444444-4444-4444-4444-444444444444"
    f_att = "55555555-5555-5555-5555-555555555555"

    def handler(sql: str, params: tuple[Any, ...]):
        # Full-text leg on file_chunks (12 cols: id, file_id, conv_id, is_global, filename, chunk_index, locator, content, context_header, section_path, chunk_type, chunk_meta)
        if "plainto_tsquery" in sql:
            return [
                ("c-global", f_global, conv_other, True, "global.md", 2, "第 1 页", "预算策略说明全局版", "global.md", "总览", "text", {}),
                ("c-attached", f_att, conv_cur, False, "attached.md", 1, "第 3 页", "预算策略核心指标 1200 万", "attached.md", "核心指标", "text", {}),
            ]
        # Neighbor expansion query: SELECT chunk_index, content, COALESCE(section_path, '')
        if "chunk_index = ANY" in sql:
            fid_str = str(params[1])
            if fid_str == f_att:
                return [
                    (0, "上文：2026 Q3 部门预算背景。", "核心指标"),
                    (2, "下文：其中研发占比 60%。", "核心指标"),
                ]
            return []
        return []

    pool = _FakePgPool(handler)
    retriever = UnifiedKnowledgeRetriever(pool=pool, embedding_client=_StubEmbeddingClient(None))
    items = await retriever.search_files(
        user_id=uid,
        query="预算策略",
        conversation_id=conv_cur,
        attached_file_ids=[f_att],
        top_k=4,
        expand_neighbors=True,
        apply_rerank=False,
    )
    assert len(items) == 2
    # Attached file gets 1.45x boost and should rank above global file
    assert items[0].metadata["file_id"] == f_att
    assert items[0].score > items[1].score
    assert items[0].expanded is True
    # Neighbor window should have expanded around chunk_index 1
    assert "上文：2026 Q3 部门预算背景" in items[0].content
    assert "下文：其中研发占比 60%" in items[0].content


@pytest.mark.asyncio
async def test_search_unified_corrective_retry_and_summary_fallback() -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    conv_id = "22222222-2222-2222-2222-222222222222"
    fid = "55555555-5555-5555-5555-555555555555"

    def handler(sql: str, params: tuple[Any, ...]):
        if "FROM conversation_files" in sql and "summary" in sql:
            return [
                (fid, "q3_report.pdf", "这是 Q3 财报摘要，营收增长 28%。", "document", 5),
            ]
        return []

    pool = _FakePgPool(handler)
    retriever = UnifiedKnowledgeRetriever(pool=pool, embedding_client=_StubEmbeddingClient(None))
    items, diag = await retriever.search_unified(
        user_id=uid,
        queries=["Q3 营收增长"],
        sources=["file"],
        conversation_id=conv_id,
        attached_file_ids=[fid],
        top_k=4,
        enable_corrective=True,
        stage="prefetch",
    )
    assert diag.corrective_retries >= 1
    assert len(items) == 1
    assert items[0].source_type == "file"
    assert "Q3 财报摘要" in items[0].content


@pytest.mark.asyncio
async def test_query_plan_l0_l1_l2_layering() -> None:
    # L0: trivial greeting -> skip
    plan_hi = await build_query_plan(
        messages=[HumanMessage(content="你好")],
        rag_scope=RagScope(mode="auto"),
        attachments=[],
        memory_enabled=True,
        memory_index="",
        conversation_kind="main",
        allow_llm_rewrite=False,
    )
    assert plan_hi.should_prefetch is False
    assert plan_hi.skipped_reason == "trivial_greeting"

    # L0: mode="off" -> skip
    plan_off = await build_query_plan(
        messages=[HumanMessage(content="总结我的合同文档")],
        rag_scope=RagScope(mode="off"),
        attachments=[],
        memory_enabled=True,
        memory_index="",
        conversation_kind="side",
        allow_llm_rewrite=False,
    )
    assert plan_off.should_prefetch is False
    assert plan_off.skipped_reason == "rag_scope_off"

    # L1: files_only -> restrict sources to ["file"]
    plan_files = await build_query_plan(
        messages=[HumanMessage(content="这份合同的违约金条款是什么？")],
        rag_scope=RagScope(mode="files_only", include_memory=False, include_chats=False),
        attachments=[{"file_id": "f-99", "filename": "contract.pdf", "attached": True}],
        memory_enabled=True,
        memory_index="",
        conversation_kind="side",
        allow_llm_rewrite=False,
    )
    assert plan_files.should_prefetch is True
    assert plan_files.sources == ["file"]
    assert plan_files.attached_file_ids == ["f-99"]

    # L2: multi-turn deictic query -> calls fast LLM rewrite
    class _FakeLLM:
        async def ainvoke(self, msgs):
            return SimpleNamespace(content='{"queries": ["Q3 财报 第三个风险点", "供应链风险应对方案"]}')

    class _FakeRouter:
        async def get_chat_model(self, route: str, **kwargs):
            return _FakeLLM(), "stub-fast"

    import app.rag.query_rewriter as qr_mod
    orig_get_settings = qr_mod.get_settings
    qr_mod.get_settings = lambda: SimpleNamespace(
        rag_query_rewrite_enabled=True,
        llm_model="stub-fast",
        llm_base_url="https://api.example.com/v1",
    )  # type: ignore[assignment]
    try:
        plan_l2 = await build_query_plan(
            messages=[
                HumanMessage(content="帮我看下 Q3 财报里的主要风险点"),
                AIMessage(content="主要有三个风险：1.汇率 2.库存 3.供应链中断"),
                HumanMessage(content="那里面提到的第三个风险点，上次我们怎么决定的？"),
            ],
            rag_scope=RagScope(mode="auto", include_memory=True, include_chats=True),
            attachments=[],
            memory_enabled=True,
            memory_index="",
            conversation_kind="side",
            router=_FakeRouter(),  # type: ignore[arg-type]
            allow_llm_rewrite=True,
        )
    finally:
        qr_mod.get_settings = orig_get_settings
    assert plan_l2.should_prefetch is True
    assert plan_l2.used_llm_rewrite is True
    assert "Q3 财报 第三个风险点" in plan_l2.queries
    assert "chat" in plan_l2.sources


def test_citation_registry_deduplicates_and_formats() -> None:
    reg = CitationRegistry()
    e1 = EvidenceItem(
        citation_id="",
        source_type="file",
        source_id="f-1",
        chunk_id="c-1",
        title="plan.md",
        subtitle="第 1-20 行",
        content="架构重构核心方案内容",
        snippet="架构重构核心方案内容",
        score=0.92,
        confidence="high",
        metadata={"file_id": "f-1"},
    )
    e1_dup = EvidenceItem(
        citation_id="",
        source_type="file",
        source_id="f-1",
        chunk_id="c-1",
        title="plan.md",
        subtitle="第 1-20 行",
        content="架构重构核心方案内容",
        snippet="架构重构核心方案内容",
        score=0.88,
        confidence="high",
        metadata={"file_id": "f-1"},
    )
    e2 = EvidenceItem(
        citation_id="",
        source_type="memory",
        source_id="m-1",
        chunk_id="m-1",
        title="技术栈偏好",
        subtitle="preferences",
        content="用户偏好使用 Vue 3 与 FastAPI。",
        snippet="用户偏好使用 Vue 3 与 FastAPI。",
        score=0.81,
        confidence="medium",
        metadata={"collection": "preferences"},
    )

    reg.register([e1])
    reg.register([e1_dup, e2])

    assert e1.citation_id == "S1"
    assert e1_dup.citation_id == "S1"
    assert e2.citation_id == "S2"
    payloads = reg.all_citations()
    assert [p["citation_id"] for p in payloads] == ["S1", "S2"]
    assert payloads[0]["title"] == "plan.md"
    assert payloads[1]["source_type"] == "memory"


@pytest.mark.asyncio
async def test_search_chats_includes_immutable_episodes_with_message_anchor() -> None:
    uid = "11111111-1111-1111-1111-111111111111"
    main_conv_id = "22222222-2222-2222-2222-222222222222"
    ep_id = "66666666-6666-6666-6666-666666666666"
    start_msg_id = "77777777-7777-7777-7777-777777777777"

    def handler(sql: str, params: tuple[Any, ...]):
        if "FROM conversation_episodes" in sql and "plainto_tsquery" in sql:
            return [
                (
                    ep_id,
                    main_conv_id,
                    "main",
                    3,
                    "Redis 缓存穿透治理方案",
                    "确定采用空值短 TTL 60 秒与分布式互斥锁防止缓存击穿。",
                    ["空值 TTL=60s", "使用 Redis SET NX 互斥锁"],
                    ["Redis", "TTL=60s"],
                    start_msg_id,
                    None,
                )
            ]
        return []

    pool = _FakePgPool(handler)
    retriever = UnifiedKnowledgeRetriever(pool=pool, embedding_client=_StubEmbeddingClient(None))
    # Even when exclude_conversation_id == main_conv_id, archived episodes of main chat MUST remain searchable!
    items = await retriever.search_chats(
        user_id=uid,
        query="Redis 缓存穿透",
        scope="all",
        exclude_conversation_id=main_conv_id,
        top_k=4,
        apply_rerank=False,
    )
    assert len(items) == 1
    assert items[0].title == "Redis 缓存穿透治理方案"
    assert items[0].metadata["message_id"] == start_msg_id
    assert items[0].metadata["conversation_id"] == main_conv_id


def test_system_prompt_prefix_cache_order_with_l0_pinned_memories() -> None:
    from app.graph.builder import _build_system_prompt, format_current_time

    prompt = _build_system_prompt(
        {
            "conversation_kind": "main",
            "assistant_name": "Whitz",
            "persona": "资深架构师",
            "pinned_memories": "- [个人画像与偏好] 编码规范：一律使用 TypeScript strict 与 Python 类型注解",
            "rolling_summary": "### 进行中目标与待办\n- [进行中] 完成四层上下文重构",
            "cross_chat_context": "近期活跃旁聊目录...",
            "memory_enabled": True,
        },
        {},
    )
    idx_pinned = prompt.find("核心常驻记忆（L0")
    idx_l1 = prompt.find("主聊天工作态与历史进展（L1")
    idx_time = prompt.find("## 当前时间")
    idx_cross = prompt.find("## 跨旁聊全局记忆")
    assert 0 < idx_pinned < idx_l1 < idx_time < idx_cross
    # Minute-level timestamp (no :SS seconds segment)
    ts = format_current_time("Asia/Shanghai")
    assert len(ts.split("（")[0].split(":")) == 2

