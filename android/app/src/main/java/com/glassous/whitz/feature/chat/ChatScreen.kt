package com.glassous.whitz.feature.chat

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.CloseFullscreen
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.OpenInFull
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearWavyProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.PullToRefreshDefaults
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.glassous.whitz.R
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.UploadTaskStatus
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.model.quotaPercentLabel
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzBrandMark
import com.glassous.whitz.ui.theme.WhitzGlassCircleButton
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzLogoMark
import com.glassous.whitz.ui.theme.WhitzProgressiveBlurBottom
import com.glassous.whitz.ui.theme.WhitzProgressiveBlurTop
import com.glassous.whitz.ui.theme.WhitzTextField
import dev.chrisbanes.haze.hazeSource
import dev.chrisbanes.haze.rememberHazeState
import kotlinx.coroutines.launch
import java.util.Calendar
import kotlin.math.roundToInt

private fun currentGreeting(): String {
    val h = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
    return when {
        h < 5 -> "夜深了"
        h < 12 -> "早上好"
        h < 14 -> "中午好"
        h < 18 -> "下午好"
        else -> "晚上好"
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    vm: ChatViewModel,
    onOpenSettings: () -> Unit,
    onOpenTaskDetails: (Int) -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val user by vm.user.collectAsState()
    val authReady by vm.authReady.collectAsState()
    val colors = LocalWhitzColors.current
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()
    val snackbarHostState = remember { SnackbarHostState() }
    val density = LocalDensity.current
    val focusManager = LocalFocusManager.current
    val inputFocusRequester = remember { FocusRequester() }
    val headerHazeState = rememberHazeState()

    var inputText by remember { mutableStateOf("") }
    var isInputFocused by remember { mutableStateOf(false) }
    var composerExpanded by remember { mutableStateOf(false) }
    var plusMenuExpanded by remember { mutableStateOf(false) }
    var showSearch by remember { mutableStateOf(false) }
    var showSkillPicker by remember { mutableStateOf(false) }
    var showLibraryPicker by remember { mutableStateOf(false) }
    var desktopSidebarCollapsed by remember { mutableStateOf(false) }
    var showAttachMenu by remember { mutableStateOf(false) }

    var renameTarget by remember { mutableStateOf<Conversation?>(null) }
    var deleteTarget by remember { mutableStateOf<Conversation?>(null) }
    var bottomOverlayHeightPx by remember { mutableIntStateOf(0) }
    var bottomBlurHeightPx by remember { mutableIntStateOf(0) }
    var stageCoords by remember { mutableStateOf<LayoutCoordinates?>(null) }
    var chatAreaCoords by remember { mutableStateOf<LayoutCoordinates?>(null) }
    var composerRowCoords by remember { mutableStateOf<LayoutCoordinates?>(null) }
    var plusButtonCoords by remember { mutableStateOf<LayoutCoordinates?>(null) }
    var plusAnchorBounds by remember { mutableStateOf<Rect?>(null) }

    val refreshPlusAnchor = {
        val stage = stageCoords
        val btn = plusButtonCoords
        if (stage != null && btn != null && stage.isAttached && btn.isAttached) {
            plusAnchorBounds = stage.localBoundingBoxOf(btn, clipBounds = false)
        }
    }
    val refreshBottomBlurHeight = {
        val chat = chatAreaCoords
        val row = composerRowCoords
        if (chat != null && row != null && chat.isAttached && row.isAttached) {
            val rowRect = chat.localBoundingBoxOf(row, clipBounds = false)
            val rowMidY = (rowRect.top + rowRect.bottom) / 2f
            bottomBlurHeightPx = (chat.size.height - rowMidY).roundToInt().coerceAtLeast(0)
        }
    }
    val dismissPlusMenu = {
        showAttachMenu = false
        plusMenuExpanded = false
    }

    val filePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments()
    ) { uris ->
        if (uris.isNotEmpty()) {
            vm.enqueuePickedUris(uris)
        }
    }

    LaunchedEffect(Unit) {
        vm.loadInitialData()
    }

    val imeVisible = WindowInsets.ime.getBottom(density) > 0
    var wasImeVisible by remember { mutableStateOf(false) }
    LaunchedEffect(imeVisible) {
        if (wasImeVisible && !imeVisible && isInputFocused) {
            focusManager.clearFocus()
        }
        wasImeVisible = imeVisible
    }

    val visibleMessages = remember(ui.messages) { filterVisibleMessages(ui.messages) }
    val runningToolName = remember(ui.messages, ui.streaming) {
        if (ui.streaming) computeRunningTool(ui.messages) else null
    }
    val currentStepInfo = remember(ui.plan, ui.streaming) {
        if (ui.streaming) computeCurrentStep(ui.plan) else null
    }
    val liveStepLabel = remember(currentStepInfo, runningToolName, ui.plan, ui.streaming) {
        if (ui.streaming) computeLiveStepLabel(currentStepInfo, runningToolName, ui.plan) else null
    }
    val resolvedTurn = remember(
        ui.messages,
        ui.selectedTurnId,
        ui.activeAssistantId,
        ui.streaming,
        ui.plan,
        ui.reasoning,
    ) {
        resolveTurnDetails(
            messages = ui.messages,
            selectedTurnId = ui.selectedTurnId,
            activeAssistantId = ui.activeAssistantId,
            streaming = ui.streaming,
            livePlan = ui.plan,
            liveReasoning = ui.reasoning,
        )
    }

    // Top of the newest message must clear the floating header (status bar + 66dp button row),
    // otherwise the first line of that message is hidden behind the frosted buttons.
    val revealTopOffsetPx = with(density) {
        (WindowInsets.statusBars.asPaddingValues().calculateTopPadding() + 68.dp).roundToPx()
    }
    val conversationScrollKey = ui.currentConvId ?: "local-new"
    var revealedConversationKey by remember { mutableStateOf<String?>(null) }

    val lastMsgContentLen = visibleMessages.lastOrNull()?.content?.length ?: 0
    LaunchedEffect(conversationScrollKey, visibleMessages.size, lastMsgContentLen) {
        if (visibleMessages.isEmpty()) return@LaunchedEffect
        val lastIndex = visibleMessages.lastIndex
        // Entering a conversation (or returning from another page) jumps straight to the top of the
        // newest message, aligned with the web client. Streaming updates animate from there.
        if (revealedConversationKey != conversationScrollKey) {
            revealedConversationKey = conversationScrollKey
            listState.scrollToItem(lastIndex, scrollOffset = -revealTopOffsetPx)
        } else {
            listState.animateScrollToItem(lastIndex, scrollOffset = -revealTopOffsetPx)
        }
    }

    // Back key handling: overlays & drawer close before exiting
    BackHandler(enabled = ui.previewTarget != null) { vm.closeFilePreview() }
    BackHandler(enabled = showSearch) { showSearch = false }
    BackHandler(enabled = showSkillPicker) { showSkillPicker = false }
    BackHandler(enabled = showLibraryPicker) { showLibraryPicker = false }
    BackHandler(enabled = plusMenuExpanded) { dismissPlusMenu() }
    BackHandler(enabled = composerExpanded) { composerExpanded = false }
    BackHandler(enabled = drawerState.isOpen) {
        scope.launch { drawerState.close() }
    }

    BoxWithConstraints(modifier = Modifier.fillMaxSize().background(colors.canvas)) {
        val isExpandedScreen = maxWidth >= 840.dp

        val mainStage: @Composable () -> Unit = {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .onGloballyPositioned { coords ->
                        stageCoords = coords
                        refreshPlusAnchor()
                    },
            ) {
                Row(modifier = Modifier.fillMaxSize()) {
                // Expanded screen: persistent collapsible sidebar
                if (isExpandedScreen) {
                    val railWidth by animateDpAsState(
                        targetValue = if (desktopSidebarCollapsed) 68.dp else 320.dp,
                        animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
                        label = "sidebarWidth",
                    )
                    Surface(
                        color = colors.sidebar,
                        border = BorderStroke(0.5.dp, colors.line),
                        modifier = Modifier
                            .width(railWidth)
                            .fillMaxHeight(),
                    ) {
                        SidebarContent(
                            ui = ui,
                            user = user,
                            authReady = authReady,
                            collapsed = desktopSidebarCollapsed,
                            showCloseButton = false,
                            onCloseDrawer = {},
                            onNewChat = { vm.startNewConversation() },
                            onOpenSearch = { showSearch = true },
                            onRefreshConversations = { vm.refreshConversations() },
                            onSelectConv = { vm.openConversation(it) },
                            onTogglePin = { id, pin -> vm.togglePin(id, pin) },
                            onRename = { renameTarget = it },
                            onDelete = { deleteTarget = it },
                            onOpenSettings = onOpenSettings,
                        )
                    }
                }

                // Center Chat Area (100% edge-to-edge)
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight()
                        .onGloballyPositioned { coords ->
                            chatAreaCoords = coords
                            refreshBottomBlurHeight()
                        },
                ) {
                    val statusTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
                    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
                    val composerOverlayDp = with(density) { bottomOverlayHeightPx.toDp() }
                    val listTopPadding = statusTop + 68.dp
                    val listBottomPadding = (if (composerOverlayDp > 0.dp) composerOverlayDp else 108.dp + navBottom) + 16.dp

                    // 1. Messages or Empty State (also the blur source for the floating header)
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .hazeSource(headerHazeState),
                    ) {
                        if (visibleMessages.isEmpty()) {
                            Column(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .clickable(
                                        interactionSource = remember { MutableInteractionSource() },
                                        indication = null,
                                    ) {
                                        if (isInputFocused) focusManager.clearFocus()
                                    }
                                    .padding(
                                        start = 24.dp,
                                        end = 24.dp,
                                        top = listTopPadding,
                                        bottom = listBottomPadding,
                                    ),
                                verticalArrangement = Arrangement.Center,
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                val greeting = remember { currentGreeting() }
                                val name = user?.displayName?.trim().orEmpty()
                                Text(
                                    text = if (name.isNotEmpty()) "$greeting，$name" else greeting,
                                    fontSize = if (isExpandedScreen) 36.sp else 30.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    letterSpacing = (-0.6).sp,
                                    color = colors.fg,
                                    textAlign = TextAlign.Center,
                                )
                            }
                        } else {
                            LazyColumn(
                                state = listState,
                                modifier = Modifier.fillMaxSize(),
                                contentPadding = PaddingValues(
                                    start = if (isExpandedScreen) 32.dp else 16.dp,
                                    end = if (isExpandedScreen) 32.dp else 16.dp,
                                    top = listTopPadding,
                                    bottom = listBottomPadding,
                                ),
                                verticalArrangement = Arrangement.spacedBy(16.dp),
                            ) {
                                items(visibleMessages, key = { it.id }) { msg ->
                                    Box(
                                        modifier = Modifier.fillMaxWidth(),
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        Box(modifier = Modifier.widthIn(max = 780.dp).fillMaxWidth()) {
                                            val isSelected = msg.id == resolvedTurn.turnId
                                            MessageBubble(
                                                message = msg,
                                                streaming = ui.streaming,
                                                isActiveTurn = msg.id == ui.activeAssistantId,
                                                isSelectedTurn = isSelected,
                                                liveLabel = if (msg.id == ui.activeAssistantId && ui.streaming) liveStepLabel else null,
                                                turnPlan = if (isSelected) resolvedTurn.plan else null,
                                                turnReasoning = if (isSelected) resolvedTurn.reasoning else null,
                                                convFiles = ui.files,
                                                onCopy = {
                                                    scope.launch { snackbarHostState.showSnackbar("已复制到剪贴板") }
                                                },
                                                onRegenerate = { vm.regenerate(it) },
                                                onEditSubmit = { id, content -> vm.editAndResend(id, content) },
                                                onOpenTurnDetails = { id ->
                                                    vm.selectTurn(id)
                                                    onOpenTaskDetails(0)
                                                },
                                                onOpenFile = { f -> vm.openFilePreview(f) },
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 2a. Status bar scrim only (same look as the bottom scrim); the header row itself
                    //     stays fully transparent.
                    if (statusTop > 0.dp) {
                        WhitzProgressiveBlurTop(
                            modifier = Modifier
                                .align(Alignment.TopCenter)
                                .fillMaxWidth()
                                .height(statusTop + 12.dp),
                            maxAlpha = 0.85f,
                        )
                    }

                    // 2b. Floating Header: no title, frosted circular buttons only
                    Row(
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .fillMaxWidth()
                            .statusBarsPadding()
                            .padding(horizontal = 10.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        WhitzGlassCircleButton(
                            hazeState = headerHazeState,
                            showBorder = visibleMessages.isNotEmpty(),
                            onClick = {
                                if (isExpandedScreen) {
                                    desktopSidebarCollapsed = !desktopSidebarCollapsed
                                } else {
                                    scope.launch { drawerState.open() }
                                }
                            },
                        ) {
                            Icon(
                                painter = painterResource(R.drawable.ic_sidebar_toggle),
                                contentDescription = "切换侧栏",
                                tint = colors.fgMuted,
                                modifier = Modifier.size(23.dp),
                            )
                        }

                        Spacer(modifier = Modifier.weight(1f))

                        AnimatedVisibility(
                            visible = visibleMessages.isNotEmpty(),
                            enter = fadeIn(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()),
                            exit = fadeOut(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()),
                        ) {
                            Box {
                                WhitzGlassCircleButton(
                                    hazeState = headerHazeState,
                                    showBorder = visibleMessages.isNotEmpty(),
                                    onClick = { onOpenTaskDetails(0) },
                                ) {
                                    Icon(
                                        painter = painterResource(R.drawable.ic_task_panel),
                                        contentDescription = "步骤与文件",
                                        tint = colors.fgMuted,
                                        modifier = Modifier.size(22.dp),
                                    )
                                }
                                if (ui.files.isNotEmpty()) {
                                    Box(
                                        modifier = Modifier
                                            .align(Alignment.TopEnd)
                                            .padding(top = 6.dp, end = 6.dp)
                                            .size(7.dp)
                                            .clip(CircleShape)
                                            .background(colors.fg),
                                    )
                                }
                            }
                        }
                    }

                    // 3. Bottom Gradient Scrim + Floating Composer & Pending Cards
                    val bottomBlurHeightDp = if (bottomBlurHeightPx > 0) {
                        with(density) { bottomBlurHeightPx.toDp() }
                    } else {
                        56.dp + navBottom
                    }
                    WhitzProgressiveBlurBottom(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .fillMaxWidth()
                            .height(bottomBlurHeightDp),
                    )

                    val hasAttachmentsOrSkills = ui.uploads.isNotEmpty() ||
                        ui.attachedIds.isNotEmpty() ||
                        ui.selectedSkillNames.isNotEmpty()
                    val isComposerActive = isInputFocused || inputText.isNotEmpty() || hasAttachmentsOrSkills

                    val composerBottomPadding by animateDpAsState(
                        targetValue = if (isComposerActive) 10.dp else 24.dp,
                        animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
                        label = "composerBottomPadding",
                    )
                    val composerHorizontalInset by animateDpAsState(
                        targetValue = if (isComposerActive) 0.dp else if (isExpandedScreen) 64.dp else 18.dp,
                        animationSpec = MaterialTheme.motionScheme.defaultEffectsSpec(),
                        label = "composerHorizontalInset",
                    )
                    val composerCapsuleMinHeight by animateDpAsState(
                        targetValue = if (isComposerActive) 48.dp else if (isExpandedScreen) 104.dp else 62.dp,
                        animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
                        label = "composerCapsuleMinHeight",
                    )
                    val composerCapsuleCorner by animateDpAsState(
                        targetValue = if (isComposerActive) 26.dp else 30.dp,
                        animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
                        label = "composerCapsuleCorner",
                    )
                    val plusButtonSize by animateDpAsState(
                        targetValue = if (isComposerActive) 48.dp else 60.dp,
                        animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
                        label = "plusButtonSize",
                    )

                    Column(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .fillMaxWidth()
                            .onSizeChanged { bottomOverlayHeightPx = it.height }
                            .navigationBarsPadding()
                            .imePadding()
                            .padding(
                                start = if (isExpandedScreen) 24.dp else 12.dp,
                                end = if (isExpandedScreen) 24.dp else 12.dp,
                                top = 10.dp,
                                bottom = composerBottomPadding.coerceAtLeast(0.dp),
                            ),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Column(
                            modifier = Modifier.widthIn(max = 780.dp).fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            ui.pendingControl?.let { ctrl ->
                                if (ctrl.kind == "approval") {
                                    ApprovalCard(control = ctrl, onApprove = { vm.approveControl(it) })
                                } else {
                                    ClarifyCard(control = ctrl, onSubmit = { vm.clarifyControl(it) })
                                }
                            }

                            ui.pendingMemory.forEach { mem ->
                                MemoryPendingCard(
                                    item = mem,
                                    onResolve = { id, act, c -> vm.resolvePendingMemory(id, act, c) },
                                )
                            }

                            ui.pendingSkills.forEach { sk ->
                                SkillPendingCard(
                                    item = sk,
                                    onResolve = { id, act, c -> vm.resolvePendingSkill(id, act, c) },
                                )
                            }

                            val bannerError = ui.error ?: ui.fileError
                            if (!bannerError.isNullOrBlank()) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(12.dp))
                                        .background(colors.dangerWeak)
                                        .padding(horizontal = 12.dp, vertical = 8.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(bannerError, color = colors.danger, fontSize = 12.5.sp, modifier = Modifier.weight(1f))
                                    IconButton(onClick = { vm.clearError() }, modifier = Modifier.size(24.dp)) {
                                        Icon(Icons.Default.Close, contentDescription = "关闭", tint = colors.danger, modifier = Modifier.size(14.dp))
                                    }
                                }
                            }

                            // Standalone circular '+' button + borderless, shadowless input capsule
                            // (plus menu overlay lives in a separate layer above mainStage so it never shifts layout)
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .onGloballyPositioned { coords ->
                                        composerRowCoords = coords
                                        refreshBottomBlurHeight()
                                    }
                                    .padding(horizontal = composerHorizontalInset.coerceAtLeast(0.dp)),
                                verticalAlignment = Alignment.Bottom,
                            ) {
                                // Independent circular '+' button on the left
                                Box(
                                    modifier = Modifier.onGloballyPositioned { coords ->
                                        plusButtonCoords = coords
                                        refreshPlusAnchor()
                                    },
                                ) {
                                    Surface(
                                        onClick = {
                                            if (plusMenuExpanded) {
                                                dismissPlusMenu()
                                            } else {
                                                plusMenuExpanded = true
                                            }
                                        },
                                        shape = CircleShape,
                                        color = if (plusMenuExpanded) colors.hover else colors.surface,
                                        modifier = Modifier.size(plusButtonSize.coerceAtLeast(0.dp)),
                                    ) {
                                        Box(contentAlignment = Alignment.Center) {
                                            Icon(
                                                Icons.Default.Add,
                                                contentDescription = "展开工具",
                                                tint = colors.fg,
                                                modifier = Modifier.size(21.dp),
                                            )
                                        }
                                    }
                                    if (ui.selectedSkillNames.isNotEmpty()) {
                                        Box(
                                            modifier = Modifier
                                                .align(Alignment.TopEnd)
                                                .padding(3.dp)
                                                .size(8.dp)
                                                .clip(CircleShape)
                                                .background(MaterialTheme.colorScheme.primary),
                                        )
                                    }
                                }

                                Spacer(modifier = Modifier.width(8.dp))

                                // Borderless, shadowless input capsule
                                Surface(
                                    modifier = Modifier
                                        .weight(1f)
                                        .heightIn(min = composerCapsuleMinHeight.coerceAtLeast(0.dp)),
                                    shape = RoundedCornerShape(composerCapsuleCorner.coerceAtLeast(0.dp)),
                                    color = colors.surface,
                                ) {
                                        Column(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .clickable(
                                                    interactionSource = remember { MutableInteractionSource() },
                                                    indication = null,
                                                    onClick = { inputFocusRequester.requestFocus() },
                                                )
                                                .padding(horizontal = 12.dp, vertical = 6.dp),
                                            verticalArrangement = Arrangement.Center,
                                        ) {
                                            val attachedFiles = ui.files.filter { it.id in ui.attachedIds }
                                            if (ui.uploads.isNotEmpty() || attachedFiles.isNotEmpty() || ui.selectedSkillNames.isNotEmpty()) {
                                                FlowRow(
                                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                                    verticalArrangement = Arrangement.spacedBy(6.dp),
                                                    modifier = Modifier.padding(bottom = 8.dp, start = 4.dp, end = 4.dp),
                                                ) {
                                                    ui.uploads.forEach { task ->
                                                        Row(
                                                            modifier = Modifier
                                                                .clip(RoundedCornerShape(10.dp))
                                                                .background(colors.canvas)
                                                                .padding(horizontal = 8.dp, vertical = 5.dp),
                                                            verticalAlignment = Alignment.CenterVertically,
                                                        ) {
                                                            Column(modifier = Modifier.width(120.dp)) {
                                                                Text(task.filename, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, color = colors.fg)
                                                                if (task.status == UploadTaskStatus.ERROR) {
                                                                    Text(task.error ?: "失败", fontSize = 10.sp, color = colors.danger, maxLines = 1)
                                                                } else {
                                                                    Spacer(modifier = Modifier.height(2.dp))
                                                                    LinearWavyProgressIndicator(
                                                                        progress = { task.progress / 100f },
                                                                        modifier = Modifier.fillMaxWidth().height(4.dp),
                                                                    )
                                                                }
                                                            }
                                                            Spacer(modifier = Modifier.width(4.dp))
                                                            Icon(
                                                                Icons.Default.Close,
                                                                contentDescription = "取消",
                                                                tint = colors.fgFaint,
                                                                modifier = Modifier.size(14.dp).clickable { vm.cancelOrDismissUpload(task.localId) },
                                                            )
                                                        }
                                                    }

                                                    attachedFiles.forEach { f ->
                                                        Row(
                                                            modifier = Modifier
                                                                .clip(RoundedCornerShape(10.dp))
                                                                .background(colors.canvas)
                                                                .padding(horizontal = 8.dp, vertical = 4.dp),
                                                            verticalAlignment = Alignment.CenterVertically,
                                                        ) {
                                                            Icon(Icons.Default.AttachFile, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(13.dp))
                                                            Spacer(modifier = Modifier.width(4.dp))
                                                            Text(f.filename, fontSize = 12.sp, color = colors.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                                            Spacer(modifier = Modifier.width(4.dp))
                                                            Icon(
                                                                Icons.Default.Close,
                                                                contentDescription = "移除",
                                                                tint = colors.fgFaint,
                                                                modifier = Modifier.size(14.dp).clickable { vm.detachFile(f.id) },
                                                            )
                                                        }
                                                    }

                                                    ui.selectedSkillNames.forEach { sk ->
                                                        Row(
                                                            modifier = Modifier
                                                                .clip(RoundedCornerShape(10.dp))
                                                                .background(colors.canvas)
                                                                .padding(horizontal = 8.dp, vertical = 4.dp),
                                                            verticalAlignment = Alignment.CenterVertically,
                                                        ) {
                                                            Icon(Icons.Default.AutoAwesome, contentDescription = null, tint = colors.fg, modifier = Modifier.size(13.dp))
                                                            Spacer(modifier = Modifier.width(4.dp))
                                                            Text(sk, fontSize = 12.sp, color = colors.fg)
                                                            Spacer(modifier = Modifier.width(4.dp))
                                                            Icon(
                                                                Icons.Default.Close,
                                                                contentDescription = "移除技能",
                                                                tint = colors.fgFaint,
                                                                modifier = Modifier.size(14.dp).clickable { vm.toggleSkillSelection(sk) },
                                                            )
                                                        }
                                                    }
                                                }
                                            }

                                            val canExpandInput = inputText.length > 60 || inputText.contains('\n') || composerExpanded
                                            val hasActiveUploads = ui.uploads.any { it.status != UploadTaskStatus.ERROR }
                                            val canSend = inputText.isNotBlank() && !hasActiveUploads

                                            val inputMinHeight by animateDpAsState(
                                                targetValue = if (composerExpanded) 200.dp else 24.dp,
                                                animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
                                                label = "inputMinHeight",
                                            )
                                            val inputMaxHeight by animateDpAsState(
                                                targetValue = if (composerExpanded) 240.dp else 110.dp,
                                                animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
                                                label = "inputMaxHeight",
                                            )
                                            val safeInputMinHeight = inputMinHeight.coerceAtLeast(24.dp)
                                            val safeInputMaxHeight = inputMaxHeight.coerceAtLeast(safeInputMinHeight)

                                            val inputFieldContent: @Composable (Modifier) -> Unit = { fieldMod ->
                                                Box(
                                                    modifier = fieldMod.padding(horizontal = 4.dp, vertical = 6.dp),
                                                ) {
                                                    if (inputText.isEmpty()) {
                                                        Text(
                                                            text = if (ui.agentStatus?.ready == false) "助理初始化中..." else "给 Whitz 发消息...",
                                                            color = colors.fgFaint,
                                                            fontSize = 15.sp,
                                                            maxLines = 1,
                                                            overflow = TextOverflow.Ellipsis,
                                                        )
                                                    }
                                                    BasicTextField(
                                                        value = inputText,
                                                        onValueChange = {
                                                            inputText = it
                                                            if (plusMenuExpanded) dismissPlusMenu()
                                                        },
                                                        textStyle = TextStyle(
                                                            color = colors.fg,
                                                            fontSize = 15.sp,
                                                            lineHeight = 22.sp,
                                                        ),
                                                        cursorBrush = SolidColor(colors.fg),
                                                        maxLines = Int.MAX_VALUE,
                                                        modifier = Modifier
                                                            .fillMaxWidth()
                                                            .heightIn(min = safeInputMinHeight, max = safeInputMaxHeight)
                                                            .focusRequester(inputFocusRequester)
                                                            .onFocusChanged { isInputFocused = it.isFocused },
                                                    )
                                                }
                                            }

                                            val sendOrStopContent: @Composable () -> Unit = {
                                                ComposerSendOrStopButton(
                                                    streaming = ui.streaming,
                                                    canSend = canSend,
                                                    onStop = { vm.stopRun() },
                                                    onSend = {
                                                        val text = inputText
                                                        inputText = ""
                                                        composerExpanded = false
                                                        dismissPlusMenu()
                                                        vm.sendMessage(text)
                                                    },
                                                )
                                            }

                                            val expandToggleButton: @Composable () -> Unit = {
                                                IconButton(
                                                    onClick = { composerExpanded = !composerExpanded },
                                                    modifier = Modifier.size(36.dp),
                                                ) {
                                                    Icon(
                                                        imageVector = if (composerExpanded) Icons.Default.CloseFullscreen else Icons.Default.OpenInFull,
                                                        contentDescription = if (composerExpanded) "收起输入框" else "展开输入框",
                                                        tint = colors.fgMuted,
                                                        modifier = Modifier.size(16.dp),
                                                    )
                                                }
                                            }

                                            if (isExpandedScreen) {
                                                val expandedReservedEnd by animateDpAsState(
                                                    targetValue = if (canExpandInput) 40.dp else 0.dp,
                                                    animationSpec = MaterialTheme.motionScheme.defaultEffectsSpec(),
                                                    label = "expandedReservedEnd",
                                                )
                                                Box(modifier = Modifier.fillMaxWidth()) {
                                                    inputFieldContent(
                                                        Modifier
                                                            .fillMaxWidth()
                                                            .padding(end = expandedReservedEnd.coerceAtLeast(0.dp)),
                                                    )
                                                    androidx.compose.animation.AnimatedVisibility(
                                                        visible = canExpandInput,
                                                        enter = fadeIn(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
                                                            scaleIn(initialScale = 0.8f, animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()),
                                                        exit = fadeOut(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
                                                            scaleOut(targetScale = 0.8f, animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()),
                                                        modifier = Modifier.align(Alignment.TopEnd),
                                                    ) {
                                                        expandToggleButton()
                                                    }
                                                }
                                                Spacer(modifier = Modifier.height(4.dp))
                                                Row(
                                                    modifier = Modifier.fillMaxWidth(),
                                                    verticalAlignment = Alignment.CenterVertically,
                                                    horizontalArrangement = Arrangement.End,
                                                ) {
                                                    sendOrStopContent()
                                                }
                                            } else {
                                                val mobileComposerMinHeight by animateDpAsState(
                                                    targetValue = if (canExpandInput) 88.dp else 0.dp,
                                                    animationSpec = MaterialTheme.motionScheme.defaultEffectsSpec(),
                                                    label = "mobileComposerMinHeight",
                                                )
                                                Box(
                                                    modifier = Modifier
                                                        .fillMaxWidth()
                                                        .heightIn(min = mobileComposerMinHeight.coerceAtLeast(0.dp)),
                                                ) {
                                                    inputFieldContent(
                                                        Modifier
                                                            .fillMaxWidth()
                                                            .align(if (canExpandInput || composerExpanded) Alignment.TopStart else Alignment.CenterStart)
                                                            .padding(end = 44.dp),
                                                    )
                                                    androidx.compose.animation.AnimatedVisibility(
                                                        visible = canExpandInput,
                                                        enter = fadeIn(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
                                                            scaleIn(initialScale = 0.8f, animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()),
                                                        exit = fadeOut(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
                                                            scaleOut(targetScale = 0.8f, animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()),
                                                        modifier = Modifier.align(Alignment.TopEnd),
                                                    ) {
                                                        expandToggleButton()
                                                    }
                                                    Box(modifier = Modifier.align(Alignment.BottomEnd)) {
                                                        sendOrStopContent()
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                    SnackbarHost(
                        hostState = snackbarHostState,
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .navigationBarsPadding()
                            .padding(bottom = 90.dp),
                    )
                }
            }

                ComposerPlusMenuOverlay(
                    visible = plusMenuExpanded,
                    anchorBounds = { plusAnchorBounds },
                    selectedSkillCount = ui.selectedSkillNames.size,
                    showAttachMenu = showAttachMenu,
                    onDismiss = dismissPlusMenu,
                    onOpenAttachMenu = { showAttachMenu = true },
                    onDismissAttachMenu = { showAttachMenu = false },
                    onUploadLocalFile = {
                        dismissPlusMenu()
                        filePickerLauncher.launch(arrayOf("*/*"))
                    },
                    onPickFromLibrary = {
                        dismissPlusMenu()
                        showLibraryPicker = true
                    },
                    onOpenSkillPicker = {
                        dismissPlusMenu()
                        showSkillPicker = true
                    },
                )
            }
        }

        if (isExpandedScreen) {
            mainStage()
        } else {
            ModalNavigationDrawer(
                drawerState = drawerState,
                drawerContent = {
                    ModalDrawerSheet(
                        drawerContainerColor = colors.sidebar,
                        windowInsets = WindowInsets(0),
                        modifier = Modifier.width(332.dp),
                    ) {
                        SidebarContent(
                            ui = ui,
                            user = user,
                            authReady = authReady,
                            collapsed = false,
                            showCloseButton = true,
                            onCloseDrawer = { scope.launch { drawerState.close() } },
                            onNewChat = {
                                vm.startNewConversation()
                                scope.launch { drawerState.close() }
                            },
                            onOpenSearch = { showSearch = true },
                            onRefreshConversations = { vm.refreshConversations() },
                            onSelectConv = {
                                vm.openConversation(it)
                                scope.launch { drawerState.close() }
                            },
                            onTogglePin = { id, pin -> vm.togglePin(id, pin) },
                            onRename = { renameTarget = it },
                            onDelete = { deleteTarget = it },
                            onOpenSettings = {
                                scope.launch { drawerState.close() }
                                onOpenSettings()
                            },
                        )
                    }
                },
            ) {
                mainStage()
            }
        }
    }

    // Dialogs & Sheets
    if (showSearch) {
        SearchDialog(
            results = ui.searchResults,
            searching = ui.searching,
            onQueryChange = { vm.searchConversations(it) },
            onSelectConversation = { id ->
                vm.openConversation(id)
                scope.launch { drawerState.close() }
            },
            onDismiss = { showSearch = false },
        )
    }

    if (showSkillPicker) {
        SkillPickerDialog(
            skills = ui.enabledSkills,
            selectedNames = ui.selectedSkillNames,
            onToggle = { vm.toggleSkillSelection(it) },
            onDismiss = { showSkillPicker = false },
        )
    }

    if (showLibraryPicker) {
        LibraryAttachDialog(
            fetchLibrary = { q -> vm.fetchLibraryFiles(q) },
            onAttach = { ids -> vm.attachFromLibrary(ids) },
            onDismiss = { showLibraryPicker = false },
        )
    }

    ui.previewTarget?.let { target ->
        FilePreviewDialog(target = target, onDismiss = { vm.closeFilePreview() })
    }

    renameTarget?.let { conv ->
        var newTitle by remember(conv.id) { mutableStateOf(conv.title) }
        AlertDialog(
            onDismissRequest = { renameTarget = null },
            containerColor = colors.canvas,
            title = { Text("重命名对话", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = {
                WhitzTextField(
                    value = newTitle,
                    onValueChange = { newTitle = it },
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            dismissButton = { TextButton(onClick = { renameTarget = null }) { Text("取消") } },
            confirmButton = {
                Button(
                    onClick = {
                        vm.renameConversation(conv.id, newTitle)
                        renameTarget = null
                    },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text("保存") }
            },
        )
    }

    deleteTarget?.let { conv ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            containerColor = colors.canvas,
            title = { Text("删除对话", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = { Text("确定要删除「${conv.title}」吗？删除后无法恢复。", color = colors.fgMuted) },
            dismissButton = { TextButton(onClick = { deleteTarget = null }) { Text("取消") } },
            confirmButton = {
                Button(
                    onClick = {
                        vm.deleteConversation(conv.id)
                        deleteTarget = null
                    },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = colors.danger),
                ) { Text("删除") }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun SidebarContent(
    ui: ChatUiState,
    user: User?,
    authReady: Boolean,
    collapsed: Boolean,
    showCloseButton: Boolean,
    onCloseDrawer: () -> Unit,
    onNewChat: () -> Unit,
    onOpenSearch: () -> Unit,
    onRefreshConversations: () -> Unit,
    onSelectConv: (String) -> Unit,
    onTogglePin: (String, Boolean) -> Unit,
    onRename: (Conversation) -> Unit,
    onDelete: (Conversation) -> Unit,
    onOpenSettings: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .padding(horizontal = 10.dp),
    ) {
        // Brand Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (collapsed) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .clickable(onClick = onNewChat),
                    contentAlignment = Alignment.Center,
                ) {
                    WhitzLogoMark(modifier = Modifier.size(26.dp))
                }
            } else {
                WhitzBrandMark(
                    modifier = Modifier
                        .clip(RoundedCornerShape(10.dp))
                        .clickable(onClick = onNewChat)
                        .padding(horizontal = 4.dp, vertical = 4.dp),
                )
                Spacer(modifier = Modifier.weight(1f))
                if (showCloseButton) {
                    IconButton(onClick = onCloseDrawer, modifier = Modifier.size(34.dp)) {
                        Icon(Icons.Default.Close, contentDescription = "关闭侧栏", tint = colors.fgFaint, modifier = Modifier.size(18.dp))
                    }
                }
            }
        }

        // Action Buttons: New Chat & Search
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(42.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .clickable(onClick = onNewChat)
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Add, contentDescription = "新建对话", tint = colors.fg, modifier = Modifier.size(20.dp))
                if (!collapsed) {
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("新建对话", fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(42.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .clickable(onClick = onOpenSearch)
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Search, contentDescription = "搜索对话", tint = colors.fgMuted, modifier = Modifier.size(19.dp))
                if (!collapsed) {
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("搜索对话", fontSize = 14.5.sp, fontWeight = FontWeight.Medium, color = colors.fgMuted)
                }
            }
        }

        Spacer(modifier = Modifier.height(10.dp))

        // Conversation List
        if (collapsed) {
            Spacer(modifier = Modifier.weight(1f))
        } else {
            val pinned = remember(ui.conversations) { ui.conversations.filter { it.isPinned } }
            val recent = remember(ui.conversations) { ui.conversations.filterNot { it.isPinned } }
            val showColdStartLoading = (!authReady || ui.conversationsLoading) && ui.conversations.isEmpty()

            if (showColdStartLoading) {
                // Cold-start loading indicator: large, centered, and independent from pull-to-refresh
                Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    WhitzLoadingIndicator(size = 56.dp)
                }
            } else {
                val pullRefreshState = rememberPullToRefreshState()
                PullToRefreshBox(
                    isRefreshing = ui.conversationsRefreshing,
                    onRefresh = onRefreshConversations,
                    state = pullRefreshState,
                    indicator = {
                        PullToRefreshDefaults.LoadingIndicator(
                            state = pullRefreshState,
                            isRefreshing = ui.conversationsRefreshing,
                            modifier = Modifier.align(Alignment.TopCenter),
                        )
                    },
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                ) {
                    if (ui.conversations.isEmpty()) {
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .verticalScroll(rememberScrollState()),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("暂无历史对话", color = colors.fgFaint, fontSize = 13.sp)
                        }
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(vertical = 6.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            if (pinned.isNotEmpty()) {
                                item(key = "hdr-pinned") {
                                    Text(
                                        text = "置顶对话",
                                        fontSize = 11.5.sp,
                                        fontWeight = FontWeight.Medium,
                                        color = colors.fgFaint,
                                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                                    )
                                }
                                items(pinned, key = { it.id }) { conv ->
                                    ConversationRow(
                                        conv = conv,
                                        selected = conv.id == ui.currentConvId,
                                        onSelect = { onSelectConv(conv.id) },
                                        onTogglePin = { onTogglePin(conv.id, !conv.isPinned) },
                                        onRename = { onRename(conv) },
                                        onDelete = { onDelete(conv) },
                                    )
                                }
                            }

                            if (recent.isNotEmpty()) {
                                if (pinned.isNotEmpty()) {
                                    item(key = "hdr-recent") {
                                        Text(
                                            text = "最近对话",
                                            fontSize = 11.5.sp,
                                            fontWeight = FontWeight.Medium,
                                            color = colors.fgFaint,
                                            modifier = Modifier.padding(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 4.dp),
                                        )
                                    }
                                }
                                items(recent, key = { it.id }) { conv ->
                                    ConversationRow(
                                        conv = conv,
                                        selected = conv.id == ui.currentConvId,
                                        onSelect = { onSelectConv(conv.id) },
                                        onTogglePin = { onTogglePin(conv.id, !conv.isPinned) },
                                        onRename = { onRename(conv) },
                                        onDelete = { onDelete(conv) },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        // Footer: User profile (pure without divider or settings icon)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp, bottom = navBottom + 10.dp)
                .clip(RoundedCornerShape(14.dp))
                .clickable(onClick = onOpenSettings)
                .padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!user?.avatarUrl.isNullOrBlank()) {
                AsyncImage(
                    model = user?.avatarUrl,
                    contentDescription = "头像",
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.size(34.dp).clip(CircleShape),
                )
            } else {
                Box(
                    modifier = Modifier
                        .size(34.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primary),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = (user?.displayName?.firstOrNull() ?: 'U').uppercase(),
                        color = MaterialTheme.colorScheme.onPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 14.sp,
                    )
                }
            }
            if (!collapsed) {
                Spacer(modifier = Modifier.width(10.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = user?.displayName ?: "未登录",
                        fontSize = 13.5.sp,
                        fontWeight = FontWeight.Medium,
                        color = colors.fg,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    val creditsLabel = ui.credits?.let { "${it.tierLabel} · ${it.quotaPercentLabel()}" }
                        ?: (user?.email ?: "")
                    Text(
                        text = creditsLabel,
                        fontSize = 11.sp,
                        color = colors.fgFaint,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun ConversationRow(
    conv: Conversation,
    selected: Boolean,
    onSelect: () -> Unit,
    onTogglePin: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    var menuOpen by remember(conv.id) { mutableStateOf(false) }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(if (selected) colors.hover else colors.sidebar)
            .clickable(onClick = onSelect)
            .padding(start = 10.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (conv.isPinned) {
            Icon(
                Icons.Default.PushPin,
                contentDescription = "已置顶",
                tint = colors.fgFaint,
                modifier = Modifier.size(13.dp),
            )
            Spacer(modifier = Modifier.width(6.dp))
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = conv.title.ifBlank { "新对话" },
                fontSize = 13.5.sp,
                fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
                color = if (selected) colors.fg else colors.fgMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val time = DateTimeUtils.formatShort(conv.lastMessageAt ?: conv.updatedAt)
            if (time.isNotBlank()) {
                Text(time, fontSize = 10.5.sp, color = colors.fgFaint)
            }
        }
        Box {
            IconButton(onClick = { menuOpen = true }, modifier = Modifier.size(28.dp)) {
                Icon(Icons.Default.MoreHoriz, contentDescription = "更多", tint = colors.fgFaint, modifier = Modifier.size(16.dp))
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                DropdownMenuItem(
                    text = { Text(if (conv.isPinned) "取消置顶" else "置顶对话") },
                    leadingIcon = { Icon(Icons.Default.PushPin, contentDescription = null) },
                    onClick = {
                        menuOpen = false
                        onTogglePin()
                    },
                )
                DropdownMenuItem(
                    text = { Text("重命名") },
                    leadingIcon = { Icon(Icons.Default.Edit, contentDescription = null) },
                    onClick = {
                        menuOpen = false
                        onRename()
                    },
                )
                DropdownMenuItem(
                    text = { Text("删除", color = colors.danger) },
                    leadingIcon = { Icon(Icons.Default.Delete, contentDescription = null, tint = colors.danger) },
                    onClick = {
                        menuOpen = false
                        onDelete()
                    },
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun ComposerPlusMenuOverlay(
    visible: Boolean,
    anchorBounds: () -> Rect?,
    selectedSkillCount: Int,
    showAttachMenu: Boolean,
    onDismiss: () -> Unit,
    onOpenAttachMenu: () -> Unit,
    onDismissAttachMenu: () -> Unit,
    onUploadLocalFile: () -> Unit,
    onPickFromLibrary: () -> Unit,
    onOpenSkillPicker: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val spatialFloatSpec = MaterialTheme.motionScheme.fastSpatialSpec<Float>()
    val effectsSpec = MaterialTheme.motionScheme.fastEffectsSpec<Float>()

    // Scrim outside the card: tapping any other area dismisses the card
    if (visible) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                    onClick = onDismiss,
                ),
        )
    }

    // Separated full-stage overlay pass so opening the card never shifts the composer or message list
    Layout(
        modifier = Modifier.fillMaxSize(),
        content = {
            AnimatedVisibility(
                visible = visible && anchorBounds() != null,
                enter = scaleIn(
                    initialScale = 0.55f,
                    transformOrigin = TransformOrigin(0f, 1f),
                    animationSpec = spatialFloatSpec,
                ) + fadeIn(animationSpec = effectsSpec),
                exit = scaleOut(
                    targetScale = 0.55f,
                    transformOrigin = TransformOrigin(0f, 1f),
                    animationSpec = spatialFloatSpec,
                ) + fadeOut(animationSpec = effectsSpec),
            ) {
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = colors.hover,
                    modifier = Modifier.clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = {},
                    ),
                ) {
                    Column(
                        modifier = Modifier
                            .width(172.dp)
                            .padding(6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Box {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(42.dp)
                                    .clip(RoundedCornerShape(14.dp))
                                    .clickable(onClick = onOpenAttachMenu)
                                    .padding(horizontal = 12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(
                                    Icons.Default.AttachFile,
                                    contentDescription = "文件上传",
                                    tint = colors.fg,
                                    modifier = Modifier.size(18.dp),
                                )
                                Spacer(modifier = Modifier.width(10.dp))
                                Text(
                                    text = "文件上传",
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = colors.fg,
                                )
                            }
                            DropdownMenu(
                                expanded = showAttachMenu,
                                onDismissRequest = onDismissAttachMenu,
                            ) {
                                DropdownMenuItem(
                                    text = { Text("上传本地文件") },
                                    leadingIcon = { Icon(Icons.Default.UploadFile, contentDescription = null) },
                                    onClick = onUploadLocalFile,
                                )
                                DropdownMenuItem(
                                    text = { Text("从文件库选择") },
                                    leadingIcon = { Icon(Icons.Default.FolderOpen, contentDescription = null) },
                                    onClick = onPickFromLibrary,
                                )
                            }
                        }

                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(42.dp)
                                .clip(RoundedCornerShape(14.dp))
                                .background(if (selectedSkillCount > 0) colors.active else Color.Transparent)
                                .clickable(onClick = onOpenSkillPicker)
                                .padding(horizontal = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(
                                Icons.Default.AutoAwesome,
                                contentDescription = "技能",
                                tint = colors.fg,
                                modifier = Modifier.size(18.dp),
                            )
                            Spacer(modifier = Modifier.width(10.dp))
                            Text(
                                text = if (selectedSkillCount > 0) "技能 ($selectedSkillCount)" else "技能",
                                fontSize = 14.sp,
                                fontWeight = FontWeight.Medium,
                                color = colors.fg,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
        },
    ) { measurables, constraints ->
        val placeables = measurables.map { it.measure(constraints.copy(minWidth = 0, minHeight = 0)) }
        layout(constraints.maxWidth, constraints.maxHeight) {
            val bounds = anchorBounds()
            if (bounds != null) {
                placeables.forEach { placeable ->
                    val x = bounds.left.roundToInt().coerceIn(
                        0,
                        (constraints.maxWidth - placeable.width).coerceAtLeast(0),
                    )
                    // Align bottom-left of card with bottom-left of '+' button so it expands upward in place
                    val y = (bounds.bottom.roundToInt() - placeable.height).coerceAtLeast(0)
                    placeable.place(x, y)
                }
            }
        }
    }
}

@Composable
private fun ComposerSendOrStopButton(
    streaming: Boolean,
    canSend: Boolean,
    onStop: () -> Unit,
    onSend: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    if (streaming) {
        IconButton(
            onClick = onStop,
            modifier = Modifier
                .size(36.dp)
                .clip(CircleShape)
                .background(colors.canvas),
        ) {
            Icon(
                Icons.Default.Stop,
                contentDescription = "停止生成",
                tint = colors.fg,
                modifier = Modifier.size(18.dp),
            )
        }
    } else {
        IconButton(
            onClick = onSend,
            enabled = canSend,
            modifier = Modifier
                .size(36.dp)
                .clip(CircleShape)
                .background(if (canSend) MaterialTheme.colorScheme.primary else colors.hover),
        ) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowForward,
                contentDescription = "发送",
                tint = if (canSend) MaterialTheme.colorScheme.onPrimary else colors.fgFaint,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}

