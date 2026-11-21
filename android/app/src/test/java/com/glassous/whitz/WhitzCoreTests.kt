package com.glassous.whitz

import com.glassous.whitz.core.files.FileValidator
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.ConversationDetail
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.CreditStatus
import com.glassous.whitz.core.model.Message
import com.glassous.whitz.core.model.Plan
import com.glassous.whitz.core.model.PlanItem
import com.glassous.whitz.core.model.ReasoningBlock
import com.glassous.whitz.core.model.ReasoningTool
import com.glassous.whitz.core.model.ToolPayload
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.model.formatCredits
import com.glassous.whitz.core.model.resolveServerAssetUrl
import com.glassous.whitz.core.model.resolvedAssistantName
import com.glassous.whitz.core.network.SseParser
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.core.util.ConversationSorter
import com.glassous.whitz.feature.chat.computeLiveStepLabel
import com.glassous.whitz.feature.chat.computeStepsCount
import com.glassous.whitz.feature.chat.filterVisibleMessages
import com.glassous.whitz.feature.chat.partitionPlanSteps
import com.glassous.whitz.feature.chat.resolveTurnDetails
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class WhitzCoreTests {
    @Test
    fun sseParser_parsesEventIdAndMultilineData() {
        val block = """
            id: 1732180001-0
            event: message.delta
            data: {"text":"hello"}
        """.trimIndent()
        val ev = SseParser.parseBlock(block)
        assertNotNull(ev)
        assertEquals("1732180001-0", ev!!.id)
        assertEquals("message.delta", ev.event)
        assertEquals("hello", (ev.data["text"] as? JsonPrimitive)?.contentOrNull)
    }

    @Test
    fun sseParser_ignoresCommentsAndEmptyBlocks() {
        assertNull(SseParser.parseBlock(": keep-alive"))
        assertNull(SseParser.parseBlock("   \n  "))
    }

    @Test
    fun fileValidator_checksExtensionsMimeAndSize() {
        assertNull(FileValidator.validateFile("report.pdf", "application/pdf", 1024))
        assertNull(FileValidator.validateFile("main.py", "text/x-python", 2048))
        assertNotNull(FileValidator.validateFile("video.mp4", "video/mp4", 1024))
        assertNotNull(FileValidator.validateFile("archive.zip", "application/zip", 1024))
        assertNotNull(FileValidator.validateFile("huge.pdf", "application/pdf", 25L * 1024 * 1024))
        assertNotNull(FileValidator.validateFile("empty.txt", "text/plain", 0))
    }

    @Test
    fun conversationSorter_mainFirstThenPinnedThenMostRecent() {
        val c1 = Conversation(id = "1", kind = "side", title = "old", isPinned = false, updatedAt = "2026-01-01T00:00:00Z")
        val c2 = Conversation(id = "2", kind = "side", title = "new", isPinned = false, updatedAt = "2026-01-02T00:00:00Z")
        val c3 = Conversation(
            id = "3",
            kind = "side",
            title = "pinned",
            isPinned = true,
            pinnedAt = "2026-01-01T00:00:00Z",
            updatedAt = "2025-12-31T00:00:00Z",
        )
        val cMain = Conversation(
            id = "main-1",
            kind = "main",
            title = "主要聊天",
            isPinned = false,
            updatedAt = "2025-01-01T00:00:00Z",
        )
        val sorted = ConversationSorter.sort(listOf(c1, c2, c3, cMain))
        assertEquals(listOf("main-1", "3", "2", "1"), sorted.map { it.id })
    }

    @Test
    fun models_decodeAssistantProfileKindAndIndexStatus() {
        val userRaw = """
            {
              "id": "u-1",
              "email": "a@b.com",
              "display_name": "Alice",
              "assistant_name": "Jarvis",
              "assistant_avatar_url": "/api/users/u-1/assistant-avatar?v=123"
            }
        """.trimIndent()
        val user = WhitzJson.decodeFromString(User.serializer(), userRaw)
        assertEquals("Jarvis", user.resolvedAssistantName())
        assertEquals(
            "https://whitzapi.kamisato.top/api/users/u-1/assistant-avatar?v=123",
            resolveServerAssetUrl("https://whitzapi.kamisato.top/api", user.assistantAvatarUrl),
        )

        val fileRaw = """
            {
              "id": "f-1",
              "filename": "notes.pdf",
              "status": "ready",
              "index_status": "indexing",
              "indexed_chunks": 4
            }
        """.trimIndent()
        val file = WhitzJson.decodeFromString(ConversationFile.serializer(), fileRaw)
        assertEquals("indexing", file.indexStatus)
        assertEquals(4, file.indexedChunks)
        assertEquals(true, file.isGlobal)
    }

    @Test
    fun liveStepLabel_handlesStoppingReconnectingAndWaitingFirstByte() {
        assertEquals("正在停止生成…", computeLiveStepLabel(null, "web_search", null, stopping = true))
        assertEquals("网络重连中，正在恢复进度…", computeLiveStepLabel(null, "web_search", null, reconnecting = true))
        assertEquals("正在连接助理…", computeLiveStepLabel(null, null, null, waitingFirstByte = true))
    }

    @Test
    fun creditStatus_decodesFractionalUsedAndRemaining() {
        val raw = """
            {
              "tier": "pro",
              "tier_label": "Pro",
              "remaining": 679.7,
              "weekly": {"limit": 1250, "used": 570.3, "remaining": 679.7, "reset_at": "2026-11-27T00:00:00Z"},
              "five_hour": {"limit": null, "used": 12.5, "remaining": null, "reset_at": "2026-11-20T21:00:00Z"}
            }
        """.trimIndent()
        val parsed = WhitzJson.decodeFromString(CreditStatus.serializer(), raw)
        assertEquals(679.7, parsed.remaining, 0.001)
        assertEquals(570.3, parsed.weekly.used, 0.001)
        assertEquals("570.3", formatCredits(parsed.weekly.used))
        assertEquals("1250", formatCredits(1250.0))
    }

    @Test
    fun conversationDetail_decodesFractionalDurationMs() {
        val raw = """
            {
              "id": "conv-1",
              "title": "Test",
              "messages": [
                {
                  "id": "msg-1",
                  "role": "assistant",
                  "content": "done",
                  "tool_payload": {
                    "reasoning": [
                      {
                        "step": 1,
                        "title": "Search",
                        "tools": [
                          {"name": "web_search", "call_id": "O8e1KcE4oe9064", "duration_ms": 2712.1}
                        ]
                      }
                    ]
                  }
                }
              ]
            }
        """.trimIndent()
        val parsed = WhitzJson.decodeFromString(ConversationDetail.serializer(), raw)
        val durationMs = parsed.messages.first().toolPayload?.reasoning?.first()?.tools?.first()?.durationMs
        assertNotNull(durationMs)
        assertEquals(2712.1, durationMs!!, 0.001)
    }

    @Test
    fun messageList_filtersOutToolRoleMessages() {
        val msgs = listOf(
            Message(id = "u1", role = "user", content = "hi"),
            Message(id = "t1", role = "tool", toolName = "web_search", status = "completed"),
            Message(id = "a1", role = "assistant", content = "final answer"),
        )
        val visible = filterVisibleMessages(msgs)
        assertEquals(listOf("u1", "a1"), visible.map { it.id })
    }

    @Test
    fun turnDetails_resolvesPlanReasoningAndLiveRunningTool() {
        val blocks = listOf(
            ReasoningBlock(step = null, title = "思路", text = "planning"),
            ReasoningBlock(
                step = 1,
                stepId = "s1",
                title = "搜索资料",
                text = "searching",
                tools = listOf(ReasoningTool(name = "web_search", status = "completed")),
            ),
            ReasoningBlock(step = null, title = "总结", content = "all set"),
        )
        val msgs = listOf(
            Message(id = "u1", role = "user", content = "go"),
            Message(id = "t1", role = "tool", toolName = "web_search", status = "running"),
            Message(
                id = "a1",
                role = "assistant",
                content = "",
                status = "streaming",
                toolPayload = ToolPayload(reasoning = blocks),
            ),
        )
        val details = resolveTurnDetails(
            messages = msgs,
            selectedTurnId = "a1",
            activeAssistantId = "a1",
            streaming = true,
            livePlan = null,
            liveReasoning = blocks,
        )
        assertEquals("a1", details.turnId)
        assertEquals("web_search", details.runningTool)
        assertEquals(1, computeStepsCount(details.plan, details.reasoning))
        assertEquals("正在使用 web_search", computeLiveStepLabel(null, details.runningTool, details.plan))

        val sections = partitionPlanSteps(
            plan = Plan(items = listOf(PlanItem(id = JsonPrimitive("s1"), content = "搜索资料", status = "in_progress"))),
            reasoning = blocks,
        )
        assertEquals(1, sections.planningBlocks.size)
        assertEquals(1, sections.steps.size)
        assertEquals(1, sections.steps.first().blocks.size)
        assertEquals(1, sections.summaryBlocks.size)
        assertEquals(0, sections.looseBlocks.size)
    }

    @Test
    fun homeChatCache_roundTripsConversationsAndMainDetail() {
        val cache = com.glassous.whitz.core.storage.HomeChatCache(
            userId = "u1",
            conversations = listOf(
                Conversation(id = "main-1", kind = "main", title = "主聊"),
                Conversation(id = "side-1", kind = "side", title = "旁聊 A"),
            ),
            mainConversation = ConversationDetail(
                id = "main-1",
                kind = "main",
                title = "主聊",
                messages = listOf(
                    Message(id = "m1", role = "user", content = "你好"),
                    Message(id = "m2", role = "assistant", content = "你好！"),
                ),
            ),
            savedAtMs = 123456789L,
        )
        val encoded = WhitzJson.encodeToString(com.glassous.whitz.core.storage.HomeChatCache.serializer(), cache)
        val decoded = WhitzJson.decodeFromString(com.glassous.whitz.core.storage.HomeChatCache.serializer(), encoded)
        assertEquals("u1", decoded.userId)
        assertEquals(2, decoded.conversations.size)
        assertEquals("main-1", decoded.mainConversation?.id)
        assertEquals(2, decoded.mainConversation?.messages?.size)
        assertEquals("你好！", decoded.mainConversation?.messages?.last()?.content)
    }
}
