package com.glassous.whitz.feature.chat

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
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
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
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
import com.glassous.whitz.core.model.ReasoningTool
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzTextField

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun MessageBubble(
    message: Message,
    streaming: Boolean,
    isActiveTurn: Boolean,
    isSelectedTurn: Boolean = false,
    liveLabel: String? = null,
    turnPlan: Plan? = null,
    turnReasoning: List<ReasoningBlock>? = null,
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

            BackHandler(enabled = editing) {
                editing = false
                draft = message.content
            }

            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.End,
            ) {
                if (editing) {
                    Surface(
                        modifier = Modifier.fillMaxWidth(0.92f),
                        shape = RoundedCornerShape(18.dp),
                        color = colors.surface,
                        border = BorderStroke(1.dp, colors.lineStrong),
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            WhitzTextField(
                                value = draft,
                                onValueChange = { draft = it },
                                singleLine = false,
                                maxLines = 8,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            Spacer(modifier = Modifier.height(10.dp))
                            Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                                TextButton(onClick = { editing = false; draft = message.content }) {
                                    Text("取消", color = colors.fgMuted)
                                }
                                Spacer(modifier = Modifier.width(6.dp))
                                Button(
                                    onClick = {
                                        editing = false
                                        onEditSubmit(message.id, draft)
                                    },
                                    shapes = ButtonDefaults.shapesFor(36.dp),
                                    enabled = draft.isNotBlank() && !streaming,
                                    modifier = Modifier.height(36.dp),
                                    contentPadding = PaddingValues(horizontal = 14.dp),
                                ) { Text("保存并重发", fontSize = 13.sp) }
                            }
                        }
                    }
                } else {
                    val attachments = message.toolPayload?.attachments.orEmpty()
                    val skills = message.toolPayload?.skills.orEmpty()

                    Column(
                        modifier = Modifier
                            .widthIn(max = 320.dp)
                            .clip(RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp))
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

        "tool" -> Unit

        else -> {
            val effectiveReasoning = turnReasoning ?: message.toolPayload?.reasoning.orEmpty()
            val effectivePlan = turnPlan ?: message.toolPayload?.plan ?: derivePlanFromReasoning(effectiveReasoning)
            val isLive = isActiveTurn && streaming
            val isFailureOrCancelled = !isLive && (message.status == "failed" || message.status == "cancelled")
            val stepsCount = computeStepsCount(effectivePlan, effectiveReasoning)
            val hasStepsOrReasoning = effectiveReasoning.isNotEmpty() || !effectivePlan?.items.isNullOrEmpty()
            val artifacts = message.toolPayload?.artifacts.orEmpty()

            Column(modifier = Modifier.fillMaxWidth()) {
                if (hasStepsOrReasoning || isLive) {
                    val primaryColor = MaterialTheme.colorScheme.primary
                    Row(
                        modifier = Modifier
                            .padding(bottom = 10.dp)
                            .clip(RoundedCornerShape(999.dp))
                            .background(if (isSelectedTurn) primaryColor.copy(alpha = 0.14f) else colors.surface)
                            .clickable { onOpenTurnDetails(message.id) }
                            .padding(horizontal = 13.dp, vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (isLive) {
                            WhitzLoadingIndicator(size = 14.dp)
                            Spacer(modifier = Modifier.width(6.dp))
                        }
                        Text(
                            text = if (isLive) (liveLabel ?: "正在思考…") else "步骤查看",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Medium,
                            color = if (isSelectedTurn) primaryColor else colors.fgMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                        if (!isLive && stepsCount > 0) {
                            Text(
                                text = " · $stepsCount",
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium,
                                color = if (isSelectedTurn) primaryColor.copy(alpha = 0.8f) else colors.fgFaint,
                            )
                        }
                        Spacer(modifier = Modifier.width(4.dp))
                        Icon(
                            Icons.Default.ChevronRight,
                            contentDescription = null,
                            tint = if (isSelectedTurn) primaryColor.copy(alpha = 0.8f) else colors.fgFaint,
                            modifier = Modifier.size(14.dp),
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
                        WhitzLoadingIndicator(size = 16.dp)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(liveLabel ?: "正在思考...", fontSize = 13.5.sp, color = colors.fgMuted)
                    }
                } else if (message.status == "waiting") {
                    Text("等待你的确认...", fontSize = 13.5.sp, color = colors.warning)
                }

                if (artifacts.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(10.dp))
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
                                    .clip(RoundedCornerShape(12.dp))
                                    .background(colors.surface)
                                    .border(1.dp, colors.line, RoundedCornerShape(12.dp))
                                    .clickable { onOpenFile(convFile) }
                                    .padding(horizontal = 11.dp, vertical = 8.dp),
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

                if (isFailureOrCancelled) {
                    Spacer(modifier = Modifier.height(10.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text(
                            text = if (message.status == "failed") "回复失败，请重试。" else "已停止生成",
                            fontSize = 12.5.sp,
                            color = if (message.status == "failed") colors.danger else colors.fgFaint,
                        )
                        Button(
                            onClick = { onRegenerate(message.id) },
                            enabled = !streaming,
                            shapes = ButtonDefaults.shapesFor(28.dp),
                            modifier = Modifier.height(28.dp),
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp),
                        ) {
                            Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(13.dp))
                            Spacer(modifier = Modifier.width(4.dp))
                            Text("重试", fontSize = 12.sp)
                        }
                    }
                }

                if (!isLive && (message.content.isNotBlank() || isFailureOrCancelled)) {
                    Row(
                        modifier = Modifier.padding(top = 6.dp),
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

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun ApprovalCard(
    control: PendingControl,
    onApprove: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        color = colors.warningWeak,
        border = BorderStroke(1.dp, colors.warning.copy(alpha = 0.35f)),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
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
                        .clip(RoundedCornerShape(10.dp))
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
                OutlinedButton(
                    onClick = { onApprove("deny") },
                    shapes = ButtonDefaults.shapesFor(40.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Text("拒绝")
                }
                Button(
                    onClick = { onApprove("once") },
                    shapes = ButtonDefaults.shapesFor(40.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Text("允许一次")
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun ClarifyCard(
    control: PendingControl,
    onSubmit: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var answer by remember(control.requestId) { mutableStateOf("") }
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        color = colors.surface,
        border = BorderStroke(1.dp, colors.lineStrong),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text("需要补充信息", fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = colors.fg)
            if (!control.preview.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(control.preview, fontSize = 13.sp, color = colors.fgMuted)
            }
            Spacer(modifier = Modifier.height(10.dp))
            WhitzTextField(
                value = answer,
                onValueChange = { answer = it },
                placeholder = "输入你的回答...",
                singleLine = false,
                maxLines = 4,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.height(10.dp))
            Button(
                onClick = { onSubmit(answer) },
                shapes = ButtonDefaults.shapesFor(36.dp),
                enabled = answer.isNotBlank(),
                modifier = Modifier.align(Alignment.End),
            ) {
                Text("提交")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun MemoryPendingCard(
    item: MemoryPendingItem,
    onResolve: (id: String, action: String, content: String?) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var editing by remember(item.id) { mutableStateOf(false) }
    var draft by remember(item.id, item.content) { mutableStateOf(item.content) }

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = colors.surface,
        border = BorderStroke(1.dp, colors.lineStrong),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(
                text = "待确认记忆（${item.action}）",
                fontSize = 13.5.sp,
                fontWeight = FontWeight.SemiBold,
                color = colors.fg,
            )
            if (!item.reason.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(item.reason, fontSize = 12.sp, color = colors.fgMuted)
            }
            Spacer(modifier = Modifier.height(8.dp))
            if (editing) {
                WhitzTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    singleLine = false,
                    maxLines = 4,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                Text(draft, fontSize = 13.sp, color = colors.fg)
            }
            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { editing = !editing }) { Text(if (editing) "完成编辑" else "编辑") }
                Spacer(modifier = Modifier.weight(1f))
                OutlinedButton(
                    onClick = { onResolve(item.id, "reject", null) },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text("拒绝") }
                Button(
                    onClick = { onResolve(item.id, "approve", if (draft != item.content) draft else null) },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text("保存") }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SkillPendingCard(
    item: SkillPendingItem,
    onResolve: (id: String, action: String, content: String?) -> Unit,
) {
    val colors = LocalWhitzColors.current
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = colors.surface,
        border = BorderStroke(1.dp, colors.lineStrong),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(
                text = "待确认技能：${item.name}（${item.action}）",
                fontSize = 13.5.sp,
                fontWeight = FontWeight.SemiBold,
                color = colors.fg,
            )
            if (!item.description.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(2.dp))
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
            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Spacer(modifier = Modifier.weight(1f))
                OutlinedButton(
                    onClick = { onResolve(item.id, "reject", null) },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text("拒绝") }
                Button(
                    onClick = { onResolve(item.id, "approve", null) },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text("批准") }
            }
        }
    }
}

@Composable
fun TaskStepsPane(
    plan: Plan?,
    reasoning: List<ReasoningBlock>,
    modifier: Modifier = Modifier,
    streaming: Boolean = false,
    runningTool: String? = null,
    turnKey: String = "",
    bottomPadding: Dp = 24.dp,
) {
    val colors = LocalWhitzColors.current
    val sections = remember(plan, reasoning) { partitionPlanSteps(plan, reasoning) }
    val toggledSteps = remember(turnKey) { mutableStateMapOf<String, Boolean>() }

    LaunchedEffect(streaming) {
        if (streaming) toggledSteps.clear()
    }

    LazyColumn(
        modifier = modifier,
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = bottomPadding),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (sections.items.isNotEmpty() && sections.planningBlocks.isNotEmpty()) {
            item(key = "sec-planning-header") {
                Text("规划", fontWeight = FontWeight.Medium, fontSize = 13.5.sp, color = colors.fgMuted)
            }
            items(sections.planningBlocks.size, key = { "planning-$it" }) { idx ->
                ReasoningBlockView(block = sections.planningBlocks[idx])
            }
        }

        if (sections.steps.isNotEmpty()) {
            item(key = "sec-steps-header") {
                Column(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("执行步骤", fontWeight = FontWeight.Medium, fontSize = 13.5.sp, color = colors.fgMuted)
                        Text(
                            "${sections.doneCount} / ${sections.items.size}",
                            fontSize = 12.5.sp,
                            color = colors.fgFaint,
                        )
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    LinearProgressIndicator(
                        progress = { sections.progressPct.coerceIn(0f, 1f) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(4.dp)
                            .clip(RoundedCornerShape(999.dp)),
                        color = MaterialTheme.colorScheme.primary,
                        trackColor = colors.surface,
                    )
                }
            }
            items(sections.steps, key = { "step-${it.key}-${it.index}" }) { step ->
                val expanded = (toggledSteps[step.key] ?: (step.item.status == "in_progress")) && step.blocks.isNotEmpty()
                PlanStepCard(
                    step = step,
                    expanded = expanded,
                    onToggle = {
                        if (step.blocks.isNotEmpty()) {
                            toggledSteps[step.key] = !expanded
                        }
                    },
                )
            }
        }

        if (sections.items.isNotEmpty() && sections.summaryBlocks.isNotEmpty()) {
            item(key = "sec-summary-header") {
                Text("总结", fontWeight = FontWeight.Medium, fontSize = 13.5.sp, color = colors.fgMuted)
            }
            items(sections.summaryBlocks.size, key = { "summary-$it" }) { idx ->
                ReasoningBlockView(block = sections.summaryBlocks[idx])
            }
        }

        if (sections.looseBlocks.isNotEmpty()) {
            item(key = "sec-loose-header") {
                Text(
                    text = if (sections.items.isNotEmpty()) "其他记录" else "思考与执行",
                    fontWeight = FontWeight.Medium,
                    fontSize = 13.5.sp,
                    color = colors.fgMuted,
                )
            }
            items(sections.looseBlocks.size, key = { "loose-$it" }) { idx ->
                ReasoningBlockView(block = sections.looseBlocks[idx])
            }
        }

        if (streaming && !runningTool.isNullOrBlank()) {
            item(key = "sec-running-tool") {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(14.dp))
                        .background(colors.surface)
                        .border(0.5.dp, colors.line, RoundedCornerShape(14.dp))
                        .padding(horizontal = 14.dp, vertical = 11.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    WhitzLoadingIndicator(size = 14.dp)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = "正在调用 ${toolDisplayName(runningTool)}",
                        fontSize = 13.sp,
                        color = colors.fgMuted,
                    )
                }
            }
        }

        if (sections.items.isEmpty() && reasoning.isEmpty() && !streaming) {
            item(key = "sec-empty") {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "暂无运行详情。\n助理处理多步骤任务或读取文件时，这里会按步骤显示思考与工具调用。",
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = colors.fgFaint,
                    )
                }
            }
        }
    }
}

@Composable
fun TaskFilesPane(
    files: List<ConversationFile>,
    onOpenFile: (ConversationFile) -> Unit,
    onDeleteFile: (String) -> Unit,
    modifier: Modifier = Modifier,
    bottomPadding: Dp = 24.dp,
) {
    val colors = LocalWhitzColors.current
    if (files.isEmpty()) {
        Box(modifier = modifier.padding(32.dp), contentAlignment = Alignment.Center) {
            Text("当前对话暂无文件", color = colors.fgFaint, fontSize = 13.5.sp)
        }
    } else {
        LazyColumn(
            modifier = modifier,
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = bottomPadding),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(files, key = { it.id }) { f ->
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .clickable { onOpenFile(f) },
                    shape = RoundedCornerShape(16.dp),
                    color = colors.surface,
                    border = BorderStroke(0.5.dp, colors.line),
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.AttachFile, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(18.dp))
                        Spacer(modifier = Modifier.width(10.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(f.filename, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = colors.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("${FileValidator.formatSize(f.sizeBytes)} · ${f.source}", fontSize = 12.sp, color = colors.fgFaint)
                        }
                        IconButton(onClick = { onDeleteFile(f.id) }, modifier = Modifier.size(32.dp)) {
                            Icon(Icons.Default.Delete, contentDescription = "删除文件", tint = colors.danger, modifier = Modifier.size(17.dp))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PlanStepCard(
    step: ResolvedStepItem,
    expanded: Boolean,
    onToggle: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val hasBlocks = step.blocks.isNotEmpty()
    val rotation by animateFloatAsState(
        targetValue = if (expanded) 90f else 0f,
        label = "stepChevronRotation",
    )
    val calls = step.blocks.size
    val toolCount = step.blocks.sumOf { it.tools.size }
    val meta = listOfNotNull(
        if (calls > 0) "$calls 段思考" else null,
        if (toolCount > 0) "$toolCount 个操作" else null,
    ).joinToString(" · ")

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(colors.surface.copy(alpha = 0.78f))
            .border(1.dp, colors.line, RoundedCornerShape(14.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .let { if (hasBlocks) it.clickable(onClick = onToggle) else it }
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Box(
                modifier = Modifier.padding(top = 2.dp).size(16.dp),
                contentAlignment = Alignment.Center,
            ) {
                when (step.item.status) {
                    "in_progress" -> WhitzLoadingIndicator(size = 14.dp)
                    "completed" -> Box(
                        modifier = Modifier
                            .size(16.dp)
                            .clip(CircleShape)
                            .background(colors.success.copy(alpha = 0.16f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Default.Check,
                            contentDescription = null,
                            tint = colors.success,
                            modifier = Modifier.size(11.dp),
                        )
                    }
                    else -> Box(
                        modifier = Modifier
                            .size(12.dp)
                            .clip(CircleShape)
                            .border(1.5.dp, colors.lineStrong, CircleShape),
                    )
                }
            }
            Spacer(modifier = Modifier.width(8.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = "步骤 ${step.index}",
                        fontSize = 11.5.sp,
                        fontWeight = FontWeight.Medium,
                        color = colors.fgFaint,
                    )
                    Text(
                        text = step.item.content,
                        fontSize = 13.5.sp,
                        fontWeight = if (step.item.status == "in_progress") FontWeight.Medium else FontWeight.Normal,
                        color = when (step.item.status) {
                            "completed" -> colors.fgFaint
                            "in_progress" -> colors.fg
                            else -> colors.fgMuted
                        },
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = buildString {
                        append(planStatusLabel(step.item.status))
                        if (!expanded && meta.isNotEmpty()) append(" · $meta")
                    },
                    fontSize = 11.5.sp,
                    color = colors.fgFaint,
                )
            }
            if (hasBlocks) {
                Icon(
                    Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = colors.fgFaint,
                    modifier = Modifier
                        .padding(top = 2.dp)
                        .size(16.dp)
                        .rotate(rotation),
                )
            }
        }

        AnimatedVisibility(visible = expanded && hasBlocks) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 12.dp, end = 12.dp, bottom = 10.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                step.blocks.forEach { block ->
                    ReasoningBlockView(block = block)
                }
            }
        }
    }
}

@Composable
private fun ReasoningBlockView(block: ReasoningBlock) {
    val colors = LocalWhitzColors.current
    var contentExpanded by remember(block) { mutableStateOf(false) }
    var textExpanded by remember(block) { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (block.content.isNotBlank()) {
            val isLong = block.content.length > 180 || block.content.lines().count { it.isNotBlank() } > 3
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(colors.surface)
                    .padding(horizontal = 10.dp, vertical = 8.dp),
            ) {
                Text("过程回复", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = colors.fgFaint)
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = block.content,
                    fontSize = 13.sp,
                    lineHeight = 19.sp,
                    color = colors.fgMuted,
                    maxLines = if (isLong && !contentExpanded) 3 else Int.MAX_VALUE,
                    overflow = TextOverflow.Ellipsis,
                )
                if (isLong) {
                    Text(
                        text = if (contentExpanded) "收起" else "展开全文",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .padding(top = 4.dp)
                            .clickable { contentExpanded = !contentExpanded },
                    )
                }
            }
        }

        if (block.text.isNotBlank()) {
            val isLong = block.text.length > 180 || block.text.lines().count { it.isNotBlank() } > 3
            Column(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = block.text,
                    fontSize = 13.sp,
                    lineHeight = 19.sp,
                    color = colors.fgMuted,
                    maxLines = if (isLong && !textExpanded) 3 else Int.MAX_VALUE,
                    overflow = TextOverflow.Ellipsis,
                )
                if (isLong) {
                    Text(
                        text = if (textExpanded) "收起" else "展开全文",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .padding(top = 4.dp)
                            .clickable { textExpanded = !textExpanded },
                    )
                }
            }
        }

        block.tools.forEach { tool ->
            ToolCallRow(tool = tool)
        }
    }
}

@Composable
private fun ToolCallRow(tool: ReasoningTool) {
    val colors = LocalWhitzColors.current
    val uriHandler = LocalUriHandler.current
    var open by remember(tool) { mutableStateOf(false) }
    val rotation by animateFloatAsState(
        targetValue = if (open) 90f else 0f,
        label = "toolChevronRotation",
    )
    val summary = remember(tool) { formatToolSummary(tool) }
    val collapsedTitles = remember(tool) {
        if (isWebTool(tool)) parseWebSearchItems(tool).mapNotNull { it.title.ifBlank { null } }.take(3) else emptyList()
    }
    val isFailed = tool.status == "failed" || !tool.error.isNullOrBlank()
    val durationText = tool.durationMs?.let { ms ->
        if (ms >= 1000.0) String.format("%.1fs", ms / 1000.0) else "${ms.toInt()}ms"
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(colors.canvas.copy(alpha = 0.85f))
            .border(1.dp, colors.line, RoundedCornerShape(10.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { open = !open }
                .padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (tool.status == "running") {
                WhitzLoadingIndicator(size = 13.dp)
            } else {
                Icon(
                    imageVector = if (isFailed) Icons.Default.ErrorOutline else Icons.Default.Build,
                    contentDescription = null,
                    tint = if (isFailed) colors.danger else colors.fgFaint,
                    modifier = Modifier.size(13.dp),
                )
            }
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                text = toolDisplayName(tool.name),
                fontSize = 12.5.sp,
                fontWeight = FontWeight.Medium,
                color = if (isFailed) colors.danger else colors.fgMuted,
            )
            if (summary.isNotBlank()) {
                Spacer(modifier = Modifier.width(6.dp))
                Text(
                    text = summary,
                    fontSize = 12.sp,
                    color = colors.fgFaint,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            } else {
                Spacer(modifier = Modifier.weight(1f))
            }
            if (!durationText.isNullOrBlank()) {
                Text(
                    text = durationText,
                    fontSize = 11.sp,
                    color = colors.fgFaint,
                    modifier = Modifier.padding(end = 4.dp),
                )
            }
            Icon(
                Icons.Default.ChevronRight,
                contentDescription = null,
                tint = colors.fgFaint,
                modifier = Modifier.size(14.dp).rotate(rotation),
            )
        }

        if (!open && collapsedTitles.isNotEmpty()) {
            Column(
                modifier = Modifier.padding(start = 10.dp, end = 10.dp, bottom = 8.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                collapsedTitles.forEach { title ->
                    Text(
                        text = "· $title",
                        fontSize = 12.sp,
                        color = colors.fgFaint,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }

        AnimatedVisibility(visible = open) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (!tool.error.isNullOrBlank()) {
                    Text(
                        text = "错误：${tool.error}",
                        fontSize = 12.sp,
                        color = colors.danger,
                    )
                }
                when {
                    isWebTool(tool) -> {
                        val query = parseWebSearchQuery(tool)
                        val webItems = parseWebSearchItems(tool)
                        if (query.isNotBlank()) {
                            Text("搜索：$query", fontSize = 12.sp, color = colors.fgFaint)
                        }
                        if (webItems.isEmpty()) {
                            Text("暂无结果详情", fontSize = 12.sp, color = colors.fgFaint)
                        } else {
                            webItems.forEach { item ->
                                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                    Text(
                                        text = item.title.ifBlank { item.url },
                                        fontSize = 12.5.sp,
                                        fontWeight = FontWeight.Medium,
                                        color = colors.fgMuted,
                                    )
                                    if (item.url.isNotBlank()) {
                                        Text(
                                            text = item.url,
                                            fontSize = 11.sp,
                                            color = MaterialTheme.colorScheme.primary,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                            modifier = Modifier.clickable { uriHandler.openUri(item.url) },
                                        )
                                    }
                                    if (item.snippet.isNotBlank()) {
                                        Text(
                                            text = item.snippet,
                                            fontSize = 12.sp,
                                            color = colors.fgFaint,
                                            maxLines = 4,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                    }
                                }
                            }
                        }
                    }
                    tool.name == "todo_list" -> {
                        val changes = parseTodoChanges(tool)
                        changes.forEach { line ->
                            Text("· $line", fontSize = 12.sp, color = colors.fgFaint)
                        }
                    }
                    else -> {
                        val prettyArgs = prettyToolPayload(tool.args)
                        val prettyRes = prettyToolPayload(tool.result)
                        if (prettyArgs.isNotBlank()) {
                            Text("参数", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = colors.fgFaint)
                            Text(
                                text = prettyArgs,
                                fontSize = 11.5.sp,
                                fontFamily = FontFamily.Monospace,
                                color = colors.fgFaint,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(colors.surface)
                                    .padding(8.dp),
                            )
                        }
                        if (prettyRes.isNotBlank()) {
                            Text("结果", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = colors.fgFaint)
                            Text(
                                text = prettyRes,
                                fontSize = 11.5.sp,
                                fontFamily = FontFamily.Monospace,
                                color = colors.fgFaint,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(colors.surface)
                                    .padding(8.dp),
                            )
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
        containerColor = colors.canvas,
        title = { Text("搜索对话", fontWeight = FontWeight.SemiBold, color = colors.fg) },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                WhitzTextField(
                    value = query,
                    onValueChange = {
                        query = it
                        onQueryChange(it)
                    },
                    placeholder = "输入标题或消息关键词...",
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, tint = colors.fgMuted) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(10.dp))
                if (searching) {
                    Box(modifier = Modifier.fillMaxWidth().padding(18.dp), contentAlignment = Alignment.Center) {
                        WhitzLoadingIndicator(size = 24.dp)
                    }
                } else if (query.isNotBlank() && results.isEmpty()) {
                    Text("没有找到匹配的对话", fontSize = 13.sp, color = colors.fgFaint, modifier = Modifier.padding(8.dp))
                } else {
                    LazyColumn(modifier = Modifier.heightIn(max = 320.dp)) {
                        items(results) { hit ->
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
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

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
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
        containerColor = colors.canvas,
        title = { Text("选择本轮附加技能", fontWeight = FontWeight.SemiBold, color = colors.fg) },
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
                                .clip(RoundedCornerShape(10.dp))
                                .clickable { onToggle(sk.name) }
                                .padding(vertical = 6.dp, horizontal = 4.dp),
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
            Button(onClick = onDismiss, shapes = ButtonDefaults.shapesFor(36.dp)) { Text("完成") }
        },
    )
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
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
        containerColor = colors.canvas,
        title = { Text("从文件库选择", fontWeight = FontWeight.SemiBold, color = colors.fg) },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                WhitzTextField(
                    value = query,
                    onValueChange = { query = it },
                    placeholder = "搜索文件名...",
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(8.dp))
                if (loading) {
                    Box(modifier = Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) {
                        WhitzLoadingIndicator(size = 24.dp)
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
                                    .clip(RoundedCornerShape(10.dp))
                                    .clickable {
                                        if (checked) selectedIds.remove(f.id) else selectedIds.add(f.id)
                                    }
                                    .padding(vertical = 6.dp, horizontal = 4.dp),
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
                shapes = ButtonDefaults.shapesFor(36.dp),
                enabled = selectedIds.isNotEmpty(),
            ) {
                Text("附加 (${selectedIds.size})")
            }
        },
    )
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun FilePreviewDialog(
    target: PreviewTarget,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val uriHandler = LocalUriHandler.current

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
                        WhitzLoadingIndicator()
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
                        Button(
                            onClick = {
                                try {
                                    uriHandler.openUri(target.previewUrl)
                                } catch (_: Exception) {
                                }
                            },
                            shapes = ButtonDefaults.shapesFor(40.dp),
                        ) {
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
