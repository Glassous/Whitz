package com.glassous.whitz.feature.chat

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withLink
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.core.files.getExtLower
import com.glassous.whitz.core.files.parseDeliverablePayload
import com.glassous.whitz.core.model.DeliverableTarget
import com.glassous.whitz.ui.theme.ChevronRight
import com.glassous.whitz.ui.theme.ContentCopy
import com.glassous.whitz.ui.theme.Description
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import kotlinx.coroutines.delay

private val HEADING_REGEX = Regex("^(#{1,6})\\s+(.+)$")
private val TABLE_SEP_REGEX = Regex("^\\|?[\\s:|-]+\\|?$")
private val BULLET_REGEX = Regex("^[-*+]\\s+.+")
private val BULLET_PREFIX_REGEX = Regex("^[-*+]\\s+")
private val ORDERED_REGEX = Regex("^(\\d+\\.)\\s+(.+)")
private val TRAILING_PARTIAL_LINK_REGEX = Regex("\\[([^\\]\\n]+)]\\([^)\\n]*$")

internal sealed interface MdBlock {
    data class Heading(val level: Int, val text: String) : MdBlock
    data class Paragraph(val text: String) : MdBlock
    data class CodeBlock(
        val lang: String,
        val code: String,
        val isUnclosed: Boolean = false,
    ) : MdBlock
    data class DeliverableCard(val target: DeliverableTarget, val isLoading: Boolean) : MdBlock
    data class Quote(val text: String) : MdBlock
    data class BulletList(val items: List<String>) : MdBlock
    data class OrderedList(val items: List<Pair<String, String>>) : MdBlock
    data class Table(val headers: List<String>, val rows: List<List<String>>) : MdBlock
    data object Divider : MdBlock
}

