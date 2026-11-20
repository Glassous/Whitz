package com.glassous.whitz.feature.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.ClickableText
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.ui.theme.LocalWhitzColors

private sealed interface MdBlock {
    data class Heading(val level: Int, val text: String) : MdBlock
    data class Paragraph(val text: String) : MdBlock
    data class CodeBlock(val lang: String, val code: String) : MdBlock
    data class Quote(val text: String) : MdBlock
    data class BulletList(val items: List<String>) : MdBlock
    data class OrderedList(val items: List<Pair<String, String>>) : MdBlock
    data class Table(val headers: List<String>, val rows: List<List<String>>) : MdBlock
    data object Divider : MdBlock
}

private fun parseMarkdownBlocks(input: String): List<MdBlock> {
    val lines = input.replace("\r\n", "\n").split('\n')
    val blocks = mutableListOf<MdBlock>()
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        val trimmed = line.trim()
        if (trimmed.isEmpty()) {
            i++
            continue
        }
        // Fenced code block
        if (trimmed.startsWith("```")) {
            val lang = trimmed.removePrefix("```").trim()
            val codeLines = mutableListOf<String>()
            i++
            while (i < lines.size && !lines[i].trim().startsWith("```")) {
                codeLines.add(lines[i])
                i++
            }
            if (i < lines.size) i++
            blocks.add(MdBlock.CodeBlock(lang, codeLines.joinToString("\n")))
            continue
        }
        // Divider
        if (trimmed == "---" || trimmed == "***" || trimmed == "___") {
            blocks.add(MdBlock.Divider)
            i++
            continue
        }
        // Heading
        val headingMatch = Regex("^(#{1,6})\\s+(.+)$").find(trimmed)
        if (headingMatch != null) {
            blocks.add(MdBlock.Heading(headingMatch.groupValues[1].length, headingMatch.groupValues[2]))
            i++
            continue
        }
        // Blockquote
        if (trimmed.startsWith(">")) {
            val qLines = mutableListOf<String>()
            while (i < lines.size && lines[i].trim().startsWith(">")) {
                qLines.add(lines[i].trim().removePrefix(">").trimStart())
                i++
            }
            blocks.add(MdBlock.Quote(qLines.joinToString("\n")))
            continue
        }
        // Table
        if (trimmed.startsWith("|") && i + 1 < lines.size && lines[i + 1].trim().matches(Regex("^\\|?[\\s:|-]+\\|?$"))) {
            val headers = trimmed.trim('|').split('|').map { it.trim() }
            i += 2
            val rows = mutableListOf<List<String>>()
            while (i < lines.size && lines[i].trim().startsWith("|")) {
                rows.add(lines[i].trim().trim('|').split('|').map { it.trim() })
                i++
            }
            blocks.add(MdBlock.Table(headers, rows))
            continue
        }
        // Bullet list
        if (trimmed.matches(Regex("^[-*+]\\s+.+"))) {
            val items = mutableListOf<String>()
            while (i < lines.size && lines[i].trim().matches(Regex("^[-*+]\\s+.+"))) {
                items.add(lines[i].trim().replaceFirst(Regex("^[-*+]\\s+"), ""))
                i++
            }
            blocks.add(MdBlock.BulletList(items))
            continue
        }
        // Ordered list
        val ordRegex = Regex("^(\\d+\\.)\\s+(.+)")
        if (trimmed.matches(ordRegex)) {
            val items = mutableListOf<Pair<String, String>>()
            while (i < lines.size) {
                val m = ordRegex.find(lines[i].trim()) ?: break
                items.add(m.groupValues[1] to m.groupValues[2])
                i++
            }
            blocks.add(MdBlock.OrderedList(items))
            continue
        }
        // Paragraph
        val pLines = mutableListOf<String>()
        while (i < lines.size) {
            val cur = lines[i].trim()
            if (cur.isEmpty() || cur.startsWith("```") || cur.startsWith("#") ||
                cur.startsWith(">") || cur.matches(Regex("^[-*+]\\s+.+")) ||
                cur.matches(ordRegex) || cur == "---"
            ) break
            pLines.add(lines[i])
            i++
        }
        if (pLines.isNotEmpty()) {
            blocks.add(MdBlock.Paragraph(pLines.joinToString("\n")))
        } else {
            i++
        }
    }
    return blocks
}

