package com.glassous.whitz.feature.settings

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.glassous.whitz.core.files.FileValidator
import com.glassous.whitz.core.model.ThemePreference
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.ui.theme.LocalWhitzColors

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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsRootScreen(
    vm: SettingsViewModel,
    onBackToChat: () -> Unit,
    onLoggedOut: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var section by remember { mutableStateOf(SettingsSection.HOME) }

    LaunchedEffect(Unit) {
        vm.refreshAll()
    }

    Scaffold(
        containerColor = colors.canvas,
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = colors.canvas),
                navigationIcon = {
                    IconButton(onClick = {
                        vm.clearFeedback()
                        if (section == SettingsSection.HOME) onBackToChat()
                        else section = SettingsSection.HOME
                    }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回", tint = colors.fg)
                    }
                },
                title = {
                    Text(section.title, fontWeight = FontWeight.SemiBold, fontSize = 18.sp, color = colors.fg)
                },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
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

            when (section) {
                SettingsSection.HOME -> SettingsHomeContent(
                    vm = vm,
                    onSelect = {
                        vm.clearFeedback()
                        section = it
                    },
                    onLogout = { vm.logout(onLoggedOut) },
                )
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
    }
}

@Composable
private fun SettingsHomeContent(
    vm: SettingsViewModel,
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
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // User card
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(colors.surface)
                .clickable { onSelect(SettingsSection.PROFILE) }
                .padding(14.dp),
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
                Text(user?.email ?: "", fontSize = 13.sp, color = colors.fgMuted)
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = colors.fgFaint)
        }

        // Theme selector
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(colors.surface)
                .padding(14.dp),
        ) {
            Text("外观主题", fontWeight = FontWeight.Medium, fontSize = 14.sp, color = colors.fg)
            Spacer(modifier = Modifier.height(10.dp))
            val options = listOf(
                ThemePreference.SYSTEM to "跟随系统",
                ThemePreference.LIGHT to "浅色",
                ThemePreference.DARK to "深色",
            )
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                options.forEachIndexed { idx, (pref, label) ->
                    SegmentedButton(
                        selected = theme == pref,
                        onClick = { vm.setTheme(pref) },
                        shape = SegmentedButtonDefaults.itemShape(index = idx, count = options.size),
                    ) { Text(label, fontSize = 13.sp) }
                }
            }
        }

        // Menu items
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(colors.surface),
        ) {
            SettingsMenuRow(Icons.Default.Person, "个人资料", null) { onSelect(SettingsSection.PROFILE) }
            HorizontalDivider(color = colors.line)
            SettingsMenuRow(Icons.Default.Lock, "修改密码", null) { onSelect(SettingsSection.PASSWORD) }
            HorizontalDivider(color = colors.line)
            SettingsMenuRow(Icons.Default.Folder, "文件库", null) { onSelect(SettingsSection.LIBRARY) }
            HorizontalDivider(color = colors.line)
            SettingsMenuRow(Icons.Default.Psychology, "记忆管理", null) { onSelect(SettingsSection.MEMORY) }
            HorizontalDivider(color = colors.line)
            SettingsMenuRow(Icons.Default.AutoAwesome, "技能管理", null) { onSelect(SettingsSection.SKILLS) }
            HorizontalDivider(color = colors.line)
            SettingsMenuRow(
                Icons.Default.CreditCard,
                "会员与积分",
                ui.credits?.let { "${it.tierLabel} · ${it.remaining} 积分" },
            ) { onSelect(SettingsSection.MEMBERSHIP) }
            HorizontalDivider(color = colors.line)
            SettingsMenuRow(Icons.Default.SmartToy, "人格设定", null) { onSelect(SettingsSection.PERSONA) }
            HorizontalDivider(color = colors.line)
            SettingsMenuRow(Icons.Default.Devices, "登录设备", null) { onSelect(SettingsSection.DEVICES) }
        }

        Spacer(modifier = Modifier.height(8.dp))
        OutlinedButton(
            onClick = { confirmLogout = true },
            modifier = Modifier.fillMaxWidth().height(46.dp),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.danger),
        ) {
            Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(modifier = Modifier.width(8.dp))
            Text("退出登录")
        }
    }

    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            title = { Text("退出登录") },
            text = { Text("确定要退出当前账号吗？") },
            dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("取消") } },
            confirmButton = {
                Button(onClick = {
                    confirmLogout = false
                    onLogout()
                }) { Text("退出") }
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
            OutlinedButton(onClick = { avatarPicker.launch("image/*") }) { Text("更换头像") }
            if (!user?.avatarUrl.isNullOrBlank()) {
                TextButton(onClick = { vm.deleteAvatar() }) { Text("移除", color = colors.danger) }
            }
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(colors.surface)
                .padding(12.dp),
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

        OutlinedTextField(value = displayName, onValueChange = { displayName = it }, label = { Text("昵称") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = bio, onValueChange = { bio = it }, label = { Text("个人简介") }, modifier = Modifier.fillMaxWidth(), maxLines = 3)
        OutlinedTextField(value = gender, onValueChange = { gender = it }, label = { Text("性别") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = birthday, onValueChange = { birthday = it }, label = { Text("生日 (YYYY-MM-DD)") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = phone, onValueChange = { phone = it }, label = { Text("手机号") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = location, onValueChange = { location = it }, label = { Text("所在地") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = occupation, onValueChange = { occupation = it }, label = { Text("职业") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = website, onValueChange = { website = it }, label = { Text("个人网站") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = language, onValueChange = { language = it }, label = { Text("偏好语言") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(value = timezone, onValueChange = { timezone = it }, label = { Text("时区") }, modifier = Modifier.fillMaxWidth(), singleLine = true)

        Button(
            onClick = {
                vm.updateProfile(displayName, bio, gender, birthday, phone, location, occupation, website, language, timezone)
            },
            enabled = !ui.loading && displayName.isNotBlank(),
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) {
            Text(if (ui.loading) "保存中..." else "保存个人资料")
        }
    }
}

@Composable
private fun PasswordSettingsContent(vm: SettingsViewModel) {
    val ui by vm.ui.collectAsState()
    var current by remember { mutableStateOf("") }
    var next by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedTextField(
            value = current,
            onValueChange = { current = it },
            label = { Text("当前密码") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = next,
            onValueChange = { next = it },
            label = { Text("新密码（至少 6 位）") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = confirm,
            onValueChange = { confirm = it },
            label = { Text("确认新密码") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = {
                if (next != confirm) {
                    return@Button
                }
                vm.updatePassword(current, next)
            },
            enabled = !ui.loading && current.isNotBlank() && next.length >= 6 && next == confirm,
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) {
            Text("更新密码")
        }
    }
}

@Composable
private fun LibrarySettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var query by remember { mutableStateOf("") }
    var globalOnly by remember { mutableStateOf<Boolean?>(null) }

    LaunchedEffect(Unit) { vm.loadLibrary() }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = query,
                onValueChange = {
                    query = it
                    vm.loadLibrary(it, globalOnly)
                },
                placeholder = { Text("搜索文件名...") },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            OutlinedButton(onClick = {
                globalOnly = if (globalOnly == true) null else true
                vm.loadLibrary(query, globalOnly)
            }) {
                Text(if (globalOnly == true) "仅全局" else "全部")
            }
        }
        Spacer(modifier = Modifier.height(12.dp))
        if (ui.loading && ui.libraryFiles.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        } else if (ui.libraryFiles.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无文件", color = colors.fgFaint)
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(ui.libraryFiles, key = { it.id }) { f ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
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

@Composable
private fun MemorySettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var showAdd by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.loadMemory() }

    val mem = ui.memory
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        if (mem != null) {
            Row(
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(colors.surface).padding(12.dp),
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
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(colors.surface).padding(12.dp),
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

            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) {
                items(mem.pending, key = { "p-${it.id}" }) { p ->
                    Column(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(colors.warningWeak).padding(10.dp),
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
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(colors.surface).padding(12.dp),
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
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        }
    }

    if (showAdd) {
        var content by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showAdd = false },
            title = { Text("新增记忆") },
            text = {
                OutlinedTextField(value = content, onValueChange = { content = it }, label = { Text("记忆内容") }, modifier = Modifier.fillMaxWidth(), maxLines = 4)
            },
            dismissButton = { TextButton(onClick = { showAdd = false }) { Text("取消") } },
            confirmButton = {
                Button(onClick = {
                    vm.addMemoryEntry(content)
                    showAdd = false
                }) { Text("保存") }
            },
        )
    }
}

@Composable
private fun SkillsSettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var showCreate by remember { mutableStateOf(false) }
    var showGithub by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.loadSkills() }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { showCreate = true }, modifier = Modifier.weight(1f)) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("新建技能")
            }
            OutlinedButton(onClick = { showGithub = true }, modifier = Modifier.weight(1f)) {
                Text("从 GitHub 安装")
            }
        }
        Spacer(modifier = Modifier.height(12.dp))

        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.weight(1f)) {
            items(ui.pendingSkills, key = { "ps-${it.id}" }) { p ->
                Column(
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(colors.warningWeak).padding(10.dp),
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
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(colors.surface).padding(12.dp),
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
            title = { Text("新建自定义技能") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("技能名称 (英文标识)") }, singleLine = true)
                    OutlinedTextField(value = desc, onValueChange = { desc = it }, label = { Text("描述") }, singleLine = true)
                    OutlinedTextField(value = content, onValueChange = { content = it }, label = { Text("指令内容 (Markdown)") }, minLines = 3, maxLines = 6)
                }
            },
            dismissButton = { TextButton(onClick = { showCreate = false }) { Text("取消") } },
            confirmButton = {
                Button(onClick = {
                    vm.createSkill(name, desc, content)
                    showCreate = false
                }) { Text("创建") }
            },
        )
    }

    if (showGithub) {
        var repoUrl by remember { mutableStateOf("") }
        val selectedPaths = remember { mutableStateListOf<String>() }
        AlertDialog(
            onDismissRequest = { showGithub = false },
            title = { Text("从 GitHub 安装技能") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedTextField(
                            value = repoUrl,
                            onValueChange = { repoUrl = it },
                            label = { Text("GitHub 仓库 URL") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedButton(onClick = { vm.previewGithubSkill(repoUrl) }) { Text("解析") }
                    }
                    if (ui.githubPreviewItems.isNotEmpty()) {
                        LazyColumn(modifier = Modifier.height(180.dp)) {
                            items(ui.githubPreviewItems) { item ->
                                val checked = item.path in selectedPaths
                                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.clickable {
                                    if (checked) selectedPaths.remove(item.path) else selectedPaths.add(item.path)
                                }) {
                                    Checkbox(checked = checked, onCheckedChange = {
                                        if (checked) selectedPaths.remove(item.path) else selectedPaths.add(item.path)
                                    })
                                    Text(item.name, fontSize = 13.sp, color = colors.fg)
                                }
                            }
                        }
                    }
                }
            },
            dismissButton = { TextButton(onClick = { showGithub = false }) { Text("取消") } },
            confirmButton = {
                Button(onClick = {
                    vm.installGithubSkill(repoUrl, selectedPaths.toList())
                    showGithub = false
                }, enabled = repoUrl.isNotBlank()) { Text("安装") }
            },
        )
    }
}