internal fun parseMarkdownBlocks(input: String, isStreaming: Boolean = false): List<MdBlock> {
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
            val closed = i < lines.size
            if (closed) i++
            val rawBody = codeLines.joinToString("\n")
            if (lang.equals("deliverable", ignoreCase = true) || lang.equals("whitz-deliverable", ignoreCase = true)) {
                val parsed = parseDeliverablePayload(rawBody)
                if (parsed != null) {
                    blocks.add(MdBlock.DeliverableCard(parsed, isLoading = !closed))
                } else if (!closed) {
                    blocks.add(
                        MdBlock.DeliverableCard(
                            target = DeliverableTarget(filename = "deliverable.txt", title = "正在生成交付产物…"),
                            isLoading = true,
                        )
                    )
                } else {
                    blocks.add(MdBlock.CodeBlock(lang, rawBody, isUnclosed = false))
                }
            } else {
                blocks.add(MdBlock.CodeBlock(lang, rawBody, isUnclosed = !closed && isStreaming))
            }
            continue
        }
        // Divider
        if (trimmed == "---" || trimmed == "***" || trimmed == "___") {
            blocks.add(MdBlock.Divider)
            i++
            continue
        }
        // Heading
        val headingMatch = HEADING_REGEX.find(trimmed)
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
        if (trimmed.startsWith("|") && i + 1 < lines.size && TABLE_SEP_REGEX.matches(lines[i + 1].trim())) {
            val headers = trimmed.trim('|').split('|').map { it.trim() }
            i += 2
            val rows = mutableListOf<List<String>>()
            while (i < lines.size && lines[i].trim().startsWith("|")) {
                val rowTrimmed = lines[i].trim()
                val cells = rowTrimmed.removePrefix("|").removeSuffix("|").split('|').map { it.trim() }
                if (cells.any { it.isNotEmpty() } || !isStreaming) {
                    rows.add(cells)
                }
                i++
            }
            blocks.add(MdBlock.Table(headers, rows))
            continue
        }
        // Bullet list
        if (BULLET_REGEX.matches(trimmed)) {
            val items = mutableListOf<String>()
            while (i < lines.size && BULLET_REGEX.matches(lines[i].trim())) {
                items.add(lines[i].trim().replaceFirst(BULLET_PREFIX_REGEX, ""))
                i++
            }
            blocks.add(MdBlock.BulletList(items))
            continue
        }
        // Ordered list
        if (ORDERED_REGEX.matches(trimmed)) {
            val items = mutableListOf<Pair<String, String>>()
            while (i < lines.size) {
                val m = ORDERED_REGEX.find(lines[i].trim()) ?: break
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
                cur.startsWith(">") || BULLET_REGEX.matches(cur) ||
                ORDERED_REGEX.matches(cur) || cur == "---" ||
                (cur.startsWith("|") && i + 1 < lines.size && TABLE_SEP_REGEX.matches(lines[i + 1].trim()))
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

/**
 * Gently normalizes incomplete inline Markdown markers at the tail of an actively streaming
 * text block so partial `**bold`, `` `code ``, `~~strike`, or `[label](partial-url` don't
 * flicker raw syntax tokens while streaming.
 */
internal fun normalizeStreamingInlineTail(text: String): String {
    if (text.isEmpty()) return text
    var result = TRAILING_PARTIAL_LINK_REGEX.replace(text, "$1")
    // Close dangling inline code backtick if unpaired
    val backtickCount = result.count { it == '`' }
    if (backtickCount % 2 == 1) {
        result += "`"
    }
    // Close dangling **bold** if unpaired (excluding fenced backticks already handled)
    var boldCount = 0
    var scan = 0
    while (scan < result.length - 1) {
        if (result[scan] == '*' && result[scan + 1] == '*') {
            boldCount++
            scan += 2
        } else {
            scan++
        }
    }
    if (boldCount % 2 == 1 && !result.endsWith("**")) {
        result += "**"
    }
    // Close dangling ~~strikethrough~~ if unpaired
    var strikeCount = 0
    scan = 0
    while (scan < result.length - 1) {
        if (result[scan] == '~' && result[scan + 1] == '~') {
            strikeCount++
            scan += 2
        } else {
            scan++
        }
    }
    if (strikeCount % 2 == 1 && !result.endsWith("~~")) {
        result += "~~"
    }
    return result
}

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
                        withLink(
                            LinkAnnotation.Url(
                                url = url,
                                styles = TextLinkStyles(
                                    style = SpanStyle(
                                        color = linkColor,
                                        textDecoration = TextDecoration.Underline,
                                    ),
                                ),
                            ),
                        ) {
                            append(label)
                        }
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

@Composable
private fun rememberStreamingCursorAlpha(active: Boolean): Float {
    if (!active) return 0f
    val transition = rememberInfiniteTransition(label = "streamCursor")
    val alpha by transition.animateFloat(
        initialValue = 0.25f,
        targetValue = 0.92f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 520),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "streamCursorAlpha",
    )
    return alpha
}

@Composable
private fun InlineMdText(
    text: String,
    style: TextStyle,
    modifier: Modifier = Modifier,
    isStreamingTail: Boolean = false,
) {
    val colors = LocalWhitzColors.current
    val linkColor = if (colors.isDark) Color(0xFF93C5FD) else Color(0xFF2563EB)
    val codeBg = colors.surface
    val codeFg = colors.fg
    val effectiveText = remember(text, isStreamingTail) {
        if (isStreamingTail) normalizeStreamingInlineTail(text) else text
    }
    val baseAnnotated = remember(effectiveText, linkColor, codeBg, codeFg) {
        buildInlineAnnotated(
            text = effectiveText,
            linkColor = linkColor,
            codeBg = codeBg,
            codeFg = codeFg,
        )
    }
    if (isStreamingTail) {
        val cursorAlpha = rememberStreamingCursorAlpha(active = true)
        val cursorColor = MaterialTheme.colorScheme.primary
        val withCursor = buildAnnotatedString {
            append(baseAnnotated)
            val start = length
            append(" ●")
            addStyle(
                SpanStyle(
                    color = cursorColor.copy(alpha = cursorAlpha),
                    fontSize = 11.sp,
                ),
                start,
                length,
            )
        }
        Text(
            text = withCursor,
            style = style,
            modifier = modifier,
        )
    } else {
        Text(
            text = baseAnnotated,
            style = style,
            modifier = modifier,
        )
    }
}

@Composable
fun MarkdownText(
    markdown: String,
    modifier: Modifier = Modifier,
    isStreaming: Boolean = false,
    onOpenDeliverable: (DeliverableTarget) -> Unit = {},
) {
    val blocks = remember(markdown, isStreaming) { parseMarkdownBlocks(markdown, isStreaming) }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        blocks.forEachIndexed { index, block ->
            val isTailStreaming = isStreaming && index == blocks.lastIndex
            key(index) {
                MarkdownBlockItem(
                    block = block,
                    isTailStreaming = isTailStreaming,
                    onOpenDeliverable = onOpenDeliverable,
                )
            }
        }
    }
}

