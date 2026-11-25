package com.glassous.whitz.feature.chat

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandHorizontally
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import com.glassous.whitz.ui.theme.NoteAdd
import androidx.compose.material.icons.filled.Add
import com.glassous.whitz.ui.theme.AttachFile
import com.glassous.whitz.ui.theme.AutoAwesome
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Check
import com.glassous.whitz.ui.theme.ChevronRight
import androidx.compose.material.icons.filled.Close
import com.glassous.whitz.ui.theme.ContentCopy
import androidx.compose.material.icons.filled.Delete
import com.glassous.whitz.ui.theme.Download
import androidx.compose.material.icons.filled.Edit
import com.glassous.whitz.ui.theme.ErrorOutline
import com.glassous.whitz.ui.theme.FolderOpen
import com.glassous.whitz.ui.theme.Image
import androidx.compose.material.icons.filled.MoreVert
import com.glassous.whitz.ui.theme.MyLocation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import com.glassous.whitz.ui.theme.SentimentSatisfied
import com.glassous.whitz.ui.theme.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalHapticFeedback
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
import com.glassous.whitz.core.files.InlineMessageSegment
import com.glassous.whitz.core.files.extractInlineFileIds
import com.glassous.whitz.core.files.isConversationImageFile
import com.glassous.whitz.core.files.isImageFile
import com.glassous.whitz.core.files.parseInlineFileSegments
import com.glassous.whitz.core.model.CitationItem
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.ConversationSearchHit
import com.glassous.whitz.core.model.DeliverableTarget
import com.glassous.whitz.core.model.MemoryPendingItem
import com.glassous.whitz.core.model.Message
import com.glassous.whitz.core.model.PendingControl
import com.glassous.whitz.core.model.Plan
import com.glassous.whitz.core.model.ReasoningBlock
import com.glassous.whitz.core.model.ReasoningTool
import com.glassous.whitz.core.model.ScheduledTaskPendingItem
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.core.model.UnifiedChatSearchHit
import com.glassous.whitz.core.model.UnifiedFileSearchHit
import com.glassous.whitz.core.model.UnifiedMemorySearchHit
import com.glassous.whitz.core.model.UnifiedSearchResponse
import com.glassous.whitz.core.model.displaySideTitle
import com.glassous.whitz.core.model.displayTitle
import com.glassous.whitz.core.model.isScheduledSide
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.ui.theme.Description
import com.glassous.whitz.ui.theme.History
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.Psychology
import com.glassous.whitz.ui.theme.Schedule
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzTextField
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

internal data class ReactionOption(val key: String, val emoji: String, val label: String)

internal val USER_REACTION_OPTIONS = listOf(
    ReactionOption("like", "👍", "赞"),
    ReactionOption("love", "❤️", "超喜欢"),
    ReactionOption("insightful", "💡", "有启发"),
    ReactionOption("celebrate", "🎉", "太棒了"),
    ReactionOption("dislike", "👎", "需改进"),
)

private val AI_REACTION_LABELS = mapOf(
    "like" to ("👍" to "点赞"),
    "love" to ("❤️" to "比心"),
    "sparkle" to ("✨" to "亮点"),
    "insightful" to ("💡" to "有洞察"),
)

private val DISLIKE_REASON_OPTIONS = listOf(
    "inaccurate" to "事实有误",
    "incomplete" to "不够完整",
    "slow" to "响应偏慢",
    "other" to "其他",
)

