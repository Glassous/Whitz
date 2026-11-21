package com.glassous.whitz.feature.chat

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.BoundsTransform
import androidx.compose.animation.ExperimentalSharedTransitionApi
import androidx.compose.animation.SharedTransitionLayout
import androidx.compose.animation.SharedTransitionScope
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
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
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.OpenInFull
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.SelectAll
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
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import coil3.compose.AsyncImage
import com.glassous.whitz.R
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.Message
import com.glassous.whitz.core.model.UploadTaskStatus
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.model.quotaPercentLabel
import com.glassous.whitz.core.model.resolvedAssistantName
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

internal const val SHARED_KEY_ASSISTANT_AVATAR = "main_assistant_avatar"
internal const val SHARED_KEY_ASSISTANT_NAME = "main_assistant_name"

@OptIn(ExperimentalSharedTransitionApi::class)
internal val MainAssistantBoundsTransform = BoundsTransform { _, _ ->
    tween(durationMillis = 360, easing = FastOutSlowInEasing)
}

@OptIn(
    ExperimentalMaterial3ExpressiveApi::class,
    ExperimentalLayoutApi::class,
    ExperimentalSharedTransitionApi::class,
)
@Composable
fun ChatScreen(
    vm: ChatViewModel,
    onOpenSettings: () -> Unit,
    onOpenLibrary: () -> Unit,
    onOpenTaskDetails: (Int) -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val user by vm.user.collectAsState()
    val authReady by vm.authReady.collectAsState()
    val colors = LocalWhitzColors.current
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val conversationScrollKey = ui.currentConvId ?: "local-new"
    val listState = rememberSaveable(conversationScrollKey, saver = LazyListState.Saver) {
        LazyListState()
    }
    val snackbarHostState = remember { SnackbarHostState() }
    val density = LocalDensity.current
    val focusManager = LocalFocusManager.current
    val clipboard = LocalClipboardManager.current
    val inputFocusRequester = remember { FocusRequester() }
    val headerHazeState = rememberHazeState()

    var inputText by remember { mutableStateOf("") }
    var queuedSend by remember { mutableStateOf(false) }
    var isInputFocused by remember { mutableStateOf(false) }
    var composerExpanded by remember { mutableStateOf(false) }
    var plusMenuExpanded by remember { mutableStateOf(false) }
    var showSearch by remember { mutableStateOf(false) }
    var showSkillPicker by remember { mutableStateOf(false) }
    var showLibraryPicker by remember { mutableStateOf(false) }
    var desktopSidebarCollapsed by rememberSaveable { mutableStateOf(false) }
    var mainPanelOpen by rememberSaveable { mutableStateOf(false) }
    var showAttachMenu by remember { mutableStateOf(false) }
    var editingMessage by remember { mutableStateOf<Message?>(null) }
    var savedDraftBeforeEdit by remember { mutableStateOf<String?>(null) }
    var selectingTextMessageId by remember { mutableStateOf<String?>(null) }
    var dislikeReasonMessageId by remember { mutableStateOf<String?>(null) }
    var messageMenuVisible by remember { mutableStateOf(false) }
    var messageMenuTarget by remember { mutableStateOf<MessageMenuTarget?>(null) }

    val cancelEdit = {
        editingMessage = null
        savedDraftBeforeEdit?.let { inputText = it }
        savedDraftBeforeEdit = null
    }

    LaunchedEffect(conversationScrollKey) {
        editingMessage = null
        savedDraftBeforeEdit = null
        selectingTextMessageId = null
        dislikeReasonMessageId = null
        messageMenuVisible = false
    }

    LaunchedEffect(ui.isMainChat) {
        if (!ui.isMainChat) mainPanelOpen = false
    }

    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                vm.recoverIfNeeded()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

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

    LaunchedEffect(ui.hasActiveUploads) {
        if (!ui.hasActiveUploads && queuedSend) {
            queuedSend = false
            val trimmed = inputText.trim()
            if (trimmed.isNotEmpty() && !ui.streaming && !ui.sendingMessage) {
                inputText = ""
                composerExpanded = false
                dismissPlusMenu()
                vm.sendMessage(trimmed)
            }
        }
    }

    val visibleMessages = remember(ui.messages) { filterVisibleMessages(ui.messages) }
    val runningToolName = remember(ui.messages, ui.streaming) {
        if (ui.streaming) computeRunningTool(ui.messages) else null
    }
    val currentStepInfo = remember(ui.plan, ui.streaming) {
        if (ui.streaming) computeCurrentStep(ui.plan) else null
    }
    val liveStepLabel = remember(
        currentStepInfo,
        runningToolName,
        ui.plan,
        ui.streaming,
        ui.stopping,
        ui.reconnecting,
        ui.waitingFirstByte,
    ) {
        if (ui.streaming) {
            computeLiveStepLabel(
                currentStep = currentStepInfo,
                runningTool = runningToolName,
                plan = ui.plan,
                stopping = ui.stopping,
                reconnecting = ui.reconnecting,
                waitingFirstByte = ui.waitingFirstByte,
            )
        } else null
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

    // Top of the newest message must clear the floating header (status bar + button/avatar row),
    // otherwise the first line of that message is hidden behind the floating header.
    val revealTopOffsetPx = with(density) {
        (WindowInsets.statusBars.asPaddingValues().calculateTopPadding() + if (ui.isMainChat) 130.dp else 68.dp).roundToPx()
    }
    var revealedConversationKey by rememberSaveable { mutableStateOf<String?>(null) }
    var lastScrolledMsgCount by rememberSaveable { mutableIntStateOf(0) }
    var lastScrolledLastLen by rememberSaveable { mutableIntStateOf(0) }
    var isInitialEffect by remember { mutableStateOf(true) }

    val lastMsgContentLen = visibleMessages.lastOrNull()?.content?.length ?: 0
    LaunchedEffect(conversationScrollKey, visibleMessages.size, lastMsgContentLen) {
        if (visibleMessages.isEmpty()) {
            revealedConversationKey = null
            lastScrolledMsgCount = 0
            lastScrolledLastLen = 0
            isInitialEffect = false
            return@LaunchedEffect
        }
        val lastIndex = visibleMessages.lastIndex
        // Entering a new conversation jumps straight to the top of the newest message.
        // Returning from another page (steps or settings) preserves the reader's current scroll position.
        if (revealedConversationKey != conversationScrollKey) {
            revealedConversationKey = conversationScrollKey
            lastScrolledMsgCount = visibleMessages.size
            lastScrolledLastLen = lastMsgContentLen
            isInitialEffect = false
            listState.scrollToItem(lastIndex, scrollOffset = -revealTopOffsetPx)
        } else if (isInitialEffect) {
            lastScrolledMsgCount = visibleMessages.size
            lastScrolledLastLen = lastMsgContentLen
            isInitialEffect = false
        } else if (visibleMessages.size != lastScrolledMsgCount || lastMsgContentLen != lastScrolledLastLen) {
            lastScrolledMsgCount = visibleMessages.size
            lastScrolledLastLen = lastMsgContentLen
            listState.animateScrollToItem(lastIndex, scrollOffset = -revealTopOffsetPx)
        }
    }

    val locateMessage: (String) -> Unit = { msgId ->
        val idx = visibleMessages.indexOfFirst { it.id == msgId }
        if (idx >= 0) {
            scope.launch {
                listState.animateScrollToItem(idx, scrollOffset = -revealTopOffsetPx)
            }
        }
    }

    // Back key handling: overlays & drawer close before exiting
    BackHandler(enabled = ui.previewTarget != null) { vm.closeFilePreview() }
    BackHandler(enabled = messageMenuVisible) { messageMenuVisible = false }
    BackHandler(enabled = selectingTextMessageId != null) { selectingTextMessageId = null }
    BackHandler(enabled = editingMessage != null) { cancelEdit() }
    BackHandler(enabled = showSearch) { showSearch = false }
    BackHandler(enabled = showSkillPicker) { showSkillPicker = false }
    BackHandler(enabled = showLibraryPicker) { showLibraryPicker = false }
    BackHandler(enabled = plusMenuExpanded) { dismissPlusMenu() }
    BackHandler(enabled = mainPanelOpen) { mainPanelOpen = false }
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
                            resolveAssetUrl = { vm.resolveAssetUrl(it) },
                            onCloseDrawer = {},
                            onSelectMain = { vm.openMainConversation() },
                            onCreateSide = { vm.createSideConversation() },
                            onOpenLibrary = onOpenLibrary,
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
                SharedTransitionLayout(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight(),
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .onGloballyPositioned { coords ->
                                chatAreaCoords = coords
                                refreshBottomBlurHeight()
                            },
                    ) {
                        val statusTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
                        val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
                        val composerOverlayDp = with(density) { bottomOverlayHeightPx.toDp() }
                        val listTopPadding = statusTop + if (ui.isMainChat) 130.dp else 68.dp
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
                                Spacer(modifier = Modifier.height(10.dp))
                                Text(
                                    text = if (ui.isMainChat) {
                                        "我是你的专属助手 $assistantName，随时关联你的所有旁聊与资料库。今天想做点什么？"
                                    } else {
                                        "新建旁聊专注讨论单个主题；发送的文件会自动沉淀到全局资料库。"
                                    },
                                    fontSize = 14.sp,
                                    lineHeight = 20.sp,
                                    color = colors.fgMuted,
                                    textAlign = TextAlign.Center,
                                    modifier = Modifier.widthIn(max = 460.dp),
                                )
                            }
                        } else {
                            key(conversationScrollKey) {
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
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .animateItem(fadeOutSpec = null),
                                            contentAlignment = Alignment.Center,
                                        ) {
                                            Box(modifier = Modifier.widthIn(max = 780.dp).fillMaxWidth()) {
                                                val isSelected = msg.id == resolvedTurn.turnId
                                                MessageBubble(
                                                    message = msg,
                                                    streaming = ui.streaming,
                                                    hasActiveUploads = ui.hasActiveUploads,
                                                    reconnecting = ui.reconnecting,
                                                    waitingFirstByte = ui.waitingFirstByte,
                                                    isActiveTurn = msg.id == ui.activeAssistantId,
                                                    isSelectedTurn = isSelected,
                                                    isEditing = msg.id == editingMessage?.id,
                                                    isSelectingText = msg.id == selectingTextMessageId,
                                                    showDislikeReasons = msg.id == dislikeReasonMessageId,
                                                    liveLabel = if (msg.id == ui.activeAssistantId && ui.streaming) liveStepLabel else null,
                                                    turnPlan = if (isSelected) resolvedTurn.plan else null,
                                                    turnReasoning = if (isSelected) resolvedTurn.reasoning else null,
                                                    convFiles = ui.files,
                                                    assistantName = user?.resolvedAssistantName() ?: "Whitz",
                                                    onRegenerate = { vm.regenerate(it) },
                                                    onExitTextSelection = {
                                                        if (selectingTextMessageId == msg.id) {
                                                            selectingTextMessageId = null
                                                        }
                                                    },
                                                    onDismissDislikeReasons = {
                                                        if (dislikeReasonMessageId == msg.id) {
                                                            dislikeReasonMessageId = null
                                                        }
                                                    },
                                                    onLongPress = { windowOffset ->
                                                        val stage = stageCoords
                                                        if (stage != null && stage.isAttached) {
                                                            focusManager.clearFocus()
                                                            dismissPlusMenu()
                                                            selectingTextMessageId = null
                                                            messageMenuTarget = MessageMenuTarget(
                                                                message = msg,
                                                                anchorInStage = stage.windowToLocal(windowOffset),
                                                            )
                                                            messageMenuVisible = true
                                                        }
                                                    },
                                                    onOpenTurnDetails = { id ->
                                                        vm.selectTurn(id)
                                                        if (ui.isMainChat) {
                                                            mainPanelOpen = true
                                                        } else {
                                                            onOpenTaskDetails(0)
                                                        }
                                                    },
                                                    onOpenFile = { f -> vm.openFilePreview(f) },
                                                    onReact = { msgId, reaction, reasonCode ->
                                                        vm.reactToMessage(msgId, reaction, reasonCode)
                                                    },
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 2a. Top gradient scrim
                    if (statusTop > 0.dp || ui.isMainChat) {
                        WhitzProgressiveBlurTop(
                            modifier = Modifier
                                .align(Alignment.TopCenter)
                                .fillMaxWidth()
                                .height(statusTop + if (ui.isMainChat) 122.dp else 12.dp),
                            maxAlpha = 0.85f,
                        )
                    }

                    // 2b. Floating Header:
                    // - Main Chat: left sidebar button + enlarged centered Assistant Avatar & 80%-opaque capsule Nickname (shared element -> task panel), right toggle hidden
                    // - Side Chat: left sidebar button + right task panel toggle (unchanged)
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .fillMaxWidth()
                            .statusBarsPadding()
                            .padding(horizontal = 10.dp, vertical = 10.dp),
                    ) {
                        WhitzGlassCircleButton(
                            hazeState = headerHazeState,
                            showBorder = visibleMessages.isNotEmpty(),
                            modifier = Modifier.align(Alignment.TopStart),
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

                        if (ui.isMainChat) {
                            val mainAvatarUrl = vm.resolveAssetUrl(user?.assistantAvatarUrl)
                            androidx.compose.animation.AnimatedVisibility(
                                visible = !mainPanelOpen,
                                enter = fadeIn(tween(220)),
                                exit = fadeOut(tween(180)),
                                modifier = Modifier.align(Alignment.TopCenter),
                            ) {
                                val avatarSharedModifier = with(this@SharedTransitionLayout) {
                                    Modifier.sharedBounds(
                                        sharedContentState = rememberSharedContentState(key = SHARED_KEY_ASSISTANT_AVATAR),
                                        animatedVisibilityScope = this@AnimatedVisibility,
                                        boundsTransform = MainAssistantBoundsTransform,
                                        zIndexInOverlay = 2f,
                                    )
                                }
                                val nameSharedModifier = with(this@SharedTransitionLayout) {
                                    Modifier.sharedBounds(
                                        sharedContentState = rememberSharedContentState(key = SHARED_KEY_ASSISTANT_NAME),
                                        animatedVisibilityScope = this@AnimatedVisibility,
                                        boundsTransform = MainAssistantBoundsTransform,
                                        resizeMode = SharedTransitionScope.ResizeMode.scaleToBounds(),
                                        zIndexInOverlay = 2f,
                                    )
                                }
                                Column(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(24.dp))
                                        .clickable(
                                            interactionSource = remember { MutableInteractionSource() },
                                            indication = null,
                                        ) {
                                            focusManager.clearFocus()
                                            mainPanelOpen = true
                                        }
                                        .padding(horizontal = 16.dp, vertical = 2.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                ) {
                                    Box(
                                        modifier = avatarSharedModifier
                                            .size(60.dp)
                                            .clip(CircleShape)
                                            .background(colors.surface)
                                            .border(1.dp, colors.line, CircleShape),
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        if (!mainAvatarUrl.isNullOrBlank()) {
                                            AsyncImage(
                                                model = mainAvatarUrl,
                                                contentDescription = assistantName,
                                                contentScale = ContentScale.Crop,
                                                modifier = Modifier.fillMaxSize(),
                                            )
                                        } else {
                                            WhitzLogoMark(modifier = Modifier.size(30.dp))
                                        }
                                    }
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Surface(
                                        shape = CircleShape,
                                        color = colors.surface.copy(alpha = 0.80f),
                                        border = BorderStroke(0.5.dp, colors.line.copy(alpha = 0.65f)),
                                    ) {
                                        Text(
                                            text = assistantName,
                                            fontSize = 15.5.sp,
                                            fontWeight = FontWeight.SemiBold,
                                            color = colors.fg,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                            modifier = nameSharedModifier
                                                .padding(horizontal = 14.dp, vertical = 4.dp)
                                                .widthIn(max = 200.dp),
                                        )
                                    }
                                }
                            }
                        } else {
                            androidx.compose.animation.AnimatedVisibility(
                                visible = visibleMessages.isNotEmpty(),
                                enter = fadeIn(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()),
                                exit = fadeOut(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()),
                                modifier = Modifier.align(Alignment.TopEnd),
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
                    }

                    // 2c. Subtle background sync transition pill when showing cached homepage data
                    androidx.compose.animation.AnimatedVisibility(
                        visible = ui.initialRefreshing && ui.isMainChat && !mainPanelOpen,
                        enter = fadeIn(tween(220)) + slideInVertically(tween(260)) { -it / 2 },
                        exit = fadeOut(tween(280)) + slideOutVertically(tween(240)) { -it / 2 },
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .padding(top = statusTop + 124.dp),
                    ) {
                        Surface(
                            shape = CircleShape,
                            color = colors.surface.copy(alpha = 0.92f),
                            border = BorderStroke(0.5.dp, colors.line),
                            shadowElevation = 2.dp,
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                WhitzLoadingIndicator(size = 14.dp)
                                Text(
                                    text = if (ui.showingCachedData) "正在同步最新对话…" else "加载中…",
                                    fontSize = 11.5.sp,
                                    color = colors.fgMuted,
                                )
                            }
                        }
                    }

                    // 2d. Conversation switching loading indicator
                    androidx.compose.animation.AnimatedVisibility(
                        visible = ui.switchingConversation && !mainPanelOpen,
                        enter = fadeIn(tween(180)) + scaleIn(
                            initialScale = 0.90f,
                            animationSpec = tween(220, easing = FastOutSlowInEasing),
                        ),
                        exit = fadeOut(tween(160)) + scaleOut(
                            targetScale = 0.94f,
                            animationSpec = tween(160, easing = FastOutSlowInEasing),
                        ),
                        modifier = Modifier.align(Alignment.Center),
                    ) {
                        Surface(
                            shape = RoundedCornerShape(20.dp),
                            color = colors.surface.copy(alpha = 0.95f),
                            border = BorderStroke(0.5.dp, colors.line),
                            shadowElevation = 8.dp,
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 18.dp, vertical = 12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                WhitzLoadingIndicator(size = 20.dp)
                                Text(
                                    text = "正在加载对话…",
                                    fontSize = 13.5.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = colors.fg,
                                )
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
                        ui.selectedSkillNames.isNotEmpty() ||
                        editingMessage != null
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
                                    ApprovalCard(
                                        control = ctrl,
                                        submittingChoice = ui.approvingChoice,
                                        onApprove = { vm.approveControl(it) },
                                    )
                                } else {
                                    ClarifyCard(
                                        control = ctrl,
                                        submitting = ui.submittingClarify,
                                        onSubmit = { vm.clarifyControl(it) },
                                    )
                                }
                            }

                            ui.pendingMemory.forEach { mem ->
                                MemoryPendingCard(
                                    item = mem,
                                    busy = mem.id in ui.resolvingMemoryIds,
                                    onResolve = { id, act, c -> vm.resolvePendingMemory(id, act, c) },
                                )
                            }

                            ui.pendingSkills.forEach { sk ->
                                SkillPendingCard(
                                    item = sk,
                                    busy = sk.id in ui.resolvingSkillIds,
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
                                            editingMessage?.let { editMsg ->
                                                Row(
                                                    modifier = Modifier
                                                        .fillMaxWidth()
                                                        .padding(bottom = 6.dp)
                                                        .clip(RoundedCornerShape(12.dp))
                                                        .background(colors.canvas)
                                                        .border(0.5.dp, colors.line, RoundedCornerShape(12.dp))
                                                        .clickable { locateMessage(editMsg.id) }
                                                        .padding(horizontal = 10.dp, vertical = 6.dp),
                                                    verticalAlignment = Alignment.CenterVertically,
                                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                                ) {
                                                    Icon(
                                                        Icons.Default.Edit,
                                                        contentDescription = null,
                                                        tint = MaterialTheme.colorScheme.primary,
                                                        modifier = Modifier.size(14.dp),
                                                    )
                                                    Column(modifier = Modifier.weight(1f)) {
                                                        Text(
                                                            text = "编辑后发送",
                                                            fontSize = 11.sp,
                                                            fontWeight = FontWeight.SemiBold,
                                                            color = MaterialTheme.colorScheme.primary,
                                                        )
                                                        Text(
                                                            text = editMsg.content.replace('\n', ' '),
                                                            fontSize = 12.sp,
                                                            color = colors.fgMuted,
                                                            maxLines = 1,
                                                            overflow = TextOverflow.Ellipsis,
                                                        )
                                                    }
                                                    Row(
                                                        modifier = Modifier
                                                            .clip(RoundedCornerShape(8.dp))
                                                            .clickable { locateMessage(editMsg.id) }
                                                            .padding(horizontal = 6.dp, vertical = 3.dp),
                                                        verticalAlignment = Alignment.CenterVertically,
                                                        horizontalArrangement = Arrangement.spacedBy(3.dp),
                                                    ) {
                                                        Icon(
                                                            Icons.Default.MyLocation,
                                                            contentDescription = "定位原消息",
                                                            tint = colors.fgMuted,
                                                            modifier = Modifier.size(13.dp),
                                                        )
                                                        Text(
                                                            text = "定位",
                                                            fontSize = 11.sp,
                                                            color = colors.fgMuted,
                                                        )
                                                    }
                                                    IconButton(
                                                        onClick = cancelEdit,
                                                        modifier = Modifier.size(24.dp),
                                                    ) {
                                                        Icon(
                                                            Icons.Default.Close,
                                                            contentDescription = "取消编辑",
                                                            tint = colors.fgFaint,
                                                            modifier = Modifier.size(14.dp),
                                                        )
                                                    }
                                                }
                                            }

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
                                                                when (task.status) {
                                                                    UploadTaskStatus.ERROR -> {
                                                                        Row(
                                                                            verticalAlignment = Alignment.CenterVertically,
                                                                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                                                                        ) {
                                                                            Text(task.error ?: "失败", fontSize = 10.sp, color = colors.danger, maxLines = 1, modifier = Modifier.weight(1f, fill = false))
                                                                            if (task.localFile != null) {
                                                                                Text(
                                                                                    text = "重试",
                                                                                    fontSize = 10.5.sp,
                                                                                    fontWeight = FontWeight.Medium,
                                                                                    color = MaterialTheme.colorScheme.primary,
                                                                                    modifier = Modifier.clickable { vm.retryUpload(task.localId) },
                                                                                )
                                                                            }
                                                                        }
                                                                    }
                                                                    UploadTaskStatus.SIGNING, UploadTaskStatus.COMPLETING -> {
                                                                        Text(
                                                                            text = if (task.status == UploadTaskStatus.SIGNING) "签名中…" else "校验中…",
                                                                            fontSize = 10.sp,
                                                                            color = colors.fgFaint,
                                                                        )
                                                                    }
                                                                    UploadTaskStatus.UPLOADING -> {
                                                                        Spacer(modifier = Modifier.height(2.dp))
                                                                        LinearWavyProgressIndicator(
                                                                            progress = { task.progress / 100f },
                                                                            modifier = Modifier.fillMaxWidth().height(4.dp),
                                                                        )
                                                                    }
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
                                            val hasActiveUploads = ui.hasActiveUploads
                                            val canSend = inputText.isNotBlank() && !ui.streaming && !ui.sendingMessage && ui.agentStatus?.ready != false

                                            if (queuedSend && hasActiveUploads) {
                                                Row(
                                                    modifier = Modifier
                                                        .fillMaxWidth()
                                                        .padding(horizontal = 4.dp, vertical = 2.dp),
                                                    verticalAlignment = Alignment.CenterVertically,
                                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                                ) {
                                                    WhitzLoadingIndicator(size = 12.dp)
                                                    Text(
                                                        text = "等待上传完成自动发送…",
                                                        fontSize = 11.5.sp,
                                                        color = MaterialTheme.colorScheme.primary,
                                                        modifier = Modifier.weight(1f),
                                                    )
                                                    Text(
                                                        text = "取消",
                                                        fontSize = 11.5.sp,
                                                        fontWeight = FontWeight.Medium,
                                                        color = colors.fgMuted,
                                                        modifier = Modifier.clickable { queuedSend = false },
                                                    )
                                                }
                                            }

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
                                                        val placeholderText = when {
                                                            ui.agentStatus?.ready == false -> "助理正在初始化，请稍候…"
                                                            hasActiveUploads -> "文件上传中，可点发送排队…"
                                                            else -> "给 $assistantName 发送消息"
                                                        }
                                                        Text(
                                                            text = placeholderText,
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
                                                    stopping = ui.stopping,
                                                    sending = ui.sendingMessage || ui.waitingFirstByte,
                                                    queued = queuedSend && hasActiveUploads,
                                                    uploading = hasActiveUploads,
                                                    canSend = canSend,
                                                    onStop = { vm.stopRun() },
                                                    onSend = {
                                                        val editTarget = editingMessage
                                                        if (editTarget != null) {
                                                            val text = inputText
                                                            editingMessage = null
                                                            savedDraftBeforeEdit = null
                                                            inputText = ""
                                                            composerExpanded = false
                                                            dismissPlusMenu()
                                                            vm.editAndResend(editTarget.id, text)
                                                        } else if (hasActiveUploads) {
                                                            queuedSend = true
                                                        } else {
                                                            val text = inputText
                                                            inputText = ""
                                                            composerExpanded = false
                                                            dismissPlusMenu()
                                                            vm.sendMessage(text)
                                                        }
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

                    androidx.compose.animation.AnimatedVisibility(
                        visible = ui.isMainChat && mainPanelOpen,
                        enter = fadeIn(tween(240)),
                        exit = fadeOut(tween(280)),
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        MainChatTaskPanelOverlay(
                            sharedTransitionScope = this@SharedTransitionLayout,
                            animatedVisibilityScope = this@AnimatedVisibility,
                            assistantName = assistantName,
                            avatarUrl = vm.resolveAssetUrl(user?.assistantAvatarUrl),
                            resolvedTurn = resolvedTurn,
                            fileError = ui.fileError,
                            navBottom = navBottom,
                            onDismiss = { mainPanelOpen = false },
                        )
                    }
                    }
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

                val latestMenuMessage = messageMenuTarget?.let { target ->
                    ui.messages.firstOrNull { it.id == target.message.id } ?: target.message
                }
                MessageActionMenuOverlay(
                    visible = messageMenuVisible,
                    message = latestMenuMessage,
                    anchorInStage = messageMenuTarget?.anchorInStage,
                    streaming = ui.streaming,
                    hasActiveUploads = ui.hasActiveUploads,
                    onDismiss = { messageMenuVisible = false },
                    onCopy = { content ->
                        messageMenuVisible = false
                        clipboard.setText(AnnotatedString(content))
                        scope.launch { snackbarHostState.showSnackbar("已复制到剪贴板") }
                    },
                    onEdit = { msg ->
                        messageMenuVisible = false
                        if (editingMessage == null) {
                            savedDraftBeforeEdit = inputText
                        }
                        editingMessage = msg
                        inputText = msg.content
                        selectingTextMessageId = null
                        locateMessage(msg.id)
                        inputFocusRequester.requestFocus()
                    },
                    onSelectText = { msgId ->
                        messageMenuVisible = false
                        selectingTextMessageId = msgId
                        locateMessage(msgId)
                    },
                    onRegenerate = { msgId ->
                        messageMenuVisible = false
                        vm.regenerate(msgId)
                    },
                    onReact = { msg, reactionKey ->
                        messageMenuVisible = false
                        if (reactionKey == "dislike") {
                            val wasDisliked = msg.reactions.any { it.authorType == "user" && it.reaction == "dislike" }
                            vm.reactToMessage(msg.id, "dislike", null)
                            dislikeReasonMessageId = if (!wasDisliked) msg.id else null
                        } else {
                            if (dislikeReasonMessageId == msg.id) dislikeReasonMessageId = null
                            vm.reactToMessage(msg.id, reactionKey, null)
                        }
                    },
                )
            }
        }

        if (isExpandedScreen) {
            mainStage()
        } else {
            ModalNavigationDrawer(
                drawerState = drawerState,
                gesturesEnabled = !mainPanelOpen,
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
                            resolveAssetUrl = { vm.resolveAssetUrl(it) },
                            onCloseDrawer = { scope.launch { drawerState.close() } },
                            onSelectMain = {
                                vm.openMainConversation()
                                scope.launch { drawerState.close() }
                            },
                            onCreateSide = {
                                vm.createSideConversation()
                                scope.launch { drawerState.close() }
                            },
                            onOpenLibrary = {
                                scope.launch { drawerState.close() }
                                onOpenLibrary()
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
                            onOpenSettings = onOpenSettings,
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
            recentConversations = ui.conversations,
            assistantName = assistantName,
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
            title = { Text("重命名旁聊", fontWeight = FontWeight.SemiBold, color = colors.fg) },
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
            title = { Text("删除旁聊", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = {
                Text(
                    "确定删除旁聊「${conv.title}」吗？此操作不可撤销；该旁聊中上传的文件仍会保留在资料库中。",
                    color = colors.fgMuted,
                )
            },
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

private val SIDEBAR_ACTIVE_RUN_STATUSES = setOf(
    "starting",
    "queued",
    "running",
    "waiting",
    "waiting_for_approval",
    "waiting_for_clarify",
)

private fun isConvRunning(c: Conversation?): Boolean =
    c?.activeRunStatus != null && c.activeRunStatus in SIDEBAR_ACTIVE_RUN_STATUSES

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun SidebarContent(
    ui: ChatUiState,
    user: User?,
    authReady: Boolean,
    collapsed: Boolean,
    showCloseButton: Boolean,
    resolveAssetUrl: (String?) -> String?,
    onCloseDrawer: () -> Unit,
    onSelectMain: () -> Unit,
    onCreateSide: () -> Unit,
    onOpenLibrary: () -> Unit,
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
    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
    val assistantAvatarUrl = resolveAssetUrl(user?.assistantAvatarUrl)
    val userAvatarUrl = resolveAssetUrl(user?.avatarUrl)
    val mainConv = ui.mainConversation
    val isMainSelected = mainConv != null && ui.currentConvId == mainConv.id

    var sidebarCoords by remember { mutableStateOf<LayoutCoordinates?>(null) }
    var convMenuVisible by remember { mutableStateOf(false) }
    var convMenuTarget by remember { mutableStateOf<SidebarConvMenuTarget?>(null) }

    BackHandler(enabled = convMenuVisible) { convMenuVisible = false }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .onGloballyPositioned { sidebarCoords = it },
    ) {
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
                        .clickable(onClick = onSelectMain),
                    contentAlignment = Alignment.Center,
                ) {
                    WhitzLogoMark(modifier = Modifier.size(26.dp))
                }
            } else {
                WhitzBrandMark(
                    modifier = Modifier
                        .clip(RoundedCornerShape(10.dp))
                        .clickable(onClick = onSelectMain)
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

        // Top Action Rows: Row 1 = Search, Row 2 = Library (above Main Chat)
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(42.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .clickable(onClick = onOpenSearch)
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Search, contentDescription = "搜索", tint = colors.fgMuted, modifier = Modifier.size(19.dp))
                if (!collapsed) {
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("搜索", fontSize = 14.5.sp, fontWeight = FontWeight.Medium, color = colors.fgMuted)
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(42.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .clickable(onClick = onOpenLibrary)
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.FolderOpen, contentDescription = "资料库", tint = colors.fgMuted, modifier = Modifier.size(19.dp))
                if (!collapsed) {
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("资料库", fontSize = 14.5.sp, fontWeight = FontWeight.Medium, color = colors.fgMuted)
                }
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        if (collapsed) {
            Spacer(modifier = Modifier.weight(1f))
        } else {
            // Pinned Main Chat Entry
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(if (isMainSelected) colors.hover else Color.Transparent)
                    .clickable(onClick = onSelectMain)
                    .padding(horizontal = 10.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(30.dp)
                        .clip(CircleShape)
                        .background(colors.canvas),
                    contentAlignment = Alignment.Center,
                ) {
                    if (!assistantAvatarUrl.isNullOrBlank()) {
                        AsyncImage(
                            model = assistantAvatarUrl,
                            contentDescription = assistantName,
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.fillMaxSize(),
                        )
                    } else {
                        WhitzLogoMark(modifier = Modifier.size(16.dp))
                    }
                }
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = assistantName,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Medium,
                    color = if (isMainSelected) colors.fg else colors.fgMuted,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (isConvRunning(mainConv)) {
                    Box(
                        modifier = Modifier
                            .padding(start = 6.dp)
                            .size(6.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.primary),
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Side Chats Section Header + New Side Chat '+' Button
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 10.dp, end = 2.dp, top = 4.dp, bottom = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "旁聊",
                    fontSize = 12.5.sp,
                    fontWeight = FontWeight.Medium,
                    color = colors.fgFaint,
                    modifier = Modifier.weight(1f),
                )
                IconButton(
                    onClick = onCreateSide,
                    modifier = Modifier.size(30.dp),
                ) {
                    Icon(
                        imageVector = Icons.Default.Add,
                        contentDescription = "新建旁聊",
                        tint = colors.fgMuted,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }

            // Side Chats List
            val sideList = ui.sideConversations
            val pinned = remember(sideList) { sideList.filter { it.isPinned } }
            val recent = remember(sideList) { sideList.filterNot { it.isPinned } }
            val showColdStartLoading = (!authReady || ui.conversationsLoading) && ui.conversations.isEmpty()

            if (showColdStartLoading) {
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
                    if (sideList.isEmpty()) {
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .verticalScroll(rememberScrollState()),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = "还没有旁聊\n点击上方「+」新建旁聊",
                                color = colors.fgFaint,
                                fontSize = 13.sp,
                                textAlign = TextAlign.Center,
                                lineHeight = 20.sp,
                            )
                        }
                    } else {
                        LazyColumn(
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(vertical = 4.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            if (pinned.isNotEmpty()) {
                                item(key = "hdr-pinned") {
                                    Text(
                                        text = "置顶旁聊",
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
                                        onLongPress = { windowOffset ->
                                            val coords = sidebarCoords
                                            if (coords != null && coords.isAttached) {
                                                convMenuTarget = SidebarConvMenuTarget(
                                                    conv = conv,
                                                    anchorInSidebar = coords.windowToLocal(windowOffset),
                                                )
                                                convMenuVisible = true
                                            }
                                        },
                                    )
                                }
                            }

                            if (recent.isNotEmpty()) {
                                if (pinned.isNotEmpty()) {
                                    item(key = "hdr-recent") {
                                        Text(
                                            text = "最近旁聊",
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
                                        onLongPress = { windowOffset ->
                                            val coords = sidebarCoords
                                            if (coords != null && coords.isAttached) {
                                                convMenuTarget = SidebarConvMenuTarget(
                                                    conv = conv,
                                                    anchorInSidebar = coords.windowToLocal(windowOffset),
                                                )
                                                convMenuVisible = true
                                            }
                                        },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        // Very Bottom: User profile (kept at the very bottom)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp, bottom = navBottom + 10.dp)
                .clip(RoundedCornerShape(14.dp))
                .clickable(onClick = onOpenSettings)
                .padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!userAvatarUrl.isNullOrBlank()) {
                AsyncImage(
                    model = userAvatarUrl,
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

        val latestConv = convMenuTarget?.let { target ->
            ui.conversations.firstOrNull { it.id == target.conv.id } ?: target.conv
        }
        SidebarConvMenuOverlay(
            visible = convMenuVisible,
            conv = latestConv,
            anchorInSidebar = convMenuTarget?.anchorInSidebar,
            onDismiss = { convMenuVisible = false },
            onTogglePin = { conv ->
                convMenuVisible = false
                onTogglePin(conv.id, !conv.isPinned)
            },
            onRename = { conv ->
                convMenuVisible = false
                onRename(conv)
            },
            onDelete = { conv ->
                convMenuVisible = false
                onDelete(conv)
            },
        )
    }
}

@Composable
private fun ConversationRow(
    conv: Conversation,
    selected: Boolean,
    onSelect: () -> Unit,
    onLongPress: (Offset) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val haptic = LocalHapticFeedback.current
    var rowCoords by remember(conv.id) { mutableStateOf<LayoutCoordinates?>(null) }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(if (selected) colors.hover else Color.Transparent)
            .onGloballyPositioned { rowCoords = it }
            .pointerInput(conv.id) {
                detectTapGestures(
                    onTap = { onSelect() },
                    onLongPress = { localOffset ->
                        val coords = rowCoords
                        if (coords != null && coords.isAttached) {
                            haptic.performHapticFeedback(HapticFeedbackType.LongPress)
                            onLongPress(coords.localToWindow(localOffset))
                        }
                    },
                )
            }
            .padding(horizontal = 12.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (isConvRunning(conv)) {
            Box(
                modifier = Modifier
                    .size(6.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primary),
            )
            Spacer(modifier = Modifier.width(8.dp))
        }
        if (conv.isPinned) {
            Icon(
                Icons.Default.PushPin,
                contentDescription = "已置顶",
                tint = colors.fgFaint,
                modifier = Modifier.size(13.dp),
            )
            Spacer(modifier = Modifier.width(6.dp))
        }
        Text(
            text = conv.title.ifBlank { "新旁聊" },
            fontSize = 14.sp,
            fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
            color = if (selected) colors.fg else colors.fgMuted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
    }
}

private data class SidebarConvMenuTarget(
    val conv: Conversation,
    val anchorInSidebar: Offset,
)

private data class MessageMenuTarget(
    val message: Message,
    val anchorInStage: Offset,
)

@Composable
private fun WhitzFloatingMenuCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = colors.hover,
        border = BorderStroke(0.5.dp, colors.line),
        shadowElevation = 8.dp,
        modifier = modifier.clickable(
            interactionSource = remember { MutableInteractionSource() },
            indication = null,
            onClick = {},
        ),
    ) {
        content()
    }
}

@Composable
private fun WhitzFloatingMenuItem(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    tint: Color = LocalWhitzColors.current.fg,
    highlighted: Boolean = false,
) {
    val colors = LocalWhitzColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(42.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(if (highlighted) colors.active else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = label,
            tint = tint,
            modifier = Modifier.size(18.dp),
        )
        Spacer(modifier = Modifier.width(10.dp))
        Text(
            text = label,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            color = tint,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private val FloatingMenuEnterCurve = CubicBezierEasing(0.18f, 1.0f, 0.30f, 1.0f)
private val FloatingMenuExitCurve = CubicBezierEasing(0.4f, 0.0f, 0.2f, 1.0f)

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun SidebarConvMenuOverlay(
    visible: Boolean,
    conv: Conversation?,
    anchorInSidebar: Offset?,
    onDismiss: () -> Unit,
    onTogglePin: (Conversation) -> Unit,
    onRename: (Conversation) -> Unit,
    onDelete: (Conversation) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val density = LocalDensity.current
    val statusTopPx = with(density) { WindowInsets.statusBars.asPaddingValues().calculateTopPadding().toPx() }
    val navBottomPx = with(density) { WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding().toPx() }

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val containerWidthPx = with(density) { maxWidth.toPx() }
        val containerHeightPx = with(density) { maxHeight.toPx() }
        val edgePaddingPx = with(density) { 12.dp.toPx() }
        val verticalGapPx = with(density) { 8.dp.toPx() }
        val topSafePx = statusTopPx + edgePaddingPx
        val bottomSafePx = navBottomPx + edgePaddingPx
        val cardWidthDp = 176.dp
        val cardWidthPx = with(density) { cardWidthDp.toPx() }
        val estCardHeightPx = with(density) { 150.dp.toPx() }

        val anchor = anchorInSidebar ?: Offset.Zero
        val spaceAbove = anchor.y - verticalGapPx - topSafePx
        val spaceBelow = containerHeightPx - anchor.y - verticalGapPx - bottomSafePx
        // Prefer expanding upward unless space above is insufficient
        val expandUpward = spaceAbove >= estCardHeightPx || spaceAbove >= spaceBelow
        val estLeftX = (anchor.x - cardWidthPx / 2f).coerceIn(
            edgePaddingPx,
            (containerWidthPx - cardWidthPx - edgePaddingPx).coerceAtLeast(edgePaddingPx),
        )
        val pivotX = ((anchor.x - estLeftX) / cardWidthPx).coerceIn(0.15f, 0.85f)
        val transformOrigin = TransformOrigin(pivotX, if (expandUpward) 1f else 0f)

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

        Layout(
            modifier = Modifier.fillMaxSize(),
            content = {
                AnimatedVisibility(
                    visible = visible && conv != null && anchorInSidebar != null,
                    enter = scaleIn(
                        initialScale = 0.62f,
                        transformOrigin = transformOrigin,
                        animationSpec = tween(durationMillis = 260, easing = FloatingMenuEnterCurve),
                    ) + slideInVertically(
                        animationSpec = tween(durationMillis = 260, easing = FloatingMenuEnterCurve),
                    ) { if (expandUpward) (it * 0.24f).roundToInt() else -(it * 0.24f).roundToInt() } +
                        fadeIn(animationSpec = tween(durationMillis = 180, easing = FastOutSlowInEasing)),
                    exit = scaleOut(
                        targetScale = 0.72f,
                        transformOrigin = transformOrigin,
                        animationSpec = tween(durationMillis = 180, easing = FloatingMenuExitCurve),
                    ) + slideOutVertically(
                        animationSpec = tween(durationMillis = 180, easing = FloatingMenuExitCurve),
                    ) { if (expandUpward) (it * 0.18f).roundToInt() else -(it * 0.18f).roundToInt() } +
                        fadeOut(animationSpec = tween(durationMillis = 140, easing = FloatingMenuExitCurve)),
                ) {
                    val target = conv ?: return@AnimatedVisibility
                    WhitzFloatingMenuCard {
                        Column(
                            modifier = Modifier
                                .width(cardWidthDp)
                                .padding(6.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            WhitzFloatingMenuItem(
                                icon = Icons.Default.PushPin,
                                label = if (target.isPinned) "取消置顶" else "置顶",
                                onClick = { onTogglePin(target) },
                            )
                            WhitzFloatingMenuItem(
                                icon = Icons.Default.Edit,
                                label = "重命名",
                                onClick = { onRename(target) },
                            )
                            WhitzFloatingMenuItem(
                                icon = Icons.Default.Delete,
                                label = "删除",
                                tint = colors.danger,
                                onClick = { onDelete(target) },
                            )
                        }
                    }
                }
            },
        ) { measurables, constraints ->
            val placeables = measurables.map { it.measure(constraints.copy(minWidth = 0, minHeight = 0)) }
            val padPx = edgePaddingPx.roundToInt()
            val topPadPx = topSafePx.roundToInt()
            val bottomPadPx = bottomSafePx.roundToInt()
            val gapPx = verticalGapPx.roundToInt()
            layout(constraints.maxWidth, constraints.maxHeight) {
                if (anchorInSidebar != null) {
                    placeables.forEach { placeable ->
                        val x = (anchorInSidebar.x - placeable.width / 2f).roundToInt().coerceIn(
                            padPx,
                            (constraints.maxWidth - placeable.width - padPx).coerceAtLeast(padPx),
                        )
                        val y = if (expandUpward) {
                            (anchorInSidebar.y - gapPx - placeable.height).roundToInt().coerceAtLeast(topPadPx)
                        } else {
                            (anchorInSidebar.y + gapPx).roundToInt().coerceIn(
                                topPadPx,
                                (constraints.maxHeight - placeable.height - bottomPadPx).coerceAtLeast(topPadPx),
                            )
                        }
                        placeable.place(x, y)
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun MessageActionMenuOverlay(
    visible: Boolean,
    message: Message?,
    anchorInStage: Offset?,
    streaming: Boolean,
    hasActiveUploads: Boolean,
    onDismiss: () -> Unit,
    onCopy: (String) -> Unit,
    onEdit: (Message) -> Unit,
    onSelectText: (String) -> Unit,
    onRegenerate: (String) -> Unit,
    onReact: (Message, String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val density = LocalDensity.current
    val statusTopPx = with(density) { WindowInsets.statusBars.asPaddingValues().calculateTopPadding().toPx() }
    val navBottomPx = with(density) { WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding().toPx() }

    BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
        val containerWidthPx = with(density) { maxWidth.toPx() }
        val containerHeightPx = with(density) { maxHeight.toPx() }
        val edgePaddingPx = with(density) { 12.dp.toPx() }
        val verticalGapPx = with(density) { 10.dp.toPx() }
        val topSafePx = statusTopPx + edgePaddingPx
        val bottomSafePx = navBottomPx + edgePaddingPx
        val isAssistant = message != null && message.role != "user"
        val actionCardWidthDp = 176.dp
        val estWidthPx = with(density) { (if (isAssistant) 216.dp else actionCardWidthDp).toPx() }
        val estHeightPx = with(density) { (if (isAssistant) 224.dp else 154.dp).toPx() }

        val anchor = anchorInStage ?: Offset.Zero
        val spaceAbove = anchor.y - verticalGapPx - topSafePx
        val spaceBelow = containerHeightPx - anchor.y - verticalGapPx - bottomSafePx
        // Prefer expanding upward unless space above is insufficient
        val expandUpward = spaceAbove >= estHeightPx || spaceAbove >= spaceBelow
        val estLeftX = (anchor.x - estWidthPx / 2f).coerceIn(
            edgePaddingPx,
            (containerWidthPx - estWidthPx - edgePaddingPx).coerceAtLeast(edgePaddingPx),
        )
        val pivotX = ((anchor.x - estLeftX) / estWidthPx).coerceIn(0.15f, 0.85f)
        val transformOrigin = TransformOrigin(pivotX, if (expandUpward) 1f else 0f)

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

        Layout(
            modifier = Modifier.fillMaxSize(),
            content = {
                AnimatedVisibility(
                    visible = visible && message != null && anchorInStage != null,
                    enter = scaleIn(
                        initialScale = 0.62f,
                        transformOrigin = transformOrigin,
                        animationSpec = tween(durationMillis = 260, easing = FloatingMenuEnterCurve),
                    ) + slideInVertically(
                        animationSpec = tween(durationMillis = 260, easing = FloatingMenuEnterCurve),
                    ) { if (expandUpward) (it * 0.24f).roundToInt() else -(it * 0.24f).roundToInt() } +
                        fadeIn(animationSpec = tween(durationMillis = 180, easing = FastOutSlowInEasing)),
                    exit = scaleOut(
                        targetScale = 0.72f,
                        transformOrigin = transformOrigin,
                        animationSpec = tween(durationMillis = 180, easing = FloatingMenuExitCurve),
                    ) + slideOutVertically(
                        animationSpec = tween(durationMillis = 180, easing = FloatingMenuExitCurve),
                    ) { if (expandUpward) (it * 0.18f).roundToInt() else -(it * 0.18f).roundToInt() } +
                        fadeOut(animationSpec = tween(durationMillis = 140, easing = FloatingMenuExitCurve)),
                ) {
                    val target = message ?: return@AnimatedVisibility
                    val userReaction = target.reactions.firstOrNull { it.authorType == "user" }
                    val horizontalAlign = if (target.role == "user") Alignment.End else Alignment.Start

                    val emojiCard: (@Composable () -> Unit)? = if (target.role != "user") {
                        {
                            WhitzFloatingMenuCard {
                                Row(
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                                ) {
                                    USER_REACTION_OPTIONS.forEach { opt ->
                                        val active = userReaction?.reaction == opt.key
                                        val activeBg = when {
                                            !active -> Color.Transparent
                                            opt.key == "dislike" -> colors.dangerWeak
                                            else -> MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)
                                        }
                                        Box(
                                            modifier = Modifier
                                                .size(36.dp)
                                                .clip(CircleShape)
                                                .background(activeBg)
                                                .clickable { onReact(target, opt.key) },
                                            contentAlignment = Alignment.Center,
                                        ) {
                                            Text(opt.emoji, fontSize = 18.sp)
                                        }
                                    }
                                }
                            }
                        }
                    } else null

                    val hasActionItems = if (target.role == "user") {
                        target.content.isNotBlank() || !streaming
                    } else {
                        target.content.isNotBlank() || (!streaming && !hasActiveUploads)
                    }

                    val actionCard: (@Composable () -> Unit)? = if (hasActionItems) {
                        {
                            WhitzFloatingMenuCard {
                                Column(
                                    modifier = Modifier
                                        .width(actionCardWidthDp)
                                        .padding(6.dp),
                                    verticalArrangement = Arrangement.spacedBy(4.dp),
                                ) {
                                    if (target.role == "user") {
                                        if (target.content.isNotBlank()) {
                                            WhitzFloatingMenuItem(
                                                icon = Icons.Default.ContentCopy,
                                                label = "复制",
                                                onClick = { onCopy(target.content) },
                                            )
                                            WhitzFloatingMenuItem(
                                                icon = Icons.Default.SelectAll,
                                                label = "选中文字",
                                                onClick = { onSelectText(target.id) },
                                            )
                                        }
                                        if (!streaming) {
                                            WhitzFloatingMenuItem(
                                                icon = Icons.Default.Edit,
                                                label = "编辑后发送",
                                                onClick = { onEdit(target) },
                                            )
                                        }
                                    } else {
                                        if (target.content.isNotBlank()) {
                                            WhitzFloatingMenuItem(
                                                icon = Icons.Default.ContentCopy,
                                                label = "复制",
                                                onClick = { onCopy(target.content) },
                                            )
                                            WhitzFloatingMenuItem(
                                                icon = Icons.Default.SelectAll,
                                                label = "选中文字",
                                                onClick = { onSelectText(target.id) },
                                            )
                                        }
                                        if (!streaming && !hasActiveUploads) {
                                            WhitzFloatingMenuItem(
                                                icon = Icons.Default.Refresh,
                                                label = "重新生成",
                                                onClick = { onRegenerate(target.id) },
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    } else null

                    Column(
                        horizontalAlignment = horizontalAlign,
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        if (expandUpward) {
                            actionCard?.invoke()
                            emojiCard?.invoke()
                        } else {
                            emojiCard?.invoke()
                            actionCard?.invoke()
                        }
                    }
                }
            },
        ) { measurables, constraints ->
            val placeables = measurables.map { it.measure(constraints.copy(minWidth = 0, minHeight = 0)) }
            val padPx = edgePaddingPx.roundToInt()
            val topPadPx = topSafePx.roundToInt()
            val bottomPadPx = bottomSafePx.roundToInt()
            val gapPx = verticalGapPx.roundToInt()
            layout(constraints.maxWidth, constraints.maxHeight) {
                if (anchorInStage != null) {
                    placeables.forEach { placeable ->
                        val x = (anchorInStage.x - placeable.width / 2f).roundToInt().coerceIn(
                            padPx,
                            (constraints.maxWidth - placeable.width - padPx).coerceAtLeast(padPx),
                        )
                        val y = if (expandUpward) {
                            (anchorInStage.y - gapPx - placeable.height).roundToInt().coerceAtLeast(topPadPx)
                        } else {
                            (anchorInStage.y + gapPx).roundToInt().coerceIn(
                                topPadPx,
                                (constraints.maxHeight - placeable.height - bottomPadPx).coerceAtLeast(topPadPx),
                            )
                        }
                        placeable.place(x, y)
                    }
                }
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
                    initialScale = 0.62f,
                    transformOrigin = TransformOrigin(0f, 1f),
                    animationSpec = tween(durationMillis = 260, easing = FloatingMenuEnterCurve),
                ) + slideInVertically(
                    animationSpec = tween(durationMillis = 260, easing = FloatingMenuEnterCurve),
                ) { (it * 0.24f).roundToInt() } +
                    fadeIn(animationSpec = tween(durationMillis = 180, easing = FastOutSlowInEasing)),
                exit = scaleOut(
                    targetScale = 0.72f,
                    transformOrigin = TransformOrigin(0f, 1f),
                    animationSpec = tween(durationMillis = 180, easing = FloatingMenuExitCurve),
                ) + slideOutVertically(
                    animationSpec = tween(durationMillis = 180, easing = FloatingMenuExitCurve),
                ) { (it * 0.18f).roundToInt() } +
                    fadeOut(animationSpec = tween(durationMillis = 140, easing = FloatingMenuExitCurve)),
            ) {
                WhitzFloatingMenuCard {
                    Column(
                        modifier = Modifier
                            .width(172.dp)
                            .padding(6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Box {
                            WhitzFloatingMenuItem(
                                icon = Icons.Default.AttachFile,
                                label = "文件上传",
                                onClick = onOpenAttachMenu,
                            )
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
                                    text = { Text("从资料库选择") },
                                    leadingIcon = { Icon(Icons.Default.FolderOpen, contentDescription = null) },
                                    onClick = onPickFromLibrary,
                                )
                            }
                        }

                        WhitzFloatingMenuItem(
                            icon = Icons.Default.AutoAwesome,
                            label = if (selectedSkillCount > 0) "技能 ($selectedSkillCount)" else "技能",
                            highlighted = selectedSkillCount > 0,
                            onClick = onOpenSkillPicker,
                        )
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
    stopping: Boolean,
    sending: Boolean,
    queued: Boolean,
    uploading: Boolean,
    canSend: Boolean,
    onStop: () -> Unit,
    onSend: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    if (streaming) {
        IconButton(
            onClick = onStop,
            enabled = !stopping,
            modifier = Modifier
                .size(36.dp)
                .clip(CircleShape)
                .background(colors.canvas),
        ) {
            if (stopping) {
                WhitzLoadingIndicator(size = 16.dp, color = colors.fgMuted)
            } else {
                Icon(
                    Icons.Default.Stop,
                    contentDescription = "停止生成",
                    tint = colors.fg,
                    modifier = Modifier.size(18.dp),
                )
            }
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
            if (sending || queued || (uploading && canSend)) {
                WhitzLoadingIndicator(
                    size = 16.dp,
                    color = if (canSend) MaterialTheme.colorScheme.onPrimary else colors.fgFaint,
                )
            } else {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowForward,
                    contentDescription = "发送",
                    tint = if (canSend) MaterialTheme.colorScheme.onPrimary else colors.fgFaint,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
    }
}

