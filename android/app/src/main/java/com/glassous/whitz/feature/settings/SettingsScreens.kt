package com.glassous.whitz.feature.settings

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.CreditCard
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.SmartToy
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
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
import com.glassous.whitz.core.files.FileValidator
import com.glassous.whitz.core.model.ThemePreference
import com.glassous.whitz.core.model.formatCredits
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzTextField

enum class SettingsSection(val title: String) {
    HOME("设置"),
    PROFILE("个人资料"),
    PASSWORD("修改密码"),
    LIBRARY("文件库"),
    MEMORY("记忆管理"),
    SKILLS("技能管理"),
    MEMBERSHIP("会员与积分"),
    PERSONA("人格设定"),
    DEVICES("登录设备"),
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SettingsRootScreen(
    vm: SettingsViewModel,
    onBackToChat: () -> Unit,
    onLoggedOut: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var section by remember { mutableStateOf(SettingsSection.HOME) }
    val scrollBehavior = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()

    LaunchedEffect(Unit) {
        vm.refreshAll()
    }

    BoxWithConstraints(modifier = Modifier.fillMaxSize().background(colors.canvas)) {
        val isExpanded = maxWidth >= 840.dp

        BackHandler(enabled = !isExpanded && section != SettingsSection.HOME) {
            vm.clearFeedback()
            section = if (section == SettingsSection.PASSWORD) SettingsSection.PROFILE else SettingsSection.HOME
        }

        Scaffold(
            modifier = Modifier.nestedScroll(scrollBehavior.nestedScrollConnection),
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
                        IconButton(onClick = {
                            vm.clearFeedback()
                            if (!isExpanded && section != SettingsSection.HOME) {
                                section = if (section == SettingsSection.PASSWORD) SettingsSection.PROFILE else SettingsSection.HOME
                            } else {
                                onBackToChat()
                            }
                        }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回", tint = colors.fg)
                        }
                    },
                    title = {
                        val headerTitle = if (isExpanded && section == SettingsSection.HOME) "设置" else section.title
                        Text(headerTitle, fontWeight = FontWeight.SemiBold, color = colors.fg)
                    },
                )
            },
        ) { innerPadding ->
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(top = innerPadding.calculateTopPadding())
                    .imePadding(),
            ) {
                if (!ui.error.isNullOrBlank()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(colors.dangerWeak)
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                    ) {
                        Text(ui.error!!, color = colors.danger, fontSize = 13.sp)
                    }
                }
                if (!ui.message.isNullOrBlank()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(colors.successWeak)
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                    ) {
                        Text(ui.message!!, color = colors.success, fontSize = 13.sp)
                    }
                }

                if (isExpanded) {
                    val activeSection = if (section == SettingsSection.HOME) SettingsSection.PROFILE else section
                    Row(modifier = Modifier.fillMaxSize()) {
                        Box(
                            modifier = Modifier
                                .width(320.dp)
                                .fillMaxHeight(),
                        ) {
                            SettingsHomeContent(
                                vm = vm,
                                selectedSection = activeSection,
                                onSelect = {
                                    vm.clearFeedback()
                                    section = it
                                },
                                onLogout = { vm.logout(onLoggedOut) },
                            )
                        }
                        Box(
                            modifier = Modifier
                                .width(0.5.dp)
                                .fillMaxHeight()
                                .background(colors.line),
                        )
                        Box(modifier = Modifier.weight(1f).fillMaxHeight()) {
                            SettingsSectionBody(section = activeSection, vm = vm)
                        }
                    }
                } else {
                    if (section == SettingsSection.HOME) {
                        SettingsHomeContent(
                            vm = vm,
                            selectedSection = null,
                            onSelect = {
                                vm.clearFeedback()
                                section = it
                            },
                            onLogout = { vm.logout(onLoggedOut) },
                        )
                    } else {
                        SettingsSectionBody(section = section, vm = vm)
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsSectionBody(
    section: SettingsSection,
    vm: SettingsViewModel,
) {
    when (section) {
        SettingsSection.HOME -> Unit
        SettingsSection.PROFILE -> ProfileSettingsContent(vm)
        SettingsSection.PASSWORD -> PasswordSettingsContent(vm)
        SettingsSection.LIBRARY -> LibrarySettingsContent(vm)
        SettingsSection.MEMORY -> MemorySettingsContent(vm)
        SettingsSection.SKILLS -> SkillsSettingsContent(vm)
        SettingsSection.MEMBERSHIP -> MembershipSettingsContent(vm)
        SettingsSection.PERSONA -> PersonaSettingsContent(vm)
        SettingsSection.DEVICES -> DevicesSettingsContent(vm)
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun SettingsHomeContent(
    vm: SettingsViewModel,
    selectedSection: SettingsSection?,
    onSelect: (SettingsSection) -> Unit,
    onLogout: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val theme by vm.themePreference.collectAsState()
    val ui by vm.ui.collectAsState()
    var confirmLogout by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .navigationBarsPadding()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // User card
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(18.dp))
                .clickable { onSelect(SettingsSection.PROFILE) },
            shape = RoundedCornerShape(18.dp),
            color = colors.surface,
            border = BorderStroke(0.5.dp, colors.line),
        ) {
            Row(
                modifier = Modifier.padding(14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (!user?.avatarUrl.isNullOrBlank()) {
                    AsyncImage(
                        model = user?.avatarUrl,
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

        // Theme selector using M3E connected radio group
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

        // Menu items
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(18.dp),
            color = colors.surface,
            border = BorderStroke(0.5.dp, colors.line),
        ) {
            Column {
                SettingsMenuRow(Icons.Default.Person, "个人资料", null, selectedSection == SettingsSection.PROFILE) { onSelect(SettingsSection.PROFILE) }
                HorizontalDivider(color = colors.line)
                SettingsMenuRow(Icons.Default.Lock, "修改密码", null, selectedSection == SettingsSection.PASSWORD) { onSelect(SettingsSection.PASSWORD) }
                HorizontalDivider(color = colors.line)
                SettingsMenuRow(Icons.Default.Folder, "文件库", null, selectedSection == SettingsSection.LIBRARY) { onSelect(SettingsSection.LIBRARY) }
                HorizontalDivider(color = colors.line)
                SettingsMenuRow(Icons.Default.Psychology, "记忆管理", null, selectedSection == SettingsSection.MEMORY) { onSelect(SettingsSection.MEMORY) }
                HorizontalDivider(color = colors.line)
                SettingsMenuRow(Icons.Default.AutoAwesome, "技能管理", null, selectedSection == SettingsSection.SKILLS) { onSelect(SettingsSection.SKILLS) }
                HorizontalDivider(color = colors.line)
                SettingsMenuRow(
                    Icons.Default.CreditCard,
                    "会员与积分",
                    ui.credits?.let { "${it.tierLabel} · ${formatCredits(it.remaining)} 积分" },
                    selectedSection == SettingsSection.MEMBERSHIP,
                ) { onSelect(SettingsSection.MEMBERSHIP) }
                HorizontalDivider(color = colors.line)
                SettingsMenuRow(Icons.Default.SmartToy, "人格设定", null, selectedSection == SettingsSection.PERSONA) { onSelect(SettingsSection.PERSONA) }
                HorizontalDivider(color = colors.line)
                SettingsMenuRow(Icons.Default.Devices, "登录设备", null, selectedSection == SettingsSection.DEVICES) { onSelect(SettingsSection.DEVICES) }
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
                        onLogout()
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
    selected: Boolean,
    onClick: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(if (selected) colors.hover else colors.surface)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = if (selected) colors.fg else colors.fgMuted, modifier = Modifier.size(20.dp))
        Spacer(modifier = Modifier.width(12.dp))
        Text(title, fontSize = 15.sp, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal, color = colors.fg, modifier = Modifier.weight(1f))
        if (!badge.isNullOrBlank()) {
            Text(badge, fontSize = 12.sp, color = colors.fgFaint, modifier = Modifier.padding(end = 4.dp))
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = colors.fgFaint)
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun ProfileSettingsContent(vm: SettingsViewModel) {
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

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .navigationBarsPadding()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (!user?.avatarUrl.isNullOrBlank()) {
                AsyncImage(
                    model = user?.avatarUrl,
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

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun PasswordSettingsContent(vm: SettingsViewModel) {
    val ui by vm.ui.collectAsState()
    var current by remember { mutableStateOf("") }
    var next by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }

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

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun LibrarySettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var query by remember { mutableStateOf("") }
    var globalOnly by remember { mutableStateOf<Boolean?>(null) }
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) { vm.loadLibrary() }

    Column(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(top = 8.dp),
        ) {
            WhitzTextField(
                value = query,
                onValueChange = {
                    query = it
                    vm.loadLibrary(it, globalOnly)
                },
                placeholder = "搜索文件名...",
                modifier = Modifier.weight(1f),
            )
            OutlinedButton(
                onClick = {
                    globalOnly = if (globalOnly == true) null else true
                    vm.loadLibrary(query, globalOnly)
                },
                shapes = ButtonDefaults.shapesFor(40.dp),
            ) {
                Text(if (globalOnly == true) "仅全局" else "全部")
            }
        }
        Spacer(modifier = Modifier.height(12.dp))
        if (ui.loading && ui.libraryFiles.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { WhitzLoadingIndicator() }
        } else if (ui.libraryFiles.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无文件", color = colors.fgFaint)
            }
        } else {
            LazyColumn(
                contentPadding = PaddingValues(bottom = navBottom + 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(ui.libraryFiles, key = { it.id }) { f ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(colors.surface)
                            .padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(f.filename, fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(
                                "${FileValidator.formatSize(f.sizeBytes)} · ${if (f.isGlobal) "全局共享" else "仅对话"}",
                                fontSize = 12.sp,
                                color = colors.fgFaint,
                            )
                        }
                        Switch(
                            checked = f.isGlobal,
                            onCheckedChange = { vm.toggleLibraryGlobal(f.id, it) },
                        )
                        IconButton(onClick = { vm.deleteLibraryFile(f.id) }) {
                            Icon(Icons.Default.Delete, contentDescription = "删除", tint = colors.danger)
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun MemorySettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var showAdd by remember { mutableStateOf(false) }
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) { vm.loadMemory() }

    val mem = ui.memory
    Column(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        if (mem != null) {
            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("启用长期记忆", fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
                    Text("在跨对话中记住你的偏好与事实", fontSize = 12.sp, color = colors.fgMuted)
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
                    Text("AI 提议新记忆时等待你批准", fontSize = 12.sp, color = colors.fgMuted)
                }
                Switch(checked = mem.memoryRequireConfirm, onCheckedChange = { vm.updateMemorySettings(requireConfirm = it) })
            }
            Spacer(modifier = Modifier.height(10.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("已存记忆 (${mem.entries.size})", fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = colors.fg)
                Row {
                    TextButton(onClick = { showAdd = true }) { Text("新增") }
                    if (mem.entries.isNotEmpty()) {
                        TextButton(onClick = { vm.clearAllMemory() }) { Text("清空", color = colors.danger) }
                    }
                }
            }

            LazyColumn(
                contentPadding = PaddingValues(bottom = navBottom + 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f),
            ) {
                items(mem.pending, key = { "p-${it.id}" }) { p ->
                    Column(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.warningWeak).padding(12.dp),
                    ) {
                        Text("待确认 (${p.action})", fontWeight = FontWeight.SemiBold, fontSize = 12.sp, color = colors.warning)
                        Text(p.content, fontSize = 13.sp, color = colors.fg)
                        Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                            TextButton(onClick = { vm.resolveMemoryPending(p.id, "reject") }) { Text("拒绝") }
                            TextButton(onClick = { vm.resolveMemoryPending(p.id, "approve") }) { Text("批准") }
                        }
                    }
                }
                items(mem.entries, key = { it.id }) { e ->
                    Row(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(e.content, fontSize = 13.sp, color = colors.fg, modifier = Modifier.weight(1f))
                        IconButton(onClick = { vm.deleteMemoryEntry(e.id) }, modifier = Modifier.size(32.dp)) {
                            Icon(Icons.Default.Delete, contentDescription = "删除", tint = colors.fgFaint, modifier = Modifier.size(16.dp))
                        }
                    }
                }
            }
        } else if (ui.loading) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { WhitzLoadingIndicator() }
        }
    }

    if (showAdd) {
        var content by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showAdd = false },
            containerColor = colors.canvas,
            title = { Text("新增记忆", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = {
                WhitzTextField(
                    value = content,
                    onValueChange = { content = it },
                    label = "记忆内容",
                    singleLine = false,
                    maxLines = 4,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            dismissButton = { TextButton(onClick = { showAdd = false }) { Text("取消") } },
            confirmButton = {
                Button(
                    onClick = {
                        vm.addMemoryEntry(content)
                        showAdd = false
                    },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text("保存") }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun SkillsSettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var showCreate by remember { mutableStateOf(false) }
    var showGithub by remember { mutableStateOf(false) }
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) { vm.loadSkills() }

    Column(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Spacer(modifier = Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = { showCreate = true },
                shapes = ButtonDefaults.shapesFor(40.dp),
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("新建技能")
            }
            OutlinedButton(
                onClick = { showGithub = true },
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

    if (showCreate) {
        var name by remember { mutableStateOf("") }
        var desc by remember { mutableStateOf("") }
        var content by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showCreate = false },
            containerColor = colors.canvas,
            title = { Text("新建自定义技能", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    WhitzTextField(value = name, onValueChange = { name = it }, label = "技能名称 (英文标识)")
                    WhitzTextField(value = desc, onValueChange = { desc = it }, label = "描述")
                    WhitzTextField(value = content, onValueChange = { content = it }, label = "指令内容 (Markdown)", singleLine = false, maxLines = 6)
                }
            },
            dismissButton = { TextButton(onClick = { showCreate = false }) { Text("取消") } },
            confirmButton = {
                Button(
                    onClick = {
                        vm.createSkill(name, desc, content)
                        showCreate = false
                    },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                ) { Text("创建") }
            },
        )
    }

    if (showGithub) {
        var repoUrl by remember { mutableStateOf("") }
        var refInput by remember { mutableStateOf("") }
        var pathInput by remember { mutableStateOf("") }
        var installName by remember(ui.githubPreview?.name) { mutableStateOf(ui.githubPreview?.name ?: "") }
        AlertDialog(
            onDismissRequest = {
                vm.clearGithubPreview()
                showGithub = false
            },
            containerColor = colors.canvas,
            title = { Text("从 GitHub 安装技能", fontWeight = FontWeight.SemiBold, color = colors.fg) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
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
                            shapes = ButtonDefaults.shapesFor(40.dp),
                            enabled = repoUrl.isNotBlank() && !ui.loading,
                        ) { Text("解析") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
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
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .background(colors.surface)
                                .padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            WhitzTextField(
                                value = installName,
                                onValueChange = { installName = it },
                                label = "技能名称",
                                modifier = Modifier.fillMaxWidth(),
                            )
                            if (preview.description.isNotBlank()) {
                                Text(preview.description, fontSize = 12.sp, color = colors.fgMuted, maxLines = 3, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    vm.clearGithubPreview()
                    showGithub = false
                }) { Text("取消") }
            },
            confirmButton = {
                Button(
                    onClick = {
                        val preview = ui.githubPreview
                        vm.installGithubSkill(
                            repoUrl = repoUrl,
                            name = installName.ifBlank { preview?.name },
                            ref = preview?.ref ?: refInput,
                            path = preview?.path ?: pathInput,
                        )
                        showGithub = false
                    },
                    shapes = ButtonDefaults.shapesFor(36.dp),
                    enabled = repoUrl.isNotBlank() && ui.githubPreview != null && !ui.loading,
                ) { Text("安装") }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun MembershipSettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var redeemInput by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { vm.loadCredits() }

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
                    Text("剩余可用积分：${formatCredits(c.remaining)}", fontSize = 14.sp, color = colors.fgMuted)
                    if (!c.expiresAt.isNullOrBlank()) {
                        Text("到期时间：${DateTimeUtils.formatShort(c.expiresAt)}", fontSize = 12.sp, color = colors.fgFaint)
                    }

                    c.fiveHour.limit?.let { limit ->
                        val pct = if (limit > 0) ((limit - c.fiveHour.used).coerceAtLeast(0.0) / limit).toFloat().coerceIn(0f, 1f) else 0f
                        Text("5 小时额度：已用 ${formatCredits(c.fiveHour.used)} / $limit", fontSize = 12.sp, color = colors.fgMuted)
                        LinearWavyProgressIndicator(progress = { pct }, modifier = Modifier.fillMaxWidth())
                    }
                    c.weekly.limit?.let { limit ->
                        val pct = if (limit > 0) ((limit - c.weekly.used).coerceAtLeast(0.0) / limit).toFloat().coerceIn(0f, 1f) else 0f
                        Text("每周额度：已用 ${formatCredits(c.weekly.used)} / $limit", fontSize = 12.sp, color = colors.fgMuted)
                        LinearWavyProgressIndicator(progress = { pct }, modifier = Modifier.fillMaxWidth())
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

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun PersonaSettingsContent(vm: SettingsViewModel) {
    val user by vm.user.collectAsState()
    val ui by vm.ui.collectAsState()
    var persona by remember(user?.id) { mutableStateOf(user?.persona ?: "") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .navigationBarsPadding()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("自定义 AI 助理的回复风格、角色设定与偏好指令：", fontSize = 13.sp, color = LocalWhitzColors.current.fgMuted)
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

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun DevicesSettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) { vm.loadSessions() }

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
