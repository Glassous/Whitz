package com.glassous.whitz

import com.glassous.whitz.core.model.CitationItem
import com.glassous.whitz.core.model.ConversationContextState
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.LibraryContentSearchResponse
import com.glassous.whitz.core.model.MemoryOverview
import com.glassous.whitz.core.model.RagMode
import com.glassous.whitz.core.model.ToolPayload
import com.glassous.whitz.core.model.UnifiedSearchResponse
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.feature.chat.StreamingPhase
import com.glassous.whitz.feature.chat.computeLiveStepLabel
import com.glassous.whitz.feature.chat.normalizeStreamingInlineTail
import com.glassous.whitz.feature.chat.parseCitationIds
import com.glassous.whitz.feature.chat.resolveStreamingPhase
import com.glassous.whitz.feature.chat.toolDisplayName
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RagAndContextTests {

    @Test
    fun deserializesCitationsAndRagMetricsInToolPayload() {
        val raw = """
            {
              "citations": [
                {
                  "citation_id": "S1",
                  "source_type": "file",
                  "source_id": "file-123",
                  "title": "architecture.md",
                  "subtitle": "§2 检索架构",
                  "snippet": "采用 Hybrid BM25 + pgvector RRF 融合",
                  "score": 0.92,
                  "confidence": "high",
                  "metadata": {"conversation_id": "conv-1"}
                },
                {
                  "citation_id": "S2",
                  "source_type": "chat_digest",
                  "source_id": "conv-2",
                  "title": "需求评审",
                  "snippet": "确定使用 4 层认知记忆架构",
                  "metadata": {"conversation_id": "conv-2", "start_msg_id": "msg-88"}
                }
              ],
              "rag_metrics": {"latency_ms": 145, "hit_count": 2}
            }
        """.trimIndent()

        val payload = WhitzJson.decodeFromString(ToolPayload.serializer(), raw)
        assertEquals(2, payload.citations?.size)
        val first: CitationItem = payload.citations!![0]
        assertEquals("S1", first.citationId)
        assertEquals("file", first.sourceType)
        assertEquals("file-123", first.sourceId)
        assertEquals("architecture.md", first.title)
        assertEquals("high", first.confidence)
        assertNotNull(payload.ragMetrics)
    }

    @Test
    fun deserializesUnifiedSearchAndLibrarySearch() {
        val unifiedRaw = """
            {
              "query": "pgvector",
              "files": [
                {
                  "type": "file",
                  "file_id": "f1",
                  "filename": "rag.md",
                  "locator": "chunk#3",
                  "section_path": "RAG > 向量检索",
                  "snippet": "pgvector HNSW 索引",
                  "score": 0.88
                }
              ],
              "memories": [
                {
                  "type": "memory",
                  "entry_id": "m1",
                  "title": "数据库选型",
                  "collection": "memory",
                  "collection_name": "默认记忆",
                  "tags": ["db"],
                  "snippet": "生产使用 PostgreSQL 16 + pgvector",
                  "content": "生产使用 PostgreSQL 16 + pgvector",
                  "score": 0.81
                }
              ],
              "chats": [
                {
                  "type": "chat",
                  "match_in": "digest",
                  "conversation_id": "c1",
                  "conversation_kind": "main",
                  "conversation_title": "主聊",
                  "message_id": "msg-12",
                  "snippet": "讨论 pgvector 索引重构",
                  "score": 0.76
                }
              ],
              "total": 3
            }
        """.trimIndent()

        val unified = WhitzJson.decodeFromString(UnifiedSearchResponse.serializer(), unifiedRaw)
        assertEquals(3, unified.total)
        assertEquals(1, unified.files.size)
        assertEquals("RAG > 向量检索", unified.files[0].sectionPath)
        assertEquals(1, unified.memories.size)
        assertEquals("m1", unified.memories[0].entryId)
        assertEquals(1, unified.chats.size)
        assertEquals("digest", unified.chats[0].matchIn)
        assertEquals("msg-12", unified.chats[0].messageId)

        val libRaw = """
            {
              "query": "HNSW",
              "count": 1,
              "results": [
                {
                  "file_id": "f1",
                  "filename": "rag.md",
                  "locator": "L10-L30",
                  "section_path": "索引",
                  "snippet": "HNSW 索引参数",
                  "content": "完整正文片段",
                  "score": 0.91
                }
              ]
            }
        """.trimIndent()
        val libResp = WhitzJson.decodeFromString(LibraryContentSearchResponse.serializer(), libRaw)
        assertEquals(1, libResp.count)
        assertEquals("rag.md", libResp.results[0].filename)
    }

    @Test
    fun deserializesContextStateAndPinnedMemories() {
        val ctxRaw = """
            {
              "conversation_id": "conv-main",
              "conversation_kind": "main",
              "working_state": {
                "active_goals": [{"title": "同步 Android 端 RAG", "status": "in_progress"}],
                "recent_decisions": [{"decision": "采用四层认知记忆架构", "date": "2026-11-24", "reason": "消除滚雪球摘要退化"}],
                "open_questions": ["是否开启跨端推送"],
                "key_entities": {"Material3": "1.5.0"}
              },
              "working_state_updated_at": "2026-11-24T12:00:00Z",
              "episodes": [
                {
                  "id": "ep-1",
                  "conversation_id": "conv-main",
                  "conversation_kind": "main",
                  "episode_index": 1,
                  "topic": "RAG 重构讨论",
                  "summary": "梳理了 Hybrid 检索和引用协议",
                  "key_facts": ["采用 [[cite:S1]] 协议"],
                  "entities": ["pgvector"],
                  "start_msg_id": "msg-1",
                  "end_msg_id": "msg-20",
                  "message_count": 20
                }
              ],
              "pinned_memories_count": 3
            }
        """.trimIndent()
        val ctx = WhitzJson.decodeFromString(ConversationContextState.serializer(), ctxRaw)
        assertEquals(3, ctx.pinnedMemoriesCount)
        assertEquals(1, ctx.workingState?.activeGoals?.size)
        assertEquals("1.5.0", ctx.workingState?.keyEntities?.get("Material3"))
        assertEquals(1, ctx.episodes.size)
        assertEquals("msg-1", ctx.episodes[0].startMsgId)

        val memRaw = """
            {
              "memory_enabled": true,
              "memory_require_confirm": false,
              "pinned_count": 2,
              "pinned_limit": 10,
              "entries": [
                {
                  "id": "e1",
                  "content": "偏好中文回复",
                  "is_pinned": true,
                  "priority": 9,
                  "access_count": 14
                }
              ]
            }
        """.trimIndent()
        val overview = WhitzJson.decodeFromString(MemoryOverview.serializer(), memRaw)
        assertEquals(2, overview.pinnedCount)
        assertEquals(10, overview.pinnedLimit)
        assertTrue(overview.entries[0].isPinned)
        assertEquals(9, overview.entries[0].priority)
        assertEquals(14, overview.entries[0].accessCount)

        val fileRaw = """
            {
              "id": "file-9",
              "filename": "spec.pdf",
              "index_status": "failed",
              "indexed_chunks": 0,
              "summary": "系统规格说明书",
              "index_error": "OCR timeout"
            }
        """.trimIndent()
        val file = WhitzJson.decodeFromString(ConversationFile.serializer(), fileRaw)
        assertEquals("failed", file.indexStatus)
        assertEquals("OCR timeout", file.indexError)
        assertEquals("系统规格说明书", file.summary)
    }

    @Test
    fun ragHelpersAndCitationParsingWorkCorrectly() {
        assertEquals(RagMode.AUTO, RagMode.fromWire("auto"))
        assertEquals(RagMode.FILES_ONLY, RagMode.fromWire("files_only"))
        assertEquals(RagMode.OFF, RagMode.fromWire("off"))
        assertEquals(RagMode.AUTO, RagMode.fromWire("unknown"))

        assertEquals("多源知识检索", toolDisplayName("knowledge_search"))
        assertEquals("检索历史对话", toolDisplayName("search_chat_history"))

        assertEquals(
            StreamingPhase.RAG_PREFETCH,
            resolveStreamingPhase(
                currentStep = null,
                runningTool = null,
                plan = null,
                ragPrefetching = true,
                hasContent = false,
            ),
        )
        assertEquals(
            "正在检索知识库与记忆…",
            computeLiveStepLabel(
                currentStep = null,
                runningTool = null,
                plan = null,
                ragPrefetching = true,
                hasContent = false,
            ),
        )

        assertEquals(listOf("S1", "S2"), parseCitationIds("S1, S2 , S1"))
        val cleaned = normalizeStreamingInlineTail("根据架构文档 [[cite:S1")
        assertFalse(cleaned.contains("[[cite:"))
        assertEquals("根据架构文档 ", cleaned)
    }
}
