package com.glassous.whitz.core.files

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FileTokensTest {
    @Test
    fun serializeAndExtractInlineFileIds() {
        val id1 = "11111111-2222-3333-4444-555555555555"
        val id2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        val token1 = serializeFileToken(id1, "report [final]|v1.csv")
        assertEquals("[[file:$id1|report [final/v1.csv]]", token1)

        val message = "请分析 $token1 并对比 [[file:$id2|chart.png]] 然后再参考 $token1"
        val ids = extractInlineFileIds(message)
        assertEquals(listOf(id1, id2), ids)
    }

    @Test
    fun parseInlineFileSegmentsResolvesFallbackAndText() {
        val id1 = "11111111-2222-3333-4444-555555555555"
        val segments = parseInlineFileSegments("查看 [[file:$id1]] 的结果") { id ->
            if (id == id1) "summary.md" else null
        }
        assertEquals(3, segments.size)
        assertEquals(InlineMessageSegment.Text("查看 "), segments[0])
        assertEquals(InlineMessageSegment.FileRef(id1, "summary.md"), segments[1])
        assertEquals(InlineMessageSegment.Text(" 的结果"), segments[2])
    }

    @Test
    fun parseDeliverablePayloadHandlesValidAndInvalidJson() {
        val payload = """{"file_id":"abc-123","filename":"dashboard.html","title":"销售看板","summary":"Q4 指标总结"}"""
        val parsed = parseDeliverablePayload(payload)
        assertNotNull(parsed)
        assertEquals("abc-123", parsed!!.fileId)
        assertEquals("dashboard.html", parsed.filename)
        assertEquals(".html", parsed.ext)
        assertEquals("销售看板", parsed.title)
        assertEquals("Q4 指标总结", parsed.summary)

        assertNull(parseDeliverablePayload("not json"))
        assertNull(parseDeliverablePayload("{}"))
    }

    @Test
    fun delimitedTableRoundtripWithQuotesAndCommas() {
        val raw = "name,score,note\r\n\"Alice, B\",95,\"line1\nline2\"\r\nBob,88,\"say \"\"hi\"\"\""
        val table = parseDelimitedTable(raw, filename = "grades.csv")
        assertEquals(',', table.delimiter)
        assertEquals(listOf("name", "score", "note"), table.headers)
        assertEquals(2, table.rows.size)
        assertEquals("Alice, B", table.rows[0][0])
        assertEquals("line1\nline2", table.rows[0][2])
        assertEquals("say \"hi\"", table.rows[1][2])

        val serialized = serializeDelimitedTable(table)
        val reparsed = parseDelimitedTable(serialized, filename = "grades.csv")
        assertEquals(table.headers, reparsed.headers)
        assertEquals(table.rows, reparsed.rows)
    }

    @Test
    fun extensionClassificationHelpersWork() {
        assertTrue(isImageFile("photo.webp"))
        assertTrue(isHtmlExt("index.htm"))
        assertTrue(isCsvExt("data.tsv"))
        assertTrue(isMarkdownExt("README.md"))
        assertTrue(isWritableTextExt("notes.txt"))
        assertFalse(isWritableTextExt("archive.pdf"))
        assertNotNull(FileValidator.getFileSpec("page.htm"))
    }
}
