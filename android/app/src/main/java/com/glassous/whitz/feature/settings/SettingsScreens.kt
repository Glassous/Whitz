package com.glassous.whitz.feature.settings

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import com.glassous.whitz.ui.theme.Logout
import androidx.compose.material.icons.filled.Add
import com.glassous.whitz.ui.theme.AutoAwesome
import com.glassous.whitz.ui.theme.CreditCard
import androidx.compose.material.icons.filled.Delete
import com.glassous.whitz.ui.theme.Devices
import androidx.compose.material.icons.filled.Edit
import com.glassous.whitz.ui.theme.Folder
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import com.glassous.whitz.ui.theme.Psychology
import com.glassous.whitz.ui.theme.PushPin
import com.glassous.whitz.ui.theme.RateReview
import com.glassous.whitz.ui.theme.SmartToy
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearWavyProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MediumFlexibleTopAppBar
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.glassous.whitz.core.model.ThemePreference
import com.glassous.whitz.core.model.availablePercent
import com.glassous.whitz.core.model.fiveHourPercent
import com.glassous.whitz.core.model.quotaPercentLabel
import com.glassous.whitz.core.model.resolvedAssistantName
import com.glassous.whitz.core.model.weeklyPercent
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.feature.chat.LibraryPane
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzLogoMark
import com.glassous.whitz.ui.theme.WhitzTextField

object SettingsRoutes {
    const val GRAPH = "settings"
    const val HOME = "settings/home"
    const val PROFILE = "settings/profile"
    const val PASSWORD = "settings/password"
    const val LIBRARY = "settings/library"
    const val MEMORY = "settings/memory"
    const val MEMORY_ADD = "settings/memory/add"
    const val SKILLS = "settings/skills"
    const val SKILLS_CREATE = "settings/skills/create"
    const val SKILLS_GITHUB = "settings/skills/github"
    const val MEMBERSHIP = "settings/membership"
    const val ASSISTANT = "settings/assistant"
    const val PERSONA = "settings/persona"
    const val DEVICES = "settings/devices"
    const val FEEDBACK = "settings/feedback"
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun SettingsPageScaffold(
    title: String,
    ui: SettingsUiState,
    onBack: () -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    val colors = LocalWhitzColors.current
    val scrollBehavior = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()

    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .background(colors.canvas)
            .nestedScroll(scrollBehavior.nestedScrollConnection),
        containerColor = colors.canvas,
        contentWindowInsets = WindowInsets(0),
        topBar = {
            MediumFlexibleTopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = colors.canvas,
                    scrolledContainerColor = colors.canvas,
                ),
                scrollBehavior = scrollBehavior,
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回", tint = colors.fg)
                    }
                },
                title = {
                    Text(title, fontWeight = FontWeight.SemiBold, color = colors.fg)
                },
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = innerPadding.calculateTopPadding())
                .imePadding(),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(
                modifier = Modifier
                    .widthIn(max = 840.dp)
                    .fillMaxSize(),
            ) {
                val errorText = ui.error
                if (!errorText.isNullOrBlank()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(colors.dangerWeak)
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                    ) {
                        Text(errorText, color = colors.danger, fontSize = 13.sp)
                    }
                }
                val messageText = ui.message
                if (!messageText.isNullOrBlank()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(colors.successWeak)
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                    ) {
                        Text(messageText, color = colors.success, fontSize = 13.sp)
                    }
                }
                content()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SettingsHomeScreen(
    vm: SettingsViewModel,
    onNavigateRoute: (String) -> Unit,
    onBackToChat: () -> Unit,
    onLoggedOut: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val theme by vm.themePreference.collectAsState()
    val ui by vm.ui.collectAsState()
    var confirmLogout by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        vm.refreshAll()
    }

    SettingsPageScaffold(
        title = "设置",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBackToChat()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(18.dp))
                    .clickable {
                        vm.clearFeedback()
                        onNavigateRoute(SettingsRoutes.PROFILE)
                    },
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Row(
                    modifier = Modifier.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    val avatarUrl = vm.resolveAssetUrl(user?.avatarUrl)
                    if (!avatarUrl.isNullOrBlank()) {
                        AsyncImage(
                            model = avatarUrl,
                            contentDescription = "头像",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.size(48.dp).clip(CircleShape),
                        )
                    } else {
                        Box(
                            modifier = Modifier.size(48.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                (user?.displayName?.firstOrNull() ?: 'U').uppercase(),
                                color = MaterialTheme.colorScheme.onPrimary,
                                fontWeight = FontWeight.Bold,
                                fontSize = 18.sp,
                            )
                        }
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(user?.displayName ?: "", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = colors.fg)
                        Text(user?.email ?: "", fontSize = 13.sp, color = colors.fgMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = colors.fgFaint)
                }
            }

            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text("外观主题", fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                    Spacer(modifier = Modifier.height(10.dp))
                    WhitzConnectedRadioGroup(
                        options = listOf(
                            ThemePreference.SYSTEM to "跟随系统",
                            ThemePreference.LIGHT to "浅色",
                            ThemePreference.DARK to "深色",
                        ),
                        selected = theme,
                        onSelect = { vm.setTheme(it) },
                    )
                }
            }

            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(18.dp))
                    .clickable {
                        vm.clearFeedback()
                        onNavigateRoute(SettingsRoutes.ASSISTANT)
                    },
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Row(
                    modifier = Modifier.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    val assistantAvatarUrl = vm.resolveAssetUrl(user?.assistantAvatarUrl)
                    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
                    Surface(
                        modifier = Modifier.size(48.dp),
                        shape = CircleShape,
                        color = colors.canvas,
                        border = BorderStroke(0.5.dp, colors.line),
                    ) {
                        Box(contentAlignment = Alignment.Center) {
                            if (!assistantAvatarUrl.isNullOrBlank()) {
                                AsyncImage(
                                    model = assistantAvatarUrl,
                                    contentDescription = assistantName,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.fillMaxSize(),
                                )
                            } else {
                                WhitzLogoMark(modifier = Modifier.size(24.dp))
                            }
                        }
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = assistantName,
                            fontWeight = FontWeight.SemiBold,
                            fontSize = 16.sp,
                            color = colors.fg,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = "编辑助手头像与昵称",
                            fontSize = 13.sp,
                            color = colors.fgMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = colors.fgFaint)
                }
            }

            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Column {
                    val go: (String) -> Unit = { route ->
                        vm.clearFeedback()
                        onNavigateRoute(route)
                    }
                    SettingsMenuRow(Icons.Default.Person, "个人资料", null) { go(SettingsRoutes.PROFILE) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(Icons.Default.Lock, "修改密码", null) { go(SettingsRoutes.PASSWORD) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(Icons.Default.Folder, "资料库", null) { go(SettingsRoutes.LIBRARY) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(Icons.Default.Psychology, "记忆管理", null) { go(SettingsRoutes.MEMORY) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(Icons.Default.AutoAwesome, "技能管理", null) { go(SettingsRoutes.SKILLS) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(
                        Icons.Default.CreditCard,
                        "会员与积分",
                        ui.credits?.let { "${it.tierLabel} · ${it.quotaPercentLabel()}" },
                    ) { go(SettingsRoutes.MEMBERSHIP) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(Icons.Default.SmartToy, "专属助手", null) { go(SettingsRoutes.PERSONA) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(Icons.Default.Devices, "登录设备", null) { go(SettingsRoutes.DEVICES) }
                    HorizontalDivider(color = colors.line)
                    SettingsMenuRow(Icons.Default.RateReview, "反馈与评价", null) { go(SettingsRoutes.FEEDBACK) }
                }
            }

            Spacer(modifier = Modifier.height(4.dp))
            OutlinedButton(
                onClick = { confirmLogout = true },
                shapes = ButtonDefaults.shapesFor(46.dp),
                modifier = Modifier.fillMaxWidth().height(46.dp),
                border = BorderStroke(1.dp, colors.danger.copy(alpha = 0.35f)),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.danger),
            ) {
                Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text("退出登录", fontWeight = FontWeight.Medium)
            }
            Spacer(modifier = Modifier.height(8.dp))
        }
    }

    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            containerColor = colors.canvas,
            title = { Text("退出登录", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = { Text("确定要退出当前账号吗？", color = colors.fgMuted) },
            dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("取消") } },
            confirmButton = {
                Button(
                    onClick = {
                        confirmLogout = false
                        vm.logout(onLoggedOut)
                    },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = colors.danger),
                ) { Text("退出") }
            },
        )
    }
}

