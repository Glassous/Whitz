from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.config import AgentSettings
from app.core.models import EmbeddingClient
from app.memory.store import MemoryManager, memory_namespace
from app.rag.hybrid_retriever import HybridRetriever, rrf_fuse
from tests.conftest import FakePGPool


class FakeStore:
    def __init__(self) -> None:
        self.items: dict[tuple[tuple[str, ...], str], dict] = {}

    async def aput(self, ns: tuple[str, ...], key: str, value: dict) -> None:
        self.items[(ns, key)] = value

    async def adelete(self, ns: tuple[str, ...], key: str) -> None:
        self.items.pop((ns, key), None)

    async def asearch(self, ns: tuple[str, ...], *, query: str = "", limit: int = 8):
        out = []
        for (item_ns, key), val in self.items.items():
            if item_ns != ns:
                continue
            if query and query.lower() not in str(val.get("content", "")).lower():
                continue
            out.append(SimpleNamespace(key=key, value=val, score=0.92))
        return out[:limit]


@pytest.mark.asyncio
async def test_memory_manager_respects_enabled_and_confirm_flags():
    store = FakeStore()
    pool = FakePGPool()
    emb = EmbeddingClient(AgentSettings(embedding_model=""))
    mgr = MemoryManager(store=store, pool=pool, embedding_client=emb)
    uid = str(uuid.uuid4())
    cid = str(uuid.uuid4())

    disabled_res = await mgr.propose(
        user_id=uid,
        agent_namespace="u123",
        conversation_id=cid,
        target="memory",
        action="add",
        content="Likes pytest",
        memory_enabled=False,
        memory_require_confirm=True,
    )
    assert disabled_res["status"] == "disabled"
    assert len(pool.queries) == 0

    staged = await mgr.propose(
        user_id=uid,
        agent_namespace="u123",
        conversation_id=cid,
        target="memory",
        action="add",
        content="Prefers concise Chinese replies",
        memory_enabled=True,
        memory_require_confirm=True,
    )
    assert staged["status"] == "pending_confirmation"
    assert any("INSERT INTO memory_pending_proposals" in sql for sql, _ in pool.queries)

    saved = await mgr.propose(
        user_id=uid,
        agent_namespace="u123",
        conversation_id=cid,
        target="user",
        action="add",
        content="Senior Python engineer",
        memory_enabled=True,
        memory_require_confirm=False,
    )
    assert saved["status"] == "saved"
    assert any(ns == memory_namespace("u123") for ns, _ in store.items)

    recalled = await mgr.search(
        user_id=uid,
        agent_namespace="u123",
        query="Python",
        memory_enabled=True,
    )
    assert len(recalled) == 1
    assert recalled[0]["content"] == "Senior Python engineer"

    assert await mgr.search(user_id=uid, agent_namespace="u123", query="Python", memory_enabled=False) == []


@pytest.mark.asyncio
async def test_memory_manager_defaults_enabled_without_confirm_for_write_read_modify():
    store = FakeStore()
    pool = FakePGPool()
    emb = EmbeddingClient(AgentSettings(embedding_model=""))
    mgr = MemoryManager(store=store, pool=pool, embedding_client=emb)
    uid = str(uuid.uuid4())
    cid = str(uuid.uuid4())

    # Default flags: enabled=True, require_confirm=False -> direct write, read, modify, remove
    added = await mgr.propose(
        user_id=uid,
        agent_namespace="u_default",
        conversation_id=cid,
        target="memory",
        action="add",
        content="Uses Neovim",
    )
    assert added["status"] == "saved"

    hits = await mgr.search(user_id=uid, agent_namespace="u_default", query="Neovim")
    assert len(hits) == 1
    assert hits[0]["content"] == "Uses Neovim"

    replaced = await mgr.propose(
        user_id=uid,
        agent_namespace="u_default",
        conversation_id=cid,
        target="memory",
        action="replace",
        old_content="Uses Neovim",
        content="Uses Neovim + LazyVim",
    )
    assert replaced["status"] == "saved"

    hits_after_replace = await mgr.search(user_id=uid, agent_namespace="u_default", query="LazyVim")
    assert len(hits_after_replace) == 1
    assert hits_after_replace[0]["content"] == "Uses Neovim + LazyVim"

    removed = await mgr.propose(
        user_id=uid,
        agent_namespace="u_default",
        conversation_id=cid,
        target="memory",
        action="remove",
        content="Uses Neovim + LazyVim",
        old_content="Uses Neovim + LazyVim",
    )
    assert removed["status"] == "saved"
    assert await mgr.search(user_id=uid, agent_namespace="u_default", query="LazyVim") == []


def test_rrf_fuse_combines_vector_and_fts_ranks():
    vec_rows = [
        {"chunk_id": "c1", "file_id": "f1", "filename": "a.md", "content": "only vec", "chunk_index": 0},
        {"chunk_id": "c2", "file_id": "f1", "filename": "a.md", "content": "both", "chunk_index": 1},
    ]
    fts_rows = [
        {"chunk_id": "c3", "file_id": "f2", "filename": "b.md", "content": "only fts", "chunk_index": 0},
        {"chunk_id": "c2", "file_id": "f1", "filename": "a.md", "content": "both", "chunk_index": 1},
    ]
    fused = rrf_fuse([vec_rows, fts_rows], rrf_k=60, top_k=3)
    assert fused[0].chunk_id == "c2"
    assert fused[0].vec_rank == 2
    assert fused[0].fts_rank == 2
    assert fused[0].rrf_score > fused[1].rrf_score


@pytest.mark.asyncio
async def test_hybrid_retriever_enforces_user_and_global_library_filters():
    uid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    chunk_uuid = uuid.uuid4()

    def responder(sql: str, params: tuple):
        return [
            (chunk_uuid, uuid.UUID(fid), uuid.UUID(cid), True, "spec.md", 0, "lines 1-20", "Hybrid RAG spec")
        ]

    pool = FakePGPool(responder=responder)
    retriever = HybridRetriever(pool=pool, embedding_client=EmbeddingClient(AgentSettings(embedding_model="")))
    hits = await retriever.search(user_id=uid, conversation_id=cid, query="Hybrid RAG", top_k=5)
    assert len(hits) == 1
    assert hits[0]["filename"] == "spec.md"
    assert any(
        "fc.user_id = %s" in sql
        and "INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'" in sql
        for sql, _ in pool.queries
    )
