package com.glassous.whitz.feature.chat

import android.annotation.SuppressLint
import android.webkit.WebView
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import com.glassous.whitz.ui.theme.OpenInNew
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import com.glassous.whitz.ui.theme.ContentCopy
import com.glassous.whitz.ui.theme.Download
import androidx.compose.material.icons.filled.Edit
import com.glassous.whitz.ui.theme.MyLocation
import androidx.compose.material.icons.filled.Refresh
import com.glassous.whitz.ui.theme.Save
import com.glassous.whitz.ui.theme.ZoomIn
import com.glassous.whitz.ui.theme.ZoomOut
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil3.compose.AsyncImage
import com.glassous.whitz.core.files.CsvTableData
import com.glassous.whitz.core.files.isCsvExt
import com.glassous.whitz.core.files.isHtmlExt
import com.glassous.whitz.core.files.isMarkdownExt
import com.glassous.whitz.core.files.isWritableTextExt
import com.glassous.whitz.core.files.parseDelimitedTable
import com.glassous.whitz.core.files.serializeDelimitedTable
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzTextField
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun CsvTableViewerEditor(
    content: String,
    filename: String,
    ext: String = "",
    editable: Boolean = true,
    saving: Boolean = false,
    onSave: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = LocalWhitzColors.current
    val baseTable = remember(content, filename, ext) {
        parseDelimitedTable(content, filename, ext)
    }

    var isEditing by remember(filename) { mutableStateOf(false) }
    var filterQuery by remember(filename) { mutableStateOf("") }
    val draftHeaders = remember { mutableStateListOf<String>() }
    val draftRows = remember { mutableStateListOf<MutableList<String>>() }

    LaunchedEffect(baseTable, isEditing) {
        if (!isEditing) {
            draftHeaders.clear()
            draftHeaders.addAll(baseTable.headers)
            draftRows.clear()
            baseTable.rows.forEach { row -> draftRows.add(row.toMutableList()) }
        }
    }

    val activeHeaders = if (isEditing) draftHeaders.toList() else baseTable.headers
    val activeRows = if (isEditing) draftRows.map { it.toList() } else baseTable.rows

    val indexedVisibleRows = remember(activeRows, filterQuery, isEditing) {
        val q = filterQuery.trim().lowercase()
        activeRows.mapIndexedNotNull { idx, row ->
            if (isEditing || q.isEmpty() || row.any { it.lowercase().contains(q) }) {
                idx to row
            } else {
                null
            }
        }
    }

    val hScroll = rememberScrollState()
    val vScroll = rememberScrollState()

    Column(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Toolbar
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (!isEditing) {
                WhitzTextField(
                    value = filterQuery,
                    onValueChange = { filterQuery = it },
                    placeholder = "筛选表格行...",
                    modifier = Modifier.weight(1f),
                )
            } else {
                Text(
                    text = "${activeRows.size} 行 × ${activeHeaders.size} 列",
                    fontSize = 12.sp,
                    color = colors.fgMuted,
                    modifier = Modifier.weight(1f),
                )
            }

            if (editable) {
                if (!isEditing) {
                    OutlinedButton(
                        onClick = { isEditing = true },
                        shapes = ButtonDefaults.shapesFor(36.dp),
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    ) {
                        Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(15.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("编辑表格", fontSize = 12.sp)
                    }
                } else {
                    TextButton(onClick = {
                        val cols = draftHeaders.size.coerceAtLeast(1)
                        draftRows.add(MutableList(cols) { "" })
                    }) {
                        Text("+ 行", fontSize = 12.sp)
                    }
                    TextButton(onClick = {
                        draftHeaders.add("列 ${draftHeaders.size + 1}")
                        draftRows.forEach { it.add("") }
                    }) {
                        Text("+ 列", fontSize = 12.sp)
                    }
                    TextButton(
                        onClick = { isEditing = false },
                        enabled = !saving,
                    ) {
                        Text("取消", fontSize = 12.sp, color = colors.fgMuted)
                    }
                    Button(
                        onClick = {
                            val csvOut = serializeDelimitedTable(
                                CsvTableData(
                                    delimiter = baseTable.delimiter,
                                    headers = draftHeaders.toList(),
                                    rows = draftRows.map { it.toList() },
                                )
                            )
                            isEditing = false
                            onSave(csvOut)
                        },
                        enabled = !saving,
                        shapes = ButtonDefaults.shapesFor(36.dp),
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                    ) {
                        if (saving) {
                            WhitzLoadingIndicator(size = 13.dp, color = MaterialTheme.colorScheme.onPrimary)
                        } else {
                            Icon(Icons.Default.Save, contentDescription = null, modifier = Modifier.size(14.dp))
                            Spacer(modifier = Modifier.width(4.dp))
                            Text("保存", fontSize = 12.sp)
                        }
                    }
                }
            }
        }

        if (!isEditing) {
            Text(
                text = "共 ${activeRows.size} 行 · ${activeHeaders.size} 列${if (filterQuery.isNotBlank()) "（筛选后 ${indexedVisibleRows.size} 行）" else ""}",
                fontSize = 11.5.sp,
                color = colors.fgFaint,
            )
        }

        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
            shape = RoundedCornerShape(14.dp),
            color = colors.surface,
            border = BorderStroke(0.5.dp, colors.line),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .horizontalScroll(hScroll)
                    .verticalScroll(vScroll),
            ) {
                Column(modifier = Modifier.padding(bottom = 8.dp)) {
                    // Header row
                    Row(
                        modifier = Modifier
                            .background(colors.sidebar)
                            .border(0.5.dp, colors.line),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            modifier = Modifier
                                .width(46.dp)
                                .padding(horizontal = 8.dp, vertical = 10.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("#", fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold, color = colors.fgFaint)
                        }
                        activeHeaders.forEachIndexed { colIdx, header ->
                            Box(
                                modifier = Modifier
                                    .width(144.dp)
                                    .border(0.5.dp, colors.line)
                                    .padding(horizontal = 10.dp, vertical = 9.dp),
                            ) {
                                if (isEditing) {
                                    BasicTextField(
                                        value = draftHeaders.getOrElse(colIdx) { "" },
                                        onValueChange = { v ->
                                            if (colIdx < draftHeaders.size) draftHeaders[colIdx] = v
                                        },
                                        singleLine = true,
                                        textStyle = TextStyle(
                                            fontSize = 12.5.sp,
                                            fontWeight = FontWeight.SemiBold,
                                            color = colors.fg,
                                        ),
                                        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                } else {
                                    Text(
                                        text = header.ifEmpty { "列 ${colIdx + 1}" },
                                        fontSize = 12.5.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = colors.fg,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                            }
                        }
                    }

                    // Data rows
                    indexedVisibleRows.forEach { (origIdx, row) ->
                        Row(
                            modifier = Modifier.background(
                                if (origIdx % 2 == 1) colors.canvas.copy(alpha = 0.55f) else colors.canvas
                            ),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(
                                modifier = Modifier
                                    .width(46.dp)
                                    .padding(horizontal = 6.dp, vertical = 8.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text("${origIdx + 1}", fontSize = 11.sp, color = colors.fgFaint)
                            }
                            activeHeaders.indices.forEach { colIdx ->
                                val cellValue = row.getOrElse(colIdx) { "" }
                                Box(
                                    modifier = Modifier
                                        .width(144.dp)
                                        .border(0.5.dp, colors.line.copy(alpha = 0.65f))
                                        .padding(horizontal = 10.dp, vertical = 8.dp),
                                ) {
                                    if (isEditing) {
                                        BasicTextField(
                                            value = draftRows.getOrNull(origIdx)?.getOrElse(colIdx) { "" } ?: "",
                                            onValueChange = { v ->
                                                val targetRow = draftRows.getOrNull(origIdx) ?: return@BasicTextField
                                                while (targetRow.size <= colIdx) targetRow.add("")
                                                targetRow[colIdx] = v
                                            },
                                            textStyle = TextStyle(fontSize = 12.5.sp, color = colors.fg),
                                            cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                                            modifier = Modifier.fillMaxWidth(),
                                        )
                                    } else {
                                        Text(
                                            text = cellValue,
                                            fontSize = 12.5.sp,
                                            color = colors.fg,
                                            maxLines = 4,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun ThemedHtmlWebView(
    htmlContent: String,
    isDark: Boolean,
    modifier: Modifier = Modifier,
) {
    val preparedHtml = remember(htmlContent, isDark) {
        val bg = if (isDark) "#0f1014" else "#ffffff"
        val fg = if (isDark) "#e5e7eb" else "#111827"
        val themeTag = "<meta name=\"color-scheme\" content=\"${if (isDark) "dark" else "light"}\">" +
            "<style id=\"whitz-theme-sync\">" +
            ":root{color-scheme:${if (isDark) "dark" else "light"};}" +
            "html,body{background-color:$bg;color:$fg;margin:0;padding:12px;box-sizing:border-box;word-break:break-word;}" +
            "</style>" +
            "<script>try{document.documentElement.dataset.theme='${if (isDark) "dark" else "light"}';document.documentElement.classList.toggle('dark',${isDark});}catch(e){}</script>"
        when {
            htmlContent.contains("</head>", ignoreCase = true) -> {
                htmlContent.replaceFirst(Regex("</head>", RegexOption.IGNORE_CASE), "$themeTag</head>")
            }
            htmlContent.contains("<html", ignoreCase = true) -> {
                htmlContent + themeTag
            }
            else -> {
                "<!doctype html><html data-theme=\"${if (isDark) "dark" else "light"}\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">$themeTag</head><body>$htmlContent</body></html>"
            }
        }
    }

    AndroidView(
        modifier = modifier
            .fillMaxSize()
            .clip(RoundedCornerShape(14.dp)),
        factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.useWideViewPort = true
                settings.loadWithOverviewMode = true
            }
        },
        update = { webView ->
            webView.setBackgroundColor(if (isDark) 0xFF0F1014.toInt() else 0xFFFFFFFF.toInt())
            val prevTag = webView.tag as? Pair<*, *>
            val nextTag = preparedHtml to isDark
            if (prevTag != nextTag) {
                webView.tag = nextTag
                webView.loadDataWithBaseURL(null, preparedHtml, "text/html", "utf-8", null)
            }
        },
    )
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun DeliverableDialog(
    state: DeliverablePreviewState,
    onDismiss: () -> Unit,
    onSaveContent: (String) -> Unit,
    onResolveDownloadUrl: (suspend (ConversationFile) -> String?)? = null,
    onLocateMessage: ((ConversationFile) -> Unit)? = null,
) {
    val colors = LocalWhitzColors.current
    val uriHandler = LocalUriHandler.current
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()

    val filename = state.resolvedFile?.filename ?: state.target.filename
    val ext = state.resolvedFile?.ext?.ifBlank { state.target.ext } ?: state.target.ext
    val mimeType = state.resolvedFile?.mimeType?.ifBlank { state.target.mimeType } ?: state.target.mimeType

    val isHtml = isHtmlExt(filename, ext, mimeType)
    val isCsv = isCsvExt(filename, ext, mimeType)
    val isMd = isMarkdownExt(filename, ext, mimeType)
    val canEdit = isWritableTextExt(filename, ext) && !state.truncated && (state.resolvedFile != null || state.target.fileId.isNotEmpty())

    var activeTab by remember(filename, state.target.fileId) {
        mutableStateOf(
            when {
                isHtml -> "preview"
                isCsv -> "table"
                isMd -> "preview"
                else -> "source"
            }
        )
    }
    var editingSource by remember(filename, state.target.fileId) { mutableStateOf(false) }
    var draftSource by remember(state.content) { mutableStateOf(state.content) }
    var copiedTip by remember { mutableStateOf(false) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(colors.canvas)
                .statusBarsPadding()
                .navigationBarsPadding()
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = state.target.title?.ifBlank { null } ?: filename,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = colors.fg,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        text = buildString {
                            append(filename)
                            state.resolvedFile?.qaSnippet?.takeIf { it.isNotBlank() }?.let {
                                append(" · ")
                                append(it)
                            }
                        },
                        fontSize = 11.5.sp,
                        color = colors.fgFaint,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }

                if (state.content.isNotEmpty()) {
                    IconButton(onClick = {
                        clipboard.setText(AnnotatedString(if (editingSource) draftSource else state.content))
                        copiedTip = true
                    }) {
                        Icon(
                            if (copiedTip) Icons.Default.Check else Icons.Default.ContentCopy,
                            contentDescription = "复制内容",
                            tint = if (copiedTip) colors.success else colors.fgMuted,
                        )
                    }
                }

                if (state.resolvedFile?.messageId != null && onLocateMessage != null) {
                    IconButton(onClick = {
                        onLocateMessage(state.resolvedFile)
                        onDismiss()
                    }) {
                        Icon(Icons.Default.MyLocation, contentDescription = "定位问答消息", tint = colors.fgMuted)
                    }
                }

                if (state.resolvedFile != null && onResolveDownloadUrl != null) {
                    IconButton(onClick = {
                        scope.launch {
                            val url = onResolveDownloadUrl(state.resolvedFile)
                            if (!url.isNullOrBlank()) {
                                runCatching { uriHandler.openUri(url) }
                            }
                        }
                    }) {
                        Icon(
                            if (isHtml) Icons.AutoMirrored.Filled.OpenInNew else Icons.Default.Download,
                            contentDescription = if (isHtml) "在浏览器中打开" else "下载文件",
                            tint = colors.fgMuted,
                        )
                    }
                }

                IconButton(onClick = onDismiss) {
                    Icon(Icons.Default.Close, contentDescription = "关闭", tint = colors.fg)
                }
            }

            if (!state.target.summary.isNullOrBlank()) {
                Text(
                    text = state.target.summary,
                    fontSize = 12.5.sp,
                    color = colors.fgMuted,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp, bottom = 8.dp),
                )
            } else {
                Spacer(modifier = Modifier.height(6.dp))
            }

            // Tab selector when multi-view is available
            val tabOptions: List<Pair<String, String>> = when {
                isHtml -> listOf("preview" to "网页预览", "source" to "源码")
                isCsv -> listOf("table" to "表格视图", "source" to "源码")
                isMd -> listOf("preview" to "渲染预览", "source" to "源码")
                else -> emptyList()
            }
            if (tabOptions.isNotEmpty()) {
                WhitzConnectedRadioGroup(
                    options = tabOptions,
                    selected = activeTab,
                    onSelect = {
                        activeTab = it
                        editingSource = false
                    },
                    modifier = Modifier.padding(bottom = 8.dp),
                )
            }

            // Status banners
            if (!state.saveMessage.isNullOrBlank()) {
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = colors.successWeak,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp),
                ) {
                    Text(
                        text = state.saveMessage,
                        fontSize = 12.sp,
                        color = colors.success,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
            }
            if (!state.error.isNullOrBlank()) {
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = colors.dangerWeak,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 8.dp),
                ) {
                    Text(
                        text = state.error,
                        fontSize = 12.sp,
                        color = colors.danger,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
            }

            HorizontalDivider(color = colors.line)
            Spacer(modifier = Modifier.height(10.dp))

            // Main content area
            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                when {
                    state.loading -> {
                        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                            WhitzLoadingIndicator()
                        }
                    }
                    isHtml && activeTab == "preview" -> {
                        ThemedHtmlWebView(
                            htmlContent = state.content,
                            isDark = colors.isDark,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                    isCsv && activeTab == "table" -> {
                        CsvTableViewerEditor(
                            content = state.content,
                            filename = filename,
                            ext = ext,
                            editable = canEdit,
                            saving = state.saving,
                            onSave = onSaveContent,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                    isMd && activeTab == "preview" -> {
                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .verticalScroll(rememberScrollState()),
                        ) {
                            MarkdownText(markdown = state.content)
                        }
                    }
                    else -> {
                        Column(modifier = Modifier.fillMaxSize()) {
                            if (canEdit) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(bottom = 8.dp),
                                    horizontalArrangement = Arrangement.End,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    if (!editingSource) {
                                        OutlinedButton(
                                            onClick = {
                                                draftSource = state.content
                                                editingSource = true
                                            },
                                            shapes = ButtonDefaults.shapesFor(36.dp),
                                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                                        ) {
                                            Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(14.dp))
                                            Spacer(modifier = Modifier.width(4.dp))
                                            Text("编辑源码", fontSize = 12.sp)
                                        }
                                    } else {
                                        TextButton(
                                            onClick = { editingSource = false },
                                            enabled = !state.saving,
                                        ) {
                                            Text("取消", fontSize = 12.sp, color = colors.fgMuted)
                                        }
                                        Spacer(modifier = Modifier.width(6.dp))
                                        Button(
                                            onClick = {
                                                editingSource = false
                                                onSaveContent(draftSource)
                                            },
                                            enabled = !state.saving,
                                            shapes = ButtonDefaults.shapesFor(36.dp),
                                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                                        ) {
                                            if (state.saving) {
                                                WhitzLoadingIndicator(size = 13.dp, color = MaterialTheme.colorScheme.onPrimary)
                                            } else {
                                                Icon(Icons.Default.Save, contentDescription = null, modifier = Modifier.size(14.dp))
                                                Spacer(modifier = Modifier.width(4.dp))
                                                Text("保存", fontSize = 12.sp)
                                            }
                                        }
                                    }
                                }
                            }
                            if (state.truncated) {
                                Text(
                                    "文件内容过长，已截断预览（截断状态下暂不支持在线保存）。",
                                    fontSize = 12.sp,
                                    color = colors.warning,
                                    modifier = Modifier.padding(bottom = 6.dp),
                                )
                            }
                            Surface(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .weight(1f),
                                shape = RoundedCornerShape(14.dp),
                                color = colors.surface,
                                border = BorderStroke(0.5.dp, colors.line),
                            ) {
                                if (editingSource) {
                                    BasicTextField(
                                        value = draftSource,
                                        onValueChange = { draftSource = it },
                                        textStyle = TextStyle(
                                            fontFamily = FontFamily.Monospace,
                                            fontSize = 12.5.sp,
                                            lineHeight = 19.sp,
                                            color = colors.fg,
                                        ),
                                        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                                        modifier = Modifier
                                            .fillMaxSize()
                                            .verticalScroll(rememberScrollState())
                                            .padding(12.dp),
                                    )
                                } else {
                                    Box(
                                        modifier = Modifier
                                            .fillMaxSize()
                                            .verticalScroll(rememberScrollState())
                                            .horizontalScroll(rememberScrollState())
                                            .padding(12.dp),
                                    ) {
                                        Text(
                                            text = state.content,
                                            fontFamily = FontFamily.Monospace,
                                            fontSize = 12.5.sp,
                                            lineHeight = 19.sp,
                                            color = colors.fg,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ImageLightboxDialog(
    state: ImageLightboxState,
    onDismiss: () -> Unit,
    onLocateMessage: ((ConversationFile) -> Unit)? = null,
    onResolveDownloadUrl: (suspend (ConversationFile) -> String?)? = null,
) {
    val uriHandler = LocalUriHandler.current
    val scope = rememberCoroutineScope()
    val images = state.images
    if (images.isEmpty()) return

    val pagerState = rememberPagerState(
        initialPage = state.initialIndex.coerceIn(0, images.lastIndex),
        pageCount = { images.size },
    )
    var scale by remember(pagerState.currentPage) { mutableFloatStateOf(1f) }
    var offset by remember(pagerState.currentPage) { mutableStateOf(Offset.Zero) }

    val currentImage = images.getOrNull(pagerState.currentPage) ?: images.first()

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color(0xF008090C))
                .statusBarsPadding()
                .navigationBarsPadding(),
        ) {
            HorizontalPager(
                state = pagerState,
                userScrollEnabled = scale <= 1.05f,
                modifier = Modifier.fillMaxSize(),
            ) { page ->
                val img = images[page]
                val model = img.previewUrl ?: img.thumbUrl
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .pointerInput(page) {
                            detectTapGestures(
                                onDoubleTap = {
                                    if (scale > 1.1f) {
                                        scale = 1f
                                        offset = Offset.Zero
                                    } else {
                                        scale = 2.4f
                                    }
                                },
                            )
                        }
                        .pointerInput(page) {
                            detectTransformGestures { _, pan, zoom, _ ->
                                val nextScale = (scale * zoom).coerceIn(1f, 4f)
                                scale = nextScale
                                offset = if (nextScale > 1.02f) {
                                    Offset(
                                        x = (offset.x + pan.x).coerceIn(-900f, 900f),
                                        y = (offset.y + pan.y).coerceIn(-900f, 900f),
                                    )
                                } else {
                                    Offset.Zero
                                }
                            }
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    if (!model.isNullOrBlank()) {
                        AsyncImage(
                            model = model,
                            contentDescription = img.filename,
                            contentScale = ContentScale.Fit,
                            modifier = Modifier
                                .fillMaxSize()
                                .graphicsLayer {
                                    if (page == pagerState.currentPage) {
                                        scaleX = scale
                                        scaleY = scale
                                        translationX = offset.x
                                        translationY = offset.y
                                    }
                                },
                        )
                    } else {
                        WhitzLoadingIndicator(color = Color.White)
                    }
                }
            }

            // Top overlay controls
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .align(Alignment.TopCenter)
                    .background(Color(0x99000000))
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Surface(
                    shape = RoundedCornerShape(999.dp),
                    color = Color(0x33FFFFFF),
                ) {
                    Text(
                        text = "${pagerState.currentPage + 1} / ${images.size}",
                        fontSize = 12.sp,
                        color = Color.White,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                    )
                }
                Spacer(modifier = Modifier.width(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = currentImage.filename,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Medium,
                        color = Color.White,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    currentImage.qaSnippet?.takeIf { it.isNotBlank() }?.let { snippet ->
                        Text(
                            text = snippet,
                            fontSize = 11.sp,
                            color = Color(0xB3FFFFFF),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
                IconButton(onClick = {
                    val next = (scale - 0.5f).coerceAtLeast(1f)
                    scale = next
                    if (next <= 1.02f) offset = Offset.Zero
                }) {
                    Icon(Icons.Default.ZoomOut, contentDescription = "缩小", tint = Color.White)
                }
                IconButton(onClick = {
                    scale = (scale + 0.5f).coerceAtMost(4f)
                }) {
                    Icon(Icons.Default.ZoomIn, contentDescription = "放大", tint = Color.White)
                }
                IconButton(onClick = {
                    scale = 1f
                    offset = Offset.Zero
                }) {
                    Icon(Icons.Default.Refresh, contentDescription = "重置缩放", tint = Color.White)
                }
                if (currentImage.messageId != null && onLocateMessage != null) {
                    IconButton(onClick = {
                        onLocateMessage(currentImage)
                        onDismiss()
                    }) {
                        Icon(Icons.Default.MyLocation, contentDescription = "定位问答消息", tint = Color.White)
                    }
                }
                if (onResolveDownloadUrl != null) {
                    IconButton(onClick = {
                        scope.launch {
                            val url = onResolveDownloadUrl(currentImage)
                            if (!url.isNullOrBlank()) {
                                runCatching { uriHandler.openUri(url) }
                            }
                        }
                    }) {
                        Icon(Icons.Default.Download, contentDescription = "下载图片", tint = Color.White)
                    }
                }
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Default.Close, contentDescription = "关闭", tint = Color.White)
                }
            }

            // Bottom thumbnail strip
            if (images.size > 1) {
                LazyRow(
                    modifier = Modifier
                        .fillMaxWidth()
                        .align(Alignment.BottomCenter)
                        .background(Color(0x99000000))
                        .padding(vertical = 10.dp, horizontal = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    itemsIndexed(images, key = { _, f -> f.id }) { idx, img ->
                        val active = idx == pagerState.currentPage
                        val thumb = img.thumbUrl ?: img.previewUrl
                        Box(
                            modifier = Modifier
                                .size(52.dp)
                                .clip(RoundedCornerShape(10.dp))
                                .border(
                                    width = if (active) 2.dp else 1.dp,
                                    color = if (active) Color.White else Color(0x44FFFFFF),
                                    shape = RoundedCornerShape(10.dp),
                                )
                                .clickable {
                                    scope.launch { pagerState.animateScrollToPage(idx) }
                                },
                        ) {
                            if (!thumb.isNullOrBlank()) {
                                AsyncImage(
                                    model = thumb,
                                    contentDescription = img.filename,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.fillMaxSize(),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun CreateTextFileDialog(
    onDismiss: () -> Unit,
    onCreate: (filename: String, content: String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var filename by remember { mutableStateOf("note.md") }
    var content by remember { mutableStateOf("") }
    val presets = listOf(".md", ".txt", ".csv", ".html", ".json")

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = colors.canvas,
        title = { Text("新建工作区文件", fontWeight = FontWeight.SemiBold, color = colors.fg) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                WhitzTextField(
                    value = filename,
                    onValueChange = { filename = it },
                    label = "文件名（含扩展名）",
                    placeholder = "例如 report.md / data.csv / index.html",
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.horizontalScroll(rememberScrollState()),
                ) {
                    presets.forEach { ext ->
                        Surface(
                            shape = RoundedCornerShape(8.dp),
                            color = colors.surface,
                            border = BorderStroke(0.5.dp, colors.line),
                            modifier = Modifier.clickable {
                                val stem = filename.substringBeforeLast('.').ifBlank { "note" }
                                filename = "$stem$ext"
                            },
                        ) {
                            Text(
                                text = ext,
                                fontSize = 11.5.sp,
                                color = colors.fgMuted,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                            )
                        }
                    }
                }
                WhitzTextField(
                    value = content,
                    onValueChange = { content = it },
                    label = "初始内容（可选）",
                    placeholder = "可留空，创建后在编辑器中继续修改",
                    maxLines = 6,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 100.dp),
                )
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
        confirmButton = {
            Button(
                onClick = {
                    val clean = filename.trim()
                    if (clean.isNotEmpty()) {
                        onCreate(clean, content)
                        onDismiss()
                    }
                },
                shapes = ButtonDefaults.shapesFor(36.dp),
                enabled = filename.trim().isNotEmpty(),
            ) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("创建并打开")
            }
        },
    )
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun RenameFileDialog(
    file: ConversationFile,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var nextName by remember(file.id) { mutableStateOf(file.filename) }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = colors.canvas,
        title = { Text("重命名文件", fontWeight = FontWeight.SemiBold, color = colors.fg) },
        text = {
            WhitzTextField(
                value = nextName,
                onValueChange = { nextName = it },
                label = "新文件名",
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
        confirmButton = {
            Button(
                onClick = {
                    val clean = nextName.trim()
                    if (clean.isNotEmpty()) {
                        onConfirm(clean)
                        onDismiss()
                    }
                },
                shapes = ButtonDefaults.shapesFor(36.dp),
                enabled = nextName.trim().isNotEmpty() && nextName.trim() != file.filename,
            ) {
                Text("确认")
            }
        },
    )
}
