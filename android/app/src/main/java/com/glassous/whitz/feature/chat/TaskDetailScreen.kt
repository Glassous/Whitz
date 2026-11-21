package com.glassous.whitz.feature.chat

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MediumFlexibleTopAppBar
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.glassous.whitz.core.model.resolvedAssistantName
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup
import com.glassous.whitz.ui.theme.WhitzLogoMark

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun TaskDetailScreen(
    vm: ChatViewModel,
    initialTab: Int = 0,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    val user by vm.user.collectAsState()
    var selectedTab by rememberSaveable(initialTab) {
        mutableIntStateOf(if (initialTab == 1) 1 else 0)
    }
    var assistantModalOpen by remember { mutableStateOf(false) }
    val scrollBehavior = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
    val assistantAvatarUrl = vm.resolveAssetUrl(user?.assistantAvatarUrl)

    val resolvedTurn = remember(
        ui.messages,
        ui.selectedTurnId,
        ui.activeAssistantId,
        ui.streaming,
        ui.plan,
        ui.reasoning,
    ) {
        resolveTurnDetails(
            messages = ui.messages,
            selectedTurnId = ui.selectedTurnId,
            activeAssistantId = ui.activeAssistantId,
            streaming = ui.streaming,
            livePlan = ui.plan,
            liveReasoning = ui.reasoning,
        )
    }

    BackHandler(enabled = ui.previewTarget != null) {
        vm.closeFilePreview()
    }

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
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回",
                            tint = colors.fg,
                        )
                    }
                },
                title = {
                    Text(
                        text = when {
                            ui.isMainChat -> "助手与步骤"
                            selectedTab == 0 -> "执行步骤"
                            else -> "对话文件"
                        },
                        fontWeight = FontWeight.SemiBold,
                        color = colors.fg,
                    )
                },
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = innerPadding.calculateTopPadding()),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(
                modifier = Modifier
                    .widthIn(max = 840.dp)
                    .fillMaxSize(),
            ) {
                if (!ui.fileError.isNullOrBlank()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(colors.dangerWeak)
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                    ) {
                        Text(ui.fileError!!, color = colors.danger, fontSize = 13.sp)
                    }
                }

                if (ui.isMainChat) {
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 8.dp)
                            .clip(RoundedCornerShape(18.dp))
                            .clickable {
                                vm.clearAssistantDialogFeedback()
                                assistantModalOpen = true
                            },
                        shape = RoundedCornerShape(18.dp),
                        color = colors.surface,
                        border = BorderStroke(0.5.dp, colors.line),
                    ) {
                        Row(
                            modifier = Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(44.dp)
                                    .clip(CircleShape)
                                    .background(colors.canvas),
                                contentAlignment = Alignment.Center,
                            ) {
                                if (!assistantAvatarUrl.isNullOrBlank()) {
                                    AsyncImage(
                                        model = assistantAvatarUrl,
                                        contentDescription = assistantName,
                                        contentScale = ContentScale.Crop,
                                        modifier = Modifier.fillMaxSize(),
                                    )
                                } else {
                                    WhitzLogoMark(modifier = Modifier.size(22.dp))
                                }
                            }
                            Spacer(modifier = Modifier.width(12.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = assistantName,
                                    fontSize = 15.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = colors.fg,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    text = "专属主助手 · 点击自定义",
                                    fontSize = 11.5.sp,
                                    color = colors.fgFaint,
                                )
                            }
                            Icon(
                                imageVector = Icons.Default.Edit,
                                contentDescription = "自定义助手",
                                tint = colors.fgFaint,
                                modifier = Modifier.size(18.dp),
                            )
                        }
                    }

                    TaskStepsPane(
                        plan = resolvedTurn.plan,
                        reasoning = resolvedTurn.reasoning,
                        streaming = resolvedTurn.isLive,
                        runningTool = resolvedTurn.runningTool,
                        turnKey = resolvedTurn.turnId ?: "",
                        bottomPadding = navBottom + 24.dp,
                        modifier = Modifier.weight(1f).fillMaxWidth(),
                    )
                } else {
                    WhitzConnectedRadioGroup(
                        options = listOf(0 to "执行步骤", 1 to "对话文件 (${ui.files.size})"),
                        selected = selectedTab,
                        onSelect = { selectedTab = it },
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    )

                    AnimatedContent(
                        targetState = selectedTab,
                        transitionSpec = {
                            val forward = targetState >= initialState
                            val enter = slideInHorizontally(animationSpec = tween(240)) { width ->
                                if (forward) width / 8 else -(width / 8)
                            } + fadeIn(animationSpec = tween(180))
                            val exit = slideOutHorizontally(animationSpec = tween(200)) { width ->
                                if (forward) -(width / 12) else width / 12
                            } + fadeOut(animationSpec = tween(150))
                            enter togetherWith exit
                        },
                        label = "taskDetailTab",
                        modifier = Modifier.weight(1f).fillMaxWidth(),
                    ) { tab ->
                        if (tab == 0) {
                            TaskStepsPane(
                                plan = resolvedTurn.plan,
                                reasoning = resolvedTurn.reasoning,
                                streaming = resolvedTurn.isLive,
                                runningTool = resolvedTurn.runningTool,
                                turnKey = resolvedTurn.turnId ?: "",
                                bottomPadding = navBottom + 24.dp,
                                modifier = Modifier.fillMaxSize(),
                            )
                        } else {
                            TaskFilesPane(
                                files = ui.files,
                                deletingFileId = ui.deletingFileId,
                                onOpenFile = { vm.openFilePreview(it) },
                                onDeleteFile = { vm.deleteFile(it) },
                                bottomPadding = navBottom + 24.dp,
                                modifier = Modifier.fillMaxSize(),
                            )
                        }
                    }
                }
            }
        }
    }

    if (assistantModalOpen) {
        AssistantProfileDialog(
            user = user,
            resolveAssetUrl = { vm.resolveAssetUrl(it) },
            saving = ui.assistantSaving,
            error = ui.assistantError,
            feedback = ui.assistantFeedback,
            onPickAvatar = { vm.uploadAssistantAvatar(it) },
            onResetAvatar = { vm.deleteAssistantAvatar() },
            onSaveName = { nextName ->
                vm.updateAssistantName(nextName) {
                    assistantModalOpen = false
                }
            },
            onDismiss = { assistantModalOpen = false },
        )
    }

    ui.previewTarget?.let { target ->
        FilePreviewDialog(target = target, onDismiss = { vm.closeFilePreview() })
    }
}
