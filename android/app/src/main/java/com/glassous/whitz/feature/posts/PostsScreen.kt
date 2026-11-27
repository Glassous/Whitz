package com.glassous.whitz.feature.posts

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MediumFlexibleTopAppBar
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.glassous.whitz.core.model.PostCommentItem
import com.glassous.whitz.core.model.PostItem
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.model.resolvedAssistantName
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.feature.chat.ChatViewModel
import com.glassous.whitz.feature.chat.MarkdownText
import com.glassous.whitz.ui.theme.AutoAwesome
import com.glassous.whitz.ui.theme.LocalOneHandedConfig
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.OpenInNew
import com.glassous.whitz.ui.theme.RateReview
import com.glassous.whitz.ui.theme.WhitzCollapsibleTopBarLayout
import com.glassous.whitz.ui.theme.WhitzLoadingIndicator
import com.glassous.whitz.ui.theme.WhitzOneHandedActionButton
import com.glassous.whitz.ui.theme.WhitzOneHandedActionDock
import com.glassous.whitz.ui.theme.WhitzOneHandedBackDock
import com.glassous.whitz.ui.theme.WhitzTextField
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun PostsScreen(
    vm: ChatViewModel,
    onOpenCompose: () -> Unit,
    onOpenGuide: () -> Unit,
    onOpenMemorySettings: () -> Unit,
    onOpenConversation: (conversationId: String, prefillPrompt: String) -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val oneHanded = LocalOneHandedConfig.current
    val user by vm.user.collectAsState()
    val ui by vm.posts.ui.collectAsState()

    val isEnabled = user?.aiPostsEnabled == true
    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
    var deleteTarget by remember { mutableStateOf<PostItem?>(null) }

    LaunchedEffect(isEnabled) {
        vm.posts.markRead()
        if (isEnabled) {
            vm.posts.loadFeed(reset = true)
        } else {
            vm.posts.loadQuota()
        }
    }

    LaunchedEffect(ui.feedback, ui.error) {
        if (ui.feedback != null || ui.error != null) {
            delay(3600)
            vm.posts.clearMessages()
        }
    }

    WhitzCollapsibleTopBarLayout(
        title = "动态",
        onBack = onBack,
        actions = {
            IconButton(onClick = onOpenGuide) {
                Icon(Icons.Default.Info, contentDescription = "功能说明", tint = colors.fgMuted)
            }
            if (isEnabled) {
                IconButton(
                    onClick = { vm.posts.loadFeed(reset = true) },
                    enabled = !ui.loading,
                ) {
                    Icon(Icons.Default.Refresh, contentDescription = "刷新", tint = colors.fgMuted)
                }
            }
        },
        overlay = {
            if (isEnabled && !oneHanded.enabled) {
                FloatingActionButton(
                    onClick = onOpenCompose,
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                    shape = CircleShape,
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .navigationBarsPadding()
                        .padding(16.dp),
                ) {
                    Icon(Icons.Default.Add, contentDescription = "发布私人动态")
                }
            }
            WhitzOneHandedActionDock {
                WhitzOneHandedActionButton(onClick = onOpenGuide) {
                    Icon(
                        imageVector = Icons.Default.Info,
                        contentDescription = "功能说明",
                        tint = colors.fgMuted,
                        modifier = Modifier.size(21.dp),
                    )
                }
                if (isEnabled) {
                    WhitzOneHandedActionButton(
                        onClick = { vm.posts.loadFeed(reset = true) },
                        enabled = !ui.loading,
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "刷新",
                            tint = colors.fgMuted,
                            modifier = Modifier.size(21.dp),
                        )
                    }
                    WhitzOneHandedActionButton(
                        onClick = onOpenCompose,
                        emphasized = true,
                    ) {
                        Icon(
                            imageVector = Icons.Default.Add,
                            contentDescription = "发布私人动态",
                            modifier = Modifier.size(22.dp),
                        )
                    }
                }
                WhitzOneHandedActionButton(onClick = onBack) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = colors.fg,
                        modifier = Modifier.size(22.dp),
                    )
                }
            }
        },
    ) { topPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = topPadding),
        ) {
            AnimatedContent(
                targetState = isEnabled,
                transitionSpec = {
                    (fadeIn(tween(260)) + slideInVertically(tween(280)) { it / 20 }) togetherWith
                        fadeOut(tween(160))
                },
                label = "posts_mode_transition",
            ) { enabled ->
                if (!enabled) {
                    PostsOnboardingSection(
                        assistantName = assistantName,
                        enabling = ui.togglingEnable,
                        error = ui.error,
                        onEnable = { vm.posts.setAiPostsEnabled(true) },
                        onOpenGuide = onOpenGuide,
                    )
                } else {
                    PostsFeedSection(
                        user = user,
                        ui = ui,
                        resolveAssetUrl = { vm.resolveAssetUrl(it) },
                        onSelectFilter = { vm.posts.setFilter(it) },
                        onLoadMore = { vm.posts.loadFeed(reset = false) },
                        onOpenMemorySettings = onOpenMemorySettings,
                        onLike = { vm.posts.toggleLike(it) },
                        onBookmark = { vm.posts.toggleBookmark(it) },
                        onRequestDelete = { deleteTarget = it },
                        onAddComment = { postId, text, replyToId, triggerAi ->
                            vm.posts.addComment(postId, text, replyToId, triggerAi)
                        },
                        onDeleteComment = { postId, commentId ->
                            vm.posts.deleteComment(postId, commentId)
                        },
                        onDiscuss = { postId ->
                            vm.posts.discussInChat(postId) { res ->
                                onOpenConversation(res.conversationId, res.prefillPrompt)
                            }
                        },
                    )
                }
            }
        }
    }

    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("删除动态") },
            text = { Text("确定删除这条动态及其所有评论吗？此操作无法撤销。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        vm.posts.deletePost(target.id)
                        deleteTarget = null
                    },
                    colors = ButtonDefaults.textButtonColors(contentColor = colors.danger),
                ) {
                    Text("确认删除")
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) {
                    Text("取消")
                }
            },
        )
    }
}

