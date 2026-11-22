package com.glassous.whitz.feature.chat

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import com.glassous.whitz.ui.theme.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import com.glassous.whitz.ui.theme.Download
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import com.glassous.whitz.ui.theme.Visibility
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearWavyProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.core.files.FileValidator
import com.glassous.whitz.core.files.LibraryController
import com.glassous.whitz.core.files.LibraryUploadStatus
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzTextField

private val CATEGORY_FILTERS = listOf(
    "all" to "全部",
    "document" to "文档",
    "spreadsheet" to "表格",
    "code" to "代码",
    "image" to "图片",
)

private val SOURCE_FILTERS = listOf(
    "all" to "全部",
    "user" to "用户上传",
    "assistant" to "AI 生成",
)

@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
fun LibraryPane(
    controller: LibraryController,
    modifier: Modifier = Modifier,
    bottomPadding: Dp = 24.dp,
) {
    val colors = LocalWhitzColors.current
    val ui by controller.ui.collectAsState()
    val uriHandler = LocalUriHandler.current
    var deleteTarget by remember { mutableStateOf<ConversationFile?>(null) }

    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments(),
    ) { uris ->
        if (uris.isNotEmpty()) {
            controller.uploadUris(uris)
        }
    }

    LaunchedEffect(Unit) {
        if (ui.files.isEmpty() && !ui.loading) {
            controller.loadFiles()
        }
    }

    BackHandler(enabled = ui.previewTarget != null) {
        controller.closePreview()
    }

    Column(modifier = modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = bottomPadding),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item(key = "lib-header") {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(20.dp),
                    color = colors.surface,
                    border = BorderStroke(0.5.dp, colors.line),
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Text(
                                        text = "全部资料",
                                        fontSize = 15.5.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = colors.fg,
                                    )
                                    Box(
                                        modifier = Modifier
                                            .clip(RoundedCornerShape(999.dp))
                                            .background(colors.canvas)
                                            .padding(horizontal = 8.dp, vertical = 2.dp),
                                    ) {
                                        Text(
                                            text = ui.totalCount?.let { "共 $it 项" } ?: "本页 ${ui.files.size} 项",
                                            fontSize = 11.5.sp,
                                            color = colors.fgMuted,
                                        )
                                    }
                                }
                                Spacer(modifier = Modifier.height(3.dp))
                                Text(
                                    text = "统一管理主聊天与旁聊中的上传文件及 AI 产出；所有文件默认全局可参考。",
                                    fontSize = 12.sp,
                                    lineHeight = 17.sp,
                                    color = colors.fgMuted,
                                )
                            }
                        }

                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(
                                onClick = { filePicker.launch(arrayOf("*/*")) },
                                enabled = !ui.uploading,
                                shapes = ButtonDefaults.shapesFor(38.dp),
                                modifier = Modifier.height(38.dp),
                                contentPadding = PaddingValues(horizontal = 14.dp),
                            ) {
                                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text(if (ui.uploading) "上传中…" else "上传文件", fontSize = 13.sp)
                            }
                            OutlinedButton(
                                onClick = { controller.loadFiles() },
                                enabled = !ui.loading,
                                shapes = ButtonDefaults.shapesFor(38.dp),
                                modifier = Modifier.height(38.dp),
                                contentPadding = PaddingValues(horizontal = 14.dp),
                            ) {
                                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(15.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("刷新", fontSize = 13.sp)
                            }
                        }

                        WhitzTextField(
                            value = ui.query,
                            onValueChange = { controller.updateQuery(it) },
                            placeholder = "搜索文件名…",
                            leadingIcon = {
                                Icon(Icons.Default.Search, contentDescription = null, tint = colors.fgFaint, modifier = Modifier.size(18.dp))
                            },
                            modifier = Modifier.fillMaxWidth(),
                        )

                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text("类型", fontSize = 12.sp, color = colors.fgFaint, modifier = Modifier.padding(end = 2.dp))
                                CATEGORY_FILTERS.forEach { (value, label) ->
                                    LibraryFilterChip(
                                        label = label,
                                        selected = ui.category == value,
                                        onClick = { controller.setCategory(value) },
                                    )
                                }
                            }
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text("来源", fontSize = 12.sp, color = colors.fgFaint, modifier = Modifier.padding(end = 2.dp))
                                SOURCE_FILTERS.forEach { (value, label) ->
                                    LibraryFilterChip(
                                        label = label,
                                        selected = ui.source == value,
                                        onClick = { controller.setSource(value) },
                                    )
                                }
                            }
                        }
                    }
                }
            }

            if (ui.uploadItems.isNotEmpty()) {
                items(ui.uploadItems, key = { it.localId }) { item ->
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(14.dp),
                        color = colors.surface,
                        border = BorderStroke(0.5.dp, colors.line),
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = item.filename,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = colors.fg,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = when (item.status) {
                                        LibraryUploadStatus.SIGNING -> "签名中"
                                        LibraryUploadStatus.UPLOADING -> "${item.progress}%"
                                        LibraryUploadStatus.COMPLETING -> "校验索引中"
                                        LibraryUploadStatus.DONE -> "完成"
                                        LibraryUploadStatus.FAILED -> "失败"
                                    },
                                    fontSize = 11.5.sp,
                                    color = if (item.status == LibraryUploadStatus.FAILED) colors.danger else colors.fgFaint,
                                )
                            }
                            if (item.status != LibraryUploadStatus.DONE && item.status != LibraryUploadStatus.FAILED) {
                                Spacer(modifier = Modifier.height(6.dp))
                                if (item.status == LibraryUploadStatus.UPLOADING) {
                                    LinearWavyProgressIndicator(
                                        progress = { item.progress / 100f },
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                } else {
                                    LinearWavyProgressIndicator(modifier = Modifier.fillMaxWidth())
                                }
                            }
                        }
                    }
                }
            }

            if (!ui.error.isNullOrBlank()) {
                item(key = "lib-err") {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(colors.dangerWeak)
                            .padding(horizontal = 12.dp, vertical = 9.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(ui.error!!, color = colors.danger, fontSize = 12.5.sp, modifier = Modifier.weight(1f))
                        IconButton(onClick = { controller.clearFeedback() }, modifier = Modifier.size(22.dp)) {
                            Icon(Icons.Default.Close, contentDescription = "关闭", tint = colors.danger, modifier = Modifier.size(14.dp))
                        }
                    }
                }
            }

            if (!ui.feedback.isNullOrBlank()) {
                item(key = "lib-fb") {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(colors.successWeak)
                            .padding(horizontal = 12.dp, vertical = 9.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(ui.feedback!!, color = colors.success, fontSize = 12.5.sp, modifier = Modifier.weight(1f))
                        IconButton(onClick = { controller.clearFeedback() }, modifier = Modifier.size(22.dp)) {
                            Icon(Icons.Default.Close, contentDescription = "关闭", tint = colors.success, modifier = Modifier.size(14.dp))
                        }
                    }
                }
            }

            if (ui.loading && ui.files.isEmpty()) {
                item(key = "lib-loading") {
                    Box(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 48.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        WhitzLoadingIndicator()
                    }
                }
            } else if (ui.files.isEmpty()) {
                item(key = "lib-empty") {
                    Box(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 48.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("资料库暂无匹配文件", color = colors.fgFaint, fontSize = 13.5.sp)
                    }
                }
            } else {
                items(ui.files, key = { it.id }) { file ->
                    LibraryFileCard(
                        file = file,
                        downloading = ui.downloadingId == file.id,
                        deleting = ui.deletingId == file.id,
                        onPreview = { controller.openPreview(file) },
                        onDownload = {
                            controller.downloadFile(file) { url ->
                                try {
                                    uriHandler.openUri(url)
                                } catch (_: Exception) {
                                }
                            }
                        },
                        onDelete = { deleteTarget = file },
                    )
                }

                val total = ui.totalCount
                if (total != null && total > ui.pageSize) {
                    val maxPage = ((total + ui.pageSize - 1) / ui.pageSize).coerceAtLeast(1)
                    item(key = "lib-pagination") {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            OutlinedButton(
                                onClick = { controller.goToPage(ui.page - 1) },
                                enabled = ui.page > 1 && !ui.loading,
                                shapes = ButtonDefaults.shapesFor(34.dp),
                                modifier = Modifier.height(34.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp),
                            ) { Text("上一页", fontSize = 12.5.sp) }
                            Spacer(modifier = Modifier.width(12.dp))
                            Text("${ui.page} / $maxPage", fontSize = 12.5.sp, color = colors.fgMuted)
                            Spacer(modifier = Modifier.width(12.dp))
                            OutlinedButton(
                                onClick = { controller.goToPage(ui.page + 1) },
                                enabled = ui.page < maxPage && !ui.loading,
                                shapes = ButtonDefaults.shapesFor(34.dp),
                                modifier = Modifier.height(34.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp),
                            ) { Text("下一页", fontSize = 12.5.sp) }
                        }
                    }
                }
            }
        }
    }

    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { if (ui.deletingId == null) deleteTarget = null },
            containerColor = colors.canvas,
            title = { Text("删除文件", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = {
                Text(
                    "确定要从资料库永久删除「${target.filename}」吗？删除后，主聊天和所有旁聊都将无法再参考该文件。",
                    color = colors.fgMuted,
                )
            },
            dismissButton = {
                TextButton(
                    onClick = { deleteTarget = null },
                    enabled = ui.deletingId == null,
                ) { Text("取消") }
            },
            confirmButton = {
                Button(
                    onClick = {
                        controller.deleteFile(target) {
                            deleteTarget = null
                        }
                    },
                    enabled = ui.deletingId == null,
                    shapes = ButtonDefaults.shapesFor(36.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = colors.danger),
                ) {
                    Text(if (ui.deletingId == target.id) "删除中…" else "删除")
                }
            },
        )
    }

    ui.previewTarget?.let { target ->
        FilePreviewDialog(target = target, onDismiss = { controller.closePreview() })
    }
}

