package com.glassous.whitz.ui.theme

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ButtonGroupDefaults
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.ToggleButton
import androidx.compose.material3.ToggleButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.lerp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.util.lerp
import dev.chrisbanes.haze.HazeState
import dev.chrisbanes.haze.HazeStyle
import dev.chrisbanes.haze.HazeTint
import dev.chrisbanes.haze.hazeEffect
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlin.math.PI
import kotlin.math.cos

/**
 * M3E connected radio group replacing the retired SegmentedButtonRow.
 */
@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
fun <T> WhitzConnectedRadioGroup(
    options: List<Pair<T, String>>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = LocalWhitzColors.current
    FlowRow(
        modifier = modifier
            .fillMaxWidth()
            .background(colors.surface, RoundedCornerShape(14.dp))
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(ButtonGroupDefaults.ConnectedSpaceBetween),
    ) {
        options.forEachIndexed { index, (value, label) ->
            val isSelected = value == selected
            val shapes = when (index) {
                0 -> ButtonGroupDefaults.connectedLeadingButtonShapes()
                options.lastIndex -> ButtonGroupDefaults.connectedTrailingButtonShapes()
                else -> ButtonGroupDefaults.connectedMiddleButtonShapes()
            }
            ToggleButton(
                checked = isSelected,
                onCheckedChange = { if (it) onSelect(value) },
                shapes = shapes,
                colors = ToggleButtonDefaults.colors(
                    containerColor = Color.Transparent,
                    contentColor = colors.fgMuted,
                    checkedContainerColor = colors.canvas,
                    checkedContentColor = colors.fg,
                ),
                border = if (isSelected) BorderStroke(0.5.dp, colors.line) else null,
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 0.dp),
                modifier = Modifier
                    .weight(1f)
                    .height(38.dp)
                    .semantics { role = Role.RadioButton },
            ) {
                Text(
                    text = label,
                    fontSize = 13.sp,
                    fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

/**
 * M3E Expressive morphing loading indicator.
 */
@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun WhitzLoadingIndicator(
    modifier: Modifier = Modifier,
    size: Dp = 32.dp,
    color: Color = MaterialTheme.colorScheme.primary,
) {
    LoadingIndicator(
        modifier = modifier.size(size),
        color = color,
    )
}

/**
 * Web-aligned rounded text field without heavy boxy borders.
 */
@Composable
fun WhitzTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String? = null,
    placeholder: String? = null,
    modifier: Modifier = Modifier,
    singleLine: Boolean = true,
    maxLines: Int = if (singleLine) 1 else 6,
    enabled: Boolean = true,
    visualTransformation: VisualTransformation = VisualTransformation.None,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    keyboardActions: KeyboardActions = KeyboardActions.Default,
    trailingIcon: (@Composable () -> Unit)? = null,
    leadingIcon: (@Composable () -> Unit)? = null,
) {
    val colors = LocalWhitzColors.current
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = label?.let { { Text(it, fontSize = 13.sp) } },
        placeholder = placeholder?.let { { Text(it, color = colors.fgFaint, fontSize = 14.sp) } },
        singleLine = singleLine,
        maxLines = maxLines,
        enabled = enabled,
        visualTransformation = visualTransformation,
        keyboardOptions = keyboardOptions,
        keyboardActions = keyboardActions,
        trailingIcon = trailingIcon,
        leadingIcon = leadingIcon,
        shape = RoundedCornerShape(14.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = colors.surface.copy(alpha = 0.65f),
            unfocusedContainerColor = colors.surface.copy(alpha = 0.45f),
            disabledContainerColor = colors.surface.copy(alpha = 0.3f),
            focusedBorderColor = colors.fg.copy(alpha = 0.65f),
            unfocusedBorderColor = colors.line,
            focusedLabelColor = colors.fg,
            unfocusedLabelColor = colors.fgMuted,
            cursorColor = colors.fg,
            focusedTextColor = colors.fg,
            unfocusedTextColor = colors.fg,
        ),
        modifier = modifier,
    )
}

private fun buildEasedScrimStops(
    color: Color,
    topToBottom: Boolean,
    solidHoldFraction: Float,
    maxAlpha: Float = 1f,
    steps: Int = 24,
): Array<Pair<Float, Color>> = Array(steps + 1) { index ->
    val position = index / steps.toFloat()
    val t = if (topToBottom) position else 1f - position
    val progress = if (t <= solidHoldFraction) {
        1f
    } else {
        val u = ((t - solidHoldFraction) / (1f - solidHoldFraction)).coerceIn(0f, 1f)
        0.5f * (1f + cos(PI * u).toFloat())
    }
    position to color.copy(alpha = progress * maxAlpha)
}

/**
 * Top gradient scrim mask matching the canvas color with dense cosine-eased stops.
 */
@Composable
fun WhitzProgressiveBlurTop(
    modifier: Modifier = Modifier,
    maxAlpha: Float = 1f,
) {
    val canvas = LocalWhitzColors.current.canvas
    val brush = remember(canvas, maxAlpha) {
        Brush.verticalGradient(
            colorStops = buildEasedScrimStops(
                color = canvas,
                topToBottom = true,
                solidHoldFraction = 0.28f,
                maxAlpha = maxAlpha,
            ),
        )
    }
    Box(modifier = modifier.background(brush))
}

/**
 * Bottom gradient scrim mask matching the canvas color with dense cosine-eased stops.
 *
 * [maxAlpha] is kept below 1f on purpose so the very bottom of the scrim stays translucent
 * instead of fading into a fully opaque block.
 */
@Composable
fun WhitzProgressiveBlurBottom(
    modifier: Modifier = Modifier,
    maxAlpha: Float = 0.85f,
) {
    val canvas = LocalWhitzColors.current.canvas
    val brush = remember(canvas, maxAlpha) {
        Brush.verticalGradient(
            colorStops = buildEasedScrimStops(
                color = canvas,
                topToBottom = false,
                solidHoldFraction = 0.24f,
                maxAlpha = maxAlpha,
            ),
        )
    }
    Box(modifier = modifier.background(brush))
}

/**
 * Frosted circular button used by the floating chat header.
 * The blur is drawn by [Modifier.hazeEffect] using the supplied [dev.chrisbanes.haze.HazeState],
 * so the content scrolling underneath shows through as glass.
 *
 * [showBorder] is turned off on a fresh/empty conversation so the buttons read as clean circles
 * instead of outlined ones.
 */
@Composable
fun WhitzGlassCircleButton(
    hazeState: HazeState,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 46.dp,
    showBorder: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val hazeStyle = remember(colors.canvas) {
        HazeStyle(
            backgroundColor = colors.canvas.copy(alpha = 0.5f),
            tints = listOf(HazeTint(colors.canvas.copy(alpha = 0.55f))),
            blurRadius = 22.dp,
            noiseFactor = 0.05f,
        )
    }
    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .hazeEffect(state = hazeState, style = hazeStyle)
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = LocalIndication.current,
                onClick = onClick,
            )
            .then(
                if (showBorder) {
                    Modifier.border(0.5.dp, colors.line, CircleShape)
                } else {
                    Modifier
                },
            ),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}

/**
 * Top-bar Back button that smoothly gains a circular surface background (matching list card surface)
 * and hairline border when the page content scrolls underneath.
 */
@Composable
fun WhitzTopBarBackButton(
    onClick: () -> Unit,
    scrolled: Boolean,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val colors = LocalWhitzColors.current
    val bgAlpha by animateFloatAsState(
        targetValue = if (scrolled) 1f else 0f,
        animationSpec = tween(durationMillis = 180),
        label = "topBarBackBgAlpha",
    )
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(colors.surface.copy(alpha = bgAlpha))
            .border(
                width = 0.5.dp,
                color = colors.line.copy(alpha = bgAlpha),
                shape = CircleShape,
            ),
    ) {
        Icon(
            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
            contentDescription = "返回",
            tint = colors.fg,
        )
    }
}