@Composable
private fun MembershipSettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var redeemInput by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { vm.loadCredits() }

    val c = ui.credits
    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        if (c != null) {
            Column(
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(colors.surface).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("当前套餐：${c.tierLabel}", fontWeight = FontWeight.Bold, fontSize = 18.sp, color = colors.fg)
                Text("剩余可用积分：${c.remaining}", fontSize = 14.sp, color = colors.fgMuted)
                if (!c.expiresAt.isNullOrBlank()) {
                    Text("到期时间：${DateTimeUtils.formatShort(c.expiresAt)}", fontSize = 12.sp, color = colors.fgFaint)
                }

                c.fiveHour.limit?.let { limit ->
                    val pct = if (limit > 0) ((limit - c.fiveHour.used).coerceAtLeast(0).toFloat() / limit).coerceIn(0f, 1f) else 0f
                    Text("5 小时额度：已用 ${c.fiveHour.used} / $limit", fontSize = 12.sp, color = colors.fgMuted)
                    LinearProgressIndicator(progress = { pct }, modifier = Modifier.fillMaxWidth())
                }
                c.weekly.limit?.let { limit ->
                    val pct = if (limit > 0) ((limit - c.weekly.used).coerceAtLeast(0).toFloat() / limit).coerceIn(0f, 1f) else 0f
                    Text("每周额度：已用 ${c.weekly.used} / $limit", fontSize = 12.sp, color = colors.fgMuted)
                    LinearProgressIndicator(progress = { pct }, modifier = Modifier.fillMaxWidth())
                }
            }

            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = redeemInput,
                    onValueChange = { redeemInput = it },
                    label = { Text("输入兑换码") },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                Button(
                    onClick = {
                        vm.redeemCode(redeemInput)
                        redeemInput = ""
                    },
                    enabled = redeemInput.isNotBlank() && !ui.loading,
                    modifier = Modifier.height(54.dp),
                ) { Text("兑换") }
            }

            if (c.plans.isNotEmpty()) {
                Text("套餐方案说明", fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                c.plans.forEach { p ->
                    Column(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(colors.surface).padding(12.dp),
                    ) {
                        Text(p.label, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = colors.fg)
                        Text(p.summary, fontSize = 13.sp, color = colors.fgMuted)
                    }
                }
            }
        } else {
            Box(modifier = Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        }
    }
}

