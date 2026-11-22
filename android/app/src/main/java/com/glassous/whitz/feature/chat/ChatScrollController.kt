package com.glassous.whitz.feature.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.MutatePriority
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsDraggedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.ui.theme.LocalWhitzColors
import dev.chrisbanes.haze.HazeState
import dev.chrisbanes.haze.HazeStyle
import dev.chrisbanes.haze.HazeTint
import dev.chrisbanes.haze.hazeEffect
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.max
import kotlin.math.roundToInt

internal const val CHAT_BOTTOM_ANCHOR_KEY = "__chat_bottom_anchor__"

/**
 * Pure, JVM-testable scrolling policy decisions for streaming chat lists.
 */
object ChatScrollPolicy {
    const val RE_ENGAGE_THRESHOLD_DP = 48f
    const val JUMP_BUTTON_SHOW_THRESHOLD_DP = 84f
    const val JUMP_BUTTON_HIDE_THRESHOLD_DP = 36f
    const val USER_UPWARD_DISENGAGE_SLOP_PX = 1.5f

    /**
     * Returns true when a user touch drag is moving toward earlier messages (scrolling UP).
     */
    fun shouldDisengageOnUserPreScroll(availableY: Float): Boolean =
        availableY > USER_UPWARD_DISENGAGE_SLOP_PX

    /**
     * Returns true when a user touch drag is moving toward newer messages (scrolling DOWN).
     */
    fun isUserScrollingDown(availableY: Float): Boolean =
        availableY < -USER_UPWARD_DISENGAGE_SLOP_PX

    /**
     * Re-engages auto-follow only when the user scrolled DOWN back within [reEngageThresholdPx]
     * of the bottom edge (never right after a small upward nudge away from the bottom).
     */
    fun shouldReEngageAutoFollow(
        distanceFromBottomPx: Int,
        reEngageThresholdPx: Int,
        userScrolledDown: Boolean = true,
    ): Boolean = userScrolledDown && distanceFromBottomPx <= reEngageThresholdPx

    /**
     * Hysteresis for floating "Scroll to bottom" button visibility so tiny micro-offsets
     * never cause flicker.
     */
    fun nextJumpButtonVisibility(
        currentlyVisible: Boolean,
        distanceFromBottomPx: Int,
        showThresholdPx: Int,
        hideThresholdPx: Int,
    ): Boolean = if (currentlyVisible) {
        distanceFromBottomPx > hideThresholdPx
    } else {
        distanceFromBottomPx > showThresholdPx
    }

    /**
     * Computes pixel distance from the bottom of the last item to the visible bottom edge
     * (above bottom content padding). Returns [Int.MAX_VALUE] if the last item is not visible.
     */
    fun computeDistanceFromBottomPx(
        canScrollForward: Boolean,
        totalItemsCount: Int,
        lastVisibleItemIndex: Int?,
        lastVisibleItemEndPx: Int?,
        viewportEndOffset: Int,
        afterContentPadding: Int,
    ): Int {
        if (totalItemsCount <= 0 || !canScrollForward) return 0
        if (lastVisibleItemIndex == null || lastVisibleItemEndPx == null) return Int.MAX_VALUE
        if (lastVisibleItemIndex < totalItemsCount - 1) return Int.MAX_VALUE
        val visibleViewportEnd = viewportEndOffset - afterContentPadding
        return (lastVisibleItemEndPx - visibleViewportEnd).coerceAtLeast(0)
    }

    /**
     * Computes the turn-reveal spacer height monotonically so it only shrinks as the active
     * response grows, never expanding back and causing layout oscillation or upward pushback.
     */
    fun computeMonotonicTurnSpacerPx(
        currentSpacerPx: Int,
        viewportUsableHeightPx: Int,
        turnContentHeightPx: Int,
        isInitialMeasure: Boolean,
    ): Int {
        val needed = (viewportUsableHeightPx - turnContentHeightPx).coerceAtLeast(0)
        return if (isInitialMeasure) {
            needed
        } else {
            minOf(currentSpacerPx, needed).coerceAtLeast(0)
        }
    }
}

