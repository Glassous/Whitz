from whitz_rag.retriever import DbAdapter, _to_psycopg_positional, rrf_fuse_rows


def test_positional_conversion_preserves_casts():
    sql, params = _to_psycopg_positional(
        "SELECT * FROM t WHERE id = :id AND emb <=> :vec::vector AND u = :id",
        {"id": 1, "vec": "[0]"},
    )
    assert sql == "SELECT * FROM t WHERE id = %s AND emb <=> %s::vector AND u = %s"
    assert params == (1, "[0]", 1)


def test_adapter_flags():
    assert DbAdapter().is_available is False
    pool = DbAdapter(pool=object())
    assert pool.is_available and pool.supports_parallel
    sess = DbAdapter(session=object())
    assert sess.is_available and not sess.supports_parallel


def test_trgm_threshold_is_clamped():
    assert DbAdapter._trgm_threshold_sql(5) == "SET LOCAL pg_trgm.word_similarity_threshold = 0.95"
    assert DbAdapter._trgm_threshold_sql(-1) == "SET LOCAL pg_trgm.word_similarity_threshold = 0.05"
    assert DbAdapter._trgm_threshold_sql(0.3) == "SET LOCAL pg_trgm.word_similarity_threshold = 0.30"


def test_rrf_fuses_overlapping_lists():
    a = [{"chunk_id": "x"}, {"chunk_id": "y"}]
    b = [{"chunk_id": "y"}, {"chunk_id": "z"}]
    fused = rrf_fuse_rows([a, b])
    ids = [r["chunk_id"] for r in fused]
    assert ids[0] == "y"
    assert set(ids) == {"x", "y", "z"}


def test_rrf_top_k_and_skips_missing_ids():
    rows = [{"chunk_id": str(i)} for i in range(10)] + [{"foo": 1}]
    fused = rrf_fuse_rows([rows], top_k=3)
    assert [r["chunk_id"] for r in fused] == ["0", "1", "2"]