@Composable
private fun SettingsMenuRow(
    icon: ImageVector,
    title: String,
    badge: String?,
    onClick: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(colors.surface)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(20.dp))
        Spacer(modifier = Modifier.width(12.dp))
        Text(title, fontSize = 15.sp, color = colors.fg, modifier = Modifier.weight(1f))
        if (!badge.isNullOrBlank()) {
            Text(badge, fontSize = 12.sp, color = colors.fgFaint, modifier = Modifier.padding(end = 4.dp))
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = colors.fgFaint)
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun ProfileSettingsScreen(
    vm: SettingsViewModel,
    onOpenPassword: () -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val ui by vm.ui.collectAsState()

    var displayName by remember(user?.id) { mutableStateOf(user?.displayName ?: "") }
    var bio by remember(user?.id) { mutableStateOf(user?.bio ?: "") }
    var gender by remember(user?.id) { mutableStateOf(user?.gender ?: "") }
    var birthday by remember(user?.id) { mutableStateOf(user?.birthday ?: "") }
    var phone by remember(user?.id) { mutableStateOf(user?.phone ?: "") }
    var location by remember(user?.id) { mutableStateOf(user?.location ?: "") }
    var occupation by remember(user?.id) { mutableStateOf(user?.occupation ?: "") }
    var website by remember(user?.id) { mutableStateOf(user?.website ?: "") }
    var language by remember(user?.id) { mutableStateOf(user?.preferredLanguage ?: "zh-CN") }
    var timezone by remember(user?.id) { mutableStateOf(user?.timezone ?: "Asia/Shanghai") }

    val avatarPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) vm.uploadAvatar(uri)
    }

    SettingsPageScaffold(
        title = "个人资料",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                val userAvatarUrl = vm.resolveAssetUrl(user?.avatarUrl)
                if (!userAvatarUrl.isNullOrBlank()) {
                    AsyncImage(
                        model = userAvatarUrl,
                        contentDescription = "头像",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.size(64.dp).clip(CircleShape),
                    )
                } else {
                    Box(
                        modifier = Modifier.size(64.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            (user?.displayName?.firstOrNull() ?: 'U').uppercase(),
                            color = MaterialTheme.colorScheme.onPrimary,
                            fontSize = 22.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                OutlinedButton(
                    onClick = { avatarPicker.launch("image/*") },
                    shapes = ButtonDefaults.shapesFor(40.dp),
                ) { Text("更换头像") }
                if (!user?.avatarUrl.isNullOrBlank()) {
                    TextButton(onClick = { vm.deleteAvatar() }) { Text("移除", color = colors.danger) }
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(colors.surface)
                    .padding(14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("允许 AI 读取个人资料上下文", fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                    Text("开启后对话将参考你的职业、地区、语言偏好等资料", fontSize = 12.sp, color = colors.fgMuted)
                }
                Switch(
                    checked = user?.profileContextEnabled == true,
                    onCheckedChange = { vm.toggleProfileContext(it) },
                )
            }

            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .clickable {
                        vm.clearFeedback()
                        onOpenPassword()
                    },
                shape = RoundedCornerShape(14.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                SettingsMenuRow(Icons.Default.Lock, "修改密码", null) {
                    vm.clearFeedback()
                    onOpenPassword()
                }
            }

            WhitzTextField(value = displayName, onValueChange = { displayName = it }, label = "昵称", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = bio, onValueChange = { bio = it }, label = "个人简介", singleLine = false, maxLines = 3, modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = gender, onValueChange = { gender = it }, label = "性别", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = birthday, onValueChange = { birthday = it }, label = "生日 (YYYY-MM-DD)", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = phone, onValueChange = { phone = it }, label = "手机号", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = location, onValueChange = { location = it }, label = "所在地", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = occupation, onValueChange = { occupation = it }, label = "职业", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = website, onValueChange = { website = it }, label = "个人网站", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = language, onValueChange = { language = it }, label = "偏好语言", modifier = Modifier.fillMaxWidth())
            WhitzTextField(value = timezone, onValueChange = { timezone = it }, label = "时区", modifier = Modifier.fillMaxWidth())

            Button(
                onClick = {
                    vm.updateProfile(displayName, bio, gender, birthday, phone, location, occupation, website, language, timezone)
                },
                shapes = ButtonDefaults.shapesFor(48.dp),
                enabled = !ui.loading && displayName.isNotBlank(),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (ui.loading) "保存中..." else "保存个人资料")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun PasswordSettingsScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    var current by remember { mutableStateOf("") }
    var next by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }

    SettingsPageScaffold(
        title = "修改密码",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            WhitzTextField(
                value = current,
                onValueChange = { current = it },
                label = "当前密码",
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            WhitzTextField(
                value = next,
                onValueChange = { next = it },
                label = "新密码（至少 8 位）",
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            WhitzTextField(
                value = confirm,
                onValueChange = { confirm = it },
                label = "确认新密码",
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = {
                    if (next != confirm) return@Button
                    vm.updatePassword(current, next)
                },
                shapes = ButtonDefaults.shapesFor(48.dp),
                enabled = !ui.loading && current.isNotBlank() && next.length >= 8 && next == confirm,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text("更新密码")
            }
        }
    }
}

@Composable
fun LibrarySettingsScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) { vm.library.loadFiles() }

    SettingsPageScaffold(
        title = "资料库",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        LibraryPane(
            controller = vm.library,
            bottomPadding = navBottom + 24.dp,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

@Composable
fun MemorySettingsScreen(
    vm: SettingsViewModel,
    onOpenAddMemory: () -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    var searchQuery by remember { mutableStateOf("") }
    var showCreateColDialog by remember { mutableStateOf(false) }
    var newColName by remember { mutableStateOf("") }
    var newColDesc by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { vm.loadMemory() }

    if (showCreateColDialog) {
        AlertDialog(
            onDismissRequest = { showCreateColDialog = false },
            title = { Text("新建记忆集") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    WhitzTextField(
                        value = newColName,
                        onValueChange = { newColName = it },
                        label = "名称（如：项目A、阅读笔记）",
                        modifier = Modifier.fillMaxWidth(),
                    )
                    WhitzTextField(
                        value = newColDesc,
                        onValueChange = { newColDesc = it },
                        label = "简介（可选，便于 AI 归类）",
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        vm.createMemoryCollection(newColName, description = newColDesc) {
                            newColName = ""
                            newColDesc = ""
                            showCreateColDialog = false
                        }
                    },
                    enabled = newColName.isNotBlank(),
                ) { Text("创建") }
            },
            dismissButton = {
                TextButton(onClick = { showCreateColDialog = false }) { Text("取消") }
            },
        )
    }

    SettingsPageScaffold(
        title = "记忆集管理",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            vm.clearMemorySearch()
            onBack()
        },
    ) {
        val mem = ui.memory
        Column(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            if (mem != null) {
                val activeCol = ui.selectedMemoryCollection?.let { slug ->
                    mem.collections.firstOrNull { it.slug == slug }
                }
                val filteredEntries = if (ui.selectedMemoryCollection == null) {
                    mem.entries
                } else {
                    mem.entries.filter { (it.target ?: "memory") == ui.selectedMemoryCollection }
                }

                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Text("启用长期记忆集", fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                            val pinnedCnt = mem.pinnedCount ?: mem.entries.count { it.isPinned }
                            val pinnedLim = mem.pinnedLimit ?: 10
                            Box(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(999.dp))
                                    .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f))
                                    .padding(horizontal = 7.dp, vertical = 2.dp),
                            ) {
                                Text(
                                    text = "L0 常驻 $pinnedCnt/$pinnedLim",
                                    fontSize = 10.5.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                        Text(
                            "${mem.collections.size} 个记忆集 · ${mem.entries.size} 条 · ${mem.totalCharCount ?: mem.charCount ?: 0} 字符",
                            fontSize = 12.sp,
                            color = colors.fgMuted,
                        )
                    }
                    Switch(checked = mem.memoryEnabled, onCheckedChange = { vm.updateMemorySettings(enabled = it) })
                }
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("写入记忆前需要确认", fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                        Text("关闭时 AI 可直接写入与修改记忆；开启后需你批准", fontSize = 12.sp, color = colors.fgMuted)
                    }
                    Switch(checked = mem.memoryRequireConfirm, onCheckedChange = { vm.updateMemorySettings(requireConfirm = it) })
                }
                Spacer(modifier = Modifier.height(10.dp))

                // Collections horizontal chips
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("记忆集 (${mem.collections.size})", fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = colors.fg)
                    TextButton(onClick = { showCreateColDialog = true }) { Text("+ 新建集") }
                }
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    item {
                        FilterChip(
                            selected = ui.selectedMemoryCollection == null,
                            onClick = { vm.selectMemoryCollection(null) },
                            label = { Text("全部 (${mem.entries.size})") },
                        )
                    }
                    items(mem.collections, key = { it.id }) { col ->
                        FilterChip(
                            selected = ui.selectedMemoryCollection == col.slug,
                            onClick = { vm.selectMemoryCollection(col.slug) },
                            label = { Text("${col.name} (${col.entryCount})") },
                        )
                    }
                }
                if (activeCol != null) {
                    Spacer(modifier = Modifier.height(6.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(colors.surface).padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(activeCol.name, fontWeight = FontWeight.Medium, fontSize = 13.sp, color = colors.fg)
                            if (activeCol.description.isNotBlank()) {
                                Text(activeCol.description, fontSize = 11.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        TextButton(onClick = { vm.toggleMemoryCollection(activeCol.id, !activeCol.enabled) }) {
                            Text(if (activeCol.enabled) "暂停" else "启用")
                        }
                        if (activeCol.kind != "system") {
                            TextButton(onClick = { vm.deleteMemoryCollection(activeCol.id) }) {
                                Text("删集", color = colors.danger)
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    WhitzTextField(
                        value = searchQuery,
                        onValueChange = {
                            searchQuery = it
                            if (it.isBlank()) vm.clearMemorySearch()
                        },
                        label = "RAG 语义 / 关键词检索记忆",
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = { vm.searchMemory(searchQuery) }) {
                        Text(if (ui.memorySearching) "..." else "检索")
                    }
                }

                Spacer(modifier = Modifier.height(6.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    val titleText = if (ui.memorySearchResults != null) {
                        "检索命中 (${ui.memorySearchResults!!.size})"
                    } else {
                        "已存记忆 (${filteredEntries.size})"
                    }
                    Text(titleText, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = colors.fg)
                    Row {
                        TextButton(onClick = {
                            vm.clearFeedback()
                            onOpenAddMemory()
                        }) { Text("新增") }
                        if (filteredEntries.isNotEmpty()) {
                            TextButton(onClick = { vm.clearAllMemory(activeCol?.id) }) { Text("清空", color = colors.danger) }
                        }
                    }
                }

                LazyColumn(
                    contentPadding = PaddingValues(bottom = navBottom + 24.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    val searchHits = ui.memorySearchResults
                    if (searchHits != null) {
                        items(searchHits, key = { "hit-${it.id}" }) { hit ->
                            Row(
                                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        "${hit.collectionName.ifBlank { hit.target }} · ${String.format("%.3f", hit.score)}",
                                        fontSize = 11.sp,
                                        color = MaterialTheme.colorScheme.primary,
                                    )
                                    if (hit.title.isNotBlank()) {
                                        Text(hit.title, fontWeight = FontWeight.Medium, fontSize = 13.sp, color = colors.fg)
                                    }
                                    Text(hit.content, fontSize = 13.sp, color = colors.fg)
                                }
                                IconButton(onClick = { vm.deleteMemoryEntry(hit.id) }, modifier = Modifier.size(32.dp)) {
                                    Icon(Icons.Default.Delete, contentDescription = "删除", tint = colors.fgFaint, modifier = Modifier.size(16.dp))
                                }
                            }
                        }
                    } else {
                        items(mem.pending, key = { "p-${it.id}" }) { p ->
                            Column(
                                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.warningWeak).padding(12.dp),
                            ) {
                                Text("待确认 (${p.target ?: "memory"} · ${p.action})", fontWeight = FontWeight.SemiBold, fontSize = 12.sp, color = colors.warning)
                                Text(p.content, fontSize = 13.sp, color = colors.fg)
                                Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                                    TextButton(onClick = { vm.resolveMemoryPending(p.id, "reject") }) { Text("拒绝") }
                                    TextButton(onClick = { vm.resolveMemoryPending(p.id, "approve") }) { Text("批准") }
                                }
                            }
                        }
                        items(filteredEntries, key = { it.id }) { e ->
                            val isPinning = ui.pinningMemoryId == e.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(14.dp))
                                    .background(colors.surface)
                                    .padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(
                                    modifier = Modifier.weight(1f),
                                    verticalArrangement = Arrangement.spacedBy(2.dp),
                                ) {
                                    Row(
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                                    ) {
                                        Text(
                                            e.collectionName ?: (e.target ?: "memory"),
                                            fontSize = 11.sp,
                                            color = colors.fgMuted,
                                        )
                                        if (e.isPinned) {
                                            Box(
                                                modifier = Modifier
                                                    .clip(RoundedCornerShape(6.dp))
                                                    .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.14f))
                                                    .padding(horizontal = 6.dp, vertical = 1.dp),
                                            ) {
                                                Text(
                                                    text = "L0 常驻",
                                                    fontSize = 10.sp,
                                                    fontWeight = FontWeight.SemiBold,
                                                    color = MaterialTheme.colorScheme.primary,
                                                )
                                            }
                                        }
                                    }
                                    if (e.title.isNotBlank()) {
                                        Text(e.title, fontWeight = FontWeight.Medium, fontSize = 13.sp, color = colors.fg)
                                    }
                                    Text(e.content, fontSize = 13.sp, color = colors.fg)
                                }
                                IconButton(
                                    onClick = { vm.togglePinMemoryEntry(e) },
                                    enabled = ui.pinningMemoryId == null,
                                    modifier = Modifier.size(32.dp),
                                ) {
                                    if (isPinning) {
                                        WhitzLoadingIndicator(size = 14.dp)
                                    } else {
                                        Icon(
                                            Icons.Default.PushPin,
                                            contentDescription = if (e.isPinned) "取消常驻核心" else "设为常驻核心",
                                            tint = if (e.isPinned) MaterialTheme.colorScheme.primary else colors.fgFaint,
                                            modifier = Modifier.size(16.dp),
                                        )
                                    }
                                }
                                IconButton(onClick = { vm.deleteMemoryEntry(e.id) }, modifier = Modifier.size(32.dp)) {
                                    Icon(Icons.Default.Delete, contentDescription = "删除", tint = colors.fgFaint, modifier = Modifier.size(16.dp))
                                }
                            }
                        }
                    }
                }
            } else if (ui.loading) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { WhitzLoadingIndicator() }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun AddMemoryScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val collections = ui.memory?.collections.orEmpty()
    var targetSlug by remember(ui.selectedMemoryCollection, collections) {
        mutableStateOf(ui.selectedMemoryCollection ?: collections.firstOrNull()?.slug ?: "memory")
    }
    var title by remember { mutableStateOf("") }
    var content by remember { mutableStateOf("") }

    SettingsPageScaffold(
        title = "新增记忆",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (collections.isNotEmpty()) {
                Text("目标记忆集", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = LocalWhitzColors.current.fg)
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(collections, key = { it.id }) { col ->
                        FilterChip(
                            selected = targetSlug == col.slug,
                            onClick = { targetSlug = col.slug },
                            label = { Text(col.name) },
                        )
                    }
                }
            }
            WhitzTextField(
                value = title,
                onValueChange = { title = it },
                label = "标题（可选）",
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            WhitzTextField(
                value = content,
                onValueChange = { content = it },
                label = "记忆内容",
                singleLine = false,
                maxLines = 8,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = {
                    vm.addMemoryEntry(content, target = targetSlug, title = title, onSuccess = onBack)
                },
                shapes = ButtonDefaults.shapesFor(48.dp),
                enabled = content.isNotBlank() && !ui.loading,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (ui.loading) "保存中..." else "保存")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SkillsSettingsScreen(
    vm: SettingsViewModel,
    onOpenCreateSkill: () -> Unit,
    onOpenGithubInstall: () -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) { vm.loadSkills() }

    SettingsPageScaffold(
        title = "技能管理",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            Spacer(modifier = Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = {
                        vm.clearFeedback()
                        onOpenCreateSkill()
                    },
                    shapes = ButtonDefaults.shapesFor(40.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("新建技能")
                }
                OutlinedButton(
                    onClick = {
                        vm.clearFeedback()
                        vm.clearGithubPreview()
                        onOpenGithubInstall()
                    },
                    shapes = ButtonDefaults.shapesFor(40.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Text("从 GitHub 安装")
                }
            }
            Spacer(modifier = Modifier.height(12.dp))

            LazyColumn(
                contentPadding = PaddingValues(bottom = navBottom + 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f),
            ) {
                items(ui.pendingSkills, key = { "ps-${it.id}" }) { p ->
                    Column(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.warningWeak).padding(12.dp),
                    ) {
                        Text("待确认技能：${p.name}", fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = colors.fg)
                        Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                            TextButton(onClick = { vm.resolveSkillPending(p.id, "reject") }) { Text("拒绝") }
                            TextButton(onClick = { vm.resolveSkillPending(p.id, "approve") }) { Text("批准") }
                        }
                    }
                }
                items(ui.skills, key = { it.name }) { sk ->
                    Row(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(sk.title ?: sk.name, fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                            if (sk.description.isNotBlank()) {
                                Text(sk.description, fontSize = 12.sp, color = colors.fgMuted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        Switch(checked = sk.enabled, onCheckedChange = { vm.toggleSkill(sk.name, it) })
                        if (sk.source != "builtin") {
                            IconButton(onClick = { vm.deleteSkill(sk.name) }) {
                                Icon(Icons.Default.Delete, contentDescription = "删除", tint = colors.danger)
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun CreateSkillScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    var name by remember { mutableStateOf("") }
    var desc by remember { mutableStateOf("") }
    var content by remember { mutableStateOf("") }

    SettingsPageScaffold(
        title = "新建自定义技能",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            WhitzTextField(
                value = name,
                onValueChange = { name = it },
                label = "技能名称 (英文标识)",
                modifier = Modifier.fillMaxWidth(),
            )
            WhitzTextField(
                value = desc,
                onValueChange = { desc = it },
                label = "描述",
                modifier = Modifier.fillMaxWidth(),
            )
            WhitzTextField(
                value = content,
                onValueChange = { content = it },
                label = "指令内容 (Markdown)",
                singleLine = false,
                maxLines = 12,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = {
                    vm.createSkill(name, desc, content, onSuccess = onBack)
                },
                shapes = ButtonDefaults.shapesFor(48.dp),
                enabled = name.isNotBlank() && content.isNotBlank() && !ui.loading,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (ui.loading) "创建中..." else "创建")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun GithubSkillInstallScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var repoUrl by remember { mutableStateOf("") }
    var refInput by remember { mutableStateOf("") }
    var pathInput by remember { mutableStateOf("") }
    var installName by remember(ui.githubPreview?.name) { mutableStateOf(ui.githubPreview?.name ?: "") }

    DisposableEffect(Unit) {
        onDispose { vm.clearGithubPreview() }
    }

    SettingsPageScaffold(
        title = "从 GitHub 安装技能",
        ui = ui,
        onBack = {
            vm.clearGithubPreview()
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                WhitzTextField(
                    value = repoUrl,
                    onValueChange = {
                        repoUrl = it
                        if (ui.githubPreview != null) vm.clearGithubPreview()
                    },
                    label = "GitHub 仓库 URL",
                    modifier = Modifier.weight(1f),
                )
                OutlinedButton(
                    onClick = { vm.previewGithubSkill(repoUrl, refInput, pathInput) },
                    shapes = ButtonDefaults.shapesFor(54.dp),
                    enabled = repoUrl.isNotBlank() && !ui.loading,
                    modifier = Modifier.height(54.dp),
                ) { Text("解析") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                WhitzTextField(
                    value = refInput,
                    onValueChange = { refInput = it },
                    label = "分支/Tag（可选）",
                    modifier = Modifier.weight(1f),
                )
                WhitzTextField(
                    value = pathInput,
                    onValueChange = { pathInput = it },
                    label = "子路径（可选）",
                    modifier = Modifier.weight(1f),
                )
            }
            ui.githubPreview?.let { preview ->
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    color = colors.surface,
                    border = BorderStroke(0.5.dp, colors.line),
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        WhitzTextField(
                            value = installName,
                            onValueChange = { installName = it },
                            label = "技能名称",
                            modifier = Modifier.fillMaxWidth(),
                        )
                        if (preview.description.isNotBlank()) {
                            Text(
                                preview.description,
                                fontSize = 12.5.sp,
                                color = colors.fgMuted,
                                maxLines = 4,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
            Button(
                onClick = {
                    val preview = ui.githubPreview
                    vm.installGithubSkill(
                        repoUrl = repoUrl,
                        name = installName.ifBlank { preview?.name },
                        ref = preview?.ref ?: refInput,
                        path = preview?.path ?: pathInput,
                        onSuccess = onBack,
                    )
                },
                shapes = ButtonDefaults.shapesFor(48.dp),
                enabled = repoUrl.isNotBlank() && ui.githubPreview != null && !ui.loading,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (ui.loading) "安装中..." else "安装")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun MembershipSettingsScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var redeemInput by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { vm.loadCredits() }

    SettingsPageScaffold(
        title = "会员与积分",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        val c = ui.credits
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            if (c != null) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(18.dp),
                    color = colors.surface,
                    border = BorderStroke(0.5.dp, colors.line),
                ) {
                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("当前套餐：${c.tierLabel}", fontWeight = FontWeight.Bold, fontSize = 18.sp, color = colors.fg)
                        val availablePct = c.availablePercent()
                        Text(
                            text = when {
                                c.overdrawn -> "当前可用：额度已用尽"
                                availablePct == null -> "当前可用：不限"
                                else -> "当前可用：$availablePct%"
                            },
                            fontSize = 14.sp,
                            color = if (c.overdrawn) colors.danger else colors.fgMuted,
                        )
                        if (!c.expiresAt.isNullOrBlank()) {
                            Text("到期时间：${DateTimeUtils.formatShort(c.expiresAt)}", fontSize = 12.sp, color = colors.fgFaint)
                        }

                        val weeklyPct = c.weeklyPercent()
                        Text(
                            text = weeklyPct?.let { "本周剩余：$it%" } ?: "本周剩余：不限",
                            fontSize = 12.sp,
                            color = colors.fgMuted,
                        )
                        LinearWavyProgressIndicator(
                            progress = { (weeklyPct ?: 100) / 100f },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        if (weeklyPct != null && c.weekly.resetAt.isNotBlank()) {
                            Text(
                                "${DateTimeUtils.formatShort(c.weekly.resetAt)} 重置",
                                fontSize = 11.sp,
                                color = colors.fgFaint,
                            )
                        }

                        if (c.tier != "pro") {
                            val fiveHourPct = c.fiveHourPercent()
                            Text(
                                text = fiveHourPct?.let { "5 小时剩余：$it%" } ?: "5 小时剩余：不限",
                                fontSize = 12.sp,
                                color = colors.fgMuted,
                            )
                            LinearWavyProgressIndicator(
                                progress = { (fiveHourPct ?: 100) / 100f },
                                modifier = Modifier.fillMaxWidth(),
                            )
                            if (fiveHourPct != null && c.fiveHour.resetAt.isNotBlank()) {
                                Text(
                                    "${DateTimeUtils.formatShort(c.fiveHour.resetAt)} 重置",
                                    fontSize = 11.sp,
                                    color = colors.fgFaint,
                                )
                            }
                        }
                    }
                }

                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    WhitzTextField(
                        value = redeemInput,
                        onValueChange = { redeemInput = it },
                        label = "输入兑换码",
                        modifier = Modifier.weight(1f),
                    )
                    Button(
                        onClick = {
                            vm.redeemCode(redeemInput)
                            redeemInput = ""
                        },
                        shapes = ButtonDefaults.shapesFor(54.dp),
                        enabled = redeemInput.isNotBlank() && !ui.loading,
                        modifier = Modifier.height(54.dp),
                    ) { Text("兑换") }
                }

                if (c.plans.isNotEmpty()) {
                    Text("套餐方案说明", fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                    c.plans.forEach { p ->
                        Column(
                            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(14.dp),
                        ) {
                            Text(p.label, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                            Text(p.summary, fontSize = 13.sp, color = colors.fgMuted)
                            Text(
                                "最大并发 ${p.maxRunsPerUser} 个 · 单轮工具调用上限 ${p.maxToolIterations} 次",
                                fontSize = 12.sp,
                                color = colors.fgFaint,
                            )
                        }
                    }
                }
            } else {
                Box(modifier = Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                    WhitzLoadingIndicator()
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun AssistantSettingsScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val ui by vm.ui.collectAsState()
    val currentName = user?.resolvedAssistantName() ?: "Whitz"
    val assistantAvatarUrl = vm.resolveAssetUrl(user?.assistantAvatarUrl)
    var nameDraft by remember(user?.assistantName) { mutableStateOf(currentName) }

    val avatarPicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) vm.uploadAssistantAvatar(uri)
    }

    SettingsPageScaffold(
        title = "编辑助手",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(64.dp)
                            .clip(CircleShape)
                            .background(colors.canvas),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (!assistantAvatarUrl.isNullOrBlank()) {
                            AsyncImage(
                                model = assistantAvatarUrl,
                                contentDescription = currentName,
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize(),
                            )
                        } else {
                            WhitzLogoMark(modifier = Modifier.size(30.dp))
                        }
                    }
                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("助手头像", fontSize = 14.sp, fontWeight = FontWeight.Medium, color = colors.fg)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = { avatarPicker.launch("image/*") },
                                enabled = !ui.loading,
                                shapes = ButtonDefaults.shapesFor(36.dp),
                                modifier = Modifier.height(36.dp),
                                contentPadding = PaddingValues(horizontal = 14.dp),
                            ) {
                                Text("更换头像", fontSize = 13.sp)
                            }
                            if (!user?.assistantAvatarUrl.isNullOrBlank()) {
                                TextButton(
                                    onClick = { vm.deleteAssistantAvatar() },
                                    enabled = !ui.loading,
                                    modifier = Modifier.height(36.dp),
                                ) {
                                    Text("恢复默认", fontSize = 13.sp, color = colors.fgMuted)
                                }
                            }
                        }
                    }
                }
            }

            WhitzTextField(
                value = nameDraft,
                onValueChange = { if (it.length <= 80) nameDraft = it },
                label = "助手昵称",
                placeholder = "Whitz",
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                text = "留空保存将恢复默认名称「Whitz」。",
                fontSize = 12.sp,
                color = colors.fgFaint,
            )

            Button(
                onClick = { vm.updateAssistantName(nameDraft) },
                shapes = ButtonDefaults.shapesFor(48.dp),
                enabled = !ui.loading,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (ui.loading) "保存中…" else "保存")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun PersonaSettingsScreen(
    vm: SettingsViewModel,
    onOpenEditAssistant: () -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val ui by vm.ui.collectAsState()
    var persona by remember(user?.id) { mutableStateOf(user?.persona ?: "") }

    val assistantNameDisplay = user?.resolvedAssistantName() ?: "Whitz"
    val assistantAvatarUrl = vm.resolveAssetUrl(user?.assistantAvatarUrl)

    SettingsPageScaffold(
        title = "专属助手",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Box(
                            modifier = Modifier
                                .size(50.dp)
                                .clip(RoundedCornerShape(14.dp))
                                .background(colors.canvas),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (!assistantAvatarUrl.isNullOrBlank()) {
                                AsyncImage(
                                    model = assistantAvatarUrl,
                                    contentDescription = assistantNameDisplay,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.fillMaxSize(),
                                )
                            } else {
                                WhitzLogoMark(modifier = Modifier.size(24.dp))
                            }
                        }
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = assistantNameDisplay,
                                fontSize = 15.5.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = colors.fg,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = "主聊天助手头像与昵称，默认显示 Whitz 图标与名称。",
                                fontSize = 12.sp,
                                color = colors.fgMuted,
                            )
                        }
                    }
                    OutlinedButton(
                        onClick = {
                            vm.clearFeedback()
                            onOpenEditAssistant()
                        },
                        shapes = ButtonDefaults.shapesFor(38.dp),
                        modifier = Modifier.fillMaxWidth().height(38.dp),
                    ) {
                        Text("编辑助手头像与昵称", fontSize = 13.sp)
                    }
                }
            }

            Text("自定义 AI 助理的回复风格、角色设定与偏好指令：", fontSize = 13.sp, color = colors.fgMuted)
            WhitzTextField(
                value = persona,
                onValueChange = { persona = it },
                placeholder = "例如：请用简洁专业的中文回复，优先给出可执行代码...",
                singleLine = false,
                maxLines = 12,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { vm.updatePersona(persona) },
                shapes = ButtonDefaults.shapesFor(48.dp),
                enabled = !ui.loading,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (ui.loading) "保存中..." else "保存人格设定")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun DevicesSettingsScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) { vm.loadSessions() }

    SettingsPageScaffold(
        title = "登录设备",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            if (ui.sessions.size > 1) {
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedButton(
                    onClick = { vm.deleteOtherSessions() },
                    shapes = ButtonDefaults.shapesFor(42.dp),
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.danger),
                ) {
                    Text("下线全部其他设备")
                }
                Spacer(modifier = Modifier.height(12.dp))
            }

            if (ui.loading && ui.sessions.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { WhitzLoadingIndicator() }
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(top = 8.dp, bottom = navBottom + 24.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(ui.sessions, key = { it.sessionId }) { s ->
                        Row(
                            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = (s.userAgent ?: "未知设备") + if (s.isCurrent) "（当前设备）" else "",
                                    fontWeight = FontWeight.Medium,
                                    fontSize = 14.sp,
                                    color = colors.fg,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    "IP: ${s.clientIp ?: "-"} · 最近活跃: ${DateTimeUtils.formatShort(s.lastUsedAt ?: s.createdAt)}",
                                    fontSize = 12.sp,
                                    color = colors.fgFaint,
                                )
                            }
                            if (!s.isCurrent) {
                                TextButton(onClick = { vm.deleteSession(s.sessionId) }) {
                                    Text("下线", color = colors.danger)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private val FEEDBACK_RATINGS = listOf(
    Triple(1, "😞", "很不满意"),
    Triple(2, "😕", "有待改善"),
    Triple(3, "😐", "一般般"),
    Triple(4, "😊", "比较满意"),
    Triple(5, "🥰", "非常棒"),
)

private val FEEDBACK_CATEGORIES = listOf(
    "general" to "整体体验",
    "quality" to "回答质量",
    "speed" to "响应速度",
    "ui" to "界面交互",
    "feature" to "功能建议",
    "bug" to "问题反馈",
)

@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
fun FeedbackSettingsScreen(
    vm: SettingsViewModel,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val ui by vm.ui.collectAsState()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    var rating by remember { mutableStateOf(5) }
    var category by remember { mutableStateOf("general") }
    var content by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { vm.loadFeedbacks() }

    SettingsPageScaffold(
        title = "反馈与评价",
        ui = ui,
        onBack = {
            vm.clearFeedback()
            onBack()
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .padding(bottom = navBottom + 24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            // AI Positive Reaction Toggle
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Row(
                    modifier = Modifier.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text("AI 正向互动点赞", fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                            Surface(
                                shape = RoundedCornerShape(999.dp),
                                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.14f),
                            ) {
                                Text(
                                    text = "仅正向激励",
                                    fontSize = 11.sp,
                                    color = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "开启后，助手可能会对你的精彩见解或清晰提问送上 👍、❤️、✨ 或 💡 等正向鼓励（永不出现负面评价）。",
                            fontSize = 12.5.sp,
                            color = colors.fgMuted,
                            lineHeight = 18.sp,
                        )
                    }
                    Spacer(modifier = Modifier.width(10.dp))
                    Switch(
                        checked = user?.aiReactionsEnabled ?: true,
                        enabled = !ui.aiReactionSaving,
                        onCheckedChange = { vm.toggleAiReactions(it) },
                    )
                }
            }

            // AI Daily Private Posts Preference
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(
                        modifier = Modifier.weight(1f),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text("AI 每日联网动态", fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                            Surface(
                                shape = RoundedCornerShape(999.dp),
                                color = colors.warningWeak,
                            ) {
                                Text(
                                    text = "消耗积分",
                                    fontSize = 11.sp,
                                    color = colors.warning,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                )
                            }
                        }
                        Text(
                            text = "开启后，助手将每日根据你的长期记忆与联网搜索结果生成仅自己可见的专属动态，并在你发帖或评论后间隔一段时间来点赞与回复。正常计入积分消耗，记忆为 0 或额度不足时自动跳过。",
                            fontSize = 12.5.sp,
                            lineHeight = 18.sp,
                            color = colors.fgMuted,
                        )
                    }
                    Spacer(modifier = Modifier.width(10.dp))
                    Switch(
                        checked = user?.aiPostsEnabled ?: false,
                        enabled = !ui.aiPostsSaving,
                        onCheckedChange = { vm.toggleAiPosts(it) },
                    )
                }
            }

            // Submit Feedback Form
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Column {
                        Text("提交产品评价与建议", fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                        Spacer(modifier = Modifier.height(2.dp))
                        Text("你的评分与建议将直接进入后台量化分析看板，帮助持续优化产品。", fontSize = 12.5.sp, color = colors.fgMuted)
                    }

                    Text("整体满意度", fontSize = 12.5.sp, fontWeight = FontWeight.Medium, color = colors.fgMuted)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        FEEDBACK_RATINGS.forEach { (valNum, emoji, label) ->
                            val selected = rating == valNum
                            Surface(
                                modifier = Modifier
                                    .weight(1f)
                                    .clip(RoundedCornerShape(14.dp))
                                    .clickable { rating = valNum },
                                shape = RoundedCornerShape(14.dp),
                                color = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else colors.canvas,
                                border = BorderStroke(
                                    1.dp,
                                    if (selected) MaterialTheme.colorScheme.primary else colors.line,
                                ),
                            ) {
                                Column(
                                    modifier = Modifier.padding(vertical = 8.dp, horizontal = 2.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally,
                                ) {
                                    Text(emoji, fontSize = 18.sp)
                                    Spacer(modifier = Modifier.height(2.dp))
                                    Text(label, fontSize = 10.5.sp, color = if (selected) colors.fg else colors.fgMuted, maxLines = 1)
                                }
                            }
                        }
                    }

                    Text("反馈分类", fontSize = 12.5.sp, fontWeight = FontWeight.Medium, color = colors.fgMuted)
                    androidx.compose.foundation.layout.FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        FEEDBACK_CATEGORIES.forEach { (key, label) ->
                            val selected = category == key
                            Surface(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(999.dp))
                                    .clickable { category = key },
                                shape = RoundedCornerShape(999.dp),
                                color = if (selected) MaterialTheme.colorScheme.primary else colors.canvas,
                                border = BorderStroke(0.8.dp, if (selected) MaterialTheme.colorScheme.primary else colors.line),
                            ) {
                                Text(
                                    text = label,
                                    fontSize = 12.5.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = if (selected) MaterialTheme.colorScheme.onPrimary else colors.fgMuted,
                                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                                )
                            }
                        }
                    }

                    WhitzTextField(
                        value = content,
                        onValueChange = { content = it },
                        placeholder = "告诉我们你最喜欢的功能、遇到的问题或建议…",
                        singleLine = false,
                        maxLines = 6,
                        modifier = Modifier.fillMaxWidth(),
                    )

                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        Button(
                            onClick = {
                                vm.submitFeedback(rating, category, content) {
                                    content = ""
                                    rating = 5
                                }
                            },
                            enabled = content.isNotBlank() && !ui.feedbackSubmitting,
                            shapes = ButtonDefaults.shapesFor(40.dp),
                        ) {
                            Text(if (ui.feedbackSubmitting) "提交中…" else "提交评价反馈")
                        }
                    }
                }
            }

            // History
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.5.dp, colors.line),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("我的反馈记录", fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                        Text("共 ${ui.feedbacks.size} 条", fontSize = 12.sp, color = colors.fgFaint)
                    }
                    if (ui.feedbacks.isEmpty()) {
                        Text(
                            text = "还没有提交过产品评价，欢迎随时分享你的体验。",
                            fontSize = 13.sp,
                            color = colors.fgFaint,
                            modifier = Modifier.padding(vertical = 8.dp),
                        )
                    } else {
                        ui.feedbacks.forEach { item ->
                            val ratingEmoji = FEEDBACK_RATINGS.firstOrNull { it.first == item.rating }?.second ?: "😊"
                            val catLabel = FEEDBACK_CATEGORIES.firstOrNull { it.first == item.category }?.second ?: item.category
                            val statusText = when (item.status) {
                                "resolved" -> "已解决"
                                "reviewed" -> "已查看"
                                else -> "待处理"
                            }
                            Surface(
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(14.dp),
                                color = colors.canvas,
                                border = BorderStroke(0.5.dp, colors.line),
                            ) {
                                Column(modifier = Modifier.padding(12.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            text = "$ratingEmoji ${item.rating}/5 · $catLabel · $statusText",
                                            fontSize = 12.5.sp,
                                            fontWeight = FontWeight.Medium,
                                            color = colors.fg,
                                        )
                                        Text(
                                            text = DateTimeUtils.formatShort(item.createdAt),
                                            fontSize = 11.5.sp,
                                            color = colors.fgFaint,
                                        )
                                    }
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(item.content, fontSize = 13.5.sp, color = colors.fg, lineHeight = 19.sp)
                                    if (!item.adminNote.isNullOrBlank()) {
                                        Spacer(modifier = Modifier.height(6.dp))
                                        Surface(
                                            shape = RoundedCornerShape(10.dp),
                                            color = colors.surface,
                                        ) {
                                            Text(
                                                text = "官方回复：${item.adminNote}",
                                                fontSize = 12.sp,
                                                color = colors.fgMuted,
                                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
