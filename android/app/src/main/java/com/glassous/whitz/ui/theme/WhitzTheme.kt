package com.glassous.whitz.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import com.glassous.whitz.core.model.ThemePreference

data class WhitzExtendedColors(
    val canvas: Color,
    val sidebar: Color,
    val surface: Color,
    val hover: Color,
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

private val LightColorScheme = lightColorScheme(
    primary = Color(0xFF111113),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFF0F0F2),
    onPrimaryContainer = Color(0xFF111113),
    secondary = Color(0xFF52525B),
    onSecondary = Color(0xFFFFFFFF),
    background = Color(0xFFFFFFFF),
    onBackground = Color(0xFF111113),
    surface = Color(0xFFF4F4F5),
    onSurface = Color(0xFF111113),
    surfaceVariant = Color(0xFFECECEE),
    onSurfaceVariant = Color(0xFF52525B),
    outline = Color(0xFFE4E4E7),
    outlineVariant = Color(0xFFD4D4D8),
    error = Color(0xFFDC2626),
    onError = Color(0xFFFFFFFF),
)

private val DarkColorScheme = darkColorScheme(
    primary = Color(0xFFFFFFFF),
    onPrimary = Color(0xFF000000),
    primaryContainer = Color(0xFF1F1F23),
    onPrimaryContainer = Color(0xFFF4F4F5),
    secondary = Color(0xFFA1A1AA),
    onSecondary = Color(0xFF000000),
    background = Color(0xFF000000),
    onBackground = Color(0xFFF4F4F5),
    surface = Color(0xFF18181B),
    onSurface = Color(0xFFF4F4F5),
    surfaceVariant = Color(0xFF202024),
    onSurfaceVariant = Color(0xFFA1A1AA),
    outline = Color(0xFF232327),
    outlineVariant = Color(0xFF36363C),
    error = Color(0xFFF87171),
    onError = Color(0xFF000000),
)

@Composable
fun WhitzTheme(
    preference: ThemePreference = ThemePreference.SYSTEM,
    content: @Composable () -> Unit,
) {
    val dark = when (preference) {
        ThemePreference.SYSTEM -> isSystemInDarkTheme()
        ThemePreference.LIGHT -> false
        ThemePreference.DARK -> true
    }
    val extended = if (dark) DarkExtended else LightExtended
    val scheme = if (dark) DarkColorScheme else LightColorScheme

    CompositionLocalProvider(LocalWhitzColors provides extended) {
        MaterialTheme(
            colorScheme = scheme,
            content = content,
        )
    }
}
