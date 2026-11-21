package com.glassous.whitz.core.files

import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.DeliverableTarget
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/** Inline composer/message file token: `[[file:<file_id>|<filename>]]` or `[[file:<file_id>]]`. */
val INLINE_FILE_TOKEN_REGEX = Regex("""\[\[file:([0-9a-fA-F-]{8,64})(?:\|([^\]\r\n]+))?\]\]""")

sealed interface InlineMessageSegment {
    data class Text(val value: String) : InlineMessageSegment
    data class FileRef(val fileId: String, val filename: String) : InlineMessageSegment
}

fun serializeFileToken(fileId: String, filename: String): String {
    val safeName = filename.replace("]", "").replace("|", "/").trim().ifEmpty { fileId }
    return "[[file:$fileId|$safeName]]"
}

fun extractInlineFileIds(text: String): List<String> {
    val seen = LinkedHashSet<String>()
    INLINE_FILE_TOKEN_REGEX.findAll(text).forEach { match ->
        val id = match.groupValues[1].trim()
        if (id.isNotEmpty()) seen.add(id)
    }
    return seen.toList()
}

fun parseInlineFileSegments(
    text: String,
    resolveFilename: (String) -> String? = { null },
): List<InlineMessageSegment> {
    if (text.isEmpty()) return emptyList()
    val segments = mutableListOf<InlineMessageSegment>()
    var cursor = 0
    for (match in INLINE_FILE_TOKEN_REGEX.findAll(text)) {
        if (match.range.first > cursor) {
            segments += InlineMessageSegment.Text(text.substring(cursor, match.range.first))
        }
        val fileId = match.groupValues[1].trim()
        val rawName = match.groupValues.getOrNull(2)?.trim().orEmpty()
        val resolvedName = rawName.ifEmpty { resolveFilename(fileId).orEmpty() }.ifEmpty { "文件" }
        segments += InlineMessageSegment.FileRef(fileId = fileId, filename = resolvedName)
        cursor = match.range.last + 1
    }
    if (cursor < text.length) {
        segments += InlineMessageSegment.Text(text.substring(cursor))
    }
    return segments
}

private val WRITABLE_TEXT_EXTENSIONS = setOf(
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".xml", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".vue", ".html", ".htm", ".css", ".sql", ".sh", ".log", ".ini", ".toml",
)