@Composable
private fun PostsOnboardingSection(
    assistantName: String,
    enabling: Boolean,
    error: String?,
    onEnable: () -> Unit,
    onOpenGuide: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val infiniteTransition = rememberInfiniteTransition(label = "onboarding_pulse")
    val pulse by infiniteTransition.animateFloat(
        initialValue = 0.85f,
        targetValue = 1.1f,
        animationSpec = infiniteRepeatable(
            animation = tween(5500, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulse",
    )
    val glowColor = MaterialTheme.colorScheme.primary.copy(alpha = if (colors.isDark) 0.14f else 0.08f)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 28.dp),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(glowColor, Color.Transparent),
                    center = Offset(size.width * 0.5f, size.height * 0.42f),
                    radius = size.minDimension * 0.48f * pulse,
                ),
                radius = size.minDimension * 0.48f * pulse,
                center = Offset(size.width * 0.5f, size.height * 0.42f),
            )
        }

        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Surface(
                shape = RoundedCornerShape(18.dp),
                color = colors.surface,
                border = BorderStroke(0.8.dp, colors.line),
            ) {
                Box(modifier = Modifier.size(56.dp), contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.AutoAwesome, contentDescription = null, modifier = Modifier.size(26.dp), tint = colors.fg)
                }
            }

            Text(
                text = "私人动态",
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
                color = colors.fg,
            )

            Text(
                text = "$assistantName 根据你的长期记忆，每日联网为你写动态；你也可以随时发帖，严格仅你可见。",
                fontSize = 14.sp,
                lineHeight = 21.sp,
                color = colors.fgMuted,
                textAlign = TextAlign.Center,
            )

            Text(
                text = "默认关闭 · 开启后自动生成与互动会正常消耗账号积分，0 记忆自动跳过，随时可关闭",
                fontSize = 12.sp,
                lineHeight = 18.sp,
                color = colors.fgFaint,
                textAlign = TextAlign.Center,
            )

            if (!error.isNullOrBlank()) {
                Text(text = error, fontSize = 12.5.sp, color = colors.danger, textAlign = TextAlign.Center)
            }

            Spacer(Modifier.height(6.dp))

            Button(
                onClick = onEnable,
                enabled = !enabling,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(46.dp),
                shape = RoundedCornerShape(999.dp),
            ) {
                if (enabling) {
                    WhitzLoadingIndicator(modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("正在开启...", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                } else {
                    Text("开启私人动态", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                }
            }

            OutlinedButton(
                onClick = onOpenGuide,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(44.dp),
                shape = RoundedCornerShape(999.dp),
            ) {
                Icon(Icons.Default.Info, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("功能说明", fontSize = 13.5.sp)
            }
        }
    }
}

@Composable
private fun PostsFeedSection(
    user: User?,
    ui: PostsUiState,
    resolveAssetUrl: (String?) -> String?,
    onSelectFilter: (PostFeedFilter) -> Unit,
    onLoadMore: () -> Unit,
    onOpenMemorySettings: () -> Unit,
    onLike: (String) -> Unit,
    onBookmark: (String) -> Unit,
    onRequestDelete: (PostItem) -> Unit,
    onAddComment: (String, String, String?, Boolean) -> Unit,
    onDeleteComment: (String, String) -> Unit,
    onDiscuss: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    val assistantName = user?.resolvedAssistantName() ?: "Whitz"

    Column(modifier = Modifier.fillMaxSize()) {
        // X-style 4-way Underline Tab Row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(colors.canvas),
        ) {
            PostFeedFilter.entries.forEach { f ->
                val selected = ui.filter == f
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(44.dp)
                        .clickable { onSelectFilter(f) },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = if (f == PostFeedFilter.USER) "我的" else f.label,
                        fontSize = 13.5.sp,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
                        color = if (selected) colors.fg else colors.fgMuted,
                    )
                    if (selected) {
                        Box(
                            modifier = Modifier
                                .align(Alignment.BottomCenter)
                                .width(42.dp)
                                .height(3.dp)
                                .clip(RoundedCornerShape(999.dp))
                                .background(colors.fg),
                        )
                    }
                }
            }
        }
        HorizontalDivider(color = colors.line.copy(alpha = 0.7f))

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = navBottom + 88.dp),
        ) {
            // Compact 0-memory Strip
            if (ui.quota != null && ui.quota.memoryEntryCount == 0) {
                item(key = "zero_mem") {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(colors.surface.copy(alpha = 0.65f))
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "当前长期记忆为 0，$assistantName 今日将发 0 条。",
                            fontSize = 12.5.sp,
                            color = colors.fgMuted,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            text = "添加记忆 →",
                            fontSize = 12.5.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = colors.fg,
                            modifier = Modifier.clickable(onClick = onOpenMemorySettings),
                        )
                    }
                    HorizontalDivider(color = colors.line.copy(alpha = 0.7f))
                }
            }

            if (!ui.feedback.isNullOrBlank() || !ui.error.isNullOrBlank()) {
                item(key = "banner") {
                    val isErr = !ui.error.isNullOrBlank()
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(if (isErr) colors.dangerWeak else colors.successWeak)
                            .padding(horizontal = 16.dp, vertical = 9.dp),
                    ) {
                        Text(
                            text = ui.error ?: ui.feedback.orEmpty(),
                            color = if (isErr) colors.danger else colors.success,
                            fontSize = 12.5.sp,
                        )
                    }
                }
            }

            if (ui.loading && ui.items.isEmpty()) {
                item(key = "loading") {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 56.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        WhitzLoadingIndicator()
                    }
                }
            } else if (ui.items.isEmpty()) {
                item(key = "empty") {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 28.dp, vertical = 56.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        Text("还没有动态", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
                        Text(
                            text = "点击右下角发布你的私人想法，或等待 $assistantName 每日联网为你更新。",
                            fontSize = 13.sp,
                            color = colors.fgMuted,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
            } else {
                items(ui.items, key = { it.id }) { post ->
                    XStylePostItem(
                        post = post,
                        user = user,
                        resolveAssetUrl = resolveAssetUrl,
                        onLike = { onLike(post.id) },
                        onBookmark = { onBookmark(post.id) },
                        onDelete = { onRequestDelete(post) },
                        onDiscuss = { onDiscuss(post.id) },
                        onAddComment = { text, replyToId, triggerAi ->
                            onAddComment(post.id, text, replyToId, triggerAi)
                        },
                        onDeleteComment = { commentId -> onDeleteComment(post.id, commentId) },
                    )
                    HorizontalDivider(color = colors.line.copy(alpha = 0.65f))
                }

                if (!ui.nextCursor.isNullOrBlank()) {
                    item(key = "load_more") {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 16.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            TextButton(onClick = onLoadMore, enabled = !ui.loadingMore) {
                                Text(if (ui.loadingMore) "加载中..." else "加载更多")
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun XStylePostItem(
    post: PostItem,
    user: User?,
    resolveAssetUrl: (String?) -> String?,
    onLike: () -> Unit,
    onBookmark: () -> Unit,
    onDelete: () -> Unit,
    onDiscuss: () -> Unit,
    onAddComment: (String, String?, Boolean) -> Unit,
    onDeleteComment: (String) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val uriHandler = LocalUriHandler.current
    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
    val userName = user?.displayName?.ifBlank { "我" } ?: "我"

    val isAi = post.authorType == "ai"
    val authorName = if (isAi) assistantName else userName
    val authorAvatar = resolveAssetUrl(if (isAi) user?.assistantAvatarUrl else user?.avatarUrl)

    var commentsExpanded by remember(post.id) { mutableStateOf(false) }
    var replyTarget by remember(post.id) { mutableStateOf<PostCommentItem?>(null) }
    var commentText by remember(post.id) { mutableStateOf("") }
    var triggerAiReply by remember(post.id) { mutableStateOf(true) }

    val kindLabel = when (post.postKind) {
        "opinion" -> "观点"
        "digest" -> "资讯"
        "insight" -> "观察"
        "inspiration" -> "灵感"
        else -> "动态"
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        // Left Avatar Column
        if (!authorAvatar.isNullOrBlank()) {
            AsyncImage(
                model = authorAvatar,
                contentDescription = authorName,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(colors.surface),
            )
        } else {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(if (isAi) MaterialTheme.colorScheme.primary else colors.surface),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = authorName.take(1).uppercase(),
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Bold,
                    color = if (isAi) MaterialTheme.colorScheme.onPrimary else colors.fg,
                )
            }
        }

        // Right Content Column
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            // Single-line compact header
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Row(
                    modifier = Modifier.weight(1f),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    Text(
                        text = authorName,
                        fontSize = 14.5.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = colors.fg,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (isAi) {
                        Surface(shape = RoundedCornerShape(4.dp), color = colors.surface) {
                            Text(
                                text = kindLabel,
                                fontSize = 10.5.sp,
                                fontWeight = FontWeight.Medium,
                                color = colors.fgMuted,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp),
                            )
                        }
                    }
                    val metaSuffix = buildString {
                        if (!post.sourceCollectionName.isNullOrBlank()) append("· ${post.sourceCollectionName} ")
                        else if (!isAi && post.memoryEntryId != null) append("· 已入记忆 ")
                        append("· ${DateTimeUtils.formatShort(post.createdAt)}")
                    }
                    Text(
                        text = metaSuffix,
                        fontSize = 12.sp,
                        color = colors.fgFaint,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                IconButton(onClick = onDelete, modifier = Modifier.size(26.dp)) {
                    Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(15.dp), tint = colors.fgFaint)
                }
            }

            if (post.title.isNotBlank()) {
                Text(
                    text = post.title,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                    lineHeight = 21.sp,
                    color = colors.fg,
                )
            }

            MarkdownText(markdown = post.content)

            if (post.tags.isNotEmpty()) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    post.tags.forEach { tag ->
                        Text("#$tag", fontSize = 12.5.sp, color = colors.fgFaint)
                    }
                }
            }

            // Compact X-style link preview cards
            if (post.webSources.isNotEmpty()) {
                Surface(
                    shape = RoundedCornerShape(14.dp),
                    color = colors.surface.copy(alpha = 0.45f),
                    border = BorderStroke(0.7.dp, colors.line),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column {
                        post.webSources.take(3).forEachIndexed { idx, src ->
                            if (idx > 0) HorizontalDivider(color = colors.line.copy(alpha = 0.6f))
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        if (src.url.startsWith("http://") || src.url.startsWith("https://")) {
                                            runCatching { uriHandler.openUri(src.url) }
                                        }
                                    }
                                    .padding(horizontal = 11.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = src.title.ifBlank { src.url },
                                        fontSize = 12.5.sp,
                                        fontWeight = FontWeight.Medium,
                                        color = colors.fg,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    if (src.siteName.isNotBlank()) {
                                        Text(src.siteName, fontSize = 11.sp, color = colors.fgFaint)
                                    }
                                }
                                Spacer(Modifier.width(8.dp))
                                Icon(Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null, modifier = Modifier.size(13.dp), tint = colors.fgFaint)
                            }
                        }
                    }
                }
            }

            if (post.aiLiked) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Icon(Icons.Default.Favorite, contentDescription = null, modifier = Modifier.size(12.dp), tint = colors.danger)
                    Text("$assistantName 赞了", fontSize = 11.5.sp, color = colors.fgFaint)
                }
            }

            // X-style evenly spaced action row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 2.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                XActionIcon(
                    icon = Icons.Filled.RateReview,
                    label = if (post.commentCount > 0) "${post.commentCount}" else "",
                    tint = if (commentsExpanded) colors.fg else colors.fgFaint,
                    onClick = { commentsExpanded = !commentsExpanded },
                )
                XActionIcon(
                    icon = if (post.isLiked) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                    label = if (post.isLiked) "已赞" else "",
                    tint = if (post.isLiked) colors.danger else colors.fgFaint,
                    onClick = onLike,
                )
                XActionIcon(
                    icon = Icons.Default.Star,
                    label = "",
                    tint = if (post.isBookmarked) colors.warning else colors.fgFaint,
                    onClick = onBookmark,
                )
                Text(
                    text = "聊聊",
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    color = colors.fgMuted,
                    modifier = Modifier
                        .clip(RoundedCornerShape(999.dp))
                        .clickable(onClick = onDiscuss)
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }

            // Threaded comments
            AnimatedVisibility(
                visible = commentsExpanded,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut(),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    post.comments.forEach { comment ->
                        val cAuthor = if (comment.authorType == "ai") assistantName else userName
                        val replyToName = when (comment.replyToAuthorType) {
                            "ai" -> assistantName
                            "user" -> userName
                            else -> null
                        }
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(start = 8.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(5.dp),
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text(cAuthor, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
                                    if (replyToName != null) {
                                        Text("回复 $replyToName", fontSize = 11.sp, color = colors.fgFaint)
                                    }
                                    Text("· ${DateTimeUtils.formatShort(comment.createdAt)}", fontSize = 11.sp, color = colors.fgFaint)
                                }
                                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    Text("回复", fontSize = 11.5.sp, color = colors.fgMuted, modifier = Modifier.clickable { replyTarget = comment })
                                    Text("删除", fontSize = 11.5.sp, color = colors.fgFaint, modifier = Modifier.clickable { onDeleteComment(comment.id) })
                                }
                            }
                            if (!comment.replyToExcerpt.isNullOrBlank()) {
                                Text(
                                    text = "引用：${comment.replyToExcerpt}",
                                    fontSize = 11.sp,
                                    color = colors.fgFaint,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            Text(comment.content, fontSize = 13.sp, lineHeight = 19.sp, color = colors.fg)
                            if (comment.aiLiked) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                                    Icon(Icons.Default.Favorite, contentDescription = null, modifier = Modifier.size(11.dp), tint = colors.danger)
                                    Text("$assistantName 赞了", fontSize = 11.sp, color = colors.fgFaint)
                                }
                            }
                        }
                    }

                    replyTarget?.let { target ->
                        val targetName = if (target.authorType == "ai") assistantName else userName
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .background(colors.surface)
                                .padding(horizontal = 10.dp, vertical = 5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(
                                text = "回复 $targetName：${target.content}",
                                fontSize = 11.5.sp,
                                color = colors.fgMuted,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(onClick = { replyTarget = null }, modifier = Modifier.size(20.dp)) {
                                Icon(Icons.Default.Close, contentDescription = "取消", modifier = Modifier.size(13.dp), tint = colors.fgFaint)
                            }
                        }
                    }

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        WhitzTextField(
                            value = commentText,
                            onValueChange = { commentText = it },
                            placeholder = if (replyTarget != null) "输入回复..." else "发布回复...",
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        IconButton(
                            onClick = {
                                val cleaned = commentText.trim()
                                if (cleaned.isNotEmpty()) {
                                    onAddComment(cleaned, replyTarget?.id, triggerAiReply)
                                    commentText = ""
                                    replyTarget = null
                                }
                            },
                            enabled = commentText.trim().isNotEmpty(),
                        ) {
                            Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "发送")
                        }
                    }

                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.clickable { triggerAiReply = !triggerAiReply },
                    ) {
                        Checkbox(checked = triggerAiReply, onCheckedChange = { triggerAiReply = it })
                        Text("邀请 $assistantName 稍后回复", fontSize = 11.5.sp, color = colors.fgFaint)
                    }
                }
            }
        }
    }
}

