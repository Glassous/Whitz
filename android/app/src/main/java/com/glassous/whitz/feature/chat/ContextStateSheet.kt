package com.glassous.whitz.feature.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.core.model.ConversationContextState
import com.glassous.whitz.core.model.ConversationEpisodeItem
import com.glassous.whitz.core.model.ConversationWorkingState
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.ui.theme.History
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.MyLocation
import com.glassous.whitz.ui.theme.Psychology
import com.glassous.whitz.ui.theme.PushPin
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator

@OptIn(
    ExperimentalMaterial3Api::class,
    ExperimentalMaterial3ExpressiveApi::class,
    ExperimentalLayoutApi::class,
)
@Composable
fun ContextStateSheet(
    state: ConversationContextState?,
    loading: Boolean,
    saving: Boolean,
    archiving: Boolean,
    error: String?,
    onRefresh: () -> Unit,
    onUpdateWorkingState: (ConversationWorkingState) -> Unit,
    onArchiveNow: () -> Unit,
    onLocateMessage: (String) -> Unit,
    onOpenMemorySettings: () -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = colors.canvas,
        contentColor = colors.fg,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 16.dp),
        ) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(34.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Default.Psychology,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(19.dp),
                    )
                }
                Spacer(modifier = Modifier.width(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "认知记忆状态",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = colors.fg,
                    )
                    Text(
                        text = "L0 常驻核心 · L1 工作态 · L2 情景归档",
                        fontSize = 11.5.sp,
                        color = colors.fgMuted,
                    )
                }
                IconButton(onClick = onRefresh, enabled = !loading) {
                    if (loading) {
                        WhitzLoadingIndicator(size = 16.dp)
                    } else {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "刷新记忆状态",
                            tint = colors.fgMuted,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(10.dp))

            // Quick Action Bar: L0 Pinned Chip + Archive Now Button
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Surface(
                    shape = RoundedCornerShape(999.dp),
                    color = colors.surface,
                    border = BorderStroke(0.5.dp, colors.line),
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .clickable {
                            onDismiss()
                            onOpenMemorySettings()
                        },
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(5.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.PushPin,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(13.dp),
                        )
                        Text(
                            text = "L0 常驻核心 · ${state?.pinnedMemoriesCount ?: 0} 条",
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium,
                            color = colors.fg,
                        )
                    }
                }

                Spacer(modifier = Modifier.weight(1f))

                FilledTonalButton(
                    onClick = onArchiveNow,
                    enabled = !archiving && !loading,
                    shapes = ButtonDefaults.shapesFor(34.dp),
                    modifier = Modifier.height(34.dp),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 0.dp),
                ) {
                    if (archiving) {
                        WhitzLoadingIndicator(size = 13.dp)
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("归档中…", fontSize = 12.sp)
                    } else {
                        Icon(
                            imageVector = Icons.Default.History,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                        )
                        Spacer(modifier = Modifier.width(5.dp))
                        Text("立即归档历史", fontSize = 12.sp)
                    }
                }
            }

            if (!error.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .background(colors.dangerWeak)
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                ) {
                    Text(text = error, fontSize = 12.sp, color = colors.danger)
                }
            }

            Spacer(modifier = Modifier.height(10.dp))
            HorizontalDivider(color = colors.line)

            if (loading && state == null) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 44.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    WhitzLoadingIndicator()
                }
            } else {
                val ws = state?.workingState
                val hasStructuredWs = ws != null && (
                    ws.activeGoals.isNotEmpty() ||
                        ws.recentDecisions.isNotEmpty() ||
                        ws.openQuestions.isNotEmpty() ||
                        ws.keyEntities.isNotEmpty()
                    )
                val episodes = state?.episodes.orEmpty()

                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f, fill = false),
                    contentPadding = PaddingValues(top = 12.dp, bottom = 24.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    // L1 Section Header
                    item(key = "l1-header") {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(
                                text = "L1 结构化工作态",
                                fontSize = 13.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = colors.fg,
                            )
                            val updatedAt = state?.workingStateUpdatedAt
                            if (!updatedAt.isNullOrBlank()) {
                                Text(
                                    text = "更新于 ${DateTimeUtils.formatShort(updatedAt)}",
                                    fontSize = 11.sp,
                                    color = colors.fgFaint,
                                )
                            }
                        }
                    }

                    if (hasStructuredWs && ws != null) {
                        if (ws.activeGoals.isNotEmpty()) {
                            item(key = "l1-goals") {
                                WorkingStateSectionCard(title = "进行中的目标") {
                                    ws.activeGoals.forEachIndexed { idx, g ->
                                        val statusLabel = when (g.status) {
                                            "blocked" -> "受阻"
                                            "pending" -> "待开始"
                                            else -> "进行中"
                                        }
                                        val statusColor = when (g.status) {
                                            "blocked" -> colors.danger
                                            "pending" -> colors.fgMuted
                                            else -> MaterialTheme.colorScheme.primary
                                        }
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        ) {
                                            Box(
                                                modifier = Modifier
                                                    .clip(RoundedCornerShape(6.dp))
                                                    .background(statusColor.copy(alpha = 0.12f))
                                                    .padding(horizontal = 6.dp, vertical = 2.dp),
                                            ) {
                                                Text(
                                                    text = statusLabel,
                                                    fontSize = 10.5.sp,
                                                    fontWeight = FontWeight.Medium,
                                                    color = statusColor,
                                                )
                                            }
                                            Text(
                                                text = g.title,
                                                fontSize = 13.sp,
                                                color = colors.fg,
                                                modifier = Modifier.weight(1f),
                                            )
                                            IconButton(
                                                onClick = {
                                                    onUpdateWorkingState(
                                                        ws.copy(activeGoals = ws.activeGoals.filterIndexed { i, _ -> i != idx })
                                                    )
                                                },
                                                enabled = !saving,
                                                modifier = Modifier.size(24.dp),
                                            ) {
                                                Icon(
                                                    Icons.Default.Close,
                                                    contentDescription = "移除目标",
                                                    tint = colors.fgFaint,
                                                    modifier = Modifier.size(14.dp),
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        if (ws.recentDecisions.isNotEmpty()) {
                            item(key = "l1-decisions") {
                                WorkingStateSectionCard(title = "已确认的决策") {
                                    ws.recentDecisions.forEachIndexed { idx, d ->
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            verticalAlignment = Alignment.Top,
                                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        ) {
                                            Column(modifier = Modifier.weight(1f)) {
                                                Text(
                                                    text = d.decision,
                                                    fontSize = 13.sp,
                                                    fontWeight = FontWeight.Medium,
                                                    color = colors.fg,
                                                )
                                                val sub = listOfNotNull(
                                                    d.date?.takeIf { it.isNotBlank() },
                                                    d.reason?.takeIf { it.isNotBlank() },
                                                ).joinToString(" · ")
                                                if (sub.isNotBlank()) {
                                                    Text(
                                                        text = sub,
                                                        fontSize = 11.5.sp,
                                                        color = colors.fgMuted,
                                                    )
                                                }
                                            }
                                            IconButton(
                                                onClick = {
                                                    onUpdateWorkingState(
                                                        ws.copy(recentDecisions = ws.recentDecisions.filterIndexed { i, _ -> i != idx })
                                                    )
                                                },
                                                enabled = !saving,
                                                modifier = Modifier.size(24.dp),
                                            ) {
                                                Icon(
                                                    Icons.Default.Close,
                                                    contentDescription = "移除决策",
                                                    tint = colors.fgFaint,
                                                    modifier = Modifier.size(14.dp),
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        if (ws.openQuestions.isNotEmpty()) {
                            item(key = "l1-questions") {
                                WorkingStateSectionCard(title = "待跟进的问题") {
                                    ws.openQuestions.forEachIndexed { idx, q ->
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        ) {
                                            Text(
                                                text = "• $q",
                                                fontSize = 13.sp,
                                                color = colors.fg,
                                                modifier = Modifier.weight(1f),
                                            )
                                            IconButton(
                                                onClick = {
                                                    onUpdateWorkingState(
                                                        ws.copy(openQuestions = ws.openQuestions.filterIndexed { i, _ -> i != idx })
                                                    )
                                                },
                                                enabled = !saving,
                                                modifier = Modifier.size(24.dp),
                                            ) {
                                                Icon(
                                                    Icons.Default.Close,
                                                    contentDescription = "移除问题",
                                                    tint = colors.fgFaint,
                                                    modifier = Modifier.size(14.dp),
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        if (ws.keyEntities.isNotEmpty()) {
                            item(key = "l1-entities") {
                                WorkingStateSectionCard(title = "关键实体与约束") {
                                    FlowRow(
                                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        verticalArrangement = Arrangement.spacedBy(6.dp),
                                    ) {
                                        ws.keyEntities.entries.forEach { (k, v) ->
                                            Surface(
                                                shape = RoundedCornerShape(10.dp),
                                                color = colors.canvas,
                                                border = BorderStroke(0.5.dp, colors.line),
                                            ) {
                                                Row(
                                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                                    verticalAlignment = Alignment.CenterVertically,
                                                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                                                ) {
                                                    Text(
                                                        text = "$k：$v",
                                                        fontSize = 12.sp,
                                                        color = colors.fg,
                                                        maxLines = 1,
                                                        overflow = TextOverflow.Ellipsis,
                                                    )
                                                    Icon(
                                                        imageVector = Icons.Default.Close,
                                                        contentDescription = "移除实体",
                                                        tint = colors.fgFaint,
                                                        modifier = Modifier
                                                            .size(13.dp)
                                                            .clickable(enabled = !saving) {
                                                                val nextEntities = ws.keyEntities.toMutableMap()
                                                                nextEntities.remove(k)
                                                                onUpdateWorkingState(ws.copy(keyEntities = nextEntities))
                                                            },
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    } else if (!state?.rollingSummary.isNullOrBlank()) {
                        item(key = "l1-legacy") {
                            WorkingStateSectionCard(title = "会话工作摘要") {
                                Text(
                                    text = state?.rollingSummary.orEmpty(),
                                    fontSize = 13.sp,
                                    lineHeight = 19.sp,
                                    color = colors.fgMuted,
                                )
                            }
                        }
                    } else {
                        item(key = "l1-empty") {
                            Surface(
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(14.dp),
                                color = colors.surface,
                                border = BorderStroke(0.5.dp, colors.line),
                            ) {
                                Text(
                                    text = "对话变长后，系统会自动提炼当前目标、已确认决策与关键实体到 L1 工作态，避免长对话跑偏。",
                                    fontSize = 12.5.sp,
                                    lineHeight = 18.sp,
                                    color = colors.fgMuted,
                                    modifier = Modifier.padding(12.dp),
                                )
                            }
                        }
                    }

                    // L2 Episodes Section
                    item(key = "l2-header") {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(top = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(
                                text = "L2 情景归档时间线 (${episodes.size})",
                                fontSize = 13.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = colors.fg,
                            )
                            Text(
                                text = "可被 RAG 按需精确召回",
                                fontSize = 11.sp,
                                color = colors.fgFaint,
                            )
                        }
                    }

                    if (episodes.isEmpty()) {
                        item(key = "l2-empty") {
                            Surface(
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(14.dp),
                                color = colors.surface,
                                border = BorderStroke(0.5.dp, colors.line),
                            ) {
                                Text(
                                    text = "暂无历史情景归档。你可以点击上方「立即归档历史」手动打包，或在对话超过滑窗阈值后由后台自动归档。",
                                    fontSize = 12.5.sp,
                                    lineHeight = 18.sp,
                                    color = colors.fgMuted,
                                    modifier = Modifier.padding(12.dp),
                                )
                            }
                        }
                    } else {
                        items(episodes, key = { it.id }) { ep ->
                            EpisodeTimelineCard(
                                episode = ep,
                                onLocate = { msgId ->
                                    onDismiss()
                                    onLocateMessage(msgId)
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun WorkingStateSectionCard(
    title: String,
    content: @Composable () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = colors.surface,
        border = BorderStroke(0.5.dp, colors.line),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = title,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
                color = colors.fgMuted,
            )
            content()
        }
    }
}

@Composable
private fun EpisodeTimelineCard(
    episode: ConversationEpisodeItem,
    onLocate: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = colors.surface,
        border = BorderStroke(0.5.dp, colors.line),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f))
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                ) {
                    Text(
                        text = "#${episode.episodeIndex}",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                Text(
                    text = episode.topic.ifBlank { "对话情景 #${episode.episodeIndex}" },
                    fontSize = 13.5.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = colors.fg,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = "${episode.messageCount} 条消息",
                    fontSize = 11.sp,
                    color = colors.fgFaint,
                )
            }

            if (episode.summary.isNotBlank()) {
                Text(
                    text = episode.summary,
                    fontSize = 12.5.sp,
                    lineHeight = 18.sp,
                    color = colors.fgMuted,
                )
            }

            if (episode.keyFacts.isNotEmpty()) {
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    episode.keyFacts.take(4).forEach { fact ->
                        Text(
                            text = "· $fact",
                            fontSize = 12.sp,
                            color = colors.fgFaint,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }

            val startId = episode.startMsgId
            if (!startId.isNullOrBlank()) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(
                        onClick = { onLocate(startId) },
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp),
                    ) {
                        Icon(
                            imageVector = Icons.Default.MyLocation,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("定位原文", fontSize = 12.sp)
                    }
                }
            }
        }
    }
}
