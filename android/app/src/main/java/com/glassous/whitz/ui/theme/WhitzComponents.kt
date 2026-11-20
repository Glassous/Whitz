package com.glassous.whitz.ui.theme

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ButtonGroupDefaults
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.ToggleButton
import androidx.compose.material3.ToggleButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
    steps: Int = 24,
): Array<Pair<Float, Color>> = Array(steps + 1) { index ->
    val position = index / steps.toFloat()
    val t = if (topToBottom) position else 1f - position
    val alpha = if (t <= solidHoldFraction) {
        1f
    } else {
        val u = ((t - solidHoldFraction) / (1f - solidHoldFraction)).coerceIn(0f, 1f)
        0.5f * (1f + cos(PI * u).toFloat())
    }
    position to color.copy(alpha = alpha)
}

/**
 * Top gradient scrim mask matching the canvas color with dense cosine-eased stops.
 */
@Composable
fun WhitzProgressiveBlurTop(
    modifier: Modifier = Modifier,
) {
    val canvas = LocalWhitzColors.current.canvas
    val brush = remember(canvas) {
        Brush.verticalGradient(
            colorStops = buildEasedScrimStops(
                color = canvas,
                topToBottom = true,
                solidHoldFraction = 0.28f,
            ),
        )
    }
    Box(modifier = modifier.background(brush))
}

/**
 * Bottom gradient scrim mask matching the canvas color with dense cosine-eased stops.
 */
@Composable
fun WhitzProgressiveBlurBottom(
    modifier: Modifier = Modifier,
) {
    val canvas = LocalWhitzColors.current.canvas
    val brush = remember(canvas) {
        Brush.verticalGradient(
            colorStops = buildEasedScrimStops(
                color = canvas,
                topToBottom = false,
                solidHoldFraction = 0.24f,
            ),
        )
    }
    Box(modifier = modifier.background(brush))
}
