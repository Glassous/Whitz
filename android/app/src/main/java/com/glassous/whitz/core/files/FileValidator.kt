package com.glassous.whitz.core.files

data class AllowedFileSpec(
    val ext: String,
    val category: String, // "document" | "spreadsheet" | "code" | "image"
    val mime: String,
    val label: String,
)

object FileValidator {
    const val MAX_FILE_SIZE_MB = 20L
    const val MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024L * 1024L
    const val MAX_FILES_PER_CONVERSATION = 20

    const val SUPPORTED_TYPES_SUMMARY =
        "支持文档（PDF/DOCX/TXT/MD）、表格数据（XLSX/CSV/JSON/YAML/XML）、代码文本及图片（PNG/JPG/WebP/GIF），单文件最大 20 MB"

    val ALLOWED_SPECS: Map<String, AllowedFileSpec> = mapOf(
        ".pdf" to AllowedFileSpec(".pdf", "document", "application/pdf", "PDF"),
        ".docx" to AllowedFileSpec(
            ".docx",
            "document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "Word"
        ),
        ".txt" to AllowedFileSpec(".txt", "document", "text/plain", "文本"),
        ".md" to AllowedFileSpec(".md", "document", "text/markdown", "Markdown"),
        ".markdown" to AllowedFileSpec(".markdown", "document", "text/markdown", "Markdown"),
        ".xlsx" to AllowedFileSpec(
            ".xlsx",
            "spreadsheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Excel"
        ),
        ".csv" to AllowedFileSpec(".csv", "spreadsheet", "text/csv", "CSV"),
        ".tsv" to AllowedFileSpec(".tsv", "spreadsheet", "text/tab-separated-values", "TSV"),
        ".json" to AllowedFileSpec(".json", "spreadsheet", "application/json", "JSON"),
        ".jsonl" to AllowedFileSpec(".jsonl", "spreadsheet", "application/x-ndjson", "JSONL"),
        ".yaml" to AllowedFileSpec(".yaml", "spreadsheet", "application/x-yaml", "YAML"),
        ".yml" to AllowedFileSpec(".yml", "spreadsheet", "application/x-yaml", "YAML"),
        ".xml" to AllowedFileSpec(".xml", "spreadsheet", "application/xml", "XML"),
        ".py" to AllowedFileSpec(".py", "code", "text/x-python", "Python"),
        ".js" to AllowedFileSpec(".js", "code", "text/javascript", "JS"),
        ".ts" to AllowedFileSpec(".ts", "code", "text/typescript", "TS"),
        ".tsx" to AllowedFileSpec(".tsx", "code", "text/tsx", "TSX"),
        ".jsx" to AllowedFileSpec(".jsx", "code", "text/jsx", "JSX"),
        ".vue" to AllowedFileSpec(".vue", "code", "text/plain", "Vue"),
        ".html" to AllowedFileSpec(".html", "code", "text/html", "HTML"),
        ".htm" to AllowedFileSpec(".htm", "code", "text/html", "HTML"),
        ".css" to AllowedFileSpec(".css", "code", "text/css", "CSS"),
        ".sql" to AllowedFileSpec(".sql", "code", "application/sql", "SQL"),
        ".sh" to AllowedFileSpec(".sh", "code", "text/x-shellscript", "Shell"),
        ".log" to AllowedFileSpec(".log", "code", "text/plain", "日志"),
        ".ini" to AllowedFileSpec(".ini", "code", "text/plain", "INI"),
        ".toml" to AllowedFileSpec(".toml", "code", "application/toml", "TOML"),
        ".png" to AllowedFileSpec(".png", "image", "image/png", "PNG"),
        ".jpg" to AllowedFileSpec(".jpg", "image", "image/jpeg", "JPG"),
        ".jpeg" to AllowedFileSpec(".jpeg", "image", "image/jpeg", "JPEG"),
        ".webp" to AllowedFileSpec(".webp", "image", "image/webp", "WebP"),
        ".gif" to AllowedFileSpec(".gif", "image", "image/gif", "GIF"),
    )

    private val BLOCKED_MIME_PREFIXES = listOf("video/", "audio/")
    private val BLOCKED_MIME_EXACT = setOf(
        "application/zip",
        "application/x-zip-compressed",
        "application/x-rar-compressed",
        "application/vnd.rar",
        "application/x-7z-compressed",
        "application/x-tar",
        "application/gzip",
        "application/x-gzip",
        "application/x-msdownload",
        "application/x-dosexec",
        "application/x-executable",
        "application/x-mach-binary",
        "image/svg+xml",
    )

    fun getFileExt(filename: String): String {
        val clean = filename.trim()
        val dot = clean.lastIndexOf('.')
        if (dot <= 0 || dot == clean.length - 1) return ""
        return clean.substring(dot).lowercase()
    }

    fun getFileSpec(filename: String): AllowedFileSpec? {
        val ext = getFileExt(filename)
        return if (ext.isNotEmpty()) ALLOWED_SPECS[ext] else null
    }

    fun isBlockedMime(mime: String?): Boolean {
        if (mime.isNullOrBlank()) return false
        val base = mime.substringBefore(';').trim().lowercase()
        if (base.isEmpty() || base == "application/octet-stream") return false
        if (BLOCKED_MIME_PREFIXES.any { base.startsWith(it) }) return true
        return base in BLOCKED_MIME_EXACT
    }

    fun validateFile(filename: String, mimeType: String?, sizeBytes: Long): String? {
        if (sizeBytes <= 0) return "文件为空"
        if (sizeBytes > MAX_FILE_SIZE_BYTES) return "超过 ${MAX_FILE_SIZE_MB} MB 大小限制"
        if (isBlockedMime(mimeType)) return "不支持该文件类型"
        if (getFileSpec(filename) == null) return "不支持的文件扩展名"
        return null
    }

    fun formatSize(bytes: Long): String {
        if (bytes < 1024) return "$bytes B"
        val kb = bytes / 1024.0
        if (kb < 1024) return String.format("%.1f KB", kb)
        val mb = kb / 1024.0
        return String.format("%.2f MB", mb)
    }
}