@Composable
fun ChatTimeDivider(
    label: String,
    modifier: Modifier = Modifier,
) {
    val colors = LocalWhitzColors.current
    Box(
        modifier = modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            shape = RoundedCornerShape(999.dp),
            color = colors.surface.copy(alpha = 0.78f),
        ) {
            Text(
                text = label,
                fontSize = 11.5.sp,
                fontWeight = FontWeight.Medium,
                color = colors.fgFaint,
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 2.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun MessageBubble(
    message: Message,
    streaming: Boolean,
    hasActiveUploads: Boolean = false,
    reconnecting: Boolean = false,
    waitingFirstByte: Boolean = false,
    ragPrefetching: Boolean = false,
    isActiveTurn: Boolean,
    isSelectedTurn: Boolean = false,
    isHighlighted: Boolean = false,
    isEditing: Boolean = false,
    isSelectingText: Boolean = false,
    showDislikeReasons: Boolean = false,
    liveLabel: String? = null,
    pendingControl: PendingControl? = null,
    turnPlan: Plan? = null,
    turnReasoning: List<ReasoningBlock>? = null,
    turnCitations: List<CitationItem>? = null,
    convFiles: List<ConversationFile>,
    assistantName: String = "Whitz",
    onRegenerate: (String) -> Unit,
    onExitTextSelection: () -> Unit = {},
    onDismissDislikeReasons: () -> Unit = {},
    onLongPress: (Offset) -> Unit = {},
    onOpenTurnDetails: (String) -> Unit,
    onOpenFile: (ConversationFile) -> Unit,
    onOpenDeliverable: (DeliverableTarget) -> Unit = {},
    onOpenCitation: (CitationItem) -> Unit = {},
    onOpenLightbox: (ConversationFile, List<ConversationFile>?) -> Unit = { f, _ -> onOpenFile(f) },
    onReact: (messageId: String, reaction: String, reasonCode: String?) -> Unit = { _, _, _ -> },
) {
    val colors = LocalWhitzColors.current
    val haptic = LocalHapticFeedback.current

    when (message.role) {
        "user" -> {
            var bubbleCoords by remember(message.id) { mutableStateOf<LayoutCoordinates?>(null) }

            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.End,
            ) {
                val attachments = message.toolPayload?.attachments.orEmpty()
                val inlineIds = remember(message.content) { extractInlineFileIds(message.content).toSet() }
                val barAttachments = remember(attachments, inlineIds) {
                    attachments.filterNot { it.id in inlineIds }
                }
                val messageImageFiles = remember(attachments, convFiles) {
                    attachments.mapNotNull { att ->
                        val resolved = convFiles.firstOrNull { it.id == att.id } ?: ConversationFile(
                            id = att.id,
                            filename = att.filename,
                            ext = att.ext,
                            category = att.category,
                            sizeBytes = att.sizeBytes,
                        )
                        if (isConversationImageFile(resolved)) resolved else null
                    }
                }
                val inlineSegments = remember(message.content, convFiles) {
                    parseInlineFileSegments(message.content) { id ->
                        convFiles.firstOrNull { it.id == id }?.filename
                    }
                }
                val skills = message.toolPayload?.skills.orEmpty()
                val bubbleShape = RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp)

                if (isEditing || isSelectingText) {
                    Surface(
                        modifier = Modifier.padding(bottom = 5.dp),
                        shape = RoundedCornerShape(999.dp),
                        color = colors.surface,
                        border = BorderStroke(0.8.dp, colors.lineStrong),
                    ) {
                        Row(
                            modifier = Modifier
                                .clickable(enabled = isSelectingText, onClick = onExitTextSelection)
                                .padding(horizontal = 10.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(5.dp),
                        ) {
                            if (isEditing) {
                                Icon(
                                    Icons.Default.Edit,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(12.dp),
                                )
                                Text(
                                    text = "正在编辑此消息",
                                    fontSize = 11.5.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = colors.fg,
                                )
                            } else {
                                Text(
                                    text = "长按拖动选择文字",
                                    fontSize = 11.5.sp,
                                    color = colors.fgMuted,
                                )
                                Text(
                                    text = "完成",
                                    fontSize = 11.5.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }
                }

                Column(
                    modifier = Modifier
                        .widthIn(max = 320.dp)
                        .clip(bubbleShape)
                        .background(MaterialTheme.colorScheme.primary)
                        .then(
                            when {
                                isEditing || isSelectingText -> Modifier.border(1.5.dp, colors.fgMuted.copy(alpha = 0.7f), bubbleShape)
                                isHighlighted -> Modifier.border(2.dp, colors.warning, bubbleShape)
                                else -> Modifier
                            },
                        )
                        .onGloballyPositioned { bubbleCoords = it }
                        .then(
                            if (!isSelectingText) {
                                Modifier.pointerInput(message.id) {
                                    detectTapGestures(
                                        onLongPress = { localOffset ->
                                            val coords = bubbleCoords
                                            if (coords != null && coords.isAttached) {
                                                haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                                onLongPress(coords.localToWindow(localOffset))
                                            }
                                        },
                                    )
                                }
                            } else {
                                Modifier
                            },
                        )
                        .padding(horizontal = 14.dp, vertical = 10.dp),
                ) {
                    if (barAttachments.isNotEmpty()) {
                        val hasContentAfter = inlineSegments.isNotEmpty() || skills.isNotEmpty()
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                            modifier = Modifier.padding(bottom = if (hasContentAfter) 6.dp else 0.dp),
                        ) {
                            barAttachments.forEach { att ->
                                val targetFile = convFiles.firstOrNull { it.id == att.id } ?: ConversationFile(
                                    id = att.id,
                                    filename = att.filename,
                                    ext = att.ext,
                                    category = att.category,
                                    sizeBytes = att.sizeBytes,
                                )
                                val isImg = isConversationImageFile(targetFile)
                                if (isImg) {
                                    PureMessageImageThumb(
                                        file = targetFile,
                                        sizeDp = 76.dp,
                                        onClick = { onOpenLightbox(targetFile, messageImageFiles.ifEmpty { null }) },
                                    )
                                } else {
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
                    if (inlineSegments.isNotEmpty()) {
                        val isLongUserInput = remember(message.content) {
                            message.content.length >= 200 || message.content.count { it == '\n' } >= 6
                        }
                        var isUserExpanded by remember(message.id) { mutableStateOf(false) }
                        val collapseActive = isLongUserInput && !isUserExpanded && !isSelectingText
                        val contentBlock: @Composable () -> Unit = {
                            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                inlineSegments.forEach { seg ->
                                    when (seg) {
                                        is InlineMessageSegment.Text -> {
                                            val display = seg.value.trim('\n')
                                            if (display.isNotBlank()) {
                                                Text(
                                                    text = display,
                                                    color = MaterialTheme.colorScheme.onPrimary,
                                                    fontSize = 15.sp,
                                                    lineHeight = 22.sp,
                                                )
                                            }
                                        }
                                        is InlineMessageSegment.FileRef -> {
                                            val targetFile = convFiles.firstOrNull { it.id == seg.fileId } ?: ConversationFile(
                                                id = seg.fileId,
                                                filename = seg.filename,
                                            )
                                            if (isConversationImageFile(targetFile)) {
                                                PureMessageImageThumb(
                                                    file = targetFile,
                                                    sizeDp = 120.dp,
                                                    onClick = { onOpenLightbox(targetFile, messageImageFiles.ifEmpty { null }) },
                                                )
                                            } else {
                                                Row(
                                                    modifier = Modifier
                                                        .clip(RoundedCornerShape(10.dp))
                                                        .background(MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.16f))
                                                        .clickable { onOpenFile(targetFile) }
                                                        .padding(horizontal = 9.dp, vertical = 6.dp),
                                                    verticalAlignment = Alignment.CenterVertically,
                                                ) {
                                                    Icon(
                                                        Icons.Default.AttachFile,
                                                        contentDescription = null,
                                                        tint = MaterialTheme.colorScheme.onPrimary,
                                                        modifier = Modifier.size(14.dp),
                                                    )
                                                    Spacer(modifier = Modifier.width(5.dp))
                                                    Text(
                                                        text = seg.filename,
                                                        color = MaterialTheme.colorScheme.onPrimary,
                                                        fontSize = 12.5.sp,
                                                        fontWeight = FontWeight.Medium,
                                                        maxLines = 1,
                                                        overflow = TextOverflow.Ellipsis,
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        Box(
                            modifier = if (collapseActive) {
                                Modifier.heightIn(max = 168.dp).clipToBounds()
                            } else {
                                Modifier
                            },
                        ) {
                            if (isSelectingText) {
                                SelectionContainer { contentBlock() }
                            } else {
                                contentBlock()
                            }
                            if (collapseActive) {
                                Box(
                                    modifier = Modifier
                                        .align(Alignment.BottomCenter)
                                        .fillMaxWidth()
                                        .height(34.dp)
                                        .background(
                                            Brush.verticalGradient(
                                                colors = listOf(
                                                    Color.Transparent,
                                                    MaterialTheme.colorScheme.primary,
                                                ),
                                            ),
                                        ),
                                )
                            }
                        }
                        if (isLongUserInput && !isSelectingText) {
                            Spacer(modifier = Modifier.height(6.dp))
                            Row(
                                modifier = Modifier
                                    .align(Alignment.End)
                                    .clip(RoundedCornerShape(999.dp))
                                    .background(MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.14f))
                                    .clickable { isUserExpanded = !isUserExpanded }
                                    .padding(horizontal = 8.dp, vertical = 3.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(2.dp),
                            ) {
                                Text(
                                    text = if (isUserExpanded) "收起" else "展开全文",
                                    color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.92f),
                                    fontSize = 11.5.sp,
                                    fontWeight = FontWeight.Medium,
                                )
                                Icon(
                                    imageVector = Icons.Default.ChevronRight,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.92f),
                                    modifier = Modifier
                                        .size(13.dp)
                                        .rotate(if (isUserExpanded) -90f else 90f),
                                )
                            }
                        }
                    }
                }

                val aiReaction = message.reactions.firstOrNull { it.authorType == "assistant" }
                if (aiReaction != null) {
                    val (emoji, label) = AI_REACTION_LABELS[aiReaction.reaction] ?: ("👍" to "点赞")
                    Surface(
                        modifier = Modifier.padding(top = 4.dp),
                        shape = RoundedCornerShape(999.dp),
                        color = colors.surface,
                        border = BorderStroke(0.5.dp, colors.line),
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 9.dp, vertical = 3.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Text(emoji, fontSize = 12.sp)
                            Text(
                                text = "$assistantName · $label",
                                fontSize = 11.5.sp,
                                color = colors.fgMuted,
                            )
                            val note = aiReaction.comment
                            if (!note.isNullOrBlank()) {
                                Text(
                                    text = "· $note",
                                    fontSize = 11.sp,
                                    color = colors.fgFaint,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.widthIn(max = 150.dp),
                                )
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
            val effectiveCitations = remember(turnCitations, message.toolPayload?.citations) {
                val base = message.toolPayload?.citations.orEmpty()
                val live = turnCitations.orEmpty()
                if (live.isEmpty()) base
                else {
                    val map = LinkedHashMap<String, CitationItem>()
                    base.forEach { map[it.citationId] = it }
                    live.forEach { map[it.citationId] = it }
                    map.values.toList()
                }
            }
            var citationsExpanded by remember(message.id) { mutableStateOf(false) }
            var highlightedCitationId by remember(message.id) { mutableStateOf<String?>(null) }
            val handleInlineCitationClick: (String) -> Unit = { citeId ->
                val matched = effectiveCitations.firstOrNull {
                    it.citationId.equals(citeId, ignoreCase = true)
                }
                citationsExpanded = true
                highlightedCitationId = matched?.citationId ?: citeId
                if (matched != null) {
                    onOpenCitation(matched)
                }
            }
            val isLive = isActiveTurn && streaming
            val isWaitingControl = isLive && (message.status == "waiting" || pendingControl != null)
            val isFailureOrCancelled = !isLive && (message.status == "failed" || message.status == "cancelled")
            val stepsCount = computeStepsCount(effectivePlan, effectiveReasoning)
            val hasStepsOrReasoning = effectiveReasoning.isNotEmpty() || !effectivePlan?.items.isNullOrEmpty()
            val artifacts = message.toolPayload?.artifacts.orEmpty()
            val canOpenMenu = !isLive && (message.content.isNotBlank() || isFailureOrCancelled)
            var assistantCoords by remember(message.id) { mutableStateOf<LayoutCoordinates?>(null) }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .onGloballyPositioned { assistantCoords = it }
                    .then(
                        if (canOpenMenu && !isSelectingText) {
                            Modifier.pointerInput(message.id, canOpenMenu) {
                                detectTapGestures(
                                    onLongPress = { localOffset ->
                                        val coords = assistantCoords
                                        if (coords != null && coords.isAttached) {
                                            haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                                            onLongPress(coords.localToWindow(localOffset))
                                        }
                                    },
                                )
                            }
                        } else {
                            Modifier
                        },
                    ),
            ) {
                if (isSelectingText) {
                    Surface(
                        modifier = Modifier.padding(bottom = 8.dp),
                        shape = RoundedCornerShape(999.dp),
                        color = colors.surface,
                        border = BorderStroke(0.8.dp, colors.lineStrong),
                    ) {
                        Row(
                            modifier = Modifier
                                .clickable(onClick = onExitTextSelection)
                                .padding(horizontal = 10.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text(
                                text = "长按拖动选择文字",
                                fontSize = 11.5.sp,
                                color = colors.fgMuted,
                            )
                            Text(
                                text = "完成",
                                fontSize = 11.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                }

                if (hasStepsOrReasoning || isLive) {
                    val primaryColor = MaterialTheme.colorScheme.primary
                    val pillText = if (isLive) (liveLabel ?: "正在思考…") else "步骤查看"
                    Row(
                        modifier = Modifier
                            .padding(bottom = 10.dp)
                            .clip(RoundedCornerShape(999.dp))
                            .background(
                                when {
                                    isWaitingControl -> colors.warningWeak
                                    isSelectedTurn -> primaryColor.copy(alpha = 0.14f)
                                    else -> colors.surface
                                },
                            )
                            .clickable { onOpenTurnDetails(message.id) }
                            .padding(horizontal = 13.dp, vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (isLive) {
                            WhitzLoadingIndicator(
                                size = 14.dp,
                                color = if (isWaitingControl) colors.warning else primaryColor,
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                        }
                        AnimatedContent(
                            targetState = pillText,
                            transitionSpec = {
                                fadeIn(animationSpec = tween(160)) togetherWith fadeOut(animationSpec = tween(120))
                            },
                            label = "liveStepPillLabel",
                            modifier = Modifier.weight(1f, fill = false),
                        ) { label ->
                            Text(
                                text = label,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium,
                                color = when {
                                    isWaitingControl -> colors.warning
                                    isSelectedTurn -> primaryColor
                                    else -> colors.fgMuted
                                },
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
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
                            tint = when {
                                isWaitingControl -> colors.warning.copy(alpha = 0.85f)
                                isSelectedTurn -> primaryColor.copy(alpha = 0.8f)
                                else -> colors.fgFaint
                            },
                            modifier = Modifier.size(14.dp),
                        )
                    }
                }

                if (message.content.isNotBlank()) {
                    val showLiveCursor = isLive && !isWaitingControl
                    if (isSelectingText) {
                        SelectionContainer {
                            MarkdownText(
                                markdown = message.content,
                                isStreaming = showLiveCursor,
                                modifier = Modifier.fillMaxWidth(),
                                onOpenDeliverable = onOpenDeliverable,
                                onOpenCitation = handleInlineCitationClick,
                            )
                        }
                    } else {
                        MarkdownText(
                            markdown = message.content,
                            isStreaming = showLiveCursor,
                            modifier = Modifier.fillMaxWidth(),
                            onOpenDeliverable = onOpenDeliverable,
                            onOpenCitation = handleInlineCitationClick,
                        )
                    }
                } else if (isLive || message.status == "streaming") {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.padding(vertical = 4.dp),
                    ) {
                        StreamingTypingDots(
                            color = if (isWaitingControl) colors.warning else MaterialTheme.colorScheme.primary,
                        )
                        val statusText = when {
                            reconnecting -> "正在恢复实时输出…"
                            isWaitingControl -> if (pendingControl?.kind == "approval") {
                                "正在等待你的审批确认…"
                            } else {
                                "正在等待你的澄清回答，提交后将继续执行…"
                            }
                            ragPrefetching -> "正在检索知识库与记忆…"
                            waitingFirstByte -> "助理已接收请求，正在准备回复…"
                            else -> "正在组织回答…"
                        }
                        Text(
                            text = statusText,
                            fontSize = 13.5.sp,
                            color = if (isWaitingControl) colors.warning else colors.fgFaint,
                        )
                    }
                } else if (message.status == "waiting") {
                    Text("等待你的确认...", fontSize = 13.5.sp, color = colors.warning)
                }

                if (effectiveCitations.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(10.dp))
                    CitationsDisclosureCard(
                        citations = effectiveCitations,
                        expanded = citationsExpanded,
                        highlightedCitationId = highlightedCitationId,
                        onToggleExpanded = { citationsExpanded = !citationsExpanded },
                        onOpenCitation = onOpenCitation,
                    )
                }

                if (artifacts.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(10.dp))
                    val artifactFiles = remember(artifacts, convFiles) {
                        artifacts.map { art ->
                            convFiles.firstOrNull { it.id == art.id } ?: ConversationFile(
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
                        }
                    }
                    val imageArtifacts = remember(artifactFiles) {
                        artifactFiles.filter { isConversationImageFile(it) }
                    }
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        artifactFiles.forEach { convFile ->
                            if (isConversationImageFile(convFile)) {
                                PureMessageImageThumb(
                                    file = convFile,
                                    sizeDp = 96.dp,
                                    onClick = { onOpenLightbox(convFile, imageArtifacts.ifEmpty { null }) },
                                )
                            } else {
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
                                        Text(convFile.filename, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = colors.fg)
                                        Text(FileValidator.formatSize(convFile.sizeBytes), fontSize = 11.sp, color = colors.fgFaint)
                                    }
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
                            enabled = !streaming && !hasActiveUploads,
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

                if (canOpenMenu) {
                    val userReaction = message.reactions.firstOrNull { it.authorType == "user" }
                    val selectedMeta = USER_REACTION_OPTIONS.firstOrNull { it.key == userReaction?.reaction }

                    if (selectedMeta != null) {
                        Surface(
                            modifier = Modifier.padding(top = 6.dp),
                            shape = RoundedCornerShape(999.dp),
                            color = if (selectedMeta.key == "dislike") colors.dangerWeak else colors.surface,
                            border = BorderStroke(
                                0.5.dp,
                                if (selectedMeta.key == "dislike") colors.danger.copy(alpha = 0.4f) else colors.line,
                            ),
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 9.dp, vertical = 3.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                Text(selectedMeta.emoji, fontSize = 12.sp)
                                Text(
                                    text = selectedMeta.label,
                                    fontSize = 11.5.sp,
                                    color = if (selectedMeta.key == "dislike") colors.danger else colors.fgMuted,
                                )
                            }
                        }
                    }

                    if (showDislikeReasons && userReaction?.reaction == "dislike") {
                        FlowRow(
                            modifier = Modifier.padding(top = 6.dp),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text(
                                text = "反馈原因：",
                                fontSize = 11.5.sp,
                                color = colors.fgFaint,
                                modifier = Modifier.align(Alignment.CenterVertically),
                            )
                            DISLIKE_REASON_OPTIONS.forEach { (code, label) ->
                                val selected = userReaction.reasonCode == code
                                Surface(
                                    shape = RoundedCornerShape(999.dp),
                                    color = if (selected) colors.dangerWeak else colors.surface,
                                    border = BorderStroke(
                                        0.8.dp,
                                        if (selected) colors.danger.copy(alpha = 0.5f) else colors.line,
                                    ),
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(999.dp))
                                        .clickable {
                                            onReact(message.id, "dislike", code)
                                            onDismissDislikeReasons()
                                        },
                                ) {
                                    Text(
                                        text = label,
                                        fontSize = 11.5.sp,
                                        color = if (selected) colors.danger else colors.fgMuted,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
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

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun ApprovalCard(
    control: PendingControl,
    submittingChoice: String? = null,
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
                    enabled = submittingChoice == null,
                    shapes = ButtonDefaults.shapesFor(40.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (submittingChoice == "deny") "拒绝中…" else "拒绝")
                }
                Button(
                    onClick = { onApprove("once") },
                    enabled = submittingChoice == null,
                    shapes = ButtonDefaults.shapesFor(40.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (submittingChoice == "once") "批准中…" else "允许一次")
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
fun ClarifyCard(
    control: PendingControl,
    submitting: Boolean = false,
    onSubmit: (com.glassous.whitz.core.model.ClarifySubmitPayload) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val questions = remember(control.requestId, control.executionGeneration, control.clarify, control.preview) {
        val list = control.clarify?.questions.orEmpty()
        if (list.isNotEmpty()) list
        else listOf(
            com.glassous.whitz.core.model.ClarifyQuestionItem(
                id = "q1",
                question = control.clarify?.question ?: control.preview ?: "请补充更多信息以便继续。",
                options = control.clarify?.options.orEmpty(),
                multiple = control.clarify?.multiple ?: false,
                allowCustom = true,
            ),
        )
    }
    val isMulti = questions.size > 1
    val introText = remember(control.clarify, control.preview, questions) {
        if (!isMulti) ""
        else {
            val raw = (control.clarify?.question ?: control.preview).orEmpty().trim()
            if (raw.isBlank() || raw == questions.firstOrNull()?.question) "" else raw
        }
    }
    val selectedMap = remember(control.requestId, control.executionGeneration) {
        androidx.compose.runtime.mutableStateMapOf<String, List<String>>()
    }
    val textMap = remember(control.requestId, control.executionGeneration) {
        androidx.compose.runtime.mutableStateMapOf<String, String>()
    }
    val answeredCount = questions.count { q ->
        !selectedMap[q.id].isNullOrEmpty() || !textMap[q.id].isNullOrBlank()
    }
    val canSubmit = !submitting && answeredCount > 0

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        color = colors.surface,
        border = BorderStroke(1.dp, colors.lineStrong),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("助理需要你澄清", fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = colors.fg)
                if (isMulti) {
                    Text(
                        "已答 $answeredCount / ${questions.size}",
                        fontSize = 11.5.sp,
                        color = colors.fgMuted,
                    )
                }
            }
            if (introText.isNotBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(introText, fontSize = 13.sp, color = colors.fgMuted)
            }
            Spacer(modifier = Modifier.height(10.dp))
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 320.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                questions.forEachIndexed { idx, q ->
                    val currentSelected = selectedMap[q.id].orEmpty()
                    val currentText = textMap[q.id].orEmpty()
                    val title = if (isMulti && !Regex("^\\s*\\d+[.、)）]\\s*").containsMatchIn(q.question)) {
                        "${idx + 1}. ${q.question}"
                    } else {
                        q.question
                    }
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .then(
                                if (isMulti) {
                                    Modifier
                                        .clip(RoundedCornerShape(12.dp))
                                        .background(colors.canvas.copy(alpha = 0.6f))
                                        .padding(10.dp)
                                } else {
                                    Modifier
                                }
                            ),
                    ) {
                        Text(title, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = colors.fg)
                        if (q.options.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            FlowRow(
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                verticalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                q.options.forEach { opt ->
                                    val selected = opt in currentSelected
                                    val accentColor = MaterialTheme.colorScheme.primary
                                    val accentBg = MaterialTheme.colorScheme.primaryContainer
                                    Surface(
                                        shape = RoundedCornerShape(10.dp),
                                        color = if (selected) accentBg else colors.canvas,
                                        border = BorderStroke(1.dp, if (selected) accentColor else colors.line),
                                        modifier = Modifier.clickable(enabled = !submitting) {
                                            selectedMap[q.id] = if (q.multiple) {
                                                if (selected) currentSelected - opt else currentSelected + opt
                                            } else {
                                                if (selected) emptyList() else listOf(opt)
                                            }
                                        },
                                    ) {
                                        Row(
                                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        ) {
                                            if (selected) {
                                                Icon(
                                                    Icons.Default.Check,
                                                    contentDescription = null,
                                                    tint = accentColor,
                                                    modifier = Modifier.size(14.dp),
                                                )
                                            }
                                            Text(
                                                opt,
                                                fontSize = 12.5.sp,
                                                color = if (selected) accentColor else colors.fgMuted,
                                            )
                                        }
                                    }
                                }
                            }
                        }
                        if (q.allowCustom || q.options.isEmpty()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            WhitzTextField(
                                value = currentText,
                                onValueChange = { textMap[q.id] = it },
                                placeholder = q.placeholder
                                    ?: if (q.options.isNotEmpty()) "补充说明或填写其他答案（可选）..." else "输入你的回答...",
                                enabled = !submitting,
                                singleLine = false,
                                maxLines = if (isMulti) 3 else 4,
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                }
            }
            Spacer(modifier = Modifier.height(10.dp))
            Button(
                onClick = {
                    val answers = questions.map { q ->
                        com.glassous.whitz.core.model.ClarifyAnswerItem(
                            id = q.id,
                            question = q.question,
                            selected = selectedMap[q.id].orEmpty(),
                            text = textMap[q.id].orEmpty().trim(),
                        )
                    }
                    val formatted = questions.mapIndexedNotNull { idx, q ->
                        val sel = selectedMap[q.id].orEmpty()
                        val txt = textMap[q.id].orEmpty().trim()
                        if (sel.isEmpty() && txt.isBlank()) return@mapIndexedNotNull null
                        val combined = when {
                            sel.isNotEmpty() && txt.isNotBlank() -> "${sel.joinToString("、")}（$txt）"
                            sel.isNotEmpty() -> sel.joinToString("、")
                            else -> txt
                        }
                        if (isMulti) "${idx + 1}. ${q.question}\n答：$combined" else combined
                    }.joinToString("\n\n").trim()
                    if (formatted.isNotBlank()) {
                        onSubmit(com.glassous.whitz.core.model.ClarifySubmitPayload(formatted, answers))
                    }
                },
                shapes = ButtonDefaults.shapesFor(36.dp),
                enabled = canSubmit,
                modifier = Modifier.align(Alignment.End),
            ) {
                Text(if (submitting) "提交中…" else "提交")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun MemoryPendingCard(
    item: MemoryPendingItem,
    busy: Boolean = false,
    onResolve: (id: String, action: String, content: String?) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var editing by remember(item.id) { mutableStateOf(false) }
    var draft by remember(item.id, item.content) { mutableStateOf(item.content) }
    var pendingAction by remember(item.id) { mutableStateOf<String?>(null) }
    LaunchedEffect(busy) {
        if (!busy) pendingAction = null
    }

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
                    enabled = !busy,
                    singleLine = false,
                    maxLines = 4,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                Text(draft, fontSize = 13.sp, color = colors.fg)
            }
            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(
                    onClick = { editing = !editing },
                    enabled = !busy,
                ) { Text(if (editing) "完成编辑" else "编辑") }
                Spacer(modifier = Modifier.weight(1f))
                OutlinedButton(
                    onClick = {
                        pendingAction = "reject"
                        onResolve(item.id, "reject", null)
                    },
                    enabled = !busy,
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text(if (busy && pendingAction == "reject") "拒绝中…" else "拒绝") }
                Button(
                    onClick = {
                        pendingAction = "approve"
                        onResolve(item.id, "approve", if (draft != item.content) draft else null)
                    },
                    enabled = !busy && (!editing || draft.isNotBlank()),
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text(if (busy && pendingAction != "reject") "保存中…" else "保存") }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SkillPendingCard(
    item: SkillPendingItem,
    busy: Boolean = false,
    onResolve: (id: String, action: String, content: String?) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var pendingAction by remember(item.id) { mutableStateOf<String?>(null) }
    LaunchedEffect(busy) {
        if (!busy) pendingAction = null
    }
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
                    onClick = {
                        pendingAction = "reject"
                        onResolve(item.id, "reject", null)
                    },
                    enabled = !busy,
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text(if (busy && pendingAction == "reject") "拒绝中…" else "拒绝") }
                Button(
                    onClick = {
                        pendingAction = "approve"
                        onResolve(item.id, "approve", null)
                    },
                    enabled = !busy,
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text(if (busy && pendingAction != "reject") "处理中…" else "批准") }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SchedulePendingCard(
    item: ScheduledTaskPendingItem,
    busy: Boolean = false,
    onResolve: (id: String, action: String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    var pendingAction by remember(item.id) { mutableStateOf<String?>(null) }
    LaunchedEffect(busy) {
        if (!busy) pendingAction = null
    }
    val actionTitle = when (item.action) {
        "update" -> "修改定时任务"
        "pause" -> "暂停定时任务"
        "resume" -> "恢复定时任务"
        "delete" -> "删除定时任务"
        else -> "新建定时任务"
    }
    val taskName = (item.payload["name"] as? JsonPrimitive)?.contentOrNull ?: "未命名定时任务"
    val taskPrompt = (item.payload["prompt"] as? JsonPrimitive)?.contentOrNull.orEmpty()

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = colors.surface,
        border = BorderStroke(1.dp, colors.lineStrong),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    text = "$actionTitle：$taskName",
                    fontSize = 13.5.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = colors.fg,
                    modifier = Modifier.weight(1f),
                )
                if (item.scheduleDescription.isNotBlank()) {
                    Text(
                        text = item.scheduleDescription,
                        fontSize = 11.5.sp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            }
            if (taskPrompt.isNotBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = taskPrompt,
                    fontSize = 12.5.sp,
                    color = colors.fgMuted,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (!item.reason.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "说明：${item.reason}",
                    fontSize = 11.5.sp,
                    color = colors.fgFaint,
                )
            }
            Spacer(modifier = Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Spacer(modifier = Modifier.weight(1f))
                OutlinedButton(
                    onClick = {
                        pendingAction = "reject"
                        onResolve(item.id, "reject")
                    },
                    enabled = !busy,
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text(if (busy && pendingAction == "reject") "拒绝中…" else "拒绝") }
                Button(
                    onClick = {
                        pendingAction = "approve"
                        onResolve(item.id, "approve")
                    },
                    enabled = !busy,
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) {
                    Text(
                        if (busy && pendingAction != "reject") "处理中…"
                        else if (item.action == "delete") "确认删除" else "确认生效"
                    )
                }
            }
        }
    }
}

@Composable
private fun StreamingTypingDots(
    color: Color,
    modifier: Modifier = Modifier,
) {
    val transition = rememberInfiniteTransition(label = "streamingDots")
    val dot1 by transition.animateFloat(
        initialValue = 0.28f,
        targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 560, delayMillis = 0),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "dot1",
    )
    val dot2 by transition.animateFloat(
        initialValue = 0.28f,
        targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 560, delayMillis = 160),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "dot2",
    )
    val dot3 by transition.animateFloat(
        initialValue = 0.28f,
        targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 560, delayMillis = 320),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "dot3",
    )
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.size(5.dp).clip(CircleShape).background(color.copy(alpha = dot1)))
        Box(modifier = Modifier.size(5.dp).clip(CircleShape).background(color.copy(alpha = dot2)))
        Box(modifier = Modifier.size(5.dp).clip(CircleShape).background(color.copy(alpha = dot3)))
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
    val stepsListState = rememberLazyListState()
    var followLiveSteps by remember(turnKey) { mutableStateOf(true) }

    val stepsNestedScroll = remember(turnKey) {
        object : NestedScrollConnection {
            override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                if (source == NestedScrollSource.UserInput) {
                    if (ChatScrollPolicy.shouldDisengageOnUserPreScroll(available.y)) {
                        followLiveSteps = false
                    } else if (ChatScrollPolicy.isUserScrollingDown(available.y) && !stepsListState.canScrollForward) {
                        followLiveSteps = true
                    }
                }
                return Offset.Zero
            }
        }
    }

    LaunchedEffect(streaming) {
        if (streaming) {
            toggledSteps.clear()
            followLiveSteps = true
        }
    }

    val liveReasoningSignature = remember(reasoning, runningTool, sections.doneCount) {
        "${reasoning.size}:${reasoning.lastOrNull()?.text?.length ?: 0}:${reasoning.lastOrNull()?.tools?.size ?: 0}:${runningTool.orEmpty()}:${sections.doneCount}"
    }
    LaunchedEffect(streaming, liveReasoningSignature) {
        if (streaming && followLiveSteps && !stepsListState.isScrollInProgress) {
            val total = stepsListState.layoutInfo.totalItemsCount
            if (total > 0 && stepsListState.canScrollForward) {
                stepsListState.animateScrollToItem(total - 1)
            }
        }
    }

    LazyColumn(
        state = stepsListState,
        modifier = modifier.nestedScroll(stepsNestedScroll),
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
private fun PureMessageImageThumb(
    file: ConversationFile,
    sizeDp: Dp,
    onClick: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val model = file.thumbUrl ?: file.previewUrl
    Box(
        modifier = Modifier
            .size(sizeDp)
            .clip(RoundedCornerShape(12.dp))
            .background(colors.surface)
            .border(0.5.dp, colors.line, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        if (!model.isNullOrBlank()) {
            AsyncImage(
                model = model,
                contentDescription = file.filename,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Icon(
                Icons.Default.Image,
                contentDescription = file.filename,
                tint = colors.fgFaint,
                modifier = Modifier.size(22.dp),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun TaskFilesPane(
    files: List<ConversationFile>,
    deletingFileId: String? = null,
    isMainChat: Boolean = false,
    mainFileScope: String = "all",
    onMainScopeChange: ((String) -> Unit)? = null,
    groupedByConversation: Boolean = isMainChat && mainFileScope == "all",
    onOpenFile: (ConversationFile) -> Unit,
    onOpenLightbox: ((ConversationFile, List<ConversationFile>) -> Unit)? = null,
    onInsertFile: ((ConversationFile) -> Unit)? = null,
    onLocateMessage: ((ConversationFile) -> Unit)? = null,
    onRenameFile: ((ConversationFile) -> Unit)? = null,
    onCreateFile: (() -> Unit)? = null,
    onOpenLibraryPicker: (() -> Unit)? = null,
    onUploadFiles: (() -> Unit)? = null,
    onDeleteFile: (String) -> Unit,
    modifier: Modifier = Modifier,
    bottomPadding: Dp = 24.dp,
) {
    val colors = LocalWhitzColors.current
    val allImages = remember(files) { files.filter { isConversationImageFile(it) } }

    Column(modifier = modifier) {
        if (isMainChat && onMainScopeChange != null) {
            WhitzConnectedRadioGroup(
                options = listOf("all" to "全部对话", "conversation" to "仅主聊"),
                selected = mainFileScope,
                onSelect = onMainScopeChange,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 6.dp),
            )
        }

        if (onCreateFile != null || onOpenLibraryPicker != null || onUploadFiles != null) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (onCreateFile != null) {
                    OutlinedButton(
                        onClick = onCreateFile,
                        shapes = ButtonDefaults.shapesFor(34.dp),
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                        modifier = Modifier.weight(1f).height(34.dp),
                    ) {
                        Icon(Icons.AutoMirrored.Filled.NoteAdd, contentDescription = null, modifier = Modifier.size(14.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("新建", fontSize = 12.sp, maxLines = 1)
                    }
                }
                if (onOpenLibraryPicker != null) {
                    OutlinedButton(
                        onClick = onOpenLibraryPicker,
                        shapes = ButtonDefaults.shapesFor(34.dp),
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                        modifier = Modifier.weight(1f).height(34.dp),
                    ) {
                        Icon(Icons.Default.FolderOpen, contentDescription = null, modifier = Modifier.size(14.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("资料库", fontSize = 12.sp, maxLines = 1)
                    }
                }
                if (onUploadFiles != null) {
                    OutlinedButton(
                        onClick = onUploadFiles,
                        shapes = ButtonDefaults.shapesFor(34.dp),
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                        modifier = Modifier.weight(1f).height(34.dp),
                    ) {
                        Icon(Icons.Default.AttachFile, contentDescription = null, modifier = Modifier.size(14.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("上传", fontSize = 12.sp, maxLines = 1)
                    }
                }
            }
        }

        if (files.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
                Text(
                    text = if (isMainChat) {
                        "暂无工作区文件。\n可点击上方「新建」创建文本/表格/网页，或上传、从资料库引用。"
                    } else {
                        "当前旁聊暂无文件。\n可新建、上传或引用资料库文件。"
                    },
                    fontSize = 13.sp,
                    lineHeight = 20.sp,
                    color = colors.fgFaint,
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = bottomPadding),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (groupedByConversation) {
                    val grouped = linkedMapOf<String, MutableList<ConversationFile>>()
                    for (f in files) {
                        val key = f.conversationId ?: "__current__"
                        grouped.getOrPut(key) { mutableListOf() }.add(f)
                    }
                    grouped.forEach { (convKey, groupFiles) ->
                        val sample = groupFiles.first()
                        val groupTitle = sample.conversationTitle?.takeIf { it.isNotBlank() }
                            ?: if (sample.conversationKind == "main") "主聊" else "旁聊对话"
                        item(key = "grp-hdr-$convKey") {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(top = 6.dp, bottom = 2.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = groupTitle,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = colors.fgMuted,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                Text(
                                    text = "${groupFiles.size} 个",
                                    fontSize = 11.sp,
                                    color = colors.fgFaint,
                                )
                            }
                        }
                        val groupImages = groupFiles.filter { isConversationImageFile(it) }
                        val groupDocs = groupFiles.filterNot { isConversationImageFile(it) }
                        if (groupImages.isNotEmpty()) {
                            item(key = "grp-imgs-$convKey") {
                                WorkspacePureImageGrid(
                                    images = groupImages,
                                    allImages = allImages,
                                    deletingFileId = deletingFileId,
                                    onOpenImage = { f -> onOpenLightbox?.invoke(f, allImages) ?: onOpenFile(f) },
                                    onInsertFile = onInsertFile,
                                    onLocateMessage = onLocateMessage,
                                    onRenameFile = onRenameFile,
                                    onDeleteFile = onDeleteFile,
                                )
                            }
                        }
                        items(groupDocs, key = { "doc-${convKey}-${it.id}" }) { f ->
                            WorkspaceFileRowCard(
                                file = f,
                                deleting = deletingFileId == f.id,
                                onOpen = { onOpenFile(f) },
                                onInsert = onInsertFile?.let { cb -> { cb(f) } },
                                onLocate = if (f.messageId != null && onLocateMessage != null) ({ onLocateMessage(f) }) else null,
                                onRename = onRenameFile?.let { cb -> { cb(f) } },
                                onDelete = { onDeleteFile(f.id) },
                            )
                        }
                    }
                } else {
                    val images = files.filter { isConversationImageFile(it) }
                    val docs = files.filterNot { isConversationImageFile(it) }
                    if (images.isNotEmpty()) {
                        item(key = "flat-imgs") {
                            WorkspacePureImageGrid(
                                images = images,
                                allImages = allImages,
                                deletingFileId = deletingFileId,
                                onOpenImage = { f -> onOpenLightbox?.invoke(f, allImages) ?: onOpenFile(f) },
                                onInsertFile = onInsertFile,
                                onLocateMessage = onLocateMessage,
                                onRenameFile = onRenameFile,
                                onDeleteFile = onDeleteFile,
                            )
                        }
                    }
                    items(docs, key = { it.id }) { f ->
                        WorkspaceFileRowCard(
                            file = f,
                            deleting = deletingFileId == f.id,
                            onOpen = { onOpenFile(f) },
                            onInsert = onInsertFile?.let { cb -> { cb(f) } },
                            onLocate = if (f.messageId != null && onLocateMessage != null) ({ onLocateMessage(f) }) else null,
                            onRename = onRenameFile?.let { cb -> { cb(f) } },
                            onDelete = { onDeleteFile(f.id) },
                        )
                    }
                }

                item(key = "files-footer-hint") {
                    Text(
                        text = "图片支持多图缩放浏览；点击文档可直接预览、编辑与重命名。",
                        fontSize = 11.5.sp,
                        lineHeight = 17.sp,
                        color = colors.fgFaint,
                        modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun WorkspacePureImageGrid(
    images: List<ConversationFile>,
    allImages: List<ConversationFile>,
    deletingFileId: String?,
    onOpenImage: (ConversationFile) -> Unit,
    onInsertFile: ((ConversationFile) -> Unit)?,
    onLocateMessage: ((ConversationFile) -> Unit)?,
    onRenameFile: ((ConversationFile) -> Unit)?,
    onDeleteFile: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        images.chunked(3).forEach { rowFiles ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                rowFiles.forEach { img ->
                    var menuOpen by remember(img.id) { mutableStateOf(false) }
                    val model = img.thumbUrl ?: img.previewUrl
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .aspectRatio(1f)
                            .clip(RoundedCornerShape(12.dp))
                            .background(colors.surface)
                            .border(0.5.dp, colors.line, RoundedCornerShape(12.dp))
                            .clickable { onOpenImage(img) },
                        contentAlignment = Alignment.Center,
                    ) {
                        if (!model.isNullOrBlank()) {
                            AsyncImage(
                                model = model,
                                contentDescription = img.filename,
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize(),
                            )
                        } else {
                            Icon(
                                Icons.Default.Image,
                                contentDescription = img.filename,
                                tint = colors.fgFaint,
                                modifier = Modifier.size(24.dp),
                            )
                        }

                        if (deletingFileId == img.id) {
                            Box(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .background(colors.canvas.copy(alpha = 0.65f)),
                                contentAlignment = Alignment.Center,
                            ) {
                                WhitzLoadingIndicator(size = 18.dp)
                            }
                        } else {
                            Box(
                                modifier = Modifier
                                    .align(Alignment.TopEnd)
                                    .padding(4.dp),
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(24.dp)
                                        .clip(CircleShape)
                                        .background(colors.canvas.copy(alpha = 0.72f))
                                        .clickable { menuOpen = true },
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(
                                        Icons.Default.MoreVert,
                                        contentDescription = "图片操作",
                                        tint = colors.fg,
                                        modifier = Modifier.size(14.dp),
                                    )
                                }
                                DropdownMenu(
                                    expanded = menuOpen,
                                    onDismissRequest = { menuOpen = false },
                                ) {
                                    if (onInsertFile != null) {
                                        DropdownMenuItem(
                                            text = { Text("插入到输入框") },
                                            onClick = {
                                                menuOpen = false
                                                onInsertFile(img)
                                            },
                                        )
                                    }
                                    if (img.messageId != null && onLocateMessage != null) {
                                        DropdownMenuItem(
                                            text = { Text("定位对应问答") },
                                            onClick = {
                                                menuOpen = false
                                                onLocateMessage(img)
                                            },
                                        )
                                    }
                                    if (onRenameFile != null) {
                                        DropdownMenuItem(
                                            text = { Text("重命名") },
                                            onClick = {
                                                menuOpen = false
                                                onRenameFile(img)
                                            },
                                        )
                                    }
                                    DropdownMenuItem(
                                        text = { Text("移除", color = colors.danger) },
                                        onClick = {
                                            menuOpen = false
                                            onDeleteFile(img.id)
                                        },
                                    )
                                }
                            }
                        }
                    }
                }
                repeat(3 - rowFiles.size) {
                    Spacer(modifier = Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun WorkspaceFileRowCard(
    file: ConversationFile,
    deleting: Boolean,
    onOpen: () -> Unit,
    onInsert: (() -> Unit)?,
    onLocate: (() -> Unit)?,
    onRename: (() -> Unit)?,
    onDelete: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    var menuOpen by remember(file.id) { mutableStateOf(false) }

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .clickable(onClick = onOpen),
        shape = RoundedCornerShape(16.dp),
        color = colors.surface,
        border = BorderStroke(0.5.dp, colors.line),
    ) {
        Row(
            modifier = Modifier.padding(start = 14.dp, end = 6.dp, top = 11.dp, bottom = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.AttachFile, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(18.dp))
            Spacer(modifier = Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(file.filename, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = colors.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        "${FileValidator.formatSize(file.sizeBytes)} · ${if (file.source == "assistant") "AI" else "上传"}",
                        fontSize = 11.5.sp,
                        color = colors.fgFaint,
                    )
                    if (file.indexStatus == "indexing") {
                        Row(
                            modifier = Modifier
                                .clip(RoundedCornerShape(6.dp))
                                .background(colors.canvas)
                                .padding(horizontal = 5.dp, vertical = 1.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(3.dp),
                        ) {
                            WhitzLoadingIndicator(size = 9.dp)
                            Text("索引中", fontSize = 10.sp, color = colors.fgMuted)
                        }
                    }
                }
                file.qaSnippet?.takeIf { it.isNotBlank() }?.let { snippet ->
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                        modifier = if (onLocate != null) Modifier.clickable(onClick = onLocate) else Modifier,
                    ) {
                        Icon(
                            Icons.Default.MyLocation,
                            contentDescription = null,
                            tint = if (onLocate != null) MaterialTheme.colorScheme.primary else colors.fgFaint,
                            modifier = Modifier.size(11.dp),
                        )
                        Text(
                            text = snippet,
                            fontSize = 11.sp,
                            color = if (onLocate != null) MaterialTheme.colorScheme.primary else colors.fgFaint,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }

            if (onInsert != null) {
                IconButton(onClick = onInsert, modifier = Modifier.size(32.dp)) {
                    Icon(Icons.Default.Add, contentDescription = "插入到输入框", tint = colors.fgMuted, modifier = Modifier.size(17.dp))
                }
            }

            if (deleting) {
                Box(modifier = Modifier.size(32.dp), contentAlignment = Alignment.Center) {
                    WhitzLoadingIndicator(size = 14.dp)
                }
            } else {
                Box {
                    IconButton(onClick = { menuOpen = true }, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Default.MoreVert, contentDescription = "更多操作", tint = colors.fgFaint, modifier = Modifier.size(17.dp))
                    }
                    DropdownMenu(
                        expanded = menuOpen,
                        onDismissRequest = { menuOpen = false },
                    ) {
                        if (onLocate != null) {
                            DropdownMenuItem(
                                text = { Text("定位对应问答") },
                                onClick = {
                                    menuOpen = false
                                    onLocate()
                                },
                            )
                        }
                        if (onRename != null) {
                            DropdownMenuItem(
                                text = { Text("重命名") },
                                onClick = {
                                    menuOpen = false
                                    onRename()
                                },
                            )
                        }
                        DropdownMenuItem(
                            text = { Text("移除", color = colors.danger) },
                            onClick = {
                                menuOpen = false
                                onDelete()
                            },
                        )
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
                text = toolDisplayName(tool),
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
private fun CitationsDisclosureCard(
    citations: List<CitationItem>,
    expanded: Boolean,
    highlightedCitationId: String?,
    onToggleExpanded: () -> Unit,
    onOpenCitation: (CitationItem) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val rotation by animateFloatAsState(
        targetValue = if (expanded) 90f else 0f,
        label = "citationsChevron",
    )
    val summaryText = remember(citations) {
        val fileCount = citations.count { it.sourceType == "file" }
        val memCount = citations.count { it.sourceType == "memory" }
        val chatCount = citations.count { it.sourceType == "chat_digest" || it.sourceType == "chat_turn" }
        val parts = buildList {
            if (fileCount > 0) add("$fileCount 份文档")
            if (memCount > 0) add("$memCount 条记忆")
            if (chatCount > 0) add("$chatCount 段历史对话")
        }
        if (parts.isNotEmpty()) "参考了 ${parts.joinToString(" · ")}" else "参考来源 · ${citations.size} 条"
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(colors.surface)
            .border(0.6.dp, colors.line, RoundedCornerShape(14.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggleExpanded)
                .padding(horizontal = 12.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Icon(
                imageVector = Icons.Default.Description,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(14.dp),
            )
            Text(
                text = summaryText,
                fontSize = 12.5.sp,
                fontWeight = FontWeight.Medium,
                color = colors.fgMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = if (expanded) "收起引用" else "展开引用",
                tint = colors.fgFaint,
                modifier = Modifier
                    .size(15.dp)
                    .rotate(rotation),
            )
        }

        AnimatedVisibility(visible = expanded) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                citations.forEach { cite ->
                    val isHighlighted = highlightedCitationId != null &&
                        highlightedCitationId.equals(cite.citationId, ignoreCase = true)
                    val typeLabel = when (cite.sourceType) {
                        "file" -> "文档"
                        "memory" -> "记忆"
                        "chat_digest", "chat_turn" -> "历史对话"
                        else -> "来源"
                    }
                    val typeIcon = when (cite.sourceType) {
                        "file" -> Icons.Default.Description
                        "memory" -> Icons.Default.Psychology
                        else -> Icons.Default.History
                    }
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = if (isHighlighted) MaterialTheme.colorScheme.primary.copy(alpha = 0.08f) else colors.canvas,
                        border = BorderStroke(
                            if (isHighlighted) 1.dp else 0.5.dp,
                            if (isHighlighted) MaterialTheme.colorScheme.primary else colors.line,
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp))
                            .clickable { onOpenCitation(cite) },
                    ) {
                        Column(
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Box(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(5.dp))
                                        .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.14f))
                                        .padding(horizontal = 5.dp, vertical = 1.dp),
                                ) {
                                    Text(
                                        text = cite.citationId,
                                        fontSize = 10.5.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = MaterialTheme.colorScheme.primary,
                                    )
                                }
                                Icon(
                                    imageVector = typeIcon,
                                    contentDescription = null,
                                    tint = colors.fgMuted,
                                    modifier = Modifier.size(13.dp),
                                )
                                Text(
                                    text = cite.title.ifBlank { typeLabel },
                                    fontSize = 12.5.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = colors.fg,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                Text(
                                    text = typeLabel,
                                    fontSize = 10.5.sp,
                                    color = colors.fgFaint,
                                )
                            }
                            if (cite.subtitle.isNotBlank()) {
                                Text(
                                    text = cite.subtitle,
                                    fontSize = 11.sp,
                                    color = colors.fgFaint,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            if (cite.snippet.isNotBlank()) {
                                Text(
                                    text = cite.snippet,
                                    fontSize = 12.sp,
                                    lineHeight = 17.sp,
                                    color = colors.fgMuted,
                                    maxLines = 3,
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

private val OMNIBOX_TABS = listOf(
    "all" to "全部",
    "chat" to "对话",
    "file" to "资料库正文",
    "memory" to "长期记忆",
)

@Composable
fun SearchDialog(
    recentConversations: List<Conversation> = emptyList(),
    assistantName: String = "Whitz",
    results: List<ConversationSearchHit>,
    unifiedResults: UnifiedSearchResponse? = null,
    selectedSourceTab: String = "all",
    searching: Boolean,
    onQueryChange: (String) -> Unit,
    onSelectSourceTab: (source: String, currentQuery: String) -> Unit = { _, _ -> },
    onSelectConversation: (convId: String, messageId: String?) -> Unit,
    onSelectFileHit: (UnifiedFileSearchHit) -> Unit = {},
    onSelectMemoryHit: (UnifiedMemorySearchHit) -> Unit = {},
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    var query by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = colors.canvas,
        title = { Text("全局统一检索", fontWeight = FontWeight.SemiBold, color = colors.fg) },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                WhitzTextField(
                    value = query,
                    onValueChange = {
                        query = it
                        onQueryChange(it)
                    },
                    placeholder = "搜索聊天、资料库正文、长期记忆…",
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, tint = colors.fgMuted) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    OMNIBOX_TABS.forEach { (key, label) ->
                        val active = selectedSourceTab == key
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(999.dp))
                                .background(if (active) MaterialTheme.colorScheme.primary else colors.surface)
                                .clickable { onSelectSourceTab(key, query) }
                                .padding(horizontal = 10.dp, vertical = 5.dp),
                        ) {
                            Text(
                                text = label,
                                fontSize = 11.5.sp,
                                fontWeight = if (active) FontWeight.SemiBold else FontWeight.Medium,
                                color = if (active) MaterialTheme.colorScheme.onPrimary else colors.fgMuted,
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.height(10.dp))
                if (searching) {
                    Box(modifier = Modifier.fillMaxWidth().padding(18.dp), contentAlignment = Alignment.Center) {
                        WhitzLoadingIndicator(size = 24.dp)
                    }
                } else if (query.isBlank()) {
                    if (recentConversations.isEmpty()) {
                        Text("暂无最近聊天", fontSize = 13.sp, color = colors.fgFaint, modifier = Modifier.padding(8.dp))
                    } else {
                        Text("最近聊天", fontSize = 11.5.sp, fontWeight = FontWeight.Medium, color = colors.fgFaint, modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp))
                        LazyColumn(modifier = Modifier.heightIn(max = 320.dp)) {
                            items(recentConversations.take(12), key = { it.id }) { c ->
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(10.dp))
                                        .clickable {
                                            onSelectConversation(c.id, null)
                                            onDismiss()
                                        }
                                        .padding(10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        text = if (c.kind == "main") assistantName else c.displaySideTitle(),
                                        fontWeight = FontWeight.Medium,
                                        fontSize = 14.sp,
                                        color = colors.fg,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.weight(1f, fill = false),
                                    )
                                    if (c.kind == "main") {
                                        Spacer(modifier = Modifier.width(6.dp))
                                        Box(
                                            modifier = Modifier
                                                .clip(RoundedCornerShape(999.dp))
                                                .background(colors.surface)
                                                .padding(horizontal = 6.dp, vertical = 2.dp),
                                        ) {
                                            Text("主聊", fontSize = 10.sp, color = colors.fgMuted)
                                        }
                                    } else if (c.isScheduledSide()) {
                                        Spacer(modifier = Modifier.width(6.dp))
                                        Row(
                                            modifier = Modifier
                                                .clip(RoundedCornerShape(999.dp))
                                                .background(colors.surface)
                                                .padding(horizontal = 6.dp, vertical = 2.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(3.dp),
                                        ) {
                                            Icon(
                                                Icons.Default.Schedule,
                                                contentDescription = null,
                                                tint = colors.fgMuted,
                                                modifier = Modifier.size(10.dp),
                                            )
                                            Text("定时", fontSize = 10.sp, color = colors.fgMuted)
                                        }
                                    }
                                    Spacer(modifier = Modifier.weight(1f))
                                    val time = DateTimeUtils.formatShort(c.lastMessageAt ?: c.updatedAt.ifBlank { c.createdAt })
                                    if (time.isNotBlank()) {
                                        Text(time, fontSize = 11.sp, color = colors.fgFaint)
                                    }
                                }
                            }
                        }
                    }
                } else if (unifiedResults != null) {
                    val chatHits = if (selectedSourceTab == "all" || selectedSourceTab == "chat") unifiedResults.chats else emptyList()
                    val fileHits = if (selectedSourceTab == "all" || selectedSourceTab == "file") unifiedResults.files else emptyList()
                    val memHits = if (selectedSourceTab == "all" || selectedSourceTab == "memory") unifiedResults.memories else emptyList()

                    if (chatHits.isEmpty() && fileHits.isEmpty() && memHits.isEmpty()) {
                        Text("没有找到匹配的结果", fontSize = 13.sp, color = colors.fgFaint, modifier = Modifier.padding(8.dp))
                    } else {
                        LazyColumn(
                            modifier = Modifier.heightIn(max = 360.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            if (fileHits.isNotEmpty()) {
                                item(key = "hdr-files") {
                                    Text(
                                        text = "资料库正文 (${fileHits.size})",
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = colors.fgFaint,
                                        modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp),
                                    )
                                }
                                items(fileHits, key = { "file-${it.fileId}-${it.locator}-${it.snippet.hashCode()}" }) { fh ->
                                    Column(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(10.dp))
                                            .clickable {
                                                onSelectFileHit(fh)
                                                onDismiss()
                                            }
                                            .padding(horizontal = 8.dp, vertical = 8.dp),
                                    ) {
                                        Row(
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(5.dp),
                                        ) {
                                            Icon(Icons.Default.Description, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(14.dp))
                                            Text(
                                                text = fh.filename.ifBlank { fh.fileId },
                                                fontWeight = FontWeight.Medium,
                                                fontSize = 13.5.sp,
                                                color = colors.fg,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                                modifier = Modifier.weight(1f),
                                            )
                                            val loc = fh.sectionPath.ifBlank { fh.locator }
                                            if (loc.isNotBlank()) {
                                                Text(loc, fontSize = 10.5.sp, color = colors.fgFaint, maxLines = 1)
                                            }
                                        }
                                        if (fh.snippet.isNotBlank()) {
                                            Text(fh.snippet, fontSize = 12.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                        }
                                    }
                                }
                            }

                            if (memHits.isNotEmpty()) {
                                item(key = "hdr-mem") {
                                    Text(
                                        text = "长期记忆 (${memHits.size})",
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = colors.fgFaint,
                                        modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp),
                                    )
                                }
                                items(memHits, key = { "mem-${it.entryId}" }) { mh ->
                                    Column(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(10.dp))
                                            .clickable {
                                                onSelectMemoryHit(mh)
                                                onDismiss()
                                            }
                                            .padding(horizontal = 8.dp, vertical = 8.dp),
                                    ) {
                                        Row(
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(5.dp),
                                        ) {
                                            Icon(Icons.Default.Psychology, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(14.dp))
                                            Text(
                                                text = mh.title.ifBlank { mh.collectionName.ifBlank { "长期记忆" } },
                                                fontWeight = FontWeight.Medium,
                                                fontSize = 13.5.sp,
                                                color = colors.fg,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                                modifier = Modifier.weight(1f),
                                            )
                                            if (mh.collectionName.isNotBlank()) {
                                                Text(mh.collectionName, fontSize = 10.5.sp, color = colors.fgFaint)
                                            }
                                        }
                                        val body = mh.snippet.ifBlank { mh.content }
                                        if (body.isNotBlank()) {
                                            Text(body, fontSize = 12.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                        }
                                    }
                                }
                            }

                            if (chatHits.isNotEmpty()) {
                                item(key = "hdr-chat") {
                                    Text(
                                        text = "对话与情景归档 (${chatHits.size})",
                                        fontSize = 11.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = colors.fgFaint,
                                        modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp),
                                    )
                                }
                                items(chatHits, key = { "chat-${it.conversationId}-${it.messageId}-${it.snippet.hashCode()}" }) { ch ->
                                    val matchTag = when (ch.matchIn) {
                                        "digest" -> "情景归档"
                                        "semantic_turn" -> "语义命中"
                                        "title" -> "标题"
                                        else -> if (ch.role == "user") "我" else assistantName
                                    }
                                    val title = if (ch.conversationKind == "main") assistantName else ch.conversationTitle.ifBlank { "新旁聊" }
                                    Column(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .clip(RoundedCornerShape(10.dp))
                                            .clickable {
                                                onSelectConversation(ch.conversationId, ch.messageId)
                                                onDismiss()
                                            }
                                            .padding(horizontal = 8.dp, vertical = 8.dp),
                                    ) {
                                        Row(
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(5.dp),
                                        ) {
                                            Icon(Icons.Default.History, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(14.dp))
                                            Text(
                                                text = title,
                                                fontWeight = FontWeight.Medium,
                                                fontSize = 13.5.sp,
                                                color = colors.fg,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                                modifier = Modifier.weight(1f),
                                            )
                                            Text(matchTag, fontSize = 10.5.sp, color = colors.fgFaint)
                                        }
                                        if (ch.snippet.isNotBlank()) {
                                            Text(ch.snippet, fontSize = 12.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                        }
                                    }
                                }
                            }
                        }
                    }
                } else if (results.isEmpty()) {
                    Text("没有找到匹配的聊天", fontSize = 13.sp, color = colors.fgFaint, modifier = Modifier.padding(8.dp))
                } else {
                    LazyColumn(modifier = Modifier.heightIn(max = 320.dp)) {
                        items(results) { hit ->
                            val roleLabel = when {
                                hit.matchIn == "title" -> "标题"
                                hit.role == "user" -> "我"
                                hit.role == "assistant" -> assistantName
                                else -> "正文"
                            }
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .clickable {
                                        onSelectConversation(hit.conversationId, hit.messageId)
                                        onDismiss()
                                    }
                                    .padding(10.dp),
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        text = hit.displayTitle(assistantName),
                                        fontWeight = FontWeight.Medium,
                                        fontSize = 14.sp,
                                        color = colors.fg,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    if (hit.conversationKind == "main") {
                                        Spacer(modifier = Modifier.width(6.dp))
                                        Box(
                                            modifier = Modifier
                                                .clip(RoundedCornerShape(999.dp))
                                                .background(colors.surface)
                                                .padding(horizontal = 6.dp, vertical = 2.dp),
                                        ) {
                                            Text("主聊", fontSize = 10.sp, color = colors.fgMuted)
                                        }
                                    } else if (hit.isScheduledSide()) {
                                        Spacer(modifier = Modifier.width(6.dp))
                                        Row(
                                            modifier = Modifier
                                                .clip(RoundedCornerShape(999.dp))
                                                .background(colors.surface)
                                                .padding(horizontal = 6.dp, vertical = 2.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(3.dp),
                                        ) {
                                            Icon(
                                                Icons.Default.Schedule,
                                                contentDescription = null,
                                                tint = colors.fgMuted,
                                                modifier = Modifier.size(10.dp),
                                            )
                                            Text("定时", fontSize = 10.sp, color = colors.fgMuted)
                                        }
                                    }
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Text(roleLabel, fontSize = 11.sp, color = colors.fgFaint)
                                }
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
        title = { Text("从个人资料库引用文件", fontWeight = FontWeight.SemiBold, color = colors.fg) },
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
                    Text("资料库暂无可用文件", fontSize = 13.sp, color = colors.fgFaint, modifier = Modifier.padding(8.dp))
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
