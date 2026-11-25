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
import com.glassous.whitz.core.model.displaySideTitle
import com.glassous.whitz.core.model.formatCredits
import com.glassous.whitz.core.model.isScheduledSide
import com.glassous.whitz.core.model.resolveServerAssetUrl
import com.glassous.whitz.core.model.resolvedAssistantName
import com.glassous.whitz.core.network.SseParser
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.core.util.ConversationSorter
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.feature.chat.computeLiveStepLabel
import com.glassous.whitz.feature.chat.computeStepsCount
import com.glassous.whitz.feature.chat.filterVisibleMessages
import com.glassous.whitz.feature.chat.partitionPlanSteps
import com.glassous.whitz.feature.chat.resolveTurnDetails
import com.glassous.whitz.feature.chat.toolDisplayName
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
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
        assertEquals("正在使用 联网搜索", computeLiveStepLabel(null, details.runningTool, details.plan))

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

    @Test
    fun models_decodeMessageReactionsAndUserFeedback() {
        val msgRaw = """
            {
              "id": "m-1",
              "role": "user",
              "content": "思路很清晰对吧",
              "status": "completed",
              "reactions": [
                {
                  "id": "r-1",
                  "message_id": "m-1",
                  "author_type": "assistant",
                  "reaction": "sparkle",
                  "comment": "精准定位问题",
                  "created_at": "2026-11-21T12:00:00Z"
                }
              ]
            }
        """.trimIndent()
        val msg = WhitzJson.decodeFromString(Message.serializer(), msgRaw)
        assertEquals(1, msg.reactions.size)
        assertEquals("assistant", msg.reactions.first().authorType)
        assertEquals("sparkle", msg.reactions.first().reaction)

        val fbRaw = """
            {
              "id": "fb-1",
              "user_id": "u-1",
              "rating": 5,
              "sentiment": "positive",
              "category": "quality",
              "content": "响应很快",
              "status": "resolved",
              "admin_note": "感谢反馈",
              "created_at": "2026-11-21T12:00:00Z",
              "updated_at": "2026-11-21T12:05:00Z"
            }
        """.trimIndent()
        val fb = WhitzJson.decodeFromString(com.glassous.whitz.core.model.UserFeedbackItem.serializer(), fbRaw)
        assertEquals(5, fb.rating)
        assertEquals("resolved", fb.status)
        assertEquals("感谢反馈", fb.adminNote)
    }

    @Test
    fun models_decodeScheduleOverviewAndPendingProposal() {
        val raw = """
            {
              "tasks": [
                {
                  "id": "t-1",
                  "conversation_id": "c-1",
                  "target_mode": "dedicated",
                  "name": "每日 AI 早报",
                  "prompt": "汇总最新 AI 动态",
                  "schedule_type": "daily",
                  "schedule_config": {"hour": 9, "minute": 0},
                  "schedule_description": "每天 09:00",
                  "timezone": "Asia/Shanghai",
                  "model_route": "auto",
                  "skill_names": ["deep-research"],
                  "enabled": true,
                  "status": "active",
                  "next_run_at": "2026-11-22T01:00:00Z",
                  "run_count": 3,
                  "consecutive_failures": 0,
                  "source": "manual",
                  "created_at": "2026-11-21T00:00:00Z",
                  "updated_at": "2026-11-21T00:00:00Z"
                }
              ],
              "pending": [
                {
                  "id": "p-1",
                  "action": "create",
                  "payload": {"name": "周报提醒", "prompt": "整理本周进展"},
                  "schedule_description": "每周五 18:00",
                  "reason": "用户口头要求",
                  "status": "pending"
                }
              ],
              "quota": {
                "tier": "plus",
                "max_active_tasks": 10,
                "active_count": 1,
                "min_interval_minutes": 15
              }
            }
        """.trimIndent()
        val overview = WhitzJson.decodeFromString(com.glassous.whitz.core.model.ScheduleOverview.serializer(), raw)
        assertEquals(1, overview.tasks.size)
        assertEquals("每日 AI 早报", overview.tasks.first().name)
        assertEquals("每天 09:00", overview.tasks.first().scheduleDescription)
        assertEquals(1, overview.pending.size)
        assertEquals("每周五 18:00", overview.pending.first().scheduleDescription)
        assertEquals(10, overview.quota.maxActiveTasks)
        assertEquals(15, overview.quota.minIntervalMinutes)
    }

    @Test
    fun scheduledConversationHelpers_andSearchProviderLabels() {
        val scheduledByFlag = Conversation(id = "c1", kind = "side", title = "每日早报", isScheduled = true)
        val scheduledByPrefix = Conversation(id = "c2", kind = "side", title = "[定时] 每周汇总", isScheduled = false)
        val normalSide = Conversation(id = "c3", kind = "side", title = "普通旁聊", isScheduled = false)
        val mainChat = Conversation(id = "c4", kind = "main", title = "[定时] 主聊", isScheduled = true)

        assertTrue(scheduledByFlag.isScheduledSide())
        assertEquals("每日早报", scheduledByFlag.displaySideTitle())
        assertTrue(scheduledByPrefix.isScheduledSide())
        assertEquals("每周汇总", scheduledByPrefix.displaySideTitle())
        assertFalse(normalSide.isScheduledSide())
        assertEquals("普通旁聊", normalSide.displaySideTitle())
        assertFalse(mainChat.isScheduledSide())

        val bochaTool = ReasoningTool(
            name = "web_search",
            args = """{"query":"国内AI动态","provider":"bocha"}""",
            result = """{"ok":true,"provider":"bocha","result_count":2}""",
        )
        val tavilyTool = ReasoningTool(
            name = "web_search",
            args = """{"query":"LangGraph docs","provider":"tavily"}""",
            result = """{"ok":true,"provider":"tavily","result_count":3}""",
        )
        assertEquals("联网搜索 · 博查", toolDisplayName(bochaTool))
        assertEquals("联网搜索 · Tavily", toolDisplayName(tavilyTool))
    }

    @Test
    fun dateTimeUtils_chatDividerRulesAndChineseFormat() {
        val zone = java.time.ZoneId.of("Asia/Shanghai")
        val nowZdt = java.time.ZonedDateTime.of(2026, 11, 25, 18, 35, 0, 0, zone)
        fun isoAt(year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int = 0): String =
            java.time.ZonedDateTime.of(year, month, day, hour, minute, second, 0, zone).toInstant().toString()

        val t1 = isoAt(2026, 11, 25, 10, 0)
        val t2 = isoAt(2026, 11, 25, 10, 4, 59)
        val t3 = isoAt(2026, 11, 25, 10, 5, 0)
        val prevNight = isoAt(2026, 11, 24, 23, 59)
        val midnight = isoAt(2026, 11, 25, 0, 0, 30)

        assertTrue(DateTimeUtils.shouldShowChatTimeDivider(null, t1, zone))
        assertFalse(DateTimeUtils.shouldShowChatTimeDivider(t1, null, zone))
        assertFalse(DateTimeUtils.shouldShowChatTimeDivider(t1, t2, zone))
        assertTrue(DateTimeUtils.shouldShowChatTimeDivider(t1, t3, zone))
        assertTrue(DateTimeUtils.shouldShowChatTimeDivider(prevNight, midnight, zone))

        assertEquals("09:05", DateTimeUtils.formatChatDivider(isoAt(2026, 11, 25, 9, 5), nowZdt))
        assertEquals("昨天 22:18", DateTimeUtils.formatChatDivider(isoAt(2026, 11, 24, 22, 18), nowZdt))
        assertEquals("星期一 14:00", DateTimeUtils.formatChatDivider(isoAt(2026, 11, 23, 14, 0), nowZdt))
        assertEquals("星期四 08:30", DateTimeUtils.formatChatDivider(isoAt(2026, 11, 19, 8, 30), nowZdt))
        assertEquals("11月18日 08:30", DateTimeUtils.formatChatDivider(isoAt(2026, 11, 18, 8, 30), nowZdt))
        assertEquals("2025年12月31日 23:59", DateTimeUtils.formatChatDivider(isoAt(2025, 12, 31, 23, 59), nowZdt))
        assertEquals("", DateTimeUtils.formatChatDivider("invalid", nowZdt))
    }
}
