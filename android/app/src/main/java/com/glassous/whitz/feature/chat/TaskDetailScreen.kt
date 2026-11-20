package com.glassous.whitz.feature.chat

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MediumFlexibleTopAppBar
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzConnectedRadioGroup

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun TaskDetailScreen(
    vm: ChatViewModel,
    initialTab: Int = 0,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val ui by vm.ui.collectAsState()
    var selectedTab by rememberSaveable(initialTab) {
        mutableIntStateOf(if (initialTab == 1) 1 else 0)
    }
    val scrollBehavior = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

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
                        text = if (selectedTab == 0) "执行步骤" else "对话文件",
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

    ui.previewTarget?.let { target ->
        FilePreviewDialog(target = target, onDismiss = { vm.closeFilePreview() })
    }
}