@Composable
private fun XActionIcon(
    icon: ImageVector,
    label: String,
    tint: Color,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 6.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(17.dp), tint = tint)
        if (label.isNotEmpty()) {
            Text(label, fontSize = 12.sp, color = tint)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun PostsGuideScreen(
    vm: ChatViewModel,
    onOpenMemorySettings: () -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val ui by vm.posts.ui.collectAsState()
    val isEnabled = user?.aiPostsEnabled == true
    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    LaunchedEffect(Unit) {
        vm.posts.loadQuota()
    }

    WhitzCollapsibleTopBarLayout(
        title = "私人动态说明",
        onBack = onBack,
        overlay = { WhitzOneHandedBackDock(onBack = onBack) },
    ) { topPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = topPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .padding(bottom = navBottom + 24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            // Live Status & Toggle Card
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = colors.surface,
                border = BorderStroke(0.6.dp, colors.line),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                            Text(
                                text = if (isEnabled) "功能已开启 · ${ui.quota?.tierLabel ?: "Free"}" else "功能未开启 · ${ui.quota?.tierLabel ?: "Free"}",
                                fontSize = 15.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = colors.fg,
                            )
                            Text(
                                text = "已启用记忆 ${ui.quota?.memoryEntryCount ?: 0} 条（${ui.quota?.activeCollectionCount ?: 0} 分类）· 预计每日 ${ui.quota?.estimatedDailyCount ?: 0}/${ui.quota?.maxDailyCap ?: 2} 条",
                                fontSize = 12.5.sp,
                                color = colors.fgMuted,
                            )
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { vm.posts.setAiPostsEnabled(!isEnabled) },
                            enabled = !ui.togglingEnable,
                            shape = RoundedCornerShape(999.dp),
                        ) {
                            Text(if (isEnabled) "关闭功能" else "开启私人动态", fontSize = 13.sp)
                        }
                        OutlinedButton(
                            onClick = onOpenMemorySettings,
                            shape = RoundedCornerShape(999.dp),
                        ) {
                            Text("管理记忆", fontSize = 13.sp)
                        }
                    }
                }
            }

            // Mechanism Card
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = colors.canvas,
                border = BorderStroke(0.8.dp, colors.line),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("核心机制", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
                    Text(
                        text = "• 严格仅你可见：AI 与用户发的动态和评论均按账号隔离。\n• 记忆驱动 + 联网搜索：$assistantName 每日结合长期记忆、近期动态与评论互动，主动联网搜集最新资讯，发表观点、资讯速递或深度观察。\n• 发帖入记忆 & 延迟互动：你的发帖自动沉淀进长期记忆，发帖或回复评论后助手会间隔一段时间再来点赞和回复。",
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = colors.fgMuted,
                    )
                }
            }

            // Quota Rules Card
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = colors.canvas,
                border = BorderStroke(0.8.dp, colors.line),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("每日发帖数量规则", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
                    Text(
                        text = "有效长期记忆为 0 条时固定发 0 条；记忆分类越多、记忆越丰富、会员档位越高，每日可发条数越多：\n• Free：最多 2 条 / 天\n• Plus：最多 5 条 / 天\n• Pro：最多 8 条 / 天",
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = colors.fgMuted,
                    )
                }
            }

            // Credit Notice Card
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = colors.warningWeak.copy(alpha = if (colors.isDark) 0.55f else 0.72f),
                border = BorderStroke(0.8.dp, colors.warning.copy(alpha = 0.4f)),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("积分额度消耗说明", fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold, color = colors.fg)
                    Text(
                        text = "本功能默认关闭。开启后，每日后台联网发帖与延迟点赞/评论回复所产生的模型调用均正常计入你的账号积分消耗；记忆为 0 或额度耗尽时自动跳过不扣费，随时可关闭。",
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = colors.fgMuted,
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PostComposerSheet(
    assistantName: String,
    publishing: Boolean,
    onDismiss: () -> Unit,
    onPublish: (title: String, content: String, tags: List<String>) -> Unit,
) {
    val colors = LocalWhitzColors.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var title by remember { mutableStateOf("") }
    var content by remember { mutableStateOf("") }
    var tagsRaw by remember { mutableStateOf("") }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = colors.canvas,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .imePadding()
                .padding(horizontal = 20.dp)
                .padding(bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("发布私人动态", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = colors.fg)
            Text(
                text = "仅自己可见 · 自动同步至长期记忆 · $assistantName 稍后会来互动",
                fontSize = 12.sp,
                color = colors.fgFaint,
            )
            WhitzTextField(
                value = title,
                onValueChange = { if (it.length <= 120) title = it },
                placeholder = "标题（可选）",
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            WhitzTextField(
                value = content,
                onValueChange = { if (it.length <= 4000) content = it },
                placeholder = "有什么新鲜事或想追踪的话题？",
                singleLine = false,
                maxLines = 8,
                modifier = Modifier.fillMaxWidth(),
            )
            WhitzTextField(
                value = tagsRaw,
                onValueChange = { if (it.length <= 120) tagsRaw = it },
                placeholder = "#标签（空格分隔，可选）",
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = {
                    val tags = tagsRaw
                        .split(Regex("[,，\\s#]+"))
                        .map { it.trim() }
                        .filter { it.isNotEmpty() }
                        .take(6)
                    onPublish(title, content, tags)
                },
                enabled = content.trim().isNotEmpty() && !publishing,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                shape = RoundedCornerShape(999.dp),
            ) {
                Text(if (publishing) "发布中..." else "发布", fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}
