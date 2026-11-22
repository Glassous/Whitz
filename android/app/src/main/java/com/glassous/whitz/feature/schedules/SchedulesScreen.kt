package com.glassous.whitz.feature.schedules

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import com.glassous.whitz.ui.theme.History
import androidx.compose.material.icons.filled.PlayArrow
import com.glassous.whitz.ui.theme.Schedule
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MediumFlexibleTopAppBar
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.core.model.SchedulePreviewResponse
import com.glassous.whitz.core.model.ScheduledTask
import com.glassous.whitz.core.model.ScheduledTaskPendingItem
import com.glassous.whitz.core.model.ScheduledTaskRun
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.feature.chat.ChatViewModel
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzTextField
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SchedulesScreen(
    vm: ChatViewModel,
    onOpenEditor: (taskId: String?) -> Unit,
    onOpenConversation: (conversationId: String) -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val state by vm.schedules.ui.collectAsState()
    val scrollBehavior = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    var historyTask by remember { mutableStateOf<ScheduledTask?>(null) }
    var deleteTarget by remember { mutableStateOf<ScheduledTask?>(null) }

    LaunchedEffect(Unit) {
        vm.schedules.loadAll()
    }

    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .background(colors.canvas)
            .nestedScroll(scrollBehavior.nestedScrollConnection),
        containerColor = colors.canvas,
        contentWindowInsets = WindowInsets(0),
        topBar = {
            MediumFlexibleTopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = colors.canvas,
                    scrolledContainerColor = colors.canvas,
                ),
                scrollBehavior = scrollBehavior,
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回",
                            tint = colors.fg,
                        )
                    }
                },
                title = {
                    Text(
                        text = "定时任务",
                        fontWeight = FontWeight.SemiBold,
                        color = colors.fg,
                    )
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { onOpenEditor(null) },
                containerColor = MaterialTheme.colorScheme.primaryContainer,
                contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.padding(bottom = navBottom),
            ) {
                Icon(Icons.Default.Add, contentDescription = "新建定时任务")
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = innerPadding.calculateTopPadding()),
            contentAlignment = Alignment.TopCenter,
        ) {
            LazyColumn(
                modifier = Modifier
                    .widthIn(max = 840.dp)
                    .fillMaxSize(),
                contentPadding = PaddingValues(
                    start = 16.dp,
                    end = 16.dp,
                    top = 8.dp,
                    bottom = navBottom + 88.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                // Quota Summary Card
                item(key = "quota-header") {
                    Surface(
                        shape = RoundedCornerShape(18.dp),
                        color = colors.surface,
                        border = BorderStroke(0.5.dp, colors.line),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Text(
                                    text = "自动化配额",
                                    fontSize = 14.5.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = colors.fg,
                                    modifier = Modifier.weight(1f),
                                )
                                Surface(
                                    shape = RoundedCornerShape(999.dp),
                                    color = colors.active,
                                ) {
                                    Text(
                                        text = "已启用 ${state.quota.activeCount} / ${state.quota.maxActiveTasks}",
                                        fontSize = 11.5.sp,
                                        fontWeight = FontWeight.Medium,
                                        color = colors.fg,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                                    )
                                }
                            }
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = "最小间隔 ${state.quota.minIntervalMinutes} 分钟 · 到点后后台无人值守运行并同步至对应对话",
                                fontSize = 12.sp,
                                color = colors.fgMuted,
                            )
                        }
                    }
                }

                // Feedback / Error Banner
                if (!state.error.isNullOrBlank() || !state.feedback.isNullOrBlank()) {
                    item(key = "status-banner") {
                        val isErr = !state.error.isNullOrBlank()
                        val msg = state.error ?: state.feedback.orEmpty()
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .background(if (isErr) colors.dangerWeak else colors.active)
                                .padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = msg,
                                color = if (isErr) colors.danger else colors.fg,
                                fontSize = 12.5.sp,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(
                                onClick = { vm.schedules.clearMessages() },
                                modifier = Modifier.size(24.dp),
                            ) {
                                Icon(
                                    Icons.Default.Close,
                                    contentDescription = "关闭",
                                    tint = if (isErr) colors.danger else colors.fg,
                                    modifier = Modifier.size(14.dp),
                                )
                            }
                        }
                    }
                }

                // Pending AI Proposals
                if (state.pending.isNotEmpty()) {
                    item(key = "pending-header") {
                        Text(
                            text = "待确认提案 (${state.pending.size})",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = colors.fgMuted,
                        )
                    }
                    items(state.pending, key = { "pending-${it.id}" }) { proposal ->
                        PendingProposalRow(
                            item = proposal,
                            busy = state.busyProposalId == proposal.id,
                            onResolve = { action -> vm.schedules.resolvePending(proposal.id, action) },
                        )
                    }
                }

                // Loading / Empty / Task Cards
                if (state.loading && state.tasks.isEmpty()) {
                    item(key = "loading") {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 48.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            WhitzLoadingIndicator()
                        }
                    }
                } else if (state.tasks.isEmpty()) {
                    item(key = "empty") {
                        Surface(
                            shape = RoundedCornerShape(18.dp),
                            color = colors.surface.copy(alpha = 0.7f),
                            border = BorderStroke(0.5.dp, colors.line),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 20.dp, vertical = 36.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Icon(
                                    imageVector = Icons.Default.Schedule,
                                    contentDescription = null,
                                    tint = colors.fgFaint,
                                    modifier = Modifier.size(36.dp),
                                )
                                Spacer(modifier = Modifier.height(10.dp))
                                Text(
                                    text = "还没有定时任务",
                                    fontSize = 15.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = colors.fg,
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = "点击右下角「+」新建任务，或在对话中让助理为你自动创建",
                                    fontSize = 12.5.sp,
                                    color = colors.fgMuted,
                                )
                            }
                        }
                    }
                } else {
                    items(state.tasks, key = { it.id }) { task ->
                        ScheduledTaskCard(
                            task = task,
                            busy = state.busyTaskId == task.id,
                            onToggle = { vm.schedules.toggleEnabled(task) },
                            onRunNow = {
                                vm.schedules.runNow(task)
                            },
                            onEdit = { onOpenEditor(task.id) },
                            onHistory = {
                                historyTask = task
                                vm.schedules.loadTaskRuns(task.id)
                            },
                            onDelete = { deleteTarget = task },
                            onOpenConversation = task.conversationId?.let { cid ->
                                { onOpenConversation(cid) }
                            },
                        )
                    }
                }
            }
        }
    }

    // Execution History Bottom Sheet
    historyTask?.let { target ->
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        val runs = state.runsByTask[target.id] ?: target.runs
        ModalBottomSheet(
            onDismissRequest = { historyTask = null },
            sheetState = sheetState,
            containerColor = colors.surface,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 18.dp)
                    .padding(bottom = navBottom + 24.dp),
            ) {
                Text(
                    text = "${target.name} · 执行历史",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = colors.fg,
                )
                Spacer(modifier = Modifier.height(12.dp))
                if (state.loadingRunsTaskId == target.id && runs.isEmpty()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 28.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        WhitzLoadingIndicator(size = 28.dp)
                    }
                } else if (runs.isEmpty()) {
                    Text(
                        text = "暂无执行记录",
                        fontSize = 13.sp,
                        color = colors.fgFaint,
                        modifier = Modifier.padding(vertical = 24.dp),
                    )
                } else {
                    LazyColumn(
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        items(runs, key = { it.id }) { run ->
                            RunHistoryItem(
                                run = run,
                                onOpenConversation = run.conversationId?.let { cid ->
                                    {
                                        historyTask = null
                                        onOpenConversation(cid)
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }

    // Delete Confirmation Dialog
    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            containerColor = colors.surface,
            title = { Text("删除定时任务", color = colors.fg) },
            text = {
                Text(
                    text = "确定要删除「${target.name}」吗？已有执行记录将一并清除，生成的对话消息会保留。",
                    color = colors.fgMuted,
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        val id = target.id
                        deleteTarget = null
                        vm.schedules.deleteTask(id)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = colors.danger),
                ) {
                    Text("确认删除", color = Color.White)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) {
                    Text("取消", color = colors.fgMuted)
                }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun PendingProposalRow(
    item: ScheduledTaskPendingItem,
    busy: Boolean,
    onResolve: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val name = (item.payload["name"] as? JsonPrimitive)?.contentOrNull ?: "定时任务变更"
    val prompt = (item.payload["prompt"] as? JsonPrimitive)?.contentOrNull.orEmpty()
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = colors.active.copy(alpha = 0.7f),
        border = BorderStroke(1.dp, colors.lineStrong),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    text = name,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = colors.fg,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = item.scheduleDescription.ifBlank { item.action },
                    fontSize = 11.5.sp,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            if (prompt.isNotBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(prompt, fontSize = 12.5.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Spacer(modifier = Modifier.weight(1f))
                OutlinedButton(
                    onClick = { onResolve("reject") },
                    enabled = !busy,
                    shapes = ButtonDefaults.shapesFor(34.dp),
                ) { Text("拒绝") }
                Button(
                    onClick = { onResolve("approve") },
                    enabled = !busy,
                    shapes = ButtonDefaults.shapesFor(34.dp),
                ) { Text(if (busy) "处理中…" else "确认生效") }
            }
        }
    }
}

@Composable
private fun ScheduledTaskCard(
    task: ScheduledTask,
    busy: Boolean,
    onToggle: () -> Unit,
    onRunNow: () -> Unit,
    onEdit: () -> Unit,
    onHistory: () -> Unit,
    onDelete: () -> Unit,
    onOpenConversation: (() -> Unit)?,
) {
    val colors = LocalWhitzColors.current
    val (statusLabel, statusBg, statusFg) = when {
        task.lastRunStatus == "running" -> Triple("执行中", colors.active, colors.fg)
        task.status == "error" -> Triple("异常暂停", colors.dangerWeak, colors.danger)
        task.status == "completed" -> Triple("已完成", colors.canvas, colors.fgMuted)
        !task.enabled || task.status == "paused" -> Triple("已暂停", colors.canvas, colors.fgMuted)
        else -> Triple("运行中", colors.successWeak, colors.success)
    }

    Surface(
        shape = RoundedCornerShape(18.dp),
        color = colors.surface,
        border = BorderStroke(0.5.dp, colors.line),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text(
                            text = task.name,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = colors.fg,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                        Surface(shape = RoundedCornerShape(999.dp), color = statusBg) {
                            Text(
                                text = statusLabel,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Medium,
                                color = statusFg,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "${task.scheduleDescription} · ${targetLabel(task.targetMode)}",
                        fontSize = 12.sp,
                        color = colors.fgMuted,
                    )
                }
                Switch(
                    checked = task.enabled,
                    onCheckedChange = { if (!busy) onToggle() },
                    enabled = !busy,
                )
            }

            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = task.prompt,
                fontSize = 13.sp,
                color = colors.fgMuted,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )

            Spacer(modifier = Modifier.height(8.dp))
            val nextStr = if (task.enabled && !task.nextRunAt.isNullOrBlank()) {
                "下次：${DateTimeUtils.formatShort(task.nextRunAt)}"
            } else {
                "下次：—"
            }
            val lastStr = if (!task.lastRunAt.isNullOrBlank()) {
                "上次：${DateTimeUtils.formatShort(task.lastRunAt)}"
            } else {
                "尚未执行"
            }
            Text(
                text = "$nextStr · $lastStr · 累计 ${task.runCount} 次",
                fontSize = 11.5.sp,
                color = colors.fgFaint,
            )

            if (!task.lastError.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "异常：${task.lastError}",
                    fontSize = 11.5.sp,
                    color = colors.danger,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            Spacer(modifier = Modifier.height(10.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(
                    onClick = onRunNow,
                    enabled = !busy,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("立即运行", fontSize = 12.5.sp)
                }
                TextButton(
                    onClick = onHistory,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Icon(Icons.Default.History, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("历史", fontSize = 12.5.sp)
                }
                if (onOpenConversation != null) {
                    TextButton(
                        onClick = onOpenConversation,
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                    ) {
                        Text("查看对话", fontSize = 12.5.sp)
                    }
                }
                Spacer(modifier = Modifier.weight(1f))
                IconButton(onClick = onEdit, modifier = Modifier.size(34.dp)) {
                    Icon(Icons.Default.Edit, contentDescription = "编辑", tint = colors.fgMuted, modifier = Modifier.size(18.dp))
                }
                IconButton(onClick = onDelete, modifier = Modifier.size(34.dp)) {
                    Icon(Icons.Default.Delete, contentDescription = "删除", tint = colors.danger, modifier = Modifier.size(18.dp))
                }
            }
        }
    }
}

@Composable
private fun RunHistoryItem(
    run: ScheduledTaskRun,
    onOpenConversation: (() -> Unit)?,
) {
    val colors = LocalWhitzColors.current
    val (label, bg, fg) = when (run.status) {
        "completed" -> Triple("成功", colors.successWeak, colors.success)
        "failed" -> Triple("失败", colors.dangerWeak, colors.danger)
        "skipped" -> Triple("跳过", colors.warningWeak, colors.warning)
        "cancelled" -> Triple("已取消", colors.canvas, colors.fgMuted)
        else -> Triple("执行中", colors.active, colors.fg)
    }
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = colors.canvas,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Surface(shape = RoundedCornerShape(999.dp), color = bg) {
                    Text(
                        text = label,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Medium,
                        color = fg,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                    )
                }
                Text(
                    text = if (run.triggerType == "manual") "手动触发" else "定时触发",
                    fontSize = 12.sp,
                    color = colors.fgMuted,
                )
                Text(
                    text = DateTimeUtils.formatShort(run.startedAt),
                    fontSize = 11.5.sp,
                    color = colors.fgFaint,
                    modifier = Modifier.weight(1f),
                )
                if (onOpenConversation != null) {
                    Text(
                        text = "查看对话",
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .clickable(onClick = onOpenConversation)
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
            }
            if (!run.summary.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = run.summary,
                    fontSize = 12.5.sp,
                    color = colors.fgMuted,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (!run.error.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(text = run.error, fontSize = 12.sp, color = colors.danger)
            }
        }
    }
}

private fun targetLabel(mode: String): String = when (mode) {
    "main" -> "投递至主聊天"
    "conversation" -> "投递至指定旁聊"
    else -> "任务专属旁聊"
}

@OptIn(
    ExperimentalMaterial3Api::class,
    ExperimentalMaterial3ExpressiveApi::class,
    ExperimentalLayoutApi::class,
)
@Composable
fun ScheduleEditorScreen(
    vm: ChatViewModel,
    taskId: String?,
    onSaved: () -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val schedState by vm.schedules.ui.collectAsState()
    val chatState by vm.ui.collectAsState()
    val user by vm.user.collectAsState()
    val scrollBehavior = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    val existing = remember(taskId, schedState.tasks) {
        taskId?.let { id -> schedState.tasks.firstOrNull { it.id == id } }
    }

    var name by remember(existing?.id) { mutableStateOf(existing?.name.orEmpty()) }
    var prompt by remember(existing?.id) { mutableStateOf(existing?.prompt.orEmpty()) }
    var scheduleType by remember(existing?.id) { mutableStateOf(existing?.scheduleType ?: "daily") }
    var timezone by remember(existing?.id) {
        mutableStateOf(existing?.timezone ?: user?.timezone ?: "Asia/Shanghai")
    }
    var targetMode by remember(existing?.id) { mutableStateOf(existing?.targetMode ?: "dedicated") }
    var targetConvId by remember(existing?.id) { mutableStateOf(existing?.conversationId.orEmpty()) }
    var modelRoute by remember(existing?.id) { mutableStateOf(existing?.modelRoute ?: "auto") }

    // Schedule config fields
    val initCfg = existing?.scheduleConfig
    var hourText by remember(existing?.id) {
        val h = (initCfg?.get("hour") as? JsonPrimitive)?.intOrNull ?: 9
        mutableStateOf(String.format("%02d", h))
    }
    var minuteText by remember(existing?.id) {
        val m = (initCfg?.get("minute") as? JsonPrimitive)?.intOrNull ?: 0
        mutableStateOf(String.format("%02d", m))
    }
    var everyMinutesText by remember(existing?.id) {
        val mins = (initCfg?.get("every_minutes") as? JsonPrimitive)?.intOrNull
            ?: maxOf(60, schedState.quota.minIntervalMinutes)
        mutableStateOf(mins.toString())
    }
    var monthDayText by remember(existing?.id) {
        val day = (initCfg?.get("day") as? JsonPrimitive)?.intOrNull ?: 1
        mutableStateOf(day.toString())
    }
    var weekdays by remember(existing?.id) {
        val arr = (initCfg?.get("weekdays") as? JsonArray)?.mapNotNull {
            (it as? JsonPrimitive)?.intOrNull
        }?.toSet()
        mutableStateOf(if (!arr.isNullOrEmpty()) arr else setOf(1, 2, 3, 4, 5))
    }
    var cronExpr by remember(existing?.id) {
        val expr = (initCfg?.get("expr") as? JsonPrimitive)?.contentOrNull ?: "0 9 * * 1-5"
        mutableStateOf(expr)
    }
    var onceLocalText by remember(existing?.id) {
        val iso = (initCfg?.get("run_at") as? JsonPrimitive)?.contentOrNull
        val zdt = runCatching {
            if (!iso.isNullOrBlank()) Instant.parse(iso).atZone(ZoneId.systemDefault())
            else ZonedDateTime.now().plusHours(1).withSecond(0).withNano(0)
        }.getOrElse { ZonedDateTime.now().plusHours(1) }
        mutableStateOf(zdt.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")))
    }

    var formError by remember { mutableStateOf<String?>(null) }
    var preview by remember { mutableStateOf<SchedulePreviewResponse?>(null) }
    var previewing by remember { mutableStateOf(false) }

    fun buildScheduleConfig(): JsonObject {
        val hour = hourText.toIntOrNull()?.coerceIn(0, 23) ?: 9
        val minute = minuteText.toIntOrNull()?.coerceIn(0, 59) ?: 0
        return when (scheduleType) {
            "once" -> {
                val parsedIso = runCatching {
                    val zone = runCatching { ZoneId.of(timezone.trim().ifBlank { "Asia/Shanghai" }) }
                        .getOrElse { ZoneId.systemDefault() }
                    val ldt = java.time.LocalDateTime.parse(
                        onceLocalText.trim().replace("T", " "),
                        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"),
                    )
                    ldt.atZone(zone).toInstant().toString()
                }.getOrElse { onceLocalText.trim() }
                buildJsonObject { put("run_at", JsonPrimitive(parsedIso)) }
            }
            "interval" -> buildJsonObject {
                put("every_minutes", JsonPrimitive((everyMinutesText.toIntOrNull() ?: 60).coerceAtLeast(1)))
            }
            "daily" -> buildJsonObject {
                put("hour", JsonPrimitive(hour))
                put("minute", JsonPrimitive(minute))
            }
            "weekly" -> buildJsonObject {
                put(
                    "weekdays",
                    buildJsonArray {
                        (weekdays.ifEmpty { setOf(1) }).sorted().forEach { add(JsonPrimitive(it)) }
                    },
                )
                put("hour", JsonPrimitive(hour))
                put("minute", JsonPrimitive(minute))
            }
            "monthly" -> buildJsonObject {
                put("day", JsonPrimitive((monthDayText.toIntOrNull() ?: 1).coerceIn(1, 31)))
                put("hour", JsonPrimitive(hour))
                put("minute", JsonPrimitive(minute))
            }
            else -> buildJsonObject { put("expr", JsonPrimitive(cronExpr.trim())) }
        }
    }

    LaunchedEffect(
        scheduleType,
        hourText,
        minuteText,
        everyMinutesText,
        monthDayText,
        weekdays,
        cronExpr,
        onceLocalText,
        timezone,
    ) {
        delay(260)
        previewing = true
        preview = runCatching {
            vm.schedules.previewSchedule(
                scheduleType = scheduleType,
                scheduleConfig = buildScheduleConfig(),
                timezone = timezone.trim().ifBlank { "Asia/Shanghai" },
            )
        }.getOrNull()
        previewing = false
    }

    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .background(colors.canvas)
            .nestedScroll(scrollBehavior.nestedScrollConnection),
        containerColor = colors.canvas,
        contentWindowInsets = WindowInsets(0),
        topBar = {
            MediumFlexibleTopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = colors.canvas,
                    scrolledContainerColor = colors.canvas,
                ),
                scrollBehavior = scrollBehavior,
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回",
                            tint = colors.fg,
                        )
                    }
                },
                title = {
                    Text(
                        text = if (existing == null) "新建定时任务" else "编辑定时任务",
                        fontWeight = FontWeight.SemiBold,
                        color = colors.fg,
                    )
                },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = innerPadding.calculateTopPadding())
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp)
                .padding(bottom = navBottom + 28.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            WhitzTextField(
                value = name,
                onValueChange = { name = it },
                label = "任务名称",
                placeholder = "例如：每日 AI 早报",
                modifier = Modifier.fillMaxWidth(),
            )

            WhitzTextField(
                value = prompt,
                onValueChange = { prompt = it },
                label = "执行指令",
                placeholder = "到点后自动发送给助理执行的具体指令…",
                singleLine = false,
                maxLines = 5,
                modifier = Modifier.fillMaxWidth(),
            )

            Text("调度方式", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
            WhitzConnectedRadioGroup(
                options = listOf(
                    "daily" to "每天",
                    "weekly" to "每周",
                    "monthly" to "每月",
                ),
                selected = scheduleType,
                onSelect = { scheduleType = it },
            )
            WhitzConnectedRadioGroup(
                options = listOf(
                    "interval" to "间隔",
                    "once" to "单次",
                    "cron" to "Cron",
                ),
                selected = scheduleType,
                onSelect = { scheduleType = it },
            )

            Surface(
                shape = RoundedCornerShape(16.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    when (scheduleType) {
                        "once" -> {
                            WhitzTextField(
                                value = onceLocalText,
                                onValueChange = { onceLocalText = it },
                                label = "执行时间 (yyyy-MM-dd HH:mm)",
                                placeholder = "2026-11-22 09:00",
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                        "interval" -> {
                            WhitzTextField(
                                value = everyMinutesText,
                                onValueChange = { everyMinutesText = it.filter(Char::isDigit) },
                                label = "间隔分钟数（最小 ${schedState.quota.minIntervalMinutes} 分钟）",
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                        "daily", "weekly", "monthly" -> {
                            if (scheduleType == "weekly") {
                                val dayLabels = listOf(
                                    1 to "一", 2 to "二", 3 to "三", 4 to "四", 5 to "五", 6 to "六", 7 to "日",
                                )
                                FlowRow(
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    verticalArrangement = Arrangement.spacedBy(6.dp),
                                ) {
                                    dayLabels.forEach { (d, lbl) ->
                                        val selected = d in weekdays
                                        FilterChip(
                                            selected = selected,
                                            onClick = {
                                                weekdays = if (selected && weekdays.size > 1) {
                                                    weekdays - d
                                                } else {
                                                    weekdays + d
                                                }
                                            },
                                            label = { Text("周$lbl") },
                                        )
                                    }
                                }
                            }
                            if (scheduleType == "monthly") {
                                WhitzTextField(
                                    value = monthDayText,
                                    onValueChange = { monthDayText = it.filter(Char::isDigit) },
                                    label = "每月几号 (1-31)",
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                WhitzTextField(
                                    value = hourText,
                                    onValueChange = { hourText = it.filter(Char::isDigit).take(2) },
                                    label = "小时 (0-23)",
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.weight(1f),
                                )
                                WhitzTextField(
                                    value = minuteText,
                                    onValueChange = { minuteText = it.filter(Char::isDigit).take(2) },
                                    label = "分钟 (0-59)",
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                        else -> {
                            WhitzTextField(
                                value = cronExpr,
                                onValueChange = { cronExpr = it },
                                label = "5 段 Cron 表达式（分 时 日 月 周）",
                                placeholder = "0 9 * * 1-5",
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }

                    WhitzTextField(
                        value = timezone,
                        onValueChange = { timezone = it },
                        label = "调度时区",
                        placeholder = "Asia/Shanghai",
                        modifier = Modifier.fillMaxWidth(),
                    )

                    // Live Preview
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .background(colors.canvas)
                            .padding(10.dp),
                    ) {
                        Text(
                            text = when {
                                previewing -> "正在校验时间…"
                                preview?.valid == true -> "规则：${preview?.scheduleDescription}"
                                else -> "规则校验"
                            },
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium,
                            color = if (preview?.valid == true) MaterialTheme.colorScheme.primary else colors.fgMuted,
                        )
                        if (preview != null && !preview!!.valid && !preview!!.error.isNullOrBlank()) {
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(preview!!.error.orEmpty(), fontSize = 12.sp, color = colors.danger)
                        } else if (!preview?.nextRuns.isNullOrEmpty()) {
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "最近触发：" + preview!!.nextRuns.take(3).joinToString(" / ") {
                                    DateTimeUtils.formatShort(it)
                                },
                                fontSize = 11.5.sp,
                                color = colors.fgFaint,
                            )
                        }
                    }
                }
            }

            Text("结果投递会话", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
            WhitzConnectedRadioGroup(
                options = listOf(
                    "dedicated" to "专属旁聊",
                    "main" to "主聊天",
                    "conversation" to "指定旁聊",
                ),
                selected = targetMode,
                onSelect = { targetMode = it },
            )

            if (targetMode == "conversation") {
                val sides = chatState.sideConversations
                if (sides.isEmpty()) {
                    Text("当前暂无可用旁聊，请先新建旁聊或选择「专属旁聊」", fontSize = 12.sp, color = colors.danger)
                } else {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        sides.forEach { conv ->
                            FilterChip(
                                selected = targetConvId == conv.id,
                                onClick = { targetConvId = conv.id },
                                label = { Text(conv.title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                            )
                        }
                    }
                }
            }

            Text("模型路由", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
            WhitzConnectedRadioGroup(
                options = listOf(
                    "auto" to "自动",
                    "default" to "标准",
                    "fast" to "快速",
                    "reasoning" to "思考",
                ),
                selected = modelRoute,
                onSelect = { modelRoute = it },
            )

            if (!formError.isNullOrBlank()) {
                Text(
                    text = formError.orEmpty(),
                    fontSize = 12.5.sp,
                    color = colors.danger,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(colors.dangerWeak)
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                )
            }

            Button(
                onClick = {
                    val trimmedName = name.trim()
                    val trimmedPrompt = prompt.trim()
                    if (trimmedName.isEmpty()) {
                        formError = "请输入任务名称"
                        return@Button
                    }
                    if (trimmedPrompt.isEmpty()) {
                        formError = "请输入执行指令"
                        return@Button
                    }
                    if (targetMode == "conversation" && targetConvId.isBlank()) {
                        formError = "请选择一个目标旁聊"
                        return@Button
                    }
                    formError = null
                    vm.schedules.saveTask(
                        editingId = existing?.id,
                        name = trimmedName,
                        prompt = trimmedPrompt,
                        scheduleType = scheduleType,
                        scheduleConfig = buildScheduleConfig(),
                        timezone = timezone.trim().ifBlank { "Asia/Shanghai" },
                        targetMode = targetMode,
                        conversationId = if (targetMode == "conversation") targetConvId else null,
                        modelRoute = modelRoute,
                        skillNames = existing?.skillNames.orEmpty(),
                        onSuccess = onSaved,
                        onError = { msg -> formError = msg },
                    )
                },
                enabled = !schedState.saving,
                shapes = ButtonDefaults.shapesFor(46.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
            ) {
                Text(
                    text = if (schedState.saving) "保存中…" else if (existing == null) "创建并启用" else "保存修改",
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}
