from __future__ import annotations

import httpx
import pytest
from app.services import file_chunks
from whitz_rag.embeddings import EmbeddingClient


def test_markdown_chunker_tracks_heading_stack_and_keeps_code_fences_intact() -> None:
    md = "\n".join(
        [
            "# 系统架构",
            "整体介绍段落。",
            "## 检索模块",
            "下面是核心代码：",
            "```python",
            "def hybrid_search(q):",
            "    # # not a heading inside code fence",
            "    return ['a', 'b']",
            "```",
            "### 排序策略",
            "采用 RRF 与 Cross-Encoder Rerank。",
        ]
    )
    specs, truncated = file_chunks._chunk_markdown_lines(md.splitlines(), max_chars=200)
    assert truncated is False
    assert len(specs) >= 3
    paths = [s.section_path for s in specs]
    assert any("系统架构 > 检索模块" in p for p in paths)
    assert any("系统架构 > 检索模块 > 排序策略" in p for p in paths)
    # Fence comment "# not a heading" must NOT leak into section_path
    assert all("not a heading" not in p for p in paths)
    code_chunk = next(s for s in specs if "def hybrid_search" in s.content)
    assert "```python" in code_chunk.content and "return ['a', 'b']" in code_chunk.content


def test_code_chunker_splits_at_symbol_boundaries() -> None:
    src = "\n".join(
        [
            "import os",
            "",
            "def alpha_task(x: int) -> int:",
            "    " + ("a = x + 1\n    " * 20).strip(),
            "    return x + 1",
            "",
            "async def beta_task(y: str) -> str:",
            "    return y.strip()",
        ]
    )
    specs, truncated = file_chunks._chunk_code_lines(src.splitlines(), max_chars=240)
    assert truncated is False
    assert all(s.chunk_type == "code" for s in specs)
    assert any("alpha_task" in s.content for s in specs)
    assert any("beta_task" in s.content for s in specs)


def test_table_chunker_prepends_header_row_to_every_chunk() -> None:
    header = "日期 | 区域 | 营收(万元) | 同比增长"
    rows = [f"2026-Q{(i % 4) + 1} | 华东-{i} | {1000 + i * 35} | +{10 + (i % 9)}%" for i in range(40)]
    specs, truncated = file_chunks._chunk_table_rows(rows, header_row=header, sheet_name="销售明细", max_chars=360)
    assert truncated is False
    assert len(specs) >= 3
    for s in specs:
        assert s.chunk_type == "table"
        assert s.content.startswith(f"表头: {header}")
        assert s.chunk_meta.get("has_header") is True
        assert s.chunk_meta.get("sheet_name") == "销售明细"


@pytest.mark.asyncio
async def test_embedding_client_dimensions_negotiation_fallback() -> None:
    seen_payloads: list[dict] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(body)
        if "dimensions" in body:
            return httpx.Response(400, json={"error": {"message": "unsupported parameter: dimensions"}})
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]},
                ]
            },
        )

    transport = httpx.MockTransport(transport_handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        class _TestEmbeddingClient(EmbeddingClient):
            def _get_http_client(self) -> httpx.AsyncClient:
                return mock_http

        client = _TestEmbeddingClient(
            base_url="https://api.example.com/v1",
            api_key="test-key",
            model="legacy-embed-v1",
            dimensions=4,
            batch_size=8,
        )
        vec1 = await client.embed_query("测试向量维度协商")
        assert vec1 is not None and len(vec1) == 4
        # First call included dimensions, got 400, retried without dimensions
        assert len(seen_payloads) == 2
        assert "dimensions" in seen_payloads[0]
        assert "dimensions" not in seen_payloads[1]

        # Second call should remember that this model doesn't support dimensions and skip directly!
        vec2 = await client.embed_query("第二次查询应跳过 dimensions")
        assert vec2 is not None and len(vec2) == 4
        assert len(seen_payloads) == 3
        assert "dimensions" not in seen_payloads[2]
