package com.glassous.whitz.feature.chat

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.UploadTaskStatus
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.ui.theme.LocalWhitzColors
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    vm: ChatViewModel,
    onOpenSettings: () -> Unit,
) {
    val ui by vm.ui.collectAsState()
    val user by vm.user.collectAsState()
    val colors = LocalWhitzColors.current
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()
    val snackbarHostState = remember { SnackbarHostState() }

    var inputText by remember { mutableStateOf("") }
    var showSearch by remember { mutableStateOf(false) }
    var showSkillPicker by remember { mutableStateOf(false) }
    var showLibraryPicker by remember { mutableStateOf(false) }
    var showTaskSheet by remember { mutableStateOf(false) }
    var showAttachMenu by remember { mutableStateOf(false) }

    var renameTarget by remember { mutableStateOf<Conversation?>(null) }
    var deleteTarget by remember { mutableStateOf<Conversation?>(null) }

    val filePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments()
    ) { uris ->
        if (uris.isNotEmpty()) {
            vm.enqueuePickedUris(uris)
        }
    }

    LaunchedEffect(Unit) {
        vm.loadInitialData()
    }

    val lastMsgContentLen = ui.messages.lastOrNull()?.content?.length ?: 0
    LaunchedEffect(ui.messages.size, lastMsgContentLen) {
        if (ui.messages.isNotEmpty()) {
            listState.animateScrollToItem(ui.messages.lastIndex)
        }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet(
                drawerContainerColor = colors.sidebar,
                modifier = Modifier.width(300.dp),
            ) {
                Column(modifier = Modifier.fillMaxHeight().padding(12.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            modifier = Modifier
                                .size(32.dp)
                                .clip(RoundedCornerShape(8.dp))
                                .background(MaterialTheme.colorScheme.primary),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("W", color = MaterialTheme.colorScheme.onPrimary, fontWeight = FontWeight.Bold)
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Text("Whitz", fontWeight = FontWeight.Bold, fontSize = 18.sp, color = colors.fg, modifier = Modifier.weight(1f))
                        IconButton(onClick = { showSearch = true }) {
                            Icon(Icons.Default.Search, contentDescription = "搜索", tint = colors.fgMuted)
                        }
                        IconButton(onClick = {
                            vm.startNewConversation()
                            scope.launch { drawerState.close() }
                        }) {
                            Icon(Icons.Default.Add, contentDescription = "新对话", tint = colors.fg)
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    HorizontalDivider(color = colors.line)
                    Spacer(modifier = Modifier.height(8.dp))

                    if (ui.conversationsLoading && ui.conversations.isEmpty()) {
                        Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                            CircularProgressIndicator(modifier = Modifier.size(22.dp))
                        }
                    } else if (ui.conversations.isEmpty()) {
                        Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                            Text("暂无历史对话", color = colors.fgFaint, fontSize = 13.sp)
                        }
                    } else {
                        LazyColumn(
                            modifier = Modifier.weight(1f),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            items(ui.conversations, key = { it.id }) { conv ->
                                val selected = conv.id == ui.currentConvId
                                var menuOpen by remember(conv.id) { mutableStateOf(false) }
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(10.dp))
                                        .background(if (selected) colors.hover else colors.sidebar)
                                        .clickable {
                                            vm.openConversation(conv.id)
                                            scope.launch { drawerState.close() }
                                        }
                                        .padding(horizontal = 10.dp, vertical = 10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    if (conv.isPinned) {
                                        Icon(
                                            Icons.Default.PushPin,
                                            contentDescription = "已置顶",
                                            tint = colors.fgMuted,
                                            modifier = Modifier.size(14.dp).padding(end = 2.dp),
                                        )
                                        Spacer(modifier = Modifier.width(4.dp))
                                    }
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            text = conv.title.ifBlank { "新对话" },
                                            fontSize = 14.sp,
                                            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                                            color = colors.fg,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                        val time = DateTimeUtils.formatShort(conv.lastMessageAt ?: conv.updatedAt)
                                        if (time.isNotBlank()) {
                                            Text(time, fontSize = 11.sp, color = colors.fgFaint)
                                        }
                                    }
                                    Box {
                                        IconButton(onClick = { menuOpen = true }, modifier = Modifier.size(28.dp)) {
                                            Icon(Icons.Default.MoreVert, contentDescription = "更多", tint = colors.fgFaint, modifier = Modifier.size(16.dp))
                                        }
                                        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                                            DropdownMenuItem(
                                                text = { Text(if (conv.isPinned) "取消置顶" else "置顶对话") },
                                                leadingIcon = { Icon(Icons.Default.PushPin, contentDescription = null) },
                                                onClick = {
                                                    menuOpen = false
                                                    vm.togglePin(conv.id, !conv.isPinned)
                                                },
                                            )
                                            DropdownMenuItem(
                                                text = { Text("重命名") },
                                                leadingIcon = { Icon(Icons.Default.Edit, contentDescription = null) },
                                                onClick = {
                                                    menuOpen = false
                                                    renameTarget = conv
                                                },
                                            )
                                            DropdownMenuItem(
                                                text = { Text("删除", color = colors.danger) },
                                                leadingIcon = { Icon(Icons.Default.Delete, contentDescription = null, tint = colors.danger) },
                                                onClick = {
                                                    menuOpen = false
                                                    deleteTarget = conv
                                                },
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }

                    HorizontalDivider(color = colors.line)
                    Spacer(modifier = Modifier.height(8.dp))

                    // Sidebar Footer: User & Credits & Settings
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .clickable {
                                scope.launch { drawerState.close() }
                                onOpenSettings()
                            }
                            .padding(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (!user?.avatarUrl.isNullOrBlank()) {
                            AsyncImage(
                                model = user?.avatarUrl,
                                contentDescription = "头像",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.size(36.dp).clip(CircleShape),
                            )
                        } else {
                            Box(
                                modifier = Modifier
                                    .size(36.dp)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.primary),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    text = (user?.displayName?.firstOrNull() ?: 'U').uppercase(),
                                    color = MaterialTheme.colorScheme.onPrimary,
                                    fontWeight = FontWeight.Bold,
                                )
                            }
                        }
                        Spacer(modifier = Modifier.width(10.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = user?.displayName ?: "未登录",
                                fontSize = 14.sp,
                                fontWeight = FontWeight.Medium,
                                color = colors.fg,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            val creditsLabel = ui.credits?.let { "${it.tierLabel} · 剩余 ${it.remaining} 积分" }
                                ?: (user?.email ?: "")
                            Text(
                                text = creditsLabel,
                                fontSize = 11.sp,
                                color = colors.fgFaint,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        Icon(Icons.Default.Settings, contentDescription = "设置", tint = colors.fgMuted, modifier = Modifier.size(20.dp))
                    }
                }
            }
        },
    ) {
        Scaffold(
            containerColor = colors.canvas,
            snackbarHost = { SnackbarHost(snackbarHostState) },
            topBar = {
                TopAppBar(
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = colors.canvas),
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) {
                            Icon(Icons.Default.Menu, contentDescription = "菜单", tint = colors.fg)
                        }
                    },
                    title = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                text = ui.currentConvTitle,
                                fontSize = 16.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = colors.fg,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false),
                            )
                            if (ui.agentStatus != null) {
                                Spacer(modifier = Modifier.width(6.dp))
                                Box(
                                    modifier = Modifier
                                        .size(8.dp)
                                        .clip(CircleShape)
                                        .background(if (ui.agentStatus?.ready == true) colors.success else colors.warning),
                                )
                            }
                        }
                    },
                    actions = {
                        IconButton(onClick = { showTaskSheet = true }) {
                            Icon(Icons.Default.Layers, contentDescription = "步骤与文件", tint = colors.fgMuted)
                        }
                        IconButton(onClick = { vm.startNewConversation() }) {
                            Icon(Icons.Default.Add, contentDescription = "新对话", tint = colors.fg)
                        }
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
                // Messages Area
                Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                    if (ui.messages.isEmpty()) {
                        Column(
                            modifier = Modifier.fillMaxSize().padding(24.dp),
                            verticalArrangement = Arrangement.Center,
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(56.dp)
                                    .clip(RoundedCornerShape(16.dp))
                                    .background(MaterialTheme.colorScheme.primary),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text("W", color = MaterialTheme.colorScheme.onPrimary, fontSize = 26.sp, fontWeight = FontWeight.Bold)
                            }
                            Spacer(modifier = Modifier.height(16.dp))
                            Text("有什么我可以帮你的？", fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                "支持文档分析、代码编写、深度推理与多轮工具调用",
                                fontSize = 13.sp,
                                color = colors.fgMuted,
                            )
                        }
                    } else {
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(14.dp),
                        ) {
                            items(ui.messages, key = { it.id }) { msg ->
                                MessageBubble(
                                    message = msg,
                                    streaming = ui.streaming,
                                    isActiveTurn = msg.id == ui.activeAssistantId,
                                    convFiles = ui.files,
                                    onCopy = {
                                        scope.launch { snackbarHostState.showSnackbar("已复制到剪贴板") }
                                    },
                                    onRegenerate = { vm.regenerate(it) },
                                    onEditSubmit = { id, content -> vm.editAndResend(id, content) },
                                    onOpenTurnDetails = { id ->
                                        vm.selectTurn(id)
                                        showTaskSheet = true
                                    },
                                    onOpenFile = { f -> vm.openFilePreview(f) },
                                )
                            }

                            ui.pendingControl?.let { ctrl ->
                                item(key = "ctrl-${ctrl.requestId ?: ctrl.kind}") {
                                    if (ctrl.kind == "approval") {
                                        ApprovalCard(control = ctrl, onApprove = { vm.approveControl(it) })
                                    } else {
                                        ClarifyCard(control = ctrl, onSubmit = { vm.clarifyControl(it) })
                                    }
                                }
                            }

                            items(ui.pendingMemory, key = { "mem-${it.id}" }) { mem ->
                                MemoryPendingCard(item = mem, onResolve = { id, act, c -> vm.resolvePendingMemory(id, act, c) })
                            }

                            items(ui.pendingSkills, key = { "skill-${it.id}" }) { sk ->
                                SkillPendingCard(item = sk, onResolve = { id, act, c -> vm.resolvePendingSkill(id, act, c) })
                            }
                        }
                    }
                }

                // Error Banner
                val bannerError = ui.error ?: ui.fileError
                if (!bannerError.isNullOrBlank()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(colors.dangerWeak)
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(bannerError, color = colors.danger, fontSize = 12.sp, modifier = Modifier.weight(1f))
                        IconButton(onClick = { vm.clearError() }, modifier = Modifier.size(24.dp)) {
                            Icon(Icons.Default.Close, contentDescription = "关闭", tint = colors.danger, modifier = Modifier.size(14.dp))
                        }
                    }
                }

                // Composer Area
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(colors.canvas)
                        .border(0.5.dp, colors.line)
                        .navigationBarsPadding()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                ) {
                    // Uploading tasks + Attached files + Selected skills
                    val attachedFiles = ui.files.filter { it.id in ui.attachedIds }
                    if (ui.uploads.isNotEmpty() || attachedFiles.isNotEmpty() || ui.selectedSkillNames.isNotEmpty()) {
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                            modifier = Modifier.padding(bottom = 8.dp),
                        ) {
                            ui.uploads.forEach { task ->
                                Row(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(colors.surface)
                                        .border(1.dp, colors.line, RoundedCornerShape(8.dp))
                                        .padding(horizontal = 8.dp, vertical = 5.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.width(120.dp)) {
                                        Text(task.filename, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, color = colors.fg)
                                        if (task.status == UploadTaskStatus.ERROR) {
                                            Text(task.error ?: "失败", fontSize = 10.sp, color = colors.danger, maxLines = 1)
                                        } else {
                                            LinearProgressIndicator(
                                                progress = { task.progress / 100f },
                                                modifier = Modifier.fillMaxWidth().height(3.dp),
                                            )
                                        }
                                    }
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Icon(
                                        Icons.Default.Close,
                                        contentDescription = "取消",
                                        tint = colors.fgFaint,
                                        modifier = Modifier.size(14.dp).clickable { vm.cancelOrDismissUpload(task.localId) },
                                    )
                                }
                            }

                            attachedFiles.forEach { f ->
                                Row(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(colors.surface)
                                        .border(1.dp, colors.line, RoundedCornerShape(8.dp))
                                        .padding(horizontal = 8.dp, vertical = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(Icons.Default.AttachFile, contentDescription = null, tint = colors.fgMuted, modifier = Modifier.size(13.dp))
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text(f.filename, fontSize = 12.sp, color = colors.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Icon(
                                        Icons.Default.Close,
                                        contentDescription = "移除",
                                        tint = colors.fgFaint,
                                        modifier = Modifier.size(14.dp).clickable { vm.detachFile(f.id) },
                                    )
                                }
                            }

                            ui.selectedSkillNames.forEach { sk ->
                                Row(
                                    modifier = Modifier
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(colors.surface)
                                        .border(1.dp, colors.lineStrong, RoundedCornerShape(8.dp))
                                        .padding(horizontal = 8.dp, vertical = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(Icons.Default.AutoAwesome, contentDescription = null, tint = colors.fg, modifier = Modifier.size(13.dp))
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text(sk, fontSize = 12.sp, color = colors.fg)
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Icon(
                                        Icons.Default.Close,
                                        contentDescription = "移除技能",
                                        tint = colors.fgFaint,
                                        modifier = Modifier.size(14.dp).clickable { vm.toggleSkillSelection(sk) },
                                    )
                                }
                            }
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.Bottom,
                    ) {
                        Box {
                            IconButton(onClick = { showAttachMenu = true }) {
                                Icon(Icons.Default.Add, contentDescription = "更多选项", tint = colors.fgMuted)
                            }
                            DropdownMenu(expanded = showAttachMenu, onDismissRequest = { showAttachMenu = false }) {
                                DropdownMenuItem(
                                    text = { Text("上传本地文件") },
                                    leadingIcon = { Icon(Icons.Default.UploadFile, contentDescription = null) },
                                    onClick = {
                                        showAttachMenu = false
                                        filePickerLauncher.launch(arrayOf("*/*"))
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text("从文件库选择") },
                                    leadingIcon = { Icon(Icons.Default.FolderOpen, contentDescription = null) },
                                    onClick = {
                                        showAttachMenu = false
                                        showLibraryPicker = true
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text("附加技能 (${ui.selectedSkillNames.size})") },
                                    leadingIcon = { Icon(Icons.Default.AutoAwesome, contentDescription = null) },
                                    onClick = {
                                        showAttachMenu = false
                                        showSkillPicker = true
                                    },
                                )
                            }
                        }

                        OutlinedTextField(
                            value = inputText,
                            onValueChange = { inputText = it },
                            placeholder = { Text("输入消息...") },
                            maxLines = 5,
                            shape = RoundedCornerShape(20.dp),
                            modifier = Modifier.weight(1f),
                        )

                        Spacer(modifier = Modifier.width(6.dp))

                        if (ui.streaming) {
                            IconButton(
                                onClick = { vm.stopRun() },
                                modifier = Modifier
                                    .size(44.dp)
                                    .clip(CircleShape)
                                    .background(colors.danger),
                            ) {
                                Icon(Icons.Default.Stop, contentDescription = "停止生成", tint = MaterialTheme.colorScheme.onError)
                            }
                        } else {
                            val canSend = inputText.isNotBlank() || ui.attachedIds.isNotEmpty()
                            IconButton(
                                onClick = {
                                    val text = inputText
                                    inputText = ""
                                    vm.sendMessage(text)
                                },
                                enabled = canSend,
                                modifier = Modifier
                                    .size(44.dp)
                                    .clip(CircleShape)
                                    .background(if (canSend) MaterialTheme.colorScheme.primary else colors.surface),
                            ) {
                                Icon(
                                    Icons.AutoMirrored.Filled.Send,
                                    contentDescription = "发送",
                                    tint = if (canSend) MaterialTheme.colorScheme.onPrimary else colors.fgFaint,
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // Dialogs & Sheets
    if (showSearch) {
        SearchDialog(
            results = ui.searchResults,
            searching = ui.searching,
            onQueryChange = { vm.searchConversations(it) },
            onSelectConversation = { id ->
                vm.openConversation(id)
                scope.launch { drawerState.close() }
            },
            onDismiss = { showSearch = false },
        )
    }

    if (showSkillPicker) {
        SkillPickerDialog(
            skills = ui.enabledSkills,
            selectedNames = ui.selectedSkillNames,
            onToggle = { vm.toggleSkillSelection(it) },
            onDismiss = { showSkillPicker = false },
        )
    }

    if (showLibraryPicker) {
        LibraryAttachDialog(
            fetchLibrary = { q -> vm.fetchLibraryFiles(q) },
            onAttach = { ids -> vm.attachFromLibrary(ids) },
            onDismiss = { showLibraryPicker = false },
        )
    }

    if (showTaskSheet) {
        val selectedMsg = ui.messages.firstOrNull { it.id == ui.selectedTurnId }
            ?: ui.messages.lastOrNull { it.role == "assistant" }
        val activeTurn = selectedMsg?.id == ui.activeAssistantId
        val sheetPlan = if (activeTurn) ui.plan ?: selectedMsg?.toolPayload?.plan else selectedMsg?.toolPayload?.plan
        val sheetReasoning = if (activeTurn) ui.reasoning else selectedMsg?.toolPayload?.reasoning.orEmpty()

        TaskDetailSheet(
            plan = sheetPlan,
            reasoning = sheetReasoning,
            files = ui.files,
            onOpenFile = { f -> vm.openFilePreview(f) },
            onDeleteFile = { id -> vm.deleteFile(id) },
            onDismiss = { showTaskSheet = false },
        )
    }

    ui.previewTarget?.let { target ->
        FilePreviewDialog(target = target, onDismiss = { vm.closeFilePreview() })
    }

    renameTarget?.let { conv ->
        var newTitle by remember(conv.id) { mutableStateOf(conv.title) }
        AlertDialog(
            onDismissRequest = { renameTarget = null },
            title = { Text("重命名对话") },
            text = {
                OutlinedTextField(
                    value = newTitle,
                    onValueChange = { newTitle = it },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            dismissButton = { TextButton(onClick = { renameTarget = null }) { Text("取消") } },
            confirmButton = {
                Button(onClick = {
                    vm.renameConversation(conv.id, newTitle)
                    renameTarget = null
                }) { Text("保存") }
            },
        )
    }

    deleteTarget?.let { conv ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("删除对话") },
            text = { Text("确定要删除「${conv.title}」吗？删除后无法恢复。") },
            dismissButton = { TextButton(onClick = { deleteTarget = null }) { Text("取消") } },
            confirmButton = {
                Button(onClick = {
                    vm.deleteConversation(conv.id)
                    deleteTarget = null
                }) { Text("删除") }
            },
        )
    }
}