private val IMAGE_EXTENSIONS = setOf(".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

fun getExtLower(filename: String): String {
    val clean = filename.trim()
    val dot = clean.lastIndexOf('.')
    if (dot < 0 || dot == clean.length - 1) return ""
    return clean.substring(dot).lowercase()
}

fun isImageFile(filename: String, mimeType: String = "", category: String = ""): Boolean {
    if (category.equals("image", ignoreCase = true)) return true
    if (mimeType.lowercase().startsWith("image/")) return true
    return getExtLower(filename) in IMAGE_EXTENSIONS
}

fun isConversationImageFile(file: ConversationFile): Boolean =
    isImageFile(file.filename, file.mimeType, file.category)

fun isWritableTextExt(filename: String, ext: String = ""): Boolean {
    val resolved = (ext.ifBlank { getExtLower(filename) }).lowercase()
    return resolved in WRITABLE_TEXT_EXTENSIONS
}

fun isHtmlExt(filename: String, ext: String = "", mimeType: String = ""): Boolean {
    val resolved = (ext.ifBlank { getExtLower(filename) }).lowercase()
    return resolved == ".html" || resolved == ".htm" || mimeType.lowercase().contains("text/html")
}

fun isCsvExt(filename: String, ext: String = "", mimeType: String = ""): Boolean {
    val resolved = (ext.ifBlank { getExtLower(filename) }).lowercase()
    return resolved == ".csv" || resolved == ".tsv" ||
        mimeType.lowercase().contains("text/csv") ||
        mimeType.lowercase().contains("tab-separated-values")
}

fun isMarkdownExt(filename: String, ext: String = "", mimeType: String = ""): Boolean {
    val resolved = (ext.ifBlank { getExtLower(filename) }).lowercase()
    return resolved == ".md" || resolved == ".markdown" || mimeType.lowercase().contains("text/markdown")
}

fun parseDeliverablePayload(rawJson: String): DeliverableTarget? {
    val trimmed = rawJson.trim()
    if (!trimmed.startsWith("{")) return null
    return runCatching {
        val obj = Json.parseToJsonElement(trimmed) as? JsonObject ?: return null
        val fileId = obj["file_id"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        val filename = obj["filename"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        if (fileId.isEmpty() && filename.isEmpty()) return null
        val title = obj["title"]?.jsonPrimitive?.contentOrNull?.trim()?.takeIf { it.isNotEmpty() }
        val summary = obj["summary"]?.jsonPrimitive?.contentOrNull?.trim()?.takeIf { it.isNotEmpty() }
        val resolvedName = filename.ifEmpty { title ?: "deliverable.txt" }
        DeliverableTarget(
            fileId = fileId,
            filename = resolvedName,
            title = title,
            summary = summary,
            ext = getExtLower(resolvedName),
        )
    }.getOrNull()
}

data class CsvTableData(
    val delimiter: Char,
    val headers: List<String>,
    val rows: List<List<String>>,
)

fun parseDelimitedTable(rawText: String, filename: String = "", ext: String = ""): CsvTableData {
    val resolvedExt = (ext.ifBlank { getExtLower(filename) }).lowercase()
    val delimiter = if (resolvedExt == ".tsv") '\t' else ','
    val clean = rawText.removePrefix("\uFEFF").replace("\r\n", "\n").replace('\r', '\n')
    val parsedRows = mutableListOf<List<String>>()
    val currentRow = mutableListOf<String>()
    val cell = StringBuilder()
    var inQuotes = false
    var i = 0
    while (i < clean.length) {
        val ch = clean[i]
        if (inQuotes) {
            if (ch == '"') {
                if (i + 1 < clean.length && clean[i + 1] == '"') {
                    cell.append('"')
                    i += 2
                    continue
                } else {
                    inQuotes = false
                }
            } else {
                cell.append(ch)
            }
        } else {
            when (ch) {
                '"' -> inQuotes = true
                delimiter -> {
                    currentRow += cell.toString()
                    cell.setLength(0)
                }
                '\n' -> {
                    currentRow += cell.toString()
                    cell.setLength(0)
                    if (currentRow.size > 1 || currentRow.firstOrNull()?.isNotEmpty() == true) {
                        parsedRows += currentRow.toList()
                    }
                    currentRow.clear()
                }
                else -> cell.append(ch)
            }
        }
        i++
    }
    if (cell.isNotEmpty() || currentRow.isNotEmpty()) {
        currentRow += cell.toString()
        if (currentRow.size > 1 || currentRow.firstOrNull()?.isNotEmpty() == true) {
            parsedRows += currentRow.toList()
        }
    }
    if (parsedRows.isEmpty()) {
        return CsvTableData(delimiter = delimiter, headers = listOf("列 1"), rows = listOf(listOf("")))
    }
    val colCount = parsedRows.maxOf { it.size }.coerceAtLeast(1)
    val padded = parsedRows.map { row ->
        if (row.size >= colCount) row else row + List(colCount - row.size) { "" }
    }
    return CsvTableData(
        delimiter = delimiter,
        headers = padded.first(),
        rows = if (padded.size > 1) padded.drop(1) else emptyList(),
    )
}

fun serializeDelimitedTable(table: CsvTableData): String {
    val allRows = listOf(table.headers) + table.rows
    val sep = table.delimiter
    return allRows.joinToString("\n") { row ->
        row.joinToString(sep.toString()) { value ->
            val needsQuote = value.contains(sep) || value.contains('"') || value.contains('\n') || value.contains('\r')
            if (!needsQuote) {
                value
            } else {
                "\"${value.replace("\"", "\"\"")}\""
            }
        }
    }
}