@Composable
private fun PersonaSettingsContent(vm: SettingsViewModel) {
    val user by vm.user.collectAsState()
    val ui by vm.ui.collectAsState()
    var persona by remember(user?.id) { mutableStateOf(user?.persona ?: "") }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("自定义 AI 助理的回复风格、角色设定与偏好指令：", fontSize = 13.sp, color = LocalWhitzColors.current.fgMuted)
        OutlinedTextField(
            value = persona,
            onValueChange = { persona = it },
            placeholder = { Text("例如：请用简洁专业的中文回复，优先给出可执行代码...") },
            minLines = 6,
            maxLines = 12,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { vm.updatePersona(persona) },
            enabled = !ui.loading,
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) {
            Text(if (ui.loading) "保存中..." else "保存人格设定")
        }
    }
}

@Composable
private fun DevicesSettingsContent(vm: SettingsViewModel) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()

    LaunchedEffect(Unit) { vm.loadSessions() }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        if (ui.sessions.size > 1) {
            OutlinedButton(
                onClick = { vm.deleteOtherSessions() },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.danger),
            ) {
                Text("下线全部其他设备")
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        if (ui.loading && ui.sessions.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(ui.sessions, key = { it.sessionId }) { s ->
                    Row(
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(colors.surface).padding(12.dp),
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
