package com.glassous.whitz.ui.theme

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.R

/**
 * Web-aligned Whitz wordmark: tight "W" vector mark + "hitz" wordmark.
 */
@Composable
fun WhitzBrandMark(
    modifier: Modifier = Modifier,
    markHeight: Dp = 16.dp,
    markWidth: Dp = 24.dp,
    fontSize: TextUnit = 22.sp,
    tint: Color = LocalWhitzColors.current.fg,
) {
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            painter = painterResource(R.drawable.ic_whitz_logo_tight),
            contentDescription = "Whitz",
            tint = tint,
            modifier = Modifier
                .width(markWidth)
                .height(markHeight),
        )
        Spacer(modifier = Modifier.width(1.dp))
        Text(
            text = "hitz",
            color = tint,
            fontSize = fontSize,
            fontWeight = FontWeight.SemiBold,
            letterSpacing = (-0.5).sp,
            modifier = Modifier.offset(y = 0.5.dp),
        )
    }
}

/**
 * Standalone Whitz W glyph (64x64 viewport).
 */
@Composable
fun WhitzLogoMark(
    modifier: Modifier = Modifier,
    tint: Color = LocalWhitzColors.current.fg,
) {
    Icon(
        painter = painterResource(R.drawable.ic_whitz_logo),
        contentDescription = "Whitz",
        tint = tint,
        modifier = modifier,
    )
}