@Stable
class ChatScrollController(
    val listState: LazyListState,
    private val scope: CoroutineScope,
    private val reEngageThresholdPx: Int,
    private val jumpShowThresholdPx: Int,
    private val jumpHideThresholdPx: Int,
) {
    /**
     * True when the list should smoothly keep the latest streaming lines visible at the bottom.
     * Disengages immediately on any upward user scroll and re-engages when the user returns to
     * the bottom or taps the floating jump button.
     */
    var autoFollow by mutableStateOf(true)
        private set

    /**
     * True while a finger is physically pressed on the list (even without moving yet).
     * Pauses programmatic auto-follow so text never slides out from under the user's finger.
     */
    var isPointerPressed by mutableStateOf(false)
        internal set

    var isDragged by mutableStateOf(false)
        internal set

    val isUserInteracting: Boolean
        get() = isPointerPressed || isDragged

    /**
     * Dynamic turn-reveal bottom spacer (in px) that anchors a newly sent user prompt near
     * the top of the viewport and shrinks monotonically to 0 as the assistant response fills
     * the screen.
     */
    var turnRevealSpacerPx by mutableIntStateOf(0)
        private set

    private var turnRevealActive by mutableStateOf(false)
    private var turnRevealInitialized by mutableStateOf(false)
    private var turnStartItemKey: String? by mutableStateOf(null)
    // +1 = user scrolled UP toward history, -1 = user scrolled DOWN toward bottom, 0 = neutral
    private var lastUserScrollDirection by mutableIntStateOf(0)

    /**
     * Pixel distance from the bottom anchor to the visible bottom edge above the composer.
     */
    val distanceFromBottomPx: Int by derivedStateOf {
        val layout = listState.layoutInfo
        val lastVisible = layout.visibleItemsInfo.lastOrNull()
        ChatScrollPolicy.computeDistanceFromBottomPx(
            canScrollForward = listState.canScrollForward,
            totalItemsCount = layout.totalItemsCount,
            lastVisibleItemIndex = lastVisible?.index,
            lastVisibleItemEndPx = lastVisible?.let { it.offset + it.size },
            viewportEndOffset = layout.viewportEndOffset,
            afterContentPadding = layout.afterContentPadding,
        )
    }

    val isAtBottom: Boolean by derivedStateOf {
        ChatScrollPolicy.shouldReEngageAutoFollow(distanceFromBottomPx, reEngageThresholdPx)
    }

    private var jumpButtonVisibleState by mutableStateOf(false)

    val showJumpToBottom: Boolean
        get() = jumpButtonVisibleState

    /**
     * Intercepts user scroll gestures BEFORE LazyColumn consumes them:
     * - Upward scroll (reading earlier messages): immediately disengages [autoFollow].
     * - Downward scroll (reading newer messages): never interferes; re-engages when bottom reached.
     */
    val nestedScrollConnection: NestedScrollConnection = object : NestedScrollConnection {
        override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
            if (source == NestedScrollSource.UserInput) {
                when {
                    ChatScrollPolicy.shouldDisengageOnUserPreScroll(available.y) -> {
                        autoFollow = false
                        lastUserScrollDirection = 1
                    }
                    ChatScrollPolicy.isUserScrollingDown(available.y) -> {
                        lastUserScrollDirection = -1
                    }
                }
            }
            return Offset.Zero
        }
    }

    /**
     * Non-consuming pointer observer that pauses auto-follow while the user holds a finger on
     * the message list without interfering with clicks, long-press menus, or scrolling.
     */
    val touchObserverModifier: Modifier = Modifier.pointerInput(this) {
        awaitPointerEventScope {
            while (true) {
                val event = awaitPointerEvent(PointerEventPass.Initial)
                isPointerPressed = event.changes.any { it.pressed }
            }
        }
    }

    internal fun updateJumpButtonVisibility() {
        val dist = distanceFromBottomPx
        jumpButtonVisibleState = ChatScrollPolicy.nextJumpButtonVisibility(
            currentlyVisible = jumpButtonVisibleState,
            distanceFromBottomPx = dist,
            showThresholdPx = jumpShowThresholdPx,
            hideThresholdPx = jumpHideThresholdPx,
        )
    }

    internal fun onInteractionSettled() {
        if (!isUserInteracting && !listState.isScrollInProgress) {
            if (!autoFollow && ChatScrollPolicy.shouldReEngageAutoFollow(
                    distanceFromBottomPx = distanceFromBottomPx,
                    reEngageThresholdPx = reEngageThresholdPx,
                    userScrolledDown = lastUserScrollDirection < 0,
                )
            ) {
                autoFollow = true
            }
            lastUserScrollDirection = 0
        }
    }

    fun resetForConversation() {
        autoFollow = true
        lastUserScrollDirection = 0
        turnRevealActive = false
        turnRevealInitialized = false
        turnStartItemKey = null
        turnRevealSpacerPx = 0
        jumpButtonVisibleState = false
    }

    fun clearTurnReveal() {
        turnRevealActive = false
        turnRevealInitialized = false
        turnStartItemKey = null
        turnRevealSpacerPx = 0
    }

    /**
     * Snap immediately to the bottom anchor when entering a conversation.
     */
    suspend fun jumpToBottomImmediate(totalItemsCount: Int) {
        if (totalItemsCount <= 0) return
        clearTurnReveal()
        autoFollow = true
        listState.scrollToItem(totalItemsCount - 1)
    }

    /**
     * Called when the user explicitly starts a new turn (send / regenerate / edit-resend).
     * Initializes a monotonic turn-reveal spacer so the new user prompt sits cleanly below the
     * floating header and the assistant's reply streams downward into open canvas.
     */
    suspend fun onNewTurnStarted(
        latestUserIndex: Int,
        latestUserKey: String?,
        viewportUsableHeightPx: Int,
        hasPreviousMessages: Boolean,
        totalItemsCount: Int,
    ) {
        autoFollow = true
        if (hasPreviousMessages && latestUserIndex >= 0 && viewportUsableHeightPx > 0) {
            turnRevealActive = true
            turnRevealInitialized = false
            turnStartItemKey = latestUserKey
            // Reserve initial runway so the new user prompt can scroll right to the top below header
            turnRevealSpacerPx = (viewportUsableHeightPx - 120).coerceAtLeast(0)
            // Wait one frame for the spacer & newly appended items to compose/layout
            withFrameNanos { }
            // Align the new user message cleanly below contentPadding.top (scrollOffset = 0)
            try {
                listState.animateScrollToItem(index = latestUserIndex, scrollOffset = 0)
            } catch (ce: CancellationException) {
                if (!currentCoroutineContext().isActive) throw ce
            }
        } else if (totalItemsCount > 0) {
            clearTurnReveal()
            withFrameNanos { }
            try {
                listState.animateScrollToItem(totalItemsCount - 1)
            } catch (ce: CancellationException) {
                if (!currentCoroutineContext().isActive) throw ce
            }
        }
    }

    /**
     * Shrinks [turnRevealSpacerPx] monotonically as the active turn grows so the top of the new
     * turn stays rock-steady while the reply fills the screen, then reaches 0 seamlessly.
     */
    internal fun updateTurnRevealSpacer(
        latestUserKey: String?,
        viewportUsableHeightPx: Int,
    ) {
        if (!turnRevealActive || viewportUsableHeightPx <= 0) return
        val targetKey = turnStartItemKey ?: latestUserKey ?: return
        val visible = listState.layoutInfo.visibleItemsInfo
        val startInfo = visible.firstOrNull { it.key == targetKey } ?: return
        val lastContentInfo = visible.lastOrNull { it.key != CHAT_BOTTOM_ANCHOR_KEY } ?: return
        val turnHeightPx = ((lastContentInfo.offset + lastContentInfo.size) - startInfo.offset).coerceAtLeast(0)
        val nextSpacer = ChatScrollPolicy.computeMonotonicTurnSpacerPx(
            currentSpacerPx = turnRevealSpacerPx,
            viewportUsableHeightPx = viewportUsableHeightPx,
            turnContentHeightPx = turnHeightPx,
            isInitialMeasure = !turnRevealInitialized,
        )
        turnRevealInitialized = true
        if (nextSpacer != turnRevealSpacerPx) {
            turnRevealSpacerPx = nextSpacer
        }
        if (nextSpacer == 0) {
            turnRevealActive = false
        }
    }

    /**
     * Smoothly scrolls to the bottom anchor when the user taps the floating button and re-engages
     * auto-follow.
     */
    fun jumpToBottomAnimated() {
        autoFollow = true
        scope.launch {
            val count = listState.layoutInfo.totalItemsCount
            if (count <= 0) return@launch
            try {
                val dist = distanceFromBottomPx
                if (dist == Int.MAX_VALUE || dist > 2600) {
                    // Jump close first so long chats don't spend seconds animating
                    listState.scrollToItem((count - 2).coerceAtLeast(0))
                }
                listState.animateScrollToItem(count - 1)
            } catch (ce: CancellationException) {
                if (!currentCoroutineContext().isActive) throw ce
            }
        }
    }

    /**
     * Navigates to a specific historical message (search hit, file origin, edit target) and
     * disengages auto-follow so streaming never pulls the user away from the located message.
     */
    suspend fun locateMessage(index: Int, topBreathingPx: Int) {
        if (index < 0) return
        autoFollow = false
        try {
            listState.animateScrollToItem(index = index, scrollOffset = -topBreathingPx)
        } catch (ce: CancellationException) {
            if (!currentCoroutineContext().isActive) throw ce
        }
    }

    /**
     * Smooth, frame-synced, non-fighting bottom follower.
     * Runs with [MutatePriority.Default] so any user touch ([MutatePriority.UserInput])
     * cancels it immediately with zero pushback.
     */
    internal suspend fun followBottomIfOverflowing() {
        if (!autoFollow || isUserInteracting) return
        val initialDist = distanceFromBottomPx
        if (initialDist <= 0) return

        val count = listState.layoutInfo.totalItemsCount
        if (count <= 0) return

        // If the bottom anchor isn't even on screen yet (large single-chunk jump), snap directly
        if (initialDist == Int.MAX_VALUE) {
            try {
                listState.scroll(MutatePriority.Default) {
                    // Yield to scrollToItem outside the scroll block
                }
                if (autoFollow && !isUserInteracting) {
                    listState.scrollToItem(count - 1)
                }
            } catch (ce: CancellationException) {
                if (!currentCoroutineContext().isActive) throw ce
            }
            return
        }

        // Smooth Choreographer-synced chase for normal streaming line growth
        try {
            listState.scroll(MutatePriority.Default) {
                while (currentCoroutineContext().isActive && autoFollow && !isUserInteracting) {
                    val remaining = distanceFromBottomPx
                    if (remaining <= 0 || remaining == Int.MAX_VALUE) break
                    val step = if (remaining <= 2) {
                        remaining.toFloat()
                    } else {
                        max(remaining * 0.32f, 2.5f).coerceAtMost(remaining.toFloat())
                    }
                    val consumed = scrollBy(step)
                    if (consumed <= 0.1f) break
                    withFrameNanos { }
                }
            }
        } catch (ce: CancellationException) {
            // MutatorMutex cancels Default priority when UserInput starts — do not kill the collector
            if (!currentCoroutineContext().isActive) throw ce
        }
    }
}

