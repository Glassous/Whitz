package com.glassous.whitz.feature.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil3.compose.AsyncImage
import com.glassous.whitz.core.files.FileValidator
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.ConversationSearchHit
import com.glassous.whitz.core.model.MemoryPendingItem
import com.glassous.whitz.core.model.Message
import com.glassous.whitz.core.model.PendingControl
import com.glassous.whitz.core.model.Plan
import com.glassous.whitz.core.model.ReasoningBlock
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.ui.theme.LocalWhitzColors

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MessageBubble(
    message: Message,
    streaming: Boolean,
    isActiveTurn: Boolean,
    convFiles: List<ConversationFile>,
    onCopy: (String) -> Unit,
    onRegenerate: (String) -> Unit,
    onEditSubmit: (String, String) -> Unit,
    onOpenTurnDetails: (String) -> Unit,
    onOpenFile: (ConversationFile) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val clipboard = LocalClipboardManager.current

    when (message.role) {
        "user" -> {
            var editing by remember(message.id) { mutableStateOf(false) }
            var draft by remember(message.id, message.content) { mutableStateOf(message.content) }

            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.End,
            ) {
                if (editing) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth(0.92f)
                            .clip(RoundedCornerShape(14.dp))
                            .background(colors.surface)
                            .border(1.dp, colors.lineStrong, RoundedCornerShape(14.dp))
                            .padding(12.dp),
                    ) {
                        OutlinedTextField(
                            value = draft,
                            onValueChange = { draft = it },
                            modifier = Modifier.fillMaxWidth(),
                            maxLines = 8,
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                            TextButton(onClick = { editing = false; draft = message.content }) { Text("取消") }
                            Spacer(modifier = Modifier.width(6.dp))
                            Button(
                                onClick = {
                                    editing = false
                                    onEditSubmit(message.id, draft)
                                },
                                enabled = draft.isNotBlank() && !streaming,
                            ) { Text("保存并重发") }
                        }
                    }
                } else {
                    val attachments = message.toolPayload?.attachments.orEmpty()
                    val skills = message.toolPayload?.skills.orEmpty()

                    Column(
                        modifier = Modifier
                            .widthIn(max = 320.dp)
                            .clip(RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp))
                            .background(MaterialTheme.colorScheme.primary)
                            .padding(horizontal = 14.dp, vertical = 10.dp),
                    ) {
                        if (attachments.isNotEmpty()) {
                            FlowRow(
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                verticalArrangement = Arrangement.spacedBy(6.dp),
                                modifier = Modifier.padding(bottom = if (message.content.isNotBlank()) 6.dp else 0.dp),
                            ) {
                                attachments.forEach { att ->
                                    val targetFile = convFiles.firstOrNull { it.id == att.id } ?: ConversationFile(
                                        id = att.id,
                                        filename = att.filename,
                                        ext = att.ext,
                                        category = att.category,
                                        sizeBytes = att.sizeBytes,
                                    )
                                    Row(
                                        modifier = Modifier
                                            .clip(RoundedCornerShape(8.dp))
                                            .background(MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.14f))
                                            .clickable { onOpenFile(targetFile) }
                                            .padding(horizontal = 8.dp, vertical = 4.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Icon(
                                            Icons.Default.AttachFile,
                                            contentDescription = null,
                                            tint = MaterialTheme.colorScheme.onPrimary,
                                            modifier = Modifier.size(13.dp),
                                        )
                                        Spacer(modifier = Modifier.width(4.dp))
                                        Text(
                                            text = att.filename,
                                            color = MaterialTheme.colorScheme.onPrimary,
                                            fontSize = 12.sp,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                    }
                                }
                            }
                        }
                        if (skills.isNotEmpty()) {
                            FlowRow(
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                modifier = Modifier.padding(bottom = 6.dp),
                            ) {
                                skills.forEach { sk ->
                                    Row(
                                        modifier = Modifier
                                            .clip(RoundedCornerShape(6.dp))
                                            .background(MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.16f))
                                            .padding(horizontal = 6.dp, vertical = 2.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Icon(
                                            Icons.Default.AutoAwesome,
                                            contentDescription = null,
                                            tint = MaterialTheme.colorScheme.onPrimary,
                                            modifier = Modifier.size(11.dp),
                                        )
                                        Spacer(modifier = Modifier.width(3.dp))
                                        Text(sk, color = MaterialTheme.colorScheme.onPrimary, fontSize = 11.sp)
                                    }
                                }
                            }
                        }
                        if (message.content.isNotBlank()) {
                            Text(
                                text = message.content,
                                color = MaterialTheme.colorScheme.onPrimary,
                                fontSize = 15.sp,
                                lineHeight = 22.sp,
                            )
                        }
                    }

                    Row(
                        modifier = Modifier.padding(top = 2.dp),
                        horizontalArrangement = Arrangement.End,
                    ) {
                        IconButton(
                            onClick = {
                                clipboard.setText(AnnotatedString(message.content))
                                onCopy(message.content)
                            },
                            modifier = Modifier.size(28.dp),
                        ) {
                            Icon(Icons.Default.ContentCopy, contentDescription = "复制", tint = colors.fgFaint, modifier = Modifier.size(14.dp))
                        }
                        if (!streaming) {
                            IconButton(
                                onClick = { editing = true },
                                modifier = Modifier.size(28.dp),
                            ) {
                                Icon(Icons.Default.Edit, contentDescription = "编辑", tint = colors.fgFaint, modifier = Modifier.size(14.dp))
                            }
                        }
                    }
                }
            }
        }

        "tool" -> {
            val isRunning = message.status == "running"
            val isFailed = message.status == "failed"
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(colors.surface)
                    .border(1.dp, colors.line, RoundedCornerShape(10.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (isRunning) {
                    CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                } else {
                    Icon(
                        imageVector = if (isFailed) Icons.Default.ErrorOutline else Icons.Default.Terminal,
                        contentDescription = null,
                        tint = if (isFailed) colors.danger else colors.success,
                        modifier = Modifier.size(15.dp),
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = message.toolName ?: "tool",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Medium,
                    color = colors.fg,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = when (message.status) {
                        "running" -> "执行中"
                        "failed" -> "失败"
                        else -> "完成"
                    },
                    fontSize = 11.sp,
                    color = if (isFailed) colors.danger else colors.fgFaint,
                )
            }
        }

        else -> {
            // Assistant message
            val hasReasoning = !message.toolPayload?.reasoning.isNullOrEmpty() || !message.toolPayload?.plan?.items.isNullOrEmpty()
            val artifacts = message.toolPayload?.artifacts.orEmpty()

            Column(modifier = Modifier.fillMaxWidth()) {
                if (hasReasoning || (isActiveTurn && streaming)) {
                    Row(
                        modifier = Modifier
                            .padding(bottom = 6.dp)
                            .clip(RoundedCornerShape(16.dp))
                            .background(colors.surface)
                            .border(1.dp, colors.line, RoundedCornerShape(16.dp))
                            .clickable { onOpenTurnDetails(message.id) }
                            .padding(horizontal = 10.dp, vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (isActiveTurn && streaming) {
                            CircularProgressIndicator(modifier = Modifier.size(12.dp), strokeWidth = 1.8.dp)
                        } else {
                            Icon(Icons.Default.Psychology, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(14.dp))
                        }
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = if (isActiveTurn && streaming) "思考与执行中 · 点击查看详情" else "查看推理步骤与计划",
                            fontSize = 12.sp,
                            color = colors.fgMuted,
                        )
                    }
                }

                if (message.content.isNotBlank()) {
                    MarkdownText(
                        markdown = message.content,
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else if (message.status == "streaming") {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
                        CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("正在思考...", fontSize = 13.sp, color = colors.fgMuted)
                    }
                } else if (message.status == "waiting") {
                    Text("等待你的确认...", fontSize = 13.sp, color = colors.warning)
                } else if (message.status == "cancelled") {
                    Text("已停止生成", fontSize = 13.sp, color = colors.fgFaint)
                }

                if (artifacts.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(8.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        artifacts.forEach { art ->
                            val convFile = convFiles.firstOrNull { it.id == art.id } ?: ConversationFile(
                                id = art.id,
                                filename = art.filename,
                                ext = art.ext,
                                mimeType = art.mimeType ?: "",
                                category = art.category,
                                sizeBytes = art.sizeBytes,
                                source = art.source ?: "assistant",
                                previewUrl = art.previewUrl,
                                thumbUrl = art.thumbUrl,
                                previewExpiresAt = art.previewExpiresAt,
                            )
                            Row(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(colors.surface)
                                    .border(1.dp, colors.line, RoundedCornerShape(10.dp))
                                    .clickable { onOpenFile(convFile) }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(Icons.Default.AttachFile, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(15.dp))
                                Spacer(modifier = Modifier.width(6.dp))
                                Column {
                                    Text(art.filename, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = colors.fg)
                                    Text(FileValidator.formatSize(art.sizeBytes), fontSize = 11.sp, color = colors.fgFaint)
                                }
                            }
                        }
                    }
                }

                if (!streaming || !isActiveTurn) {
                    Row(
                        modifier = Modifier.padding(top = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (message.content.isNotBlank()) {
                            IconButton(
                                onClick = {
                                    clipboard.setText(AnnotatedString(message.content))
                                    onCopy(message.content)
                                },
                                modifier = Modifier.size(30.dp),
                            ) {
                                Icon(Icons.Default.ContentCopy, contentDescription = "复制", tint = colors.fgFaint, modifier = Modifier.size(15.dp))
                            }
                        }
                        if (!streaming) {
                            IconButton(
                                onClick = { onRegenerate(message.id) },
                                modifier = Modifier.size(30.dp),
                            ) {
                                Icon(Icons.Default.Refresh, contentDescription = "重新生成", tint = colors.fgFaint, modifier = Modifier.size(15.dp))
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ApprovalCard(
    control: PendingControl,
    onApprove: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(colors.warningWeak)
            .border(1.dp, colors.warning.copy(alpha = 0.4f), RoundedCornerShape(14.dp))
            .padding(14.dp),
    ) {
        Text(
            text = "需要你的授权确认 · ${control.tool ?: "工具调用"}",
            fontWeight = FontWeight.SemiBold,
            fontSize = 14.sp,
            color = colors.fg,
        )
        if (!control.preview.isNullOrBlank()) {
            Spacer(modifier = Modifier.height(8.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 160.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(colors.canvas)
                    .verticalScroll(rememberScrollState())
                    .padding(10.dp),
            ) {
                Text(
                    text = control.preview,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = colors.fg,
                )
            }
        }
        Spacer(modifier = Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = { onApprove("deny") }, modifier = Modifier.weight(1f)) {
                Text("拒绝")
            }
            Button(onClick = { onApprove("once") }, modifier = Modifier.weight(1f)) {
                Text("允许一次")
            }
        }
    }
}

@Composable
fun ClarifyCard(
    control: PendingControl,
    onSubmit: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var answer by remember(control.requestId) { mutableStateOf("") }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(colors.surface)
            .border(1.dp, colors.lineStrong, RoundedCornerShape(14.dp))
            .padding(14.dp),
    ) {
        Text("需要补充信息", fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = colors.fg)
        if (!control.preview.isNullOrBlank()) {
            Spacer(modifier = Modifier.height(6.dp))
            Text(control.preview, fontSize = 13.sp, color = colors.fgMuted)
        }
        Spacer(modifier = Modifier.height(10.dp))
        OutlinedTextField(
            value = answer,
            onValueChange = { answer = it },
            placeholder = { Text("输入你的回答...") },
            modifier = Modifier.fillMaxWidth(),
            maxLines = 4,
        )
        Spacer(modifier = Modifier.height(8.dp))
        Button(
            onClick = { onSubmit(answer) },
            enabled = answer.isNotBlank(),
            modifier = Modifier.align(Alignment.End),
        ) {
            Text("提交")
        }
    }
}

@Composable
fun MemoryPendingCard(
    item: MemoryPendingItem,
    onResolve: (id: String, action: String, content: String?) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var editing by remember(item.id) { mutableStateOf(false) }
    var draft by remember(item.id, item.content) { mutableStateOf(item.content) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(colors.surface)
            .border(1.dp, colors.lineStrong, RoundedCornerShape(12.dp))
            .padding(12.dp),
    ) {
        Text(
            text = "待确认记忆（${item.action}）",
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            color = colors.fg,
        )
        if (!item.reason.isNullOrBlank()) {
            Text(item.reason, fontSize = 12.sp, color = colors.fgMuted)
        }
        Spacer(modifier = Modifier.height(6.dp))
        if (editing) {
            OutlinedTextField(value = draft, onValueChange = { draft = it }, modifier = Modifier.fillMaxWidth())
        } else {
            Text(draft, fontSize = 13.sp, color = colors.fg)
        }
        Spacer(modifier = Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = { editing = !editing }) { Text(if (editing) "完成编辑" else "编辑") }
            Spacer(modifier = Modifier.weight(1f))
            OutlinedButton(onClick = { onResolve(item.id, "reject", null) }) { Text("拒绝") }
            Button(onClick = { onResolve(item.id, "approve", if (draft != item.content) draft else null) }) {
                Text("保存")
            }
        }
    }
}

@Composable
fun SkillPendingCard(
    item: SkillPendingItem,
    onResolve: (id: String, action: String, content: String?) -> Unit,
) {
    val colors = LocalWhitzColors.current
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(colors.surface)
            .border(1.dp, colors.lineStrong, RoundedCornerShape(12.dp))
            .padding(12.dp),
    ) {
        Text(
            text = "待确认技能：${item.name}（${item.action}）",
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            color = colors.fg,
        )
        if (!item.description.isNullOrBlank()) {
            Text(item.description, fontSize = 12.sp, color = colors.fgMuted)
        }
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = item.content.take(240),
            fontSize = 12.sp,
            fontFamily = FontFamily.Monospace,
            color = colors.fgMuted,
            maxLines = 5,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(modifier = Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Spacer(modifier = Modifier.weight(1f))
            OutlinedButton(onClick = { onResolve(item.id, "reject", null) }) { Text("拒绝") }
            Button(onClick = { onResolve(item.id, "approve", null) }) { Text("批准") }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TaskDetailSheet(
    plan: Plan?,
    reasoning: List<ReasoningBlock>,
    files: List<ConversationFile>,
    onOpenFile: (ConversationFile) -> Unit,
    onDeleteFile: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    var tab by remember { mutableIntStateOf(0) }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = colors.canvas,
    ) {
        Column(modifier = Modifier.fillMaxWidth().heightIn(min = 320.dp, max = 560.dp)) {
            TabRow(selectedTabIndex = tab, containerColor = colors.canvas) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("执行步骤") })
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("对话文件 (${files.size})") })
            }

            if (tab == 0) {
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    val planItems = plan?.items.orEmpty()
                    if (planItems.isNotEmpty()) {
                        item {
                            Text("任务计划", fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = colors.fg)
                            Spacer(modifier = Modifier.height(6.dp))
                            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                planItems.forEach { p ->
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Icon(
                                            imageVector = if (p.status == "completed") Icons.Default.CheckCircle else Icons.Default.AutoAwesome,
                                            contentDescription = null,
                                            tint = if (p.status == "completed") colors.success else colors.fgMuted,
                                            modifier = Modifier.size(16.dp),
                                        )
                                        Spacer(modifier = Modifier.width(8.dp))
                                        Text(p.content, fontSize = 13.sp, color = colors.fg)
                                    }
                                }
                            }
                            HorizontalDivider(modifier = Modifier.padding(top = 12.dp), color = colors.line)
                        }
                    }

                    if (reasoning.isEmpty()) {
                        item {
                            Text("暂无详细推理步骤", fontSize = 13.sp, color = colors.fgFaint)
                        }
                    } else {
                        items(reasoning) { blk ->
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(colors.surface)
                                    .padding(12.dp),
                            ) {
                                if (blk.title.isNotBlank() || blk.step != null) {
                                    Text(
                                        text = blk.title.ifBlank { "步骤 ${blk.step}" },
                                        fontWeight = FontWeight.SemiBold,
                                        fontSize = 13.sp,
                                        color = colors.fg,
                                    )
                                    Spacer(modifier = Modifier.height(4.dp))
                                }
                                if (blk.text.isNotBlank()) {
                                    Text(blk.text, fontSize = 12.sp, color = colors.fgMuted)
                                }
                                if (blk.content.isNotBlank()) {
                                    Spacer(modifier = Modifier.height(4.dp))
                                    Text(blk.content, fontSize = 13.sp, color = colors.fg)
                                }
                                blk.tools.forEach { t ->
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(6.dp))
                                            .background(colors.canvas)
                                            .padding(8.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Icon(Icons.Default.Terminal, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(14.dp))
                                        Spacer(modifier = Modifier.width(6.dp))
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(t.name, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = colors.fg)
                                            if (!t.args.isNullOrBlank()) {
                                                Text(t.args, fontSize = 11.sp, color = colors.fgFaint, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                            }
                                        }
                                        Text(
                                            text = t.status ?: "",
                                            fontSize = 11.sp,
                                            color = if (t.status == "failed") colors.danger else colors.success,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                if (files.isEmpty()) {
                    Box(modifier = Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                        Text("当前对话暂无文件", color = colors.fgFaint, fontSize = 13.sp)
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(files, key = { it.id }) { f ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(colors.surface)
                                    .clickable { onOpenFile(f) }
                                    .padding(horizontal = 12.dp, vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(Icons.Default.AttachFile, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(18.dp))
                                Spacer(modifier = Modifier.width(10.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(f.filename, fontSize = 14.sp, color = colors.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text("${FileValidator.formatSize(f.sizeBytes)} · ${f.source}", fontSize = 11.sp, color = colors.fgFaint)
                                }
                                IconButton(onClick = { onDeleteFile(f.id) }, modifier = Modifier.size(32.dp)) {
                                    Icon(Icons.Default.Delete, contentDescription = "删除文件", tint = colors.fgFaint, modifier = Modifier.size(16.dp))
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
fun SearchDialog(
    results: List<ConversationSearchHit>,
    searching: Boolean,
    onQueryChange: (String) -> Unit,
    onSelectConversation: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    var query by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("搜索对话") },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = query,
                    onValueChange = {
                        query = it
                        onQueryChange(it)
                    },
                    placeholder = { Text("输入标题或消息关键词...") },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(10.dp))
                if (searching) {
                    Box(modifier = Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(modifier = Modifier.size(22.dp))
                    }
                } else if (query.isNotBlank() && results.isEmpty()) {
                    Text("没有找到匹配的对话", fontSize = 13.sp, color = colors.fgFaint, modifier = Modifier.padding(8.dp))
                } else {
                    LazyColumn(modifier = Modifier.heightIn(max = 320.dp)) {
                        items(results) { hit ->
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .clickable {
                                        onSelectConversation(hit.conversationId)
                                        onDismiss()
                                    }
                                    .padding(10.dp),
                            ) {
                                Text(hit.conversationTitle.ifBlank { "无标题对话" }, fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                                if (hit.snippet.isNotBlank()) {
                                    Text(hit.snippet, fontSize = 12.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("关闭") }
        },
    )
}

@Composable
fun SkillPickerDialog(
    skills: List<SkillItem>,
    selectedNames: List<String>,
    onToggle: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("选择本轮附加技能") },
        text = {
            if (skills.isEmpty()) {
                Text("暂无可用技能，请在设置 -> 技能管理中启用或创建技能。", fontSize = 13.sp, color = colors.fgMuted)
            } else {
                LazyColumn(modifier = Modifier.heightIn(max = 340.dp)) {
                    items(skills, key = { it.name }) { sk ->
                        val checked = sk.name in selectedNames
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { onToggle(sk.name) }
                                .padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(checked = checked, onCheckedChange = { onToggle(sk.name) })
                            Column(modifier = Modifier.weight(1f)) {
                                Text(sk.title ?: sk.name, fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                                if (sk.description.isNotBlank()) {
                                    Text(sk.description, fontSize = 12.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = onDismiss) { Text("完成") }
        },
    )
}

@Composable
fun LibraryAttachDialog(
    fetchLibrary: suspend (String) -> List<ConversationFile>,
    onAttach: (List<String>) -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    var query by remember { mutableStateOf("") }
    var items by remember { mutableStateOf<List<ConversationFile>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    val selectedIds = remember { mutableStateListOf<String>() }

    LaunchedEffect(query) {
        loading = true
        items = fetchLibrary(query)
        loading = false
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("从文件库选择") },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    placeholder = { Text("搜索文件名...") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(8.dp))
                if (loading) {
                    Box(modifier = Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(modifier = Modifier.size(22.dp))
                    }
                } else if (items.isEmpty()) {
                    Text("文件库暂无匹配文件", fontSize = 13.sp, color = colors.fgFaint, modifier = Modifier.padding(8.dp))
                } else {
                    LazyColumn(modifier = Modifier.heightIn(max = 300.dp)) {
                        items(items, key = { it.id }) { f ->
                            val checked = f.id in selectedIds
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        if (checked) selectedIds.remove(f.id) else selectedIds.add(f.id)
                                    }
                                    .padding(vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Checkbox(
                                    checked = checked,
                                    onCheckedChange = { if (checked) selectedIds.remove(f.id) else selectedIds.add(f.id) },
                                )
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(f.filename, fontSize = 13.sp, color = colors.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(FileValidator.formatSize(f.sizeBytes), fontSize = 11.sp, color = colors.fgFaint)
                                }
                            }
                        }
                    }
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
        confirmButton = {
            Button(
                onClick = {
                    onAttach(selectedIds.toList())
                    onDismiss()
                },
                enabled = selectedIds.isNotEmpty(),
            ) {
                Text("附加 (${selectedIds.size})")
            }
        },
    )
}

@Composable
fun FilePreviewDialog(
    target: PreviewTarget,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val uriHandler = LocalUriHandler.current

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(colors.canvas)
                .padding(16.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = target.file.filename,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 16.sp,
                    color = colors.fg,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (!target.previewUrl.isNullOrBlank()) {
                    IconButton(onClick = {
                        try {
                            uriHandler.openUri(target.previewUrl)
                        } catch (_: Exception) {
                        }
                    }) {
                        Icon(Icons.Default.Download, contentDescription = "打开/下载", tint = colors.fg)
                    }
                }
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Default.Close, contentDescription = "关闭", tint = colors.fg)
                }
            }
            HorizontalDivider(color = colors.line)
            Spacer(modifier = Modifier.height(12.dp))

            when {
                target.loading -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                }
                !target.error.isNullOrBlank() -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text(target.error, color = colors.danger)
                    }
                }
                target.file.category == "image" && !target.previewUrl.isNullOrBlank() -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        AsyncImage(
                            model = target.previewUrl,
                            contentDescription = target.file.filename,
                            contentScale = ContentScale.Fit,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }
                target.content != null -> {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .verticalScroll(rememberScrollState())
                            .horizontalScroll(rememberScrollState()),
                    ) {
                        if (target.truncated) {
                            Text("内容过长，已截断显示", fontSize = 12.sp, color = colors.warning)
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                        Text(
                            text = target.content,
                            fontFamily = FontFamily.Monospace,
                            fontSize = 12.sp,
                            color = colors.fg,
                        )
                    }
                }
                !target.previewUrl.isNullOrBlank() -> {
                    Column(
                        modifier = Modifier.fillMaxSize(),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text("该文件类型暂不支持内嵌预览", color = colors.fgMuted, fontSize = 14.sp)
                        Spacer(modifier = Modifier.height(12.dp))
                        Button(onClick = {
                            try {
                                uriHandler.openUri(target.previewUrl)
                            } catch (_: Exception) {
                            }
                        }) {
                            Icon(Icons.Default.Download, contentDescription = null)
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("在浏览器中下载 / 打开")
                        }
                    }
                }
            }
        }
    }
}