@Composable
private fun buildInlineAnnotated(
    text: String,
    linkColor: Color,
    codeBg: Color,
    codeFg: Color,
): AnnotatedString {
    return buildAnnotatedString {
        var idx = 0
        while (idx < text.length) {
            // Link [label](url)
            if (text[idx] == '[') {
                val closeBracket = text.indexOf(']', idx + 1)
                if (closeBracket > idx && closeBracket + 1 < text.length && text[closeBracket + 1] == '(') {
                    val closeParen = text.indexOf(')', closeBracket + 2)
                    if (closeParen > closeBracket + 2) {
                        val label = text.substring(idx + 1, closeBracket)
                        val url = text.substring(closeBracket + 2, closeParen)
                        val start = length
                        append(label)
                        addStyle(
                            SpanStyle(color = linkColor, textDecoration = TextDecoration.Underline),
                            start,
                            length,
                        )
                        addStringAnnotation("URL", url, start, length)
                        idx = closeParen + 1
                        continue
                    }
                }
            }
            // Inline code `code`
            if (text[idx] == '`') {
                val end = text.indexOf('`', idx + 1)
                if (end > idx) {
                    val code = text.substring(idx + 1, end)
                    val start = length
                    append(" $code ")
                    addStyle(
                        SpanStyle(
                            fontFamily = FontFamily.Monospace,
                            background = codeBg,
                            color = codeFg,
                            fontSize = 13.sp,
                        ),
                        start,
                        length,
                    )
                    idx = end + 1
                    continue
                }
            }
            // Bold **text**
            if (text.startsWith("**", idx)) {
                val end = text.indexOf("**", idx + 2)
                if (end > idx + 1) {
                    val inner = text.substring(idx + 2, end)
                    val start = length
                    append(inner)
                    addStyle(SpanStyle(fontWeight = FontWeight.Bold), start, length)
                    idx = end + 2
                    continue
                }
            }
            // Strikethrough ~~text~~
            if (text.startsWith("~~", idx)) {
                val end = text.indexOf("~~", idx + 2)
                if (end > idx + 1) {
                    val inner = text.substring(idx + 2, end)
                    val start = length
                    append(inner)
                    addStyle(SpanStyle(textDecoration = TextDecoration.LineThrough), start, length)
                    idx = end + 2
                    continue
                }
            }
            // Italic *text*
            if (text[idx] == '*' && (idx + 1 < text.length && text[idx + 1] != ' ')) {
                val end = text.indexOf('*', idx + 1)
                if (end > idx + 1) {
                    val inner = text.substring(idx + 1, end)
                    val start = length
                    append(inner)
                    addStyle(SpanStyle(fontStyle = FontStyle.Italic), start, length)
                    idx = end + 1
                    continue
                }
            }
            append(text[idx])
            idx++
        }
    }
}

@Suppress("DEPRECATION")
@Composable
private fun InlineMdText(
    text: String,
    style: TextStyle,
    modifier: Modifier = Modifier,
) {
    val colors = LocalWhitzColors.current
    val uriHandler = LocalUriHandler.current
    val annotated = buildInlineAnnotated(
        text = text,
        linkColor = if (colors.isDark) Color(0xFF93C5FD) else Color(0xFF2563EB),
        codeBg = colors.surface,
        codeFg = colors.fg,
    )
    ClickableText(
        text = annotated,
        style = style,
        modifier = modifier,
        onClick = { offset ->
            annotated.getStringAnnotations("URL", offset, offset).firstOrNull()?.let { ann ->
                try {
                    uriHandler.openUri(ann.item)
                } catch (_: Exception) {
                    /* ignore invalid URI */
                }
            }
        },
    )
}

