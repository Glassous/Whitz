package com.glassous.whitz.feature.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.core.network.LogoutReason
import com.glassous.whitz.ui.theme.LocalWhitzColors

@Composable
private fun AuthScaffold(
    title: String,
    subtitle: String,
    onBack: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(colors.canvas)
            .systemBarsPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (onBack != null) {
            Row(modifier = Modifier.fillMaxWidth()) {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回", tint = colors.fg)
                }
            }
        } else {
            Spacer(modifier = Modifier.height(24.dp))
        }

        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(RoundedCornerShape(14.dp))
                .background(MaterialTheme.colorScheme.primary),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "W",
                color = MaterialTheme.colorScheme.onPrimary,
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = title,
            fontSize = 24.sp,
            fontWeight = FontWeight.Bold,
            color = colors.fg,
        )
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = subtitle,
            fontSize = 14.sp,
            color = colors.fgMuted,
        )
        Spacer(modifier = Modifier.height(24.dp))
        Column(modifier = Modifier.fillMaxWidth()) {
            content()
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
            .clip(RoundedCornerShape(10.dp))
            .background(colors.dangerWeak)
            .border(1.dp, colors.danger.copy(alpha = 0.3f), RoundedCornerShape(10.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(text = message, color = colors.danger, fontSize = 13.sp)
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
            .clip(RoundedCornerShape(10.dp))
            .background(bg)
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(text = message, color = fg, fontSize = 13.sp)
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
    var isCodeMode by remember { mutableStateOf(false) }
    var account by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }

    AuthScaffold(
        title = "欢迎回来",
        subtitle = "登录你的 Whitz 账号，继续上次的对话",
    ) {
        logoutNotice?.let { notice ->
            InfoBanner(
                message = notice.message,
                isWarning = notice.reason == LogoutReason.EXPIRED,
            )
        }

        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            SegmentedButton(
                selected = !isCodeMode,
                onClick = {
                    isCodeMode = false
                    vm.clearError()
                    vm.clearNotice()
                },
                shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
            ) { Text("密码登录") }
            SegmentedButton(
                selected = isCodeMode,
                onClick = {
                    isCodeMode = true
                    vm.clearError()
                    vm.clearNotice()
                },
                shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
            ) { Text("验证码登录") }
        }

        Spacer(modifier = Modifier.height(16.dp))
        ErrorBanner(ui.error)
        InfoBanner(ui.codeNotice)

        OutlinedTextField(
            value = account,
            onValueChange = { account = it; vm.clearError() },
            label = { Text(if (isCodeMode) "邮箱地址" else "邮箱或用户名") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        if (!isCodeMode) {
            OutlinedTextField(
                value = password,
                onValueChange = { password = it; vm.clearError() },
                label = { Text("登录密码") },
                singleLine = true,
                visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton(onClick = { showPassword = !showPassword }) {
                        Icon(
                            if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                            contentDescription = "切换密码可见",
                        )
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            )
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onNavigateForgot) {
                    Text("忘记密码？")
                }
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = code,
                    onValueChange = { code = it; vm.clearError() },
                    label = { Text("邮箱验证码") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f),
                )
                Spacer(modifier = Modifier.width(10.dp))
                OutlinedButton(
                    onClick = { vm.sendEmailCode(account, "login") },
                    enabled = !ui.sendingCode && ui.cooldown == 0,
                    modifier = Modifier.height(54.dp),
                ) {
                    Text(
                        when {
                            ui.sendingCode -> "发送中"
                            ui.cooldown > 0 -> "${ui.cooldown}s"
                            else -> "获取验证码"
                        }
                    )
                }
            }
            Spacer(modifier = Modifier.height(16.dp))
        }

        Button(
            onClick = {
                vm.dismissLogoutNotice()
                if (isCodeMode) {
                    vm.loginWithCode(account, code, onLoginSuccess)
                } else {
                    vm.loginWithPassword(account, password, onLoginSuccess)
                }
            },
            enabled = !ui.loading,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary,
            ),
        ) {
            if (ui.loading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            } else {
                Text("登录", fontWeight = FontWeight.Medium)
            }
        }

        Spacer(modifier = Modifier.height(16.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("还没有账号？", fontSize = 14.sp, color = LocalWhitzColors.current.fgMuted)
            TextButton(onClick = onNavigateRegister) {
                Text("立即注册", fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
fun RegisterScreen(
    vm: AuthViewModel,
    onRegisterSuccess: () -> Unit,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    var email by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var displayName by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }

    AuthScaffold(
        title = "创建账号",
        subtitle = "注册 Whitz 账号开始使用 AI 助理",
        onBack = onBack,
    ) {
        ErrorBanner(ui.error)
        InfoBanner(ui.codeNotice)

        OutlinedTextField(
            value = email,
            onValueChange = { email = it; vm.clearError() },
            label = { Text("邮箱地址") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = code,
                onValueChange = { code = it; vm.clearError() },
                label = { Text("邮箱验证码") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f),
            )
            Spacer(modifier = Modifier.width(10.dp))
            OutlinedButton(
                onClick = { vm.sendEmailCode(email, "register") },
                enabled = !ui.sendingCode && ui.cooldown == 0,
                modifier = Modifier.height(54.dp),
            ) {
                Text(
                    when {
                        ui.sendingCode -> "发送中"
                        ui.cooldown > 0 -> "${ui.cooldown}s"
                        else -> "获取验证码"
                    }
                )
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        OutlinedTextField(
            value = displayName,
            onValueChange = { displayName = it; vm.clearError() },
            label = { Text("昵称") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        OutlinedTextField(
            value = password,
            onValueChange = { password = it; vm.clearError() },
            label = { Text("设置密码（至少 6 位）") },
            singleLine = true,
            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { showPassword = !showPassword }) {
                    Icon(
                        if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        contentDescription = "切换密码可见",
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(20.dp))

        Button(
            onClick = { vm.register(email, code, displayName, password, onRegisterSuccess) },
            enabled = !ui.loading,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
        ) {
            if (ui.loading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            } else {
                Text("注册并登录", fontWeight = FontWeight.Medium)
            }
        }
    }
}

@Composable
fun ForgotPasswordScreen(
    vm: AuthViewModel,
    onResetSuccess: () -> Unit,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
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

        OutlinedTextField(
            value = email,
            onValueChange = { email = it; vm.clearError() },
            label = { Text("注册邮箱") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = code,
                onValueChange = { code = it; vm.clearError() },
                label = { Text("邮箱验证码") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f),
            )
            Spacer(modifier = Modifier.width(10.dp))
            OutlinedButton(
                onClick = { vm.sendEmailCode(email, "reset_password") },
                enabled = !ui.sendingCode && ui.cooldown == 0,
                modifier = Modifier.height(54.dp),
            ) {
                Text(
                    when {
                        ui.sendingCode -> "发送中"
                        ui.cooldown > 0 -> "${ui.cooldown}s"
                        else -> "获取验证码"
                    }
                )
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        OutlinedTextField(
            value = newPassword,
            onValueChange = { newPassword = it; vm.clearError() },
            label = { Text("新密码（至少 6 位）") },
            singleLine = true,
            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { showPassword = !showPassword }) {
                    Icon(
                        if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                        contentDescription = "切换密码可见",
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(modifier = Modifier.height(20.dp))

        Button(
            onClick = { vm.resetPassword(email, code, newPassword, onResetSuccess) },
            enabled = !ui.loading,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
        ) {
            if (ui.loading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary,
                )
            } else {
                Text("确认重置", fontWeight = FontWeight.Medium)
            }
        }
    }
}