@Stable
class WhitzCollapsibleTopBarState(
    internal val maxCollapsePx: Float,
    private val collapsible: Boolean,
    private val scope: CoroutineScope,
) {
    var heightOffsetPx by mutableFloatStateOf(0f)
        internal set
    var contentOffsetPx by mutableFloatStateOf(0f)
        internal set

    val collapseFraction: Float
        get() = if (!collapsible || maxCollapsePx <= 0f) {
            1f
        } else {
            (-heightOffsetPx / maxCollapsePx).coerceIn(0f, 1f)
        }

    val isScrolled: Boolean
        get() = heightOffsetPx < -4f || contentOffsetPx < -4f

    val nestedScrollConnection = object : NestedScrollConnection {
        override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
            if (!collapsible || maxCollapsePx <= 0f) return Offset.Zero
            if (available.y < 0f && heightOffsetPx > -maxCollapsePx) {
                val prev = heightOffsetPx
                val next = (prev + available.y).coerceIn(-maxCollapsePx, 0f)
                heightOffsetPx = next
                return Offset(0f, next - prev)
            }
            return Offset.Zero
        }

        override fun onPostScroll(
            consumed: Offset,
            available: Offset,
            source: NestedScrollSource,
        ): Offset {
            if (available.y > 0f && consumed.y == 0f) {
                // Reached the very top of scroll container
                contentOffsetPx = 0f
            } else {
                contentOffsetPx = (contentOffsetPx + consumed.y).coerceAtMost(0f)
            }

            if (!collapsible || maxCollapsePx <= 0f) return Offset.Zero
            if (available.y > 0f && heightOffsetPx < 0f) {
                val prev = heightOffsetPx
                val next = (prev + available.y).coerceIn(-maxCollapsePx, 0f)
                heightOffsetPx = next
                return Offset(0f, next - prev)
            }
            return Offset.Zero
        }

        override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
            if (collapsible && maxCollapsePx > 0f) {
                val fraction = collapseFraction
                if (fraction > 0.01f && fraction < 0.99f) {
                    val target = if (fraction < 0.5f) 0f else -maxCollapsePx
                    scope.launch {
                        Animatable(heightOffsetPx).animateTo(
                            targetValue = target,
                            animationSpec = spring(
                                dampingRatio = Spring.DampingRatioNoBouncy,
                                stiffness = Spring.StiffnessMediumLow,
                            ),
                        ) {
                            heightOffsetPx = value
                        }
                    }
                }
            }
            return super.onPostFling(consumed, available)
        }
    }
}