@Composable
fun rememberChatScrollController(
    listState: LazyListState,
    conversationKey: String,
    streaming: Boolean,
    hasMessages: Boolean,
    latestUserKey: String?,
    viewportUsableHeightPx: Int,
    bottomOverlayHeightPx: Int,
): ChatScrollController {
    val density = LocalDensity.current
    val scope = rememberCoroutineScope()
    val reEngageThresholdPx = with(density) { ChatScrollPolicy.RE_ENGAGE_THRESHOLD_DP.dp.roundToPx() }
    val jumpShowThresholdPx = with(density) { ChatScrollPolicy.JUMP_BUTTON_SHOW_THRESHOLD_DP.dp.roundToPx() }
    val jumpHideThresholdPx = with(density) { ChatScrollPolicy.JUMP_BUTTON_HIDE_THRESHOLD_DP.dp.roundToPx() }

    val controller = remember(listState, conversationKey, reEngageThresholdPx, jumpShowThresholdPx, jumpHideThresholdPx) {
        ChatScrollController(
            listState = listState,
            scope = scope,
            reEngageThresholdPx = reEngageThresholdPx,
            jumpShowThresholdPx = jumpShowThresholdPx,
            jumpHideThresholdPx = jumpHideThresholdPx,
        )
    }

    val dragged by listState.interactionSource.collectIsDraggedAsState()
    LaunchedEffect(dragged) {
        controller.isDragged = dragged
    }

    // Track jump-to-bottom button visibility & automatic re-engagement when user settles at bottom
    LaunchedEffect(controller, hasMessages) {
        if (!hasMessages) return@LaunchedEffect
        snapshotFlow {
            Triple(
                controller.distanceFromBottomPx,
                controller.isUserInteracting,
                listState.isScrollInProgress,
            )
        }
            .distinctUntilChanged()
            .collect {
                controller.updateJumpButtonVisibility()
                controller.onInteractionSettled()
            }
    }

    // Monotonically shrink turn-reveal spacer as the active turn grows
    LaunchedEffect(controller, latestUserKey, viewportUsableHeightPx) {
        snapshotFlow {
            listState.layoutInfo.visibleItemsInfo.lastOrNull { it.key != CHAT_BOTTOM_ANCHOR_KEY }
                ?.let { it.offset + it.size }
        }
            .distinctUntilChanged()
            .collect {
                controller.updateTurnRevealSpacer(
                    latestUserKey = latestUserKey,
                    viewportUsableHeightPx = viewportUsableHeightPx,
                )
            }
    }

    // Single persistent auto-follow loop: reacts to streaming growth AND bottom overlay height
    // changes (approval/clarify cards, IME keyboard) without ever restarting or fighting gestures.
    LaunchedEffect(controller, streaming, bottomOverlayHeightPx) {
        snapshotFlow {
            Triple(
                controller.autoFollow && !controller.isUserInteracting,
                controller.distanceFromBottomPx,
                bottomOverlayHeightPx,
            )
        }
            .distinctUntilChanged()
            .collect { (canFollow, dist, _) ->
                if (canFollow && dist > 0) {
                    controller.followBottomIfOverflowing()
                }
            }
    }

    return controller
}

