from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timezone

import pytest

from app.services import file_cache, file_chunks, file_parser, file_types
from whitz_rag import (
    DbAdapter,
    EmbeddingClient,
    EvidenceItem,
    UnifiedKnowledgeRetriever,
    estimate_tokens,
    expand_cjk_bigrams,
)


def test_file_types_allows_htm_and_sniff_fail_closed():
    assert ".htm" in file_types.ALLOWED_FILE_TYPES
    assert file_types.ALLOWED_FILE_TYPES[".htm"] == ("code", "text/html")

    # Fail-closed when head_bytes is None or empty for binary formats
    assert file_parser.sniff_file_header(None, ext=".png", category="image") is not None
    assert file_parser.sniff_file_header(b"", ext=".pdf", category="document") is not None
    assert file_parser.sniff_file_header(None, ext=".docx", category="document") is not None
    assert file_parser.sniff_file_header(None, ext=".xlsx", category="spreadsheet") is not None

    # Valid headers pass
    assert file_parser.sniff_file_header(b"\x89PNG\r\n\x1a\n1234", ext=".png", category="image") is None
    assert file_parser.sniff_file_header(b"%PDF-1.7\n...", ext=".pdf", category="document") is None
    assert file_parser.sniff_file_header(b"PK\x03\x04...", ext=".docx", category="document") is None

    # Plain text does not fail on empty head_bytes
    assert file_parser.sniff_file_header(None, ext=".txt", category="document") is None


def test_code_chunker_preserves_overlap_line():
    # Build python lines that force a mid-function split (> 800 chars)
    lines = ["def big_fn():"] + [f"    val_{i} = 'x' * 50  # line {i}" for i in range(40)]
    specs, truncated = file_chunks._chunk_code_lines(lines, max_chars=400)
    assert not truncated
    assert len(specs) >= 2
    first_last_line = specs[0].content.splitlines()[-1]
    second_first_line = specs[1].content.splitlines()[0]
    assert first_last_line == second_first_line


def test_table_chunker_tracks_real_row_numbers_across_blanks():
    # Simulate CSV with header on row 1, blank row 2, data on rows 3 and 5
    csv_text = "name,score\n\nalice,95\n\nbob,88\n"
    specs, truncated = file_chunks._chunk_file_bytes_structured(csv_text.encode("utf-8"), ext=".csv")
    assert not truncated
    assert len(specs) == 1
    assert specs[0].chunk_meta["row_start"] == 3
    assert specs[0].chunk_meta["row_end"] == 5
    assert "3-5" in specs[0].locator


@pytest.mark.asyncio
async def test_file_cache_singleflight_deduplicates_concurrent_parses(monkeypatch):
    file_cache.get_file_cache().clear()
    downloads = 0

    async def fake_get_object_bytes(key, max_bytes=None, settings=None):
        nonlocal downloads
        downloads += 1
        await asyncio.sleep(0.03)
        return b"hello\nworld\n"

    monkeypatch.setattr("app.services.cos.get_object_bytes", fake_get_object_bytes)

    rec = types.SimpleNamespace(
        id=uuid.uuid4(),
        filename="notes.txt",
        ext=".txt",
        mime_type="text/plain",
        size_bytes=12,
        storage_key="k/notes.txt",
        etag="etag-1",
        updated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )

    res1, res2, res3 = await asyncio.gather(
        file_cache.get_or_parse_file(rec),
        file_cache.get_or_parse_file(rec),
        file_cache.get_or_parse_file(rec),
    )
    assert downloads == 1
    assert res1.lines == ["hello", "world"]
    assert res2.lines == ["hello", "world"]
    assert res3.lines == ["hello", "world"]
    # approx_bytes scaled for Python object overhead
    assert res1.approx_bytes >= 1024


@pytest.mark.asyncio
async def test_parallel_embedding_client_preserves_order(monkeypatch):
    client = EmbeddingClient(
        base_url="http://embed.test",
        api_key="k",
        model="m",
        dimensions=4,
        batch_size=2,
    )
    in_flight = 0
    max_in_flight = 0

    async def fake_post_batch(url, headers, batch, dim):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in batch]

    monkeypatch.setattr(client, "_post_batch", fake_post_batch)
    texts = ["a", "bb", "ccc", "dddd", "eeeee", "ffffff"]
    out = await client.embed_texts(texts)
    assert out is not None
    assert [v[0] for v in out] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert max_in_flight >= 2


@pytest.mark.asyncio
async def test_retriever_trgm_uses_indexable_operator_and_batched_neighbors():
    executed_sqls: list[tuple[str, float | None]] = []

    class FakeDb(DbAdapter):
        def __init__(self):
            super().__init__()

        @property
        def is_available(self) -> bool:
            return True

        async def fetch_all(self, sql, params, *, set_iterative_scan=False, trgm_threshold=None):
            executed_sqls.append((sql, trgm_threshold))
            if "FROM file_chunks" in sql and "chunk_index = ANY" in sql:
                fids = params["fids"]
                return [(fids[0], 0, "prev text", "sec1"), (fids[0], 2, "next text", "sec1")]
            return []

    retriever = UnifiedKnowledgeRetriever(db=FakeDb())
    uid = uuid.uuid4()
    await retriever._file_trgm_leg(user_uuid=uid, file_uuids=[], query="量子计算", limit=10)
    await retriever._memory_trgm_leg(base_params={"uid": uid}, col_sql="", query="量子计算", limit=10)
    await retriever._episode_trgm_leg(user_uuid=uid, scope="all", query="量子计算", limit=10)
    await retriever._turn_trgm_leg(user_uuid=uid, scope="all", excl_uuid=None, query="量子计算", limit=10)
    await retriever._digest_trgm_leg(user_uuid=uid, excl_uuid=None, query="量子计算", limit=10)

    assert len(executed_sqls) == 5
    for sql, thresh in executed_sqls:
        assert "<%" in sql
        assert "word_similarity(:q," not in sql.split("ORDER BY")[0]
        assert thresh is not None and 0.10 <= thresh <= 0.20

    # Verify _expand_file_neighbors issues 1 batched query across multiple files
    executed_sqls.clear()
    fid1, fid2 = uuid.uuid4(), uuid.uuid4()
    items = [
        EvidenceItem(
            citation_id="S1",
            source_type="file",
            source_id=str(fid1),
            chunk_id="c1",
            title="a.md",
            subtitle="",
            content="mid text",
            snippet="mid",
            score=0.9,
            metadata={"chunk_index": 1, "section_path": "sec1", "chunk_type": "text"},
        ),
        EvidenceItem(
            citation_id="S2",
            source_type="file",
            source_id=str(fid2),
            chunk_id="c2",
            title="b.md",
            subtitle="",
            content="other text",
            snippet="other",
            score=0.8,
            metadata={"chunk_index": 3, "section_path": "sec2", "chunk_type": "text"},
        ),
    ]
    await retriever._expand_file_neighbors(user_uuid=uid, items=items)
    assert len(executed_sqls) == 1
    assert items[0].expanded is True
    assert "prev text" in items[0].content and "next text" in items[0].content


def test_tokenizer_cjk_bigrams_and_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") > 0
    expanded = expand_cjk_bigrams("人工智能架构优化")
    assert "人工" in expanded and "智能" in expanded and "优化" in expanded
