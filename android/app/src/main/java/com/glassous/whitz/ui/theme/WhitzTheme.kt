package com.glassous.whitz.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.MaterialExpressiveTheme
import androidx.compose.material3.MotionScheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.expressiveLightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.glassous.whitz.core.model.OneHandedConfig
import com.glassous.whitz.core.model.ThemePreference

data class WhitzExtendedColors(
    val canvas: Color,
    val sidebar: Color,
    val surface: Color,
    val hover: Color,
    val active: Color,
    val line: Color,
    val lineStrong: Color,
    val fg: Color,
    val fgMuted: Color,
    val fgFaint: Color,
    val success: Color,
    val successWeak: Color,
    val warning: Color,
    val warningWeak: Color,
    val danger: Color,
    val dangerWeak: Color,
    val codeBg: Color,
    val isDark: Boolean,
)

private val LightExtended = WhitzExtendedColors(
    canvas = Color(0xFFFFFFFF),
    sidebar = Color(0xFFF8F9FA),
    surface = Color(0xFFF4F4F5),
    hover = Color(0xFFECECEE),
    active = Color(0xFFE4E4E7),
    line = Color(0xFFE4E4E7),
    lineStrong = Color(0xFFD4D4D8),
    fg = Color(0xFF111113),
    fgMuted = Color(0xFF52525B),
    fgFaint = Color(0xFF71717A),
    success = Color(0xFF15803D),
    successWeak = Color(0xFFECFDF3),
    warning = Color(0xFFB45309),
    warningWeak = Color(0xFFFEF3C7),
    danger = Color(0xFFDC2626),
    dangerWeak = Color(0xFFFEF2F2),
    codeBg = Color(0xFF111113),
    isDark = false,
)

private val DarkExtended = WhitzExtendedColors(
    canvas = Color(0xFF000000),
    sidebar = Color(0xFF111113),
    surface = Color(0xFF18181B),
    hover = Color(0xFF202024),
    active = Color(0xFF27272B),
    line = Color(0xFF232327),
    lineStrong = Color(0xFF36363C),
    fg = Color(0xFFF4F4F5),
    fgMuted = Color(0xFFA1A1AA),
    fgFaint = Color(0xFF7C7C85),
    success = Color(0xFF4ADE80),
    successWeak = Color(0xFF0F2417),
    warning = Color(0xFFFBBF24),
    warningWeak = Color(0xFF261F0D),
    danger = Color(0xFFF87171),
    dangerWeak = Color(0xFF2A1215),
    codeBg = Color(0xFF0A0A0C),
    isDark = true,
)

val LocalWhitzColors = staticCompositionLocalOf { LightExtended }
val LocalOneHandedConfig = staticCompositionLocalOf { OneHandedConfig() }

private val LightColorScheme = expressiveLightColorScheme().copy(
    primary = Color(0xFF111113),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFF0F0F2),
    onPrimaryContainer = Color(0xFF111113),
    secondary = Color(0xFF52525B),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE4E4E7),
    onSecondaryContainer = Color(0xFF111113),
    tertiary = Color(0xFF18181B),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFF4F4F5),
    onTertiaryContainer = Color(0xFF111113),
    background = Color(0xFFFFFFFF),
    onBackground = Color(0xFF111113),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF111113),
    surfaceVariant = Color(0xFFF4F4F5),
    onSurfaceVariant = Color(0xFF52525B),
    surfaceContainerLowest = Color(0xFFFFFFFF),
    surfaceContainerLow = Color(0xFFF8F9FA),
    surfaceContainer = Color(0xFFF4F4F5),
    surfaceContainerHigh = Color(0xFFECECEE),
    surfaceContainerHighest = Color(0xFFE4E4E7),
    outline = Color(0xFFE4E4E7),
    outlineVariant = Color(0xFFD4D4D8),
    error = Color(0xFFDC2626),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFEF2F2),
    onErrorContainer = Color(0xFFDC2626),
)

private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFFFFFFFF),
    onPrimary = Color(0xFF000000),
    primaryContainer = Color(0xFF27272B),
    onPrimaryContainer = Color(0xFFF4F4F5),
    secondary = Color(0xFFA1A1AA),
    onSecondary = Color(0xFF000000),
    secondaryContainer = Color(0xFF202024),
    onSecondaryContainer = Color(0xFFF4F4F5),
    tertiary = Color(0xFFF4F4F5),
    onTertiary = Color(0xFF000000),
    tertiaryContainer = Color(0xFF1F1F23),
    onTertiaryContainer = Color(0xFFF4F4F5),
    background = Color(0xFF000000),
    onBackground = Color(0xFFF4F4F5),
    surface = Color(0xFF000000),
    onSurface = Color(0xFFF4F4F5),
    surfaceVariant = Color(0xFF18181B),
    onSurfaceVariant = Color(0xFFA1A1AA),
    surfaceContainerLowest = Color(0xFF000000),
    surfaceContainerLow = Color(0xFF111113),
    surfaceContainer = Color(0xFF18181B),
    surfaceContainerHigh = Color(0xFF202024),
    surfaceContainerHighest = Color(0xFF27272B),
    outline = Color(0xFF232327),
    outlineVariant = Color(0xFF36363C),
    error = Color(0xFFF87171),
    onError = Color(0xFF000000),
    errorContainer = Color(0xFF2A1215),
    onErrorContainer = Color(0xFFF87171),
)

private val WhitzShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(24.dp),
    largeIncreased = RoundedCornerShape(26.dp),
    extraLargeIncreased = RoundedCornerShape(28.dp),
    extraExtraLarge = RoundedCornerShape(32.dp),
)

@Composable
fun isWhitzDarkTheme(preference: ThemePreference): Boolean = when (preference) {
    ThemePreference.SYSTEM -> isSystemInDarkTheme()
    ThemePreference.LIGHT -> false
    ThemePreference.DARK -> true
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun WhitzTheme(
    preference: ThemePreference = ThemePreference.SYSTEM,
    oneHandedConfig: OneHandedConfig = OneHandedConfig(),
    content: @Composable () -> Unit,
) {
    val dark = isWhitzDarkTheme(preference)
    val extended = if (dark) DarkExtended else LightExtended
    val scheme = if (dark) DarkColorScheme else LightColorScheme

    CompositionLocalProvider(
        LocalWhitzColors provides extended,
        LocalOneHandedConfig provides oneHandedConfig,
    ) {
        MaterialExpressiveTheme(
            colorScheme = scheme,
            motionScheme = MotionScheme.expressive(),
            shapes = WhitzShapes,
            content = content,
        )
    }
}