/**
 * Frosted-glass floating "Scroll to bottom" button positioned cleanly above the composer.
 * Shows a subtle pulsing indicator + "新内容" label while streaming is active off-screen below.
 */
@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun ScrollToBottomButton(
    visible: Boolean,
    streaming: Boolean,
    hazeState: HazeState,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = LocalWhitzColors.current
    val hazeStyle = remember(colors.canvas) {
        HazeStyle(
            backgroundColor = colors.canvas.copy(alpha = 0.65f),
            tints = listOf(HazeTint(colors.canvas.copy(alpha = 0.68f))),
            blurRadius = 22.dp,
            noiseFactor = 0.04f,
        )
    }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
            scaleIn(initialScale = 0.84f, animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()) +
            slideInVertically(animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()) { (it * 0.4f).roundToInt() },
        exit = fadeOut(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
            scaleOut(targetScale = 0.86f, animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()) +
            slideOutVertically(animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()) { (it * 0.35f).roundToInt() },
        modifier = modifier,
    ) {
        val pillShape = CircleShape
        Box(
            modifier = Modifier
                .clip(pillShape)
                .hazeEffect(state = hazeState, style = hazeStyle)
                .border(0.75.dp, colors.lineStrong.copy(alpha = 0.85f), pillShape)
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = LocalIndication.current,
                    onClick = onClick,
                )
                .animateContentSize(animationSpec = MaterialTheme.motionScheme.fastSpatialSpec()),
            contentAlignment = Alignment.Center,
        ) {
            if (streaming) {
                val pulseTransition = rememberInfiniteTransition(label = "jumpPulse")
                val dotAlpha by pulseTransition.animateFloat(
                    initialValue = 0.35f,
                    targetValue = 1f,
                    animationSpec = infiniteRepeatable(
                        animation = tween(durationMillis = 650),
                        repeatMode = RepeatMode.Reverse,
                    ),
                    label = "jumpDotAlpha",
                )
                Row(
                    modifier = Modifier
                        .height(38.dp)
                        .padding(start = 13.dp, end = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(7.dp)
                            .clip(CircleShape)
                            .background(MaterialTheme.colorScheme.primary.copy(alpha = dotAlpha)),
                    )
                    Text(
                        text = "新内容",
                        fontSize = 12.5.sp,
                        fontWeight = FontWeight.Medium,
                        color = colors.fg,
                    )
                    Icon(
                        imageVector = Icons.Default.KeyboardArrowDown,
                        contentDescription = "回到底部查看最新输出",
                        tint = colors.fg,
                        modifier = Modifier.size(18.dp),
                    )
                }
            } else {
                Box(
                    modifier = Modifier.size(40.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Default.KeyboardArrowDown,
                        contentDescription = "回到底部",
                        tint = colors.fg,
                        modifier = Modifier.size(21.dp),
                    )
                }
            }
        }
    }
}