private val TopBarExpandedBodyHeight = 96.dp
private val TopBarCollapsedBodyHeight = 56.dp
private val TopBarInternalFadeHeight = 18.dp

@Composable
fun rememberWhitzCollapsibleTopBarState(
    collapsible: Boolean = true,
): WhitzCollapsibleTopBarState {
    val density = LocalDensity.current
    val scope = rememberCoroutineScope()
    val maxCollapsePx = with(density) {
        (TopBarExpandedBodyHeight - TopBarCollapsedBodyHeight).toPx()
    }
    return remember(maxCollapsePx, collapsible, scope) {
        WhitzCollapsibleTopBarState(
            maxCollapsePx = maxCollapsePx,
            collapsible = collapsible,
            scope = scope,
        )
    }
}

/**
 * Secondary-page scaffold with:
 * - True smooth FLIP collapsing title (single Text smoothly translating & scaling via graphicsLayer)
 * - Generous spacing between circular Back button and collapsed title (18.dp gap)
 * - Scrolled Back button surface background (`colors.surface`) + hairline border (`colors.line`)
 * - Internal translucent gradient fade starting right at the bottom of the title text (no dangling gap below)
 */
@Composable
fun WhitzCollapsibleTopBarLayout(
    title: String,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    collapsible: Boolean = true,
    backEnabled: Boolean = true,
    scrolledOverride: Boolean? = null,
    applyImePadding: Boolean = false,
    actions: (@Composable RowScope.() -> Unit)? = null,
    overlay: @Composable BoxScope.() -> Unit = {},
    content: @Composable BoxScope.(topContentPadding: Dp) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val density = LocalDensity.current
    val topBarState = rememberWhitzCollapsibleTopBarState(collapsible = collapsible)
    val statusTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()

    val fraction = topBarState.collapseFraction
    val isScrolled = scrolledOverride ?: topBarState.isScrolled
    val currentBodyHeight = lerp(TopBarExpandedBodyHeight, TopBarCollapsedBodyHeight, fraction)
    val currentBarHeight = statusTop + currentBodyHeight
    // Content starts right at the bottom of the title text, sliding directly into the bar's internal fade zone
    val contentTopPadding = (currentBarHeight - TopBarInternalFadeHeight).coerceAtLeast(statusTop)

    // Cosine-eased internal gradient: solid down to the bottom of the title text, fading smoothly to transparent at bar bottom
    val solidHoldFraction = remember(currentBarHeight) {
        val total = currentBarHeight.value.coerceAtLeast(1f)
        ((total - TopBarInternalFadeHeight.value) / total).coerceIn(0.35f, 0.85f)
    }
    val topBarBrush = remember(colors.canvas, solidHoldFraction) {
        Brush.verticalGradient(
            colorStops = buildEasedScrimStops(
                color = colors.canvas,
                topToBottom = true,
                solidHoldFraction = solidHoldFraction,
                maxAlpha = 1f,
            ),
        )
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(colors.canvas)
            .nestedScroll(topBarState.nestedScrollConnection),
    ) {
        // 1. Page content (flows seamlessly under the internal translucent fade zone of the top bar)
        Box(
            modifier = Modifier
                .fillMaxSize()
                .then(if (applyImePadding) Modifier.imePadding() else Modifier),
            contentAlignment = Alignment.TopCenter,
        ) {
            content(contentTopPadding)
        }

        // 2. Collapsible Top Bar with internal gradient & FLIP title
        Box(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .fillMaxWidth()
                .height(currentBarHeight)
                .background(topBarBrush),
        ) {
            // Navigation row (Back button on start, optional actions on end)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .height(52.dp)
                    .padding(horizontal = 12.dp),
            ) {
                WhitzTopBarBackButton(
                    onClick = onBack,
                    scrolled = isScrolled,
                    enabled = backEnabled,
                    modifier = Modifier.align(Alignment.CenterStart),
                )

                if (actions != null) {
                    Row(
                        modifier = Modifier.align(Alignment.CenterEnd),
                        verticalAlignment = Alignment.CenterVertically,
                        content = actions,
                    )
                }
            }

            // Single FLIP Title: smoothly translates & scales from expanded (28sp) to collapsed (19sp)
            // Expanded: x = 20.dp, centerY = statusTop + 65.dp (baseline right at fade boundary)
            // Collapsed: x = 70.dp (12dp + 40dp back button + 18dp generous gap), centerY = statusTop + 26.dp
            val titleX = lerp(20.dp, 70.dp, fraction)
            val titleCenterY = lerp(statusTop + 65.dp, statusTop + 26.dp, fraction)
            val titleScale = lerp(1f, 19f / 28f, fraction)
            val titleXpx = with(density) { titleX.toPx() }
            val titleTopPx = with(density) { (titleCenterY - 17.dp).toPx() }

            Text(
                text = title,
                fontSize = 28.sp,
                lineHeight = 34.sp,
                fontWeight = FontWeight.SemiBold,
                color = colors.fg,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(end = if (actions != null) 96.dp else 20.dp)
                    .graphicsLayer {
                        translationX = titleXpx
                        translationY = titleTopPx
                        scaleX = titleScale
                        scaleY = titleScale
                        transformOrigin = TransformOrigin(0f, 0.5f)
                    },
            )
        }

        // 3. Overlays (FABs, One-Handed Docks, etc.)
        overlay()
    }
}
