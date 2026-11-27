package com.glassous.whitz.feature.auth

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import com.glassous.whitz.ui.theme.Visibility
import com.glassous.whitz.ui.theme.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.core.network.LogoutReason
import com.glassous.whitz.ui.theme.LocalOneHandedConfig
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzBrandMark
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzOneHandedBackDock
import com.glassous.whitz.ui.theme.WhitzTextField
import kotlin.math.hypot

@Composable
private fun AuthScaffold(
    title: String,
    subtitle: String,
    onBack: (() -> Unit)? = null,
    footer: (@Composable () -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(colors.canvas),
    ) {
        // Web-aligned ambient radial aura + masked dot-grid backdrop (edge-to-edge)
        Canvas(modifier = Modifier.fillMaxSize()) {
            val auraCenter = Offset(size.width * 0.5f, size.height * 0.08f)
            val auraRadius = size.width.coerceAtLeast(size.height) * 0.58f
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        colors.surface.copy(alpha = if (colors.isDark) 0.45f else 0.9f),
                        Color.Transparent,
                    ),
                    center = auraCenter,
                    radius = auraRadius,
                ),
                radius = auraRadius,
                center = auraCenter,
            )

            val step = 28.dp.toPx()
            val maxDist = hypot(size.width * 0.45f, size.height * 0.35f)
            val origin = Offset(size.width * 0.5f, size.height * 0.28f)
            val dotAlphaBase = if (colors.isDark) 0.22f else 0.42f
            var x = step * 0.5f
            while (x < size.width) {
                var y = step * 0.5f
                while (y < size.height * 0.72f) {
                    val d = hypot(x - origin.x, y - origin.y)
                    val mask = (1f - (d / maxDist)).coerceIn(0f, 1f)
                    if (mask > 0.04f) {
                        drawCircle(
                            color = colors.lineStrong.copy(alpha = dotAlphaBase * mask),
                            radius = 1.dp.toPx(),
                            center = Offset(x, y),
                        )
                    }
                    y += step
                }
                x += step
            }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // Top bar matching AuthLayout.vue
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (onBack != null) {
                    IconButton(onClick = onBack, modifier = Modifier.size(40.dp)) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回",
                            tint = colors.fg,
                        )
                    }
                    Spacer(modifier = Modifier.width(4.dp))
                }
                WhitzBrandMark(modifier = Modifier.padding(vertical = 4.dp))
            }

            Spacer(modifier = Modifier.weight(1f, fill = true))

            // Centered elevated card (max 416dp)
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .widthIn(max = 416.dp),
                shape = RoundedCornerShape(24.dp),
                color = colors.canvas.copy(alpha = 0.96f),
                border = BorderStroke(1.dp, colors.line),
                shadowElevation = if (colors.isDark) 10.dp else 6.dp,
            ) {
                Column(modifier = Modifier.padding(24.dp)) {
                    Text(
                        text = title,
                        fontSize = 22.sp,
                        fontWeight = FontWeight.SemiBold,
                        letterSpacing = (-0.4).sp,
                        color = colors.fg,
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = subtitle,
                        fontSize = 13.5.sp,
                        lineHeight = 19.sp,
                        color = colors.fgMuted,
                    )
                    Spacer(modifier = Modifier.height(20.dp))
                    content()
                }
            }

            if (footer != null) {
                Spacer(modifier = Modifier.height(18.dp))
                footer()
            }

            Spacer(modifier = Modifier.weight(1f, fill = true))
        }

        if (onBack != null) {
            WhitzOneHandedBackDock(onBack = onBack)
        }
    }
}

@Composable
private fun ErrorBanner(message: String?) {
    if (message.isNullOrBlank()) return
    val colors = LocalWhitzColors.current
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(colors.dangerWeak)
            .border(1.dp, colors.danger.copy(alpha = 0.28f), RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(text = message, color = colors.danger, fontSize = 13.sp, lineHeight = 18.sp)
    }
}

