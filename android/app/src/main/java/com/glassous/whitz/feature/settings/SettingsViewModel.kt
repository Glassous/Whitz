package com.glassous.whitz.feature.settings

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glassous.whitz.AppContainer
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.CreditStatus
import com.glassous.whitz.core.model.GithubSkillPreviewResponse
import com.glassous.whitz.core.model.MemoryOverview
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.core.model.ThemePreference
import com.glassous.whitz.core.model.UserSessionItem
import com.glassous.whitz.core.network.AvatarUploadRequest
import com.glassous.whitz.core.network.CreateSkillRequest
import com.glassous.whitz.core.network.GithubInstallRequest
import com.glassous.whitz.core.network.GithubPreviewRequest
import com.glassous.whitz.core.network.LibraryFilePatchRequest
import com.glassous.whitz.core.network.MemoryEntryRequest
import com.glassous.whitz.core.network.MemorySettingsRequest
import com.glassous.whitz.core.network.PendingActionRequest
import com.glassous.whitz.core.network.ProfileContextRequest
import com.glassous.whitz.core.network.RedeemRequest
import com.glassous.whitz.core.network.SkillPatchRequest
import com.glassous.whitz.core.network.UpdatePasswordRequest
import com.glassous.whitz.core.network.UpdatePersonaRequest
import com.glassous.whitz.core.network.UpdateProfileRequest
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.core.network.extractErrorMessage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import java.io.ByteArrayOutputStream

data class SettingsUiState(
    val loading: Boolean = false,
    val message: String? = null,
    val error: String? = null,
    // Credits
    val credits: CreditStatus? = null,
    // Memory
    val memory: MemoryOverview? = null,
    // Skills
    val skills: List<SkillItem> = emptyList(),
    val pendingSkills: List<SkillPendingItem> = emptyList(),
    val githubPreview: GithubSkillPreviewResponse? = null,
    // Library
    val libraryFiles: List<ConversationFile> = emptyList(),
    // Sessions
    val sessions: List<UserSessionItem> = emptyList(),
)

