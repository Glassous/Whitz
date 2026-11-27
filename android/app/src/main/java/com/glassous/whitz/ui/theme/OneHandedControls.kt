package com.glassous.whitz.ui.theme

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.glassous.whitz.core.model.OneHandedSide
import dev.chrisbanes.haze.HazeState
import dev.chrisbanes.haze.HazeStyle
import dev.chrisbanes.haze.HazeTint
import dev.chrisbanes.haze.hazeEffect

/**
 * Default ergonomic thumb-zone height above the system navigation bar for regular pages.
 * Keeps controls comfortably inside the natural thumb arc without colliding with bottom edges.
 */
val OneHandedDefaultBottomOffset: Dp = 120.dp
val OneHandedEdgeInset: Dp = 14.dp
val OneHandedButtonSize: Dp = 48.dp

/**
 * Vertical floating action dock for One-Handed Mode.
 * Anchors to BottomStart (LEFT) or BottomEnd (RIGHT) inside the parent [BoxScope],
 * raised into the natural thumb sweep zone.
 */
@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun BoxScope.WhitzOneHandedActionDock(
    visible: Boolean = LocalOneHandedConfig.current.enabled,
    side: OneHandedSide = LocalOneHandedConfig.current.side,
    bottomOffset: Dp? = null,
    applyImePadding: Boolean = true,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    val targetBottom = bottomOffset ?: (navBottom + OneHandedDefaultBottomOffset)
    val animatedBottom by animateDpAsState(
        targetValue = targetBottom.coerceAtLeast(0.dp),
        animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
        label = "oneHandedDockBottom",
    )
    val alignment = when (side) {
        OneHandedSide.LEFT -> Alignment.BottomStart
        OneHandedSide.RIGHT -> Alignment.BottomEnd
    }

    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
            scaleIn(
                initialScale = 0.88f,
                animationSpec = MaterialTheme.motionScheme.defaultSpatialSpec(),
            ),
        exit = fadeOut(animationSpec = MaterialTheme.motionScheme.fastEffectsSpec()) +
            scaleOut(
                targetScale = 0.90f,
                animationSpec = MaterialTheme.motionScheme.fastEffectsSpec(),
            ),
        modifier = modifier
            .align(alignment)
            .then(if (applyImePadding) Modifier.imePadding() else Modifier)
            .padding(
                start = OneHandedEdgeInset,
                end = OneHandedEdgeInset,
                bottom = animatedBottom,
            ),
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp),
            content = content,
        )
    }
}

/**
 * Circular 48dp button designed for the vertical One-Handed Mode dock.
 *
 * - When [emphasized] is true, uses primary container styling (replaces FABs / primary top actions).
 * - When [hazeState] is provided and [emphasized] is false, renders with frosted glass blur.
 * - Otherwise uses an elevated translucent surface with crisp hairline border.
 */
@Composable
fun WhitzOneHandedActionButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    emphasized: Boolean = false,
    hazeState: HazeState? = null,
    showBadge: Boolean = false,
    size: Dp = OneHandedButtonSize,
    content: @Composable () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val alphaMod = if (enabled) Modifier else Modifier.alpha(0.45f)

    Box(modifier = modifier.then(alphaMod)) {
        if (emphasized) {
            Surface(
                onClick = onClick,
                enabled = enabled,
                shape = CircleShape,
                color = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary,
                shadowElevation = 8.dp,
                modifier = Modifier.size(size),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    content()
                }
            }
        } else if (hazeState != null) {
            val hazeStyle = remember(colors.canvas) {
                HazeStyle(
                    backgroundColor = colors.canvas.copy(alpha = 0.58f),
                    tints = listOf(HazeTint(colors.canvas.copy(alpha = 0.62f))),
                    blurRadius = 22.dp,
                    noiseFactor = 0.05f,
                )
            }
            Box(
                modifier = Modifier
                    .size(size)
                    .clip(CircleShape)
                    .hazeEffect(state = hazeState, style = hazeStyle)
                    .clickable(
                        enabled = enabled,
                        interactionSource = remember { MutableInteractionSource() },
                        indication = LocalIndication.current,
                        onClick = onClick,
                    )
                    .border(0.6.dp, colors.lineStrong.copy(alpha = 0.75f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                content()
            }
        } else {
            Surface(
                onClick = onClick,
                enabled = enabled,
                shape = CircleShape,
                color = colors.surface.copy(alpha = 0.94f),
                contentColor = colors.fg,
                border = BorderStroke(0.6.dp, colors.lineStrong.copy(alpha = 0.75f)),
                shadowElevation = 6.dp,
                modifier = Modifier.size(size),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    content()
                }
            }
        }

        if (showBadge) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = 6.dp, end = 6.dp)
                    .size(7.dp)
                    .clip(CircleShape)
                    .background(if (emphasized) MaterialTheme.colorScheme.onPrimary else colors.fg),
            )
        }
    }
}

/**
 * Convenience single-button dock containing a Back button for sub-pages in One-Handed Mode.
 */
@Composable
fun BoxScope.WhitzOneHandedBackDock(
    onBack: () -> Unit,
    visible: Boolean = LocalOneHandedConfig.current.enabled,
    enabled: Boolean = true,
    bottomOffset: Dp? = null,
    applyImePadding: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val colors = LocalWhitzColors.current
    WhitzOneHandedActionDock(
        visible = visible,
        bottomOffset = bottomOffset,
        applyImePadding = applyImePadding,
        modifier = modifier,
    ) {
        WhitzOneHandedActionButton(
            onClick = onBack,
            enabled = enabled,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "返回",
                tint = colors.fg,
                modifier = Modifier.size(22.dp),
            )
        }
    }
}