@Composable
private fun InfoBanner(message: String?, isWarning: Boolean = false) {
    if (message.isNullOrBlank()) return
    val colors = LocalWhitzColors.current
    val bg = if (isWarning) colors.warningWeak else colors.successWeak
    val fg = if (isWarning) colors.warning else colors.success
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(bg)
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(text = message, color = fg, fontSize = 13.sp, lineHeight = 18.sp)
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun AuthPrimaryButton(
    text: String,
    loading: Boolean,
    onClick: () -> Unit,
) {
    Button(
        onClick = onClick,
        shapes = ButtonDefaults.shapesFor(48.dp),
        enabled = !loading,
        modifier = Modifier
            .fillMaxWidth()
            .height(48.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.primary,
            contentColor = MaterialTheme.colorScheme.onPrimary,
        ),
    ) {
        if (loading) {
            WhitzLoadingIndicator(
                size = 22.dp,
                color = MaterialTheme.colorScheme.onPrimary,
            )
        } else {
            Text(text, fontWeight = FontWeight.Medium, fontSize = 15.sp)
        }
    }
}

@Composable
fun LoginScreen(
    vm: AuthViewModel,
    onLoginSuccess: () -> Unit,
    onNavigateRegister: () -> Unit,
    onNavigateForgot: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val logoutNotice by vm.logoutNotice.collectAsState()
    val colors = LocalWhitzColors.current
    var isCodeMode by remember { mutableStateOf(false) }
    var account by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }

    AuthScaffold(
        title = "欢迎回来",
        subtitle = "登录你的 Whitz 账号，继续上次的对话",
        footer = {
            Row(
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("还没有账号？", fontSize = 13.sp, color = colors.fgMuted)
                TextButton(onClick = onNavigateRegister) {
                    Text("立即注册", fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = colors.fg)
                }
            }
        },
    ) {
        logoutNotice?.let { notice ->
            InfoBanner(
                message = notice.message,
                isWarning = notice.reason == LogoutReason.EXPIRED,
            )
        }

        WhitzConnectedRadioGroup(
            options = listOf(false to "密码登录", true to "验证码登录"),
            selected = isCodeMode,
            onSelect = {
                isCodeMode = it
                vm.clearError()
                vm.clearNotice()
            },
        )

        Spacer(modifier = Modifier.height(16.dp))
        ErrorBanner(ui.error)
        InfoBanner(ui.codeNotice)

        WhitzTextField(
            value = account,
            onValueChange = { account = it; vm.clearError() },
            label = if (isCodeMode) "邮箱地址" else "邮箱或用户名",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        if (!isCodeMode) {
            WhitzTextField(
                value = password,
                onValueChange = { password = it; vm.clearError() },
                label = "登录密码",
                visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton(onClick = { showPassword = !showPassword }) {
                        Icon(
                            if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                            contentDescription = "切换密码可见",
                            tint = colors.fgMuted,
                        )
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            )
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(
                    onClick = onNavigateForgot,
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
                ) {
                    Text("忘记密码？", fontSize = 12.5.sp, color = colors.fgMuted)
                }
            }
            Spacer(modifier = Modifier.height(4.dp))
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                WhitzTextField(
                    value = code,
                    onValueChange = { code = it; vm.clearError() },
                    label = "邮箱验证码",
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f),
                )
                Spacer(modifier = Modifier.width(10.dp))
                OutlinedButton(
                    onClick = { vm.sendEmailCode(account, "login") },
                    enabled = !ui.sendingCode && ui.cooldown == 0,
                    shape = RoundedCornerShape(14.dp),
                    border = BorderStroke(1.dp, colors.lineStrong),
                    modifier = Modifier.height(54.dp),
                ) {
                    Text(
                        when {
                            ui.sendingCode -> "发送中"
                            ui.cooldown > 0 -> "${ui.cooldown}s"
                            else -> "获取验证码"
                        },
                        fontSize = 13.sp,
                        color = colors.fg,
                    )
                }
            }
            Spacer(modifier = Modifier.height(18.dp))
        }

        AuthPrimaryButton(
            text = "登录",
            loading = ui.loading,
            onClick = {
                vm.dismissLogoutNotice()
                if (isCodeMode) {
                    vm.loginWithCode(account, code, onLoginSuccess)
                } else {
                    vm.loginWithPassword(account, password, onLoginSuccess)
                }
            },
        )
    }
}

