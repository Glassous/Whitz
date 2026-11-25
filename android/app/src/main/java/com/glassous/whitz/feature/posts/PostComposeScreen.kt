package com.glassous.whitz.feature.posts

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.glassous.whitz.core.model.resolvedAssistantName
import com.glassous.whitz.feature.chat.ChatViewModel
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzTextField

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PostComposeScreen(
    vm: ChatViewModel,
    onPublished: () -> Unit,
    onBack: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val user by vm.user.collectAsState()
    val ui by vm.posts.ui.collectAsState()
    val assistantName = user?.resolvedAssistantName() ?: "Whitz"
    val navBottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()

    var title by remember { mutableStateOf("") }
    var content by remember { mutableStateOf("") }
    var tagsRaw by remember { mutableStateOf("") }
    val canPublish = content.trim().isNotEmpty() && !ui.publishing

    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .imePadding(),
        containerColor = colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text("发布私人动态", fontWeight = FontWeight.SemiBold, fontSize = 17.sp) },
                navigationIcon = {
                    IconButton(onClick = onBack, enabled = !ui.publishing) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    Button(
                        onClick = {
                            val tags = tagsRaw
                                .split(Regex("[,，\\s#]+"))
                                .map { it.trim() }
                                .filter { it.isNotEmpty() }
                                .take(6)
                            vm.posts.createUserPost(title, content, tags) {
                                onPublished()
                            }
                        },
                        enabled = canPublish,
                        shape = RoundedCornerShape(999.dp),
                        contentPadding = PaddingValues(horizontal = 18.dp, vertical = 0.dp),
                        modifier = Modifier
                            .padding(end = 10.dp)
                            .height(36.dp),
                    ) {
                        Text(if (ui.publishing) "发布中..." else "发布", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = colors.canvas,
                    titleContentColor = colors.fg,
                    navigationIconContentColor = colors.fg,
                ),
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .padding(bottom = navBottom + 24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            if (!ui.error.isNullOrBlank()) {
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = colors.dangerWeak,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        text = ui.error.orEmpty(),
                        color = colors.danger,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(12.dp),
                    )
                }
            }

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
                placeholder = "写下此刻的想法、灵感、近期计划，或想追踪的话题（支持 Markdown）……",
                singleLine = false,
                maxLines = 16,
                modifier = Modifier.fillMaxWidth(),
            )

            WhitzTextField(
                value = tagsRaw,
                onValueChange = { if (it.length <= 120) tagsRaw = it },
                placeholder = "#标签（空格或逗号分隔，最多 6 个，可选）",
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "仅自己可见 · 自动同步记忆 · $assistantName 稍后会来互动",
                    fontSize = 12.sp,
                    color = colors.fgFaint,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "${content.length}/4000",
                    fontSize = 12.sp,
                    color = colors.fgFaint,
                )
            }
        }
    }
}
