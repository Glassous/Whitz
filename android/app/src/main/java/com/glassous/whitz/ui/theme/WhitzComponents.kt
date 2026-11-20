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
import dev.chrisbanes.haze.HazeProgressive
import dev.chrisbanes.haze.HazeState
import dev.chrisbanes.haze.HazeStyle
import dev.chrisbanes.haze.HazeTint
import dev.chrisbanes.haze.hazeEffect

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

/**
 * Top progressive blur + canvas fade matching Web's `.progressive-blur-top`.
 */
@Composable
fun WhitzProgressiveBlurTop(
    hazeState: HazeState,
    modifier: Modifier = Modifier,
) {
    val canvas = LocalWhitzColors.current.canvas
    Box(
        modifier = modifier
            .hazeEffect(
                state = hazeState,
                style = HazeStyle(
                    backgroundColor = canvas,
                    tint = HazeTint(canvas.copy(alpha = 0.35f)),
                    blurRadius = 18.dp,
                ),
            ) {
                progressive = HazeProgressive.verticalGradient(
                    startIntensity = 1f,
                    endIntensity = 0f,
                )
            }
            .background(
                Brush.verticalGradient(
                    colorStops = arrayOf(
                        0.0f to canvas.copy(alpha = 0.96f),
                        0.44f to canvas.copy(alpha = 0.78f),
                        0.76f to canvas.copy(alpha = 0.28f),
                        1.0f to Color.Transparent,
                    ),
                ),
            ),
    )
}

/**
 * Bottom progressive blur + canvas fade matching Web's `.progressive-blur-bottom`.
 */
@Composable
fun WhitzProgressiveBlurBottom(
    hazeState: HazeState,
    modifier: Modifier = Modifier,
) {
    val canvas = LocalWhitzColors.current.canvas
    Box(
        modifier = modifier
            .hazeEffect(
                state = hazeState,
                style = HazeStyle(
                    backgroundColor = canvas,
                    tint = HazeTint(canvas.copy(alpha = 0.28f)),
                    blurRadius = 14.dp,
                ),
            ) {
                progressive = HazeProgressive.verticalGradient(
                    startIntensity = 0f,
                    endIntensity = 1f,
                )
            }
            .background(
                Brush.verticalGradient(
                    colorStops = arrayOf(
                        0.0f to Color.Transparent,
                        0.26f to canvas.copy(alpha = 0.16f),
                        0.58f to canvas.copy(alpha = 0.52f),
                        1.0f to canvas.copy(alpha = 0.88f),
                    ),
                ),
            ),
    )
}