@Composable
private fun LibraryFilterChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(if (selected) MaterialTheme.colorScheme.primary else colors.canvas)
            .clickable(onClick = onClick)
            .padding(horizontal = 11.dp, vertical = 5.dp),
    ) {
        Text(
            text = label,
            fontSize = 12.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
            color = if (selected) MaterialTheme.colorScheme.onPrimary else colors.fgMuted,
        )
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
private fun LibraryFileCard(
    file: ConversationFile,
    downloading: Boolean,
    deleting: Boolean,
    onPreview: () -> Unit,
    onDownload: () -> Unit,
    onDelete: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .clickable(onClick = onPreview),
        shape = RoundedCornerShape(16.dp),
        color = colors.surface,
        border = BorderStroke(0.5.dp, colors.line),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.AttachFile, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = file.filename,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Medium,
                        color = colors.fg,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(modifier = Modifier.height(3.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        val sourceLabel = if (file.source == "assistant") "AI 生成" else "用户上传"
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(6.dp))
                                .background(colors.canvas)
                                .padding(horizontal = 6.dp, vertical = 2.dp),
                        ) {
                            Text(sourceLabel, fontSize = 10.5.sp, color = colors.fgMuted)
                        }
                        if (file.indexStatus == "indexing") {
                            Row(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(6.dp))
                                    .background(colors.canvas)
                                    .padding(horizontal = 6.dp, vertical = 2.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                WhitzLoadingIndicator(size = 10.dp)
                                Text("索引中", fontSize = 10.5.sp, color = colors.fgMuted)
                            }
                        }
                        Text(
                            text = "${FileValidator.formatSize(file.sizeBytes)} · ${DateTimeUtils.formatShort(file.createdAt)}",
                            fontSize = 11.5.sp,
                            color = colors.fgFaint,
                        )
                    }
                }
            }

            val sourceConvText = file.conversationTitle?.takeIf { it.isNotBlank() }
                ?: if (file.conversationId != null) "原聊天" else "资料库直传"
            Text(
                text = "来源：$sourceConvText",
                fontSize = 12.sp,
                color = colors.fgMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onPreview, contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)) {
                    Icon(Icons.Default.Visibility, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("预览", fontSize = 12.5.sp)
                }
                TextButton(
                    onClick = onDownload,
                    enabled = !downloading,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    if (downloading) {
                        WhitzLoadingIndicator(size = 14.dp)
                    } else {
                        Icon(Icons.Default.Download, contentDescription = null, modifier = Modifier.size(15.dp))
                    }
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("下载", fontSize = 12.5.sp)
                }
                TextButton(
                    onClick = onDelete,
                    enabled = !deleting,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Icon(Icons.Default.Delete, contentDescription = null, tint = colors.danger, modifier = Modifier.size(15.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("删除", fontSize = 12.5.sp, color = colors.danger)
                }
            }
        }
    }
}
