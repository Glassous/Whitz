package com.glassous.whitz.feature.chat

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.model.resolvedAssistantName
import com.glassous.whitz.ui.theme.LocalWhitzColors
import com.glassous.whitz.ui.theme.WhitzLogoMark
import com.glassous.whitz.ui.theme.WhitzTextField

@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
fun AssistantProfileDialog(
    user: User?,
    resolveAssetUrl: (String?) -> String?,
    saving: Boolean,
    error: String?,
    feedback: String?,
    onPickAvatar: (Uri) -> Unit,
    onResetAvatar: () -> Unit,
    onSaveName: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = LocalWhitzColors.current
    val currentName = user?.resolvedAssistantName() ?: "Whitz"
    val avatarUrl = resolveAssetUrl(user?.assistantAvatarUrl)
    var nameDraft by remember(user?.assistantName) { mutableStateOf(currentName) }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) onPickAvatar(uri)
    }

    AlertDialog(
        onDismissRequest = { if (!saving) onDismiss() },
        containerColor = colors.canvas,
        title = { Text("自定义助手形象", fontWeight = FontWeight.SemiBold, color = colors.fg) },
        text = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(58.dp)
                            .clip(RoundedCornerShape(16.dp))
                            .background(colors.surface)
                            .border(1.dp, colors.line, RoundedCornerShape(16.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (!avatarUrl.isNullOrBlank()) {
                            AsyncImage(
                                model = avatarUrl,
                                contentDescription = currentName,
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize(),
                            )
                        } else {
                            WhitzLogoMark(modifier = Modifier.size(28.dp))
                        }
                    }

                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("助手头像", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = colors.fg)
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            OutlinedButton(
                                onClick = { picker.launch("image/*") },
                                enabled = !saving,
                                shapes = ButtonDefaults.shapesFor(34.dp),
                                modifier = Modifier.height(34.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp),
                            ) {
                                Text("更换头像", fontSize = 12.5.sp)
                            }
                            if (!user?.assistantAvatarUrl.isNullOrBlank()) {
                                TextButton(
                                    onClick = onResetAvatar,
                                    enabled = !saving,
                                    modifier = Modifier.height(34.dp),
                                    contentPadding = PaddingValues(horizontal = 10.dp),
                                ) {
                                    Text("恢复默认", fontSize = 12.5.sp, color = colors.fgMuted)
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
                    fontSize = 11.5.sp,
                    color = colors.fgFaint,
                )

                if (!error.isNullOrBlank()) {
                    Text(error, fontSize = 12.5.sp, color = colors.danger)
                } else if (!feedback.isNullOrBlank()) {
                    Text(feedback, fontSize = 12.5.sp, color = colors.success)
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !saving) { Text("取消") }
        },
        confirmButton = {
            Button(
                onClick = { onSaveName(nameDraft.trim().ifEmpty { "Whitz" }) },
                enabled = !saving,
                shapes = ButtonDefaults.shapesFor(36.dp),
            ) {
                Text(if (saving) "保存中…" else "保存")
            }
        },
    )
}