@Composable
fun RegisterScreen(
    vm: AuthViewModel,
    onRegisterSuccess: () -> Unit,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val colors = LocalWhitzColors.current
    var email by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var displayName by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }

    AuthScaffold(
        title = "创建账号",
        subtitle = "注册 Whitz 账号，开启智能对话体验",
        onBack = onBack,
    ) {
        ErrorBanner(ui.error)
        InfoBanner(ui.codeNotice)

        WhitzTextField(
            value = email,
            onValueChange = { email = it; vm.clearError() },
            label = "邮箱地址",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            WhitzTextField(
                value = code,
                onValueChange = { code = it; vm.clearError() },
                label = "邮箱验证码",
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f),
            )
            Spacer(modifier = Modifier.width(10.dp))
            OutlinedButton(
                onClick = { vm.sendEmailCode(email, "register") },
                enabled = !ui.sendingCode && ui.cooldown == 0,
                shape = RoundedCornerShape(14.dp),
                border = BorderStroke(1.dp, colors.lineStrong),
                modifier = Modifier.height(54.dp),
            ) {
                Text(
                    when {
                        ui.sendingCode -> "发送中"
                        ui.cooldown > 0 -> "${ui.cooldown}s"
                        else -> "获取验证码"
                    },
                    fontSize = 13.sp,
                    color = colors.fg,
                )
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        WhitzTextField(
            value = displayName,
            onValueChange = { displayName = it; vm.clearError() },
            label = "昵称",
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        WhitzTextField(
            value = password,
            onValueChange = { password = it; vm.clearError() },
            label = "设置密码（至少 8 位）",
            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { showPassword = !showPassword }) {
                    Icon(
                        if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        contentDescription = "切换密码可见",
                        tint = colors.fgMuted,
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(20.dp))

        AuthPrimaryButton(
            text = "注册并登录",
            loading = ui.loading,
            onClick = { vm.register(email, code, displayName, password, onRegisterSuccess) },
        )
    }
}

@Composable
fun ForgotPasswordScreen(
    vm: AuthViewModel,
    onResetSuccess: () -> Unit,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val colors = LocalWhitzColors.current
    var email by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var newPassword by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }

    AuthScaffold(
        title = "重置密码",
        subtitle = "通过邮箱验证码设置新密码",
        onBack = onBack,
    ) {
        ErrorBanner(ui.error)
        InfoBanner(ui.codeNotice)

        WhitzTextField(
            value = email,
            onValueChange = { email = it; vm.clearError() },
            label = "注册邮箱",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            WhitzTextField(
                value = code,
                onValueChange = { code = it; vm.clearError() },
                label = "邮箱验证码",
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f),
            )
            Spacer(modifier = Modifier.width(10.dp))
            OutlinedButton(
                onClick = { vm.sendEmailCode(email, "reset_password") },
                enabled = !ui.sendingCode && ui.cooldown == 0,
                shape = RoundedCornerShape(14.dp),
                border = BorderStroke(1.dp, colors.lineStrong),
                modifier = Modifier.height(54.dp),
            ) {
                Text(
                    when {
                        ui.sendingCode -> "发送中"
                        ui.cooldown > 0 -> "${ui.cooldown}s"
                        else -> "获取验证码"
                    },
                    fontSize = 13.sp,
                    color = colors.fg,
                )
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        WhitzTextField(
            value = newPassword,
            onValueChange = { newPassword = it; vm.clearError() },
            label = "新密码（至少 8 位）",
            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { showPassword = !showPassword }) {
                    Icon(
                        if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        contentDescription = "切换密码可见",
                        tint = colors.fgMuted,
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(20.dp))

        AuthPrimaryButton(
            text = "确认重置",
            loading = ui.loading,
            onClick = { vm.resetPassword(email, code, newPassword, onResetSuccess) },
        )
    }
}
