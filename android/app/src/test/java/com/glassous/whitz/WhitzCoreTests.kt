package com.glassous.whitz

import com.glassous.whitz.core.files.FileValidator
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.network.SseParser
import com.glassous.whitz.core.util.ConversationSorter
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class WhitzCoreTests {
    @Test
    fun sseParser_parsesEventAndMultilineData() {
        val block = """
            event: message.delta
            data: {"text":"hello"}
        """.trimIndent()
        val ev = SseParser.parseBlock(block)
        assertNotNull(ev)
        assertEquals("message.delta", ev!!.event)
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
    fun conversationSorter_pinnedFirstThenMostRecent() {
        val c1 = Conversation(id = "1", title = "old", isPinned = false, updatedAt = "2026-01-01T00:00:00Z")
        val c2 = Conversation(id = "2", title = "new", isPinned = false, updatedAt = "2026-01-02T00:00:00Z")
        val c3 = Conversation(
            id = "3",
            title = "pinned",
            isPinned = true,
            pinnedAt = "2026-01-01T00:00:00Z",
            updatedAt = "2025-12-31T00:00:00Z",
        )
        val sorted = ConversationSorter.sort(listOf(c1, c2, c3))
        assertEquals(listOf("3", "2", "1"), sorted.map { it.id })
    }
}