class SettingsViewModel(
    private val container: AppContainer,
) : ViewModel() {
    private val _ui = MutableStateFlow(SettingsUiState())
    val ui: StateFlow<SettingsUiState> = _ui.asStateFlow()

    val user = container.authManager.user
    val themePreference = container.themePreference

    fun setTheme(pref: ThemePreference) {
        container.setThemePreference(pref)
    }

    fun clearFeedback() {
        _ui.update { it.copy(message = null, error = null) }
    }

    fun refreshAll() {
        viewModelScope.launch {
            try {
                val me = container.network.api.getMe()
                container.authManager.updateUser(me)
            } catch (_: Throwable) {
            }
        }
        loadCredits()
    }

    fun updateProfile(
        displayName: String,
        bio: String,
        gender: String?,
        birthday: String?,
        phone: String?,
        location: String?,
        occupation: String?,
        website: String?,
        preferredLanguage: String,
        timezone: String,
    ) {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                val updated = container.network.api.updateMe(
                    UpdateProfileRequest(
                        displayName = displayName.trim(),
                        bio = bio.trim(),
                        gender = gender?.trim()?.ifBlank { null },
                        birthday = birthday?.trim()?.ifBlank { null },
                        phone = phone?.trim()?.ifBlank { null },
                        location = location?.trim()?.ifBlank { null },
                        occupation = occupation?.trim()?.ifBlank { null },
                        website = website?.trim()?.ifBlank { null },
                        preferredLanguage = preferredLanguage.ifBlank { "zh-CN" },
                        timezone = timezone.ifBlank { "Asia/Shanghai" },
                    )
                )
                container.authManager.updateUser(updated)
                _ui.update { it.copy(loading = false, message = "个人资料已保存") }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "保存失败")) }
            }
        }
    }

    fun toggleProfileContext(enabled: Boolean) {
        viewModelScope.launch {
            try {
                val updated = container.network.api.updateProfileContext(
                    ProfileContextRequest(enabled = enabled, consent = enabled)
                )
                container.authManager.updateUser(updated)
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "更新设置失败")) }
            }
        }
    }

    fun uploadAvatar(uri: Uri) {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                val dataUrl = withContext(Dispatchers.IO) {
                    val stream = container.appContext.contentResolver.openInputStream(uri)
                        ?: throw IllegalStateException("无法读取图片")
                    val orig = stream.use { BitmapFactory.decodeStream(it) }
                        ?: throw IllegalStateException("无效的图片格式")
                    val maxDim = 512
                    val scale = minOf(maxDim.toFloat() / orig.width, maxDim.toFloat() / orig.height, 1f)
                    val w = (orig.width * scale).toInt().coerceAtLeast(1)
                    val h = (orig.height * scale).toInt().coerceAtLeast(1)
                    val scaled = if (w != orig.width || h != orig.height) {
                        Bitmap.createScaledBitmap(orig, w, h, true)
                    } else orig
                    val out = ByteArrayOutputStream()
                    scaled.compress(Bitmap.CompressFormat.JPEG, 88, out)
                    "data:image/jpeg;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
                }
                val updated = container.network.api.uploadAvatar(AvatarUploadRequest(dataUrl))
                container.authManager.updateUser(updated)
                _ui.update { it.copy(loading = false, message = "头像已更新") }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "头像上传失败")) }
            }
        }
    }

    fun deleteAvatar() {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                val updated = container.network.api.deleteAvatar()
                container.authManager.updateUser(updated)
                _ui.update { it.copy(loading = false, message = "已移除头像") }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "移除头像失败")) }
            }
        }
    }

    fun updatePassword(current: String, next: String) {
        if (current.isBlank() || next.length < 8) {
            _ui.update { it.copy(error = "请输入当前密码，且新密码至少 8 位") }
            return
        }
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                val resp = container.network.api.updatePassword(UpdatePasswordRequest(current, next))
                if (!resp.isSuccessful) {
                    throw com.glassous.whitz.core.network.ApiException(resp.code(), resp.errorBody()?.string() ?: "修改失败")
                }
                _ui.update { it.copy(loading = false, message = "密码已更新") }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "密码修改失败")) }
            }
        }
    }

    fun updatePersona(persona: String) {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                val updated = container.network.api.updatePersona(UpdatePersonaRequest(persona))
                container.authManager.updateUser(updated)
                _ui.update { it.copy(loading = false, message = "人格设定已保存") }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "保存人格设定失败")) }
            }
        }
    }

    // --- Credits ---
    fun loadCredits() {
        viewModelScope.launch {
            try {
                val c = container.network.api.getCredits()
                _ui.update { it.copy(credits = c) }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "积分加载失败")) }
            }
        }
    }

    fun redeemCode(code: String) {
        val trimmed = code.trim()
        if (trimmed.isEmpty()) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                val next = container.network.api.redeemCode(RedeemRequest(trimmed))
                _ui.update { it.copy(loading = false, credits = next, message = "兑换成功") }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "兑换失败")) }
            }
        }
    }

    // --- Memory ---
    fun loadMemory() {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true) }
            try {
                val m = container.network.api.getMemory()
                _ui.update { it.copy(loading = false, memory = m) }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "加载记忆失败")) }
            }
        }
    }

    fun updateMemorySettings(enabled: Boolean? = null, requireConfirm: Boolean? = null) {
        viewModelScope.launch {
            try {
                val m = container.network.api.updateMemorySettings(
                    MemorySettingsRequest(
                        enabled = enabled,
                        requireConfirm = requireConfirm,
                        consent = enabled == true,
                    )
                )
                _ui.update { it.copy(memory = m) }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "更新记忆设置失败")) }
            }
        }
    }

    fun addMemoryEntry(
        content: String,
        target: String = "memory",
        onSuccess: () -> Unit = {},
    ) {
        if (content.isBlank()) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                container.network.api.createMemoryEntry(MemoryEntryRequest(content.trim(), target = target))
                _ui.update { it.copy(loading = false, message = "已添加记忆") }
                loadMemory()
                onSuccess()
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "添加记忆失败")) }
            }
        }
    }

    fun updateMemoryEntry(id: String, content: String) {
        if (content.isBlank()) return
        viewModelScope.launch {
            try {
                container.network.api.updateMemoryEntry(id, MemoryEntryRequest(content.trim()))
                loadMemory()
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "更新记忆失败")) }
            }
        }
    }

    fun deleteMemoryEntry(id: String) {
        viewModelScope.launch {
            try {
                container.network.api.deleteMemoryEntry(id)
                loadMemory()
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "删除记忆失败")) }
            }
        }
    }

    fun resolveMemoryPending(id: String, action: String) {
        viewModelScope.launch {
            try {
                container.network.api.resolveMemoryPending(id, PendingActionRequest(action))
                loadMemory()
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "处理待确认记忆失败")) }
            }
        }
    }

    fun clearAllMemory() {
        viewModelScope.launch {
            try {
                container.network.api.clearMemory()
                loadMemory()
                _ui.update { it.copy(message = "已清空全部记忆") }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "清空记忆失败")) }
            }
        }
    }

    // --- Skills ---
    fun loadSkills() {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true) }
            try {
                val list = container.network.api.getSkills()
                val pending = container.network.api.getPendingSkills()
                _ui.update { it.copy(loading = false, skills = list, pendingSkills = pending) }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "加载技能失败")) }
            }
        }
    }

    fun toggleSkill(name: String, enabled: Boolean) {
        viewModelScope.launch {
            try {
                container.network.api.patchSkill(name, SkillPatchRequest(enabled))
                loadSkills()
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "切换技能失败")) }
            }
        }
    }

    fun createSkill(
        name: String,
        description: String,
        content: String,
        onSuccess: () -> Unit = {},
    ) {
        if (name.isBlank() || content.isBlank()) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                container.network.api.createSkill(CreateSkillRequest(name.trim(), description.trim(), content = content))
                _ui.update { it.copy(loading = false, message = "技能已创建") }
                loadSkills()
                onSuccess()
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "创建技能失败")) }
            }
        }
    }

    fun deleteSkill(name: String) {
        viewModelScope.launch {
            try {
                container.network.api.deleteSkill(name)
                loadSkills()
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "删除技能失败")) }
            }
        }
    }

    fun resolveSkillPending(id: String, action: String) {
        viewModelScope.launch {
            try {
                container.network.api.resolveSkillPending(id, PendingActionRequest(action))
                loadSkills()
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "处理待确认技能失败")) }
            }
        }
    }

    fun clearGithubPreview() {
        _ui.update { it.copy(githubPreview = null) }
    }

    fun previewGithubSkill(repoUrl: String, ref: String? = null, path: String? = null) {
        val url = repoUrl.trim()
        if (url.isBlank()) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, error = null, githubPreview = null) }
            try {
                val res = container.network.api.previewGithubSkill(
                    GithubPreviewRequest(
                        url = url,
                        ref = ref?.trim()?.ifBlank { null },
                        path = path?.trim()?.ifBlank { null },
                    )
                )
                _ui.update { it.copy(loading = false, githubPreview = res) }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "解析 GitHub 仓库失败")) }
            }
        }
    }

    fun installGithubSkill(
        repoUrl: String,
        name: String? = null,
        ref: String? = null,
        path: String? = null,
        onSuccess: () -> Unit = {},
    ) {
        val url = repoUrl.trim()
        if (url.isBlank()) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, error = null) }
            try {
                container.network.api.installGithubSkill(
                    GithubInstallRequest(
                        url = url,
                        name = name?.trim()?.ifBlank { null },
                        ref = ref?.trim()?.ifBlank { null },
                        path = path?.trim()?.ifBlank { null },
                        enabled = true,
                    )
                )
                _ui.update { it.copy(loading = false, githubPreview = null, message = "GitHub 技能安装成功") }
                loadSkills()
                onSuccess()
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "安装技能失败")) }
            }
        }
    }

    // --- Library ---
    fun loadLibrary(query: String = "", globalOnly: Boolean? = null) {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true) }
            try {
                val res = container.network.api.getLibraryFiles(
                    q = query.trim().ifBlank { null },
                    isGlobal = globalOnly,
                )
                val arr = when (res) {
                    is JsonArray -> res
                    is JsonObject -> res["items"] as? JsonArray
                    else -> null
                }
                val items = arr?.mapNotNull {
                    try {
                        WhitzJson.decodeFromJsonElement(ConversationFile.serializer(), it)
                    } catch (_: Exception) {
                        null
                    }
                } ?: emptyList()
                _ui.update { it.copy(loading = false, libraryFiles = items) }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "加载文件库失败")) }
            }
        }
    }

    fun toggleLibraryGlobal(fileId: String, isGlobal: Boolean) {
        viewModelScope.launch {
            try {
                val updated = container.network.api.patchLibraryFile(fileId, LibraryFilePatchRequest(isGlobal))
                _ui.update { state ->
                    state.copy(libraryFiles = state.libraryFiles.map { if (it.id == fileId) updated else it })
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "更新文件共享状态失败")) }
            }
        }
    }

    fun deleteLibraryFile(fileId: String) {
        viewModelScope.launch {
            try {
                container.network.api.deleteLibraryFile(fileId)
                _ui.update { state -> state.copy(libraryFiles = state.libraryFiles.filterNot { it.id == fileId }) }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "删除文件失败")) }
            }
        }
    }

    // --- Devices / Sessions ---
    fun loadSessions() {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true) }
            try {
                val list = container.network.api.getSessions()
                _ui.update { it.copy(loading = false, sessions = list) }
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "加载设备列表失败")) }
            }
        }
    }

    fun deleteSession(id: String) {
        viewModelScope.launch {
            try {
                container.network.api.deleteSession(id)
                loadSessions()
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "下线设备失败")) }
            }
        }
    }

    fun deleteOtherSessions() {
        viewModelScope.launch {
            try {
                container.network.api.deleteOtherSessions()
                loadSessions()
                _ui.update { it.copy(message = "已下线全部其他设备") }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "操作失败")) }
            }
        }
    }

    fun logout(onDone: () -> Unit) {
        viewModelScope.launch {
            container.authManager.revokeSession()
            onDone()
        }
    }
}