@Composable
private fun MarkdownBlockItem(
    block: MdBlock,
    isTailStreaming: Boolean,
    onOpenDeliverable: (DeliverableTarget) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val clipboard = LocalClipboardManager.current

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
                isStreamingTail = isTailStreaming,
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
                isStreamingTail = isTailStreaming,
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
                    isStreamingTail = isTailStreaming,
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
            LaunchedEffect(copied) {
                if (copied) {
                    delay(1800L)
                    copied = false
                }
            }
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
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            text = block.lang.ifBlank { "code" },
                            color = Color(0xFFA1A1AA),
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                        )
                        if (block.isUnclosed) {
                            val pulseAlpha = rememberStreamingCursorAlpha(active = true)
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(5.dp)
                                        .clip(CircleShape)
                                        .background(Color(0xFF93C5FD).copy(alpha = pulseAlpha)),
                                )
                                Text(
                                    text = "生成中…",
                                    color = Color(0xFFA1A1AA),
                                    fontSize = 10.5.sp,
                                )
                            }
                        }
                    }
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
                block.items.forEachIndexed { idx, item ->
                    val itemStreaming = isTailStreaming && idx == block.items.lastIndex
                    Row(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            text = "•",
                            color = colors.fgMuted,
                            fontSize = 15.sp,
                            modifier = Modifier.padding(end = 8.dp),
                        )
                        InlineMdText(
                            text = item,
                            isStreamingTail = itemStreaming,
                            style = TextStyle(color = colors.fg, fontSize = 15.sp, lineHeight = 22.sp),
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        }
        is MdBlock.OrderedList -> {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                block.items.forEachIndexed { idx, (num, item) ->
                    val itemStreaming = isTailStreaming && idx == block.items.lastIndex
                    Row(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            text = num,
                            color = colors.fgMuted,
                            fontSize = 14.sp,
                            modifier = Modifier.padding(end = 8.dp),
                        )
                        InlineMdText(
                            text = item,
                            isStreamingTail = itemStreaming,
                            style = TextStyle(color = colors.fg, fontSize = 15.sp, lineHeight = 22.sp),
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        }
        is MdBlock.Table -> {
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
        is MdBlock.DeliverableCard -> {
            val target = block.target
            val extLabel = getExtLower(target.filename)
                .removePrefix(".")
                .uppercase()
                .ifEmpty { "TEXT" }
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = colors.surface,
                border = BorderStroke(0.8.dp, colors.lineStrong),
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(16.dp))
                    .clickable(enabled = !block.isLoading) { onOpenDeliverable(target) },
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .size(38.dp)
                            .clip(RoundedCornerShape(11.dp))
                            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.1f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (block.isLoading) {
                            WhitzLoadingIndicator(size = 18.dp)
                        } else {
                            Icon(
                                Icons.Default.Description,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(20.dp),
                            )
                        }
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text(
                                text = target.title ?: target.filename,
                                fontSize = 14.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = colors.fg,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false),
                            )
                            Surface(
                                shape = RoundedCornerShape(6.dp),
                                color = colors.canvas,
                                border = BorderStroke(0.5.dp, colors.line),
                            ) {
                                Text(
                                    text = extLabel,
                                    fontSize = 10.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = colors.fgMuted,
                                    modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp),
                                )
                            }
                        }
                        Text(
                            text = target.summary ?: target.filename,
                            fontSize = 12.sp,
                            color = colors.fgMuted,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    if (!block.isLoading) {
                        Spacer(modifier = Modifier.width(8.dp))
                        Icon(
                            Icons.Default.ChevronRight,
                            contentDescription = "查看交付产物",
                            tint = colors.fgFaint,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }
        }
    }
}
