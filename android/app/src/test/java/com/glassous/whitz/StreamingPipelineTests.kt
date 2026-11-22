package com.glassous.whitz

import com.glassous.whitz.core.model.Plan
import com.glassous.whitz.core.model.PlanItem
import com.glassous.whitz.feature.chat.ChatScrollPolicy
import com.glassous.whitz.feature.chat.CoalescedDeltaBatch
import com.glassous.whitz.feature.chat.CurrentStepInfo
import com.glassous.whitz.feature.chat.MdBlock
import com.glassous.whitz.feature.chat.StreamDeltaCoalescer
import com.glassous.whitz.feature.chat.StreamingPhase
import com.glassous.whitz.feature.chat.computeLiveStepLabel
import com.glassous.whitz.feature.chat.normalizeStreamingInlineTail
import com.glassous.whitz.feature.chat.parseMarkdownBlocks
import com.glassous.whitz.feature.chat.resolveStreamingPhase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamingPipelineTests {

    @Test
    fun scrollPolicy_disengagesImmediatelyOnUpwardUserScrollAndNeverOnDownward() {
        assertTrue(ChatScrollPolicy.shouldDisengageOnUserPreScroll(availableY = 5f))
        assertFalse(ChatScrollPolicy.shouldDisengageOnUserPreScroll(availableY = 0.5f))
        assertFalse(ChatScrollPolicy.shouldDisengageOnUserPreScroll(availableY = -12f))

        assertTrue(ChatScrollPolicy.isUserScrollingDown(availableY = -5f))
        assertFalse(ChatScrollPolicy.isUserScrollingDown(availableY = 5f))
    }

    @Test
    fun scrollPolicy_reEngagesOnlyWhenUserScrolledDownToBottom() {
        // User scrolled down to within 48px threshold -> re-engage
        assertTrue(
            ChatScrollPolicy.shouldReEngageAutoFollow(
                distanceFromBottomPx = 24,
                reEngageThresholdPx = 48,
                userScrolledDown = true,
            ),
        )
        // User nudged slightly UP (still within 48px of bottom) -> MUST NOT re-engage
        assertFalse(
            ChatScrollPolicy.shouldReEngageAutoFollow(
                distanceFromBottomPx = 24,
                reEngageThresholdPx = 48,
                userScrolledDown = false,
            ),
        )
        // User scrolled down but still far from bottom -> stay disengaged
        assertFalse(
            ChatScrollPolicy.shouldReEngageAutoFollow(
                distanceFromBottomPx = 240,
                reEngageThresholdPx = 48,
                userScrolledDown = true,
            ),
        )
    }

    @Test
    fun scrollPolicy_jumpButtonHysteresisPreventsFlicker() {
        // Currently hidden: stays hidden at 70px, shows at 100px
        assertFalse(
            ChatScrollPolicy.nextJumpButtonVisibility(
                currentlyVisible = false,
                distanceFromBottomPx = 70,
                showThresholdPx = 84,
                hideThresholdPx = 36,
            ),
        )
        assertTrue(
            ChatScrollPolicy.nextJumpButtonVisibility(
                currentlyVisible = false,
                distanceFromBottomPx = 100,
                showThresholdPx = 84,
                hideThresholdPx = 36,
            ),
        )
        // Currently visible: stays visible at 50px, hides at 30px
        assertTrue(
            ChatScrollPolicy.nextJumpButtonVisibility(
                currentlyVisible = true,
                distanceFromBottomPx = 50,
                showThresholdPx = 84,
                hideThresholdPx = 36,
            ),
        )
        assertFalse(
            ChatScrollPolicy.nextJumpButtonVisibility(
                currentlyVisible = true,
                distanceFromBottomPx = 30,
                showThresholdPx = 84,
                hideThresholdPx = 36,
            ),
        )
    }

    @Test
    fun scrollPolicy_distanceFromBottomHandlesVisibleAndOffscreenAnchors() {
        // Cannot scroll forward -> 0px from bottom
        assertEquals(
            0,
            ChatScrollPolicy.computeDistanceFromBottomPx(
                canScrollForward = false,
                totalItemsCount = 10,
                lastVisibleItemIndex = 9,
                lastVisibleItemEndPx = 750,
                viewportEndOffset = 900,
                afterContentPadding = 150,
            ),
        )
        // Anchor is visible and 120px below visible viewport end (900 - 150 = 750)
        assertEquals(
            120,
            ChatScrollPolicy.computeDistanceFromBottomPx(
                canScrollForward = true,
                totalItemsCount = 10,
                lastVisibleItemIndex = 9,
                lastVisibleItemEndPx = 870,
                viewportEndOffset = 900,
                afterContentPadding = 150,
            ),
        )
        // Anchor not yet visible -> MAX_VALUE
        assertEquals(
            Int.MAX_VALUE,
            ChatScrollPolicy.computeDistanceFromBottomPx(
                canScrollForward = true,
                totalItemsCount = 10,
                lastVisibleItemIndex = 6,
                lastVisibleItemEndPx = 850,
                viewportEndOffset = 900,
                afterContentPadding = 150,
            ),
        )
    }

    @Test
    fun scrollPolicy_turnSpacerShrinksMonotonicallyToZero() {
        val initial = ChatScrollPolicy.computeMonotonicTurnSpacerPx(
            currentSpacerPx = 600,
            viewportUsableHeightPx = 700,
            turnContentHeightPx = 120,
            isInitialMeasure = true,
        )
        assertEquals(580, initial)

        // Response grows -> spacer shrinks
        val shrunk = ChatScrollPolicy.computeMonotonicTurnSpacerPx(
            currentSpacerPx = initial,
            viewportUsableHeightPx = 700,
            turnContentHeightPx = 400,
            isInitialMeasure = false,
        )
        assertEquals(300, shrunk)

        // Viewport jitter makes needed temporarily larger -> MUST NOT grow back
        val noBounce = ChatScrollPolicy.computeMonotonicTurnSpacerPx(
            currentSpacerPx = shrunk,
            viewportUsableHeightPx = 750,
            turnContentHeightPx = 400,
            isInitialMeasure = false,
        )
        assertEquals(300, noBounce)

        // Response exceeds viewport -> clamped to 0
        val collapsed = ChatScrollPolicy.computeMonotonicTurnSpacerPx(
            currentSpacerPx = noBounce,
            viewportUsableHeightPx = 700,
            turnContentHeightPx = 950,
            isInitialMeasure = false,
        )
        assertEquals(0, collapsed)
    }

    @Test
    fun streamDeltaCoalescer_batchesDeltasAndFlushesSynchronouslyInOrder() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        try {
            val flushed = mutableListOf<CoalescedDeltaBatch>()
            val coalescer = StreamDeltaCoalescer(
                scope = scope,
                flushIntervalMs = 40L,
                onFlush = { flushed.add(it) },
            )

            coalescer.appendContent("你")
            coalescer.appendContent("好")
            coalescer.appendContent("，世界")
            coalescer.appendReasoning(1, "分析", "思考A")
            coalescer.appendReasoning(1, "分析", "思考B")
            coalescer.appendReasoning(2, "检索", "思考C")

            // Structural event arrives immediately -> synchronous flush preserves exact order
            assertTrue(coalescer.hasPending())
            coalescer.flushNow()
            assertFalse(coalescer.hasPending())

            assertEquals(1, flushed.size)
            assertEquals("你好，世界", flushed[0].contentDelta)
            assertEquals(2, flushed[0].reasoningDeltas.size)
            assertEquals("思考A思考B", flushed[0].reasoningDeltas[0].text)
            assertEquals("思考C", flushed[0].reasoningDeltas[1].text)

            // Timed automatic flush works after flushIntervalMs
            coalescer.appendContent("后续流式片段")
            delay(100L)
            assertEquals(2, flushed.size)
            assertEquals("后续流式片段", flushed[1].contentDelta)
        } finally {
            scope.cancel()
        }
    }

    @Test
    fun markdownStreamingParser_handlesUnclosedFencesTablesAndInlineTails() {
        val streamingCode = "前言段落\n\n```kotlin\nval x = 1\nval y = 2"
        val blocks = parseMarkdownBlocks(streamingCode, isStreaming = true)
        assertEquals(2, blocks.size)
        assertTrue(blocks[0] is MdBlock.Paragraph)
        val codeBlock = blocks[1] as MdBlock.CodeBlock
        assertEquals("kotlin", codeBlock.lang)
        assertTrue(codeBlock.isUnclosed)
        assertEquals("val x = 1\nval y = 2", codeBlock.code)

        val finishedBlocks = parseMarkdownBlocks(streamingCode, isStreaming = false)
        assertFalse((finishedBlocks[1] as MdBlock.CodeBlock).isUnclosed)

        // Streaming inline tail normalization
        assertEquals("正在强调 **重点内容**", normalizeStreamingInlineTail("正在强调 **重点内容"))
        assertEquals("调用 `foo()`", normalizeStreamingInlineTail("调用 `foo()"))
        assertEquals("删除 ~~旧方案~~", normalizeStreamingInlineTail("删除 ~~旧方案"))
        assertEquals("参考 官方文档", normalizeStreamingInlineTail("参考 [官方文档](https://example.com/pa"))

        // Streaming table with partial trailing empty pipe row ignored
        val streamingTable = "| 指标 | 数值 |\n| --- | --- |\n| 延迟 | 32ms |\n|"
        val tableBlocks = parseMarkdownBlocks(streamingTable, isStreaming = true)
        assertEquals(1, tableBlocks.size)
        val table = tableBlocks[0] as MdBlock.Table
        assertEquals(listOf("指标", "数值"), table.headers)
        assertEquals(1, table.rows.size)
        assertEquals(listOf("延迟", "32ms"), table.rows[0])
    }

    @Test
    fun streamingPhase_resolvesAllLifecycleStatesAndFriendlyLabels() {
        val step = CurrentStepInfo(index = 2, total = 4, title = "整理结论")
        val donePlan = Plan(items = listOf(PlanItem(id = JsonPrimitive("1"), content = "完成", status = "completed")))

        assertEquals(
            StreamingPhase.STOPPING,
            resolveStreamingPhase(step, "web_search", donePlan, stopping = true),
        )
        assertEquals(
            StreamingPhase.RECONNECTING,
            resolveStreamingPhase(step, "web_search", donePlan, reconnecting = true),
        )
        assertEquals(
            StreamingPhase.WAITING_APPROVAL,
            resolveStreamingPhase(step, "execute_code", donePlan, pendingControlKind = "approval"),
        )
        assertEquals(
            "等待你的批准",
            computeLiveStepLabel(step, "execute_code", donePlan, pendingControlKind = "approval"),
        )
        assertEquals(
            "等待你补充信息",
            computeLiveStepLabel(step, null, donePlan, pendingControlKind = "clarify"),
        )
        assertEquals(
            "步骤 2/4 · 整理结论",
            computeLiveStepLabel(step, "web_search", donePlan),
        )
        assertEquals(
            "正在使用 读取工作区文件",
            computeLiveStepLabel(null, "mcp__whitz_files__read_workspace_file", null),
        )
        assertEquals(
            "正在生成回答…",
            computeLiveStepLabel(null, null, null, hasContent = true),
        )
        assertEquals(
            "正在思考…",
            computeLiveStepLabel(null, null, null),
        )
    }
}
