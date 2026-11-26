# whitz_rag（共享 RAG 包）

由 `server` 与 `agent` 共同复用的统一检索包。

## 模块

- `tokenizer.py`：`estimate_tokens`（中英混排 token 估算）、`expand_cjk_bigrams`（提升中文 FTS 召回）
- `embeddings.py`：`EmbeddingClient`、`RerankClient` 及 `fit_embedding`、`vector_literal`、`escape_like`、`char_trigrams`、`jaccard_sim`
- `retriever.py`：`DbAdapter`（psycopg3 连接池 / SQLAlchemy AsyncSession 双驱动）、`UnifiedKnowledgeRetriever`、`rrf_fuse_rows`、`mmr_select_evidence`
- `types.py`：`EvidenceItem`、`RagDiagnostics`、`RagScope`

## 测试

```bash
cd shared
../server/.venv/Scripts/python -m pytest tests -q
```