@Composable
fun MarkdownText(
    markdown: String,
    modifier: Modifier = Modifier,
) {
    val colors = LocalWhitzColors.current
    val clipboard = LocalClipboardManager.current
    val blocks = remember(markdown) { parseMarkdownBlocks(markdown) }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (block in blocks) {
            when (block) {
                is MdBlock.Heading -> {
                    val fontSize = when (block.level) {
                        1 -> 20.sp
                        2 -> 18.sp
                        3 -> 16.sp
                        else -> 15.sp
                    }
                    InlineMdText(
                        text = block.text,
                        style = TextStyle(
                            color = colors.fg,
                            fontSize = fontSize,
                            fontWeight = FontWeight.Bold,
                            lineHeight = (fontSize.value + 6).sp,
                        ),
                    )
                }
                is MdBlock.Paragraph -> {
                    InlineMdText(
                        text = block.text,
                        style = TextStyle(
                            color = colors.fg,
                            fontSize = 15.sp,
                            lineHeight = 22.sp,
                        ),
                    )
                }
                is MdBlock.Quote -> {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(6.dp))
                            .background(colors.surface)
                            .padding(vertical = 8.dp, horizontal = 10.dp),
                    ) {
                        Box(
                            modifier = Modifier
                                .width(3.dp)
                                .height(20.dp)
                                .background(colors.lineStrong),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        InlineMdText(
                            text = block.text,
                            style = TextStyle(
                                color = colors.fgMuted,
                                fontSize = 14.sp,
                                lineHeight = 20.sp,
                            ),
                        )
                    }
                }
                is MdBlock.CodeBlock -> {
                    var copied by remember { mutableStateOf(false) }
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp))
                            .background(colors.codeBg)
                            .border(1.dp, colors.line, RoundedCornerShape(10.dp)),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(Color.White.copy(alpha = 0.06f))
                                .padding(horizontal = 12.dp, vertical = 4.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = block.lang.ifBlank { "code" },
                                color = Color(0xFFA1A1AA),
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                            IconButton(
                                onClick = {
                                    clipboard.setText(AnnotatedString(block.code))
                                    copied = true
                                },
                                modifier = Modifier.size(28.dp),
                            ) {
                                Icon(
                                    imageVector = if (copied) Icons.Default.Check else Icons.Default.ContentCopy,
                                    contentDescription = "复制代码",
                                    tint = Color(0xFFD4D4D8),
                                    modifier = Modifier.size(14.dp),
                                )
                            }
                        }
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .horizontalScroll(rememberScrollState())
                                .padding(12.dp),
                        ) {
                            Text(
                                text = block.code,
                                color = Color(0xFFF4F4F5),
                                fontSize = 13.sp,
                                fontFamily = FontFamily.Monospace,
                                lineHeight = 19.sp,
                            )
                        }
                    }
                }
                is MdBlock.BulletList -> {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        block.items.forEach { item ->
                            Row(modifier = Modifier.fillMaxWidth()) {
                                Text(
                                    text = "•",
                                    color = colors.fgMuted,
                                    fontSize = 15.sp,
                                    modifier = Modifier.padding(end = 8.dp),
                                )
                                InlineMdText(
                                    text = item,
                                    style = TextStyle(color = colors.fg, fontSize = 15.sp, lineHeight = 22.sp),
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
                is MdBlock.OrderedList -> {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        block.items.forEach { (num, item) ->
                            Row(modifier = Modifier.fillMaxWidth()) {
                                Text(
                                    text = num,
                                    color = colors.fgMuted,
                                    fontSize = 14.sp,
                                    modifier = Modifier.padding(end = 8.dp),
                                )
                                InlineMdText(
                                    text = item,
                                    style = TextStyle(color = colors.fg, fontSize = 15.sp, lineHeight = 22.sp),
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
                is MdBlock.Table -> {
                    // 1–2 columns: stretch to the full available width, no horizontal scrolling.
                    // 3+ columns: keep the fixed-width scrollable layout.
                    val columnCount = maxOf(
                        block.headers.size,
                        block.rows.maxOfOrNull { it.size } ?: 0,
                    ).coerceAtLeast(1)
                    val stretchToWidth = columnCount <= 2
                    val cellModifier = Modifier.width(120.dp).padding(horizontal = 4.dp)

                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (stretchToWidth) {
                                    Modifier
                                } else {
                                    Modifier.horizontalScroll(rememberScrollState())
                                },
                            )
                            .clip(RoundedCornerShape(8.dp))
                            .border(1.dp, colors.line, RoundedCornerShape(8.dp)),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(colors.surface)
                                .padding(8.dp),
                        ) {
                            repeat(columnCount) { index ->
                                Text(
                                    text = block.headers.getOrNull(index).orEmpty(),
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 13.sp,
                                    color = colors.fg,
                                    modifier = if (stretchToWidth) {
                                        Modifier.weight(1f).padding(horizontal = 4.dp)
                                    } else {
                                        cellModifier
                                    },
                                )
                            }
                        }
                        block.rows.forEach { row ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .border(0.5.dp, colors.line)
                                    .padding(8.dp),
                            ) {
                                repeat(columnCount) { index ->
                                    Text(
                                        text = row.getOrNull(index).orEmpty(),
                                        fontSize = 13.sp,
                                        color = colors.fg,
                                        modifier = if (stretchToWidth) {
                                            Modifier.weight(1f).padding(horizontal = 4.dp)
                                        } else {
                                            cellModifier
                                        },
                                    )
                                }
                            }
                        }
                    }
                }
                is MdBlock.Divider -> {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(1.dp)
                            .background(colors.line),
                    )
                }
            }
        }
    }
}
