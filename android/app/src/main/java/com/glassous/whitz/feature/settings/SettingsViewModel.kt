package com.glassous.whitz.feature.settings

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glassous.whitz.AppContainer
import com.glassous.whitz.core.files.AvatarEncoder
import com.glassous.whitz.core.files.LibraryController
import com.glassous.whitz.core.model.CreditStatus
import com.glassous.whitz.core.model.GithubSkillPreviewResponse
import com.glassous.whitz.core.model.MemoryEntry
import com.glassous.whitz.core.model.MemoryOverview
import com.glassous.whitz.core.model.MemorySearchHit
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.core.model.ThemePreference
import com.glassous.whitz.core.model.UserFeedbackItem
import com.glassous.whitz.core.model.UserSessionItem
import com.glassous.whitz.core.network.AvatarUploadRequest
import com.glassous.whitz.core.network.CreateSkillRequest
import com.glassous.whitz.core.network.GithubInstallRequest
import com.glassous.whitz.core.network.GithubPreviewRequest
import com.glassous.whitz.core.network.MemoryCollectionCreateRequest
import com.glassous.whitz.core.network.MemoryCollectionUpdateRequest
import com.glassous.whitz.core.network.MemoryEntryPatchRequest
import com.glassous.whitz.core.network.MemoryEntryRequest
import com.glassous.whitz.core.network.MemorySearchRequest
import com.glassous.whitz.core.network.MemorySettingsRequest
import com.glassous.whitz.core.network.PendingActionRequest
import com.glassous.whitz.core.network.ProfileContextRequest
import com.glassous.whitz.core.network.RedeemRequest
import com.glassous.whitz.core.network.SkillPatchRequest
import com.glassous.whitz.core.network.UpdateAiPostsRequest
import com.glassous.whitz.core.network.UpdateAiReactionsRequest
import com.glassous.whitz.core.network.UpdateAssistantRequest
import com.glassous.whitz.core.network.UpdatePasswordRequest
import com.glassous.whitz.core.network.UpdatePersonaRequest
import com.glassous.whitz.core.network.UpdateProfileRequest
import com.glassous.whitz.core.network.UserFeedbackCreateRequest
import com.glassous.whitz.core.network.extractErrorMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val loading: Boolean = false,
    val message: String? = null,
    val error: String? = null,
    // Assistant Profile modal
    val assistantSaving: Boolean = false,
    val assistantFeedback: String? = null,
    val assistantError: String? = null,
    // Credits
    val credits: CreditStatus? = null,
    // Memory
    val memory: MemoryOverview? = null,
    val selectedMemoryCollection: String? = null,
    val memorySearchResults: List<MemorySearchHit>? = null,
    val memorySearching: Boolean = false,
    val pinningMemoryId: String? = null,
    // Skills
    val skills: List<SkillItem> = emptyList(),
    val pendingSkills: List<SkillPendingItem> = emptyList(),
    val githubPreview: GithubSkillPreviewResponse? = null,
    // Sessions
    val sessions: List<UserSessionItem> = emptyList(),
    // Feedback
    val feedbacks: List<UserFeedbackItem> = emptyList(),
    val feedbackSubmitting: Boolean = false,
    val aiReactionSaving: Boolean = false,
    val aiPostsSaving: Boolean = false,
)

class SettingsViewModel(
    private val container: AppContainer,
) : ViewModel() {
    private val _ui = MutableStateFlow(SettingsUiState())
    val ui: StateFlow<SettingsUiState> = _ui.asStateFlow()

    val user = container.authManager.user
    val themePreference = container.themePreference
    val library = LibraryController(viewModelScope, container)

    fun resolveAssetUrl(pathOrUrl: String?): String? = container.resolveAssetUrl(pathOrUrl)

    fun setTheme(pref: ThemePreference) {
        container.setThemePreference(pref)
    }

    fun clearFeedback() {
        _ui.update { it.copy(message = null, error = null) }
    }

    fun clearAssistantDialogFeedback() {
        _ui.update { it.copy(assistantFeedback = null, assistantError = null) }
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
                val dataUrl = AvatarEncoder.encodeToDataUrl(container.appContext.contentResolver, uri)
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

    fun uploadAssistantAvatar(uri: Uri) {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, assistantSaving = true, message = null, error = null, assistantFeedback = null, assistantError = null) }
            try {
                val dataUrl = AvatarEncoder.encodeToDataUrl(container.appContext.contentResolver, uri)
                val updated = container.network.api.uploadAssistantAvatar(AvatarUploadRequest(dataUrl))
                container.authManager.updateUser(updated)
                _ui.update { it.copy(loading = false, assistantSaving = false, message = "助手头像已更新", assistantFeedback = "助手头像已更新") }
            } catch (t: Throwable) {
                val err = extractErrorMessage(t, "助手头像上传失败")
                _ui.update { it.copy(loading = false, assistantSaving = false, error = err, assistantError = err) }
            }
        }
    }

    fun deleteAssistantAvatar() {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, assistantSaving = true, message = null, error = null, assistantFeedback = null, assistantError = null) }
            try {
                val updated = container.network.api.deleteAssistantAvatar()
                container.authManager.updateUser(updated)
                _ui.update { it.copy(loading = false, assistantSaving = false, message = "已恢复默认 Whitz 图标", assistantFeedback = "已恢复默认 Whitz 图标") }
            } catch (t: Throwable) {
                val err = extractErrorMessage(t, "恢复默认图标失败")
                _ui.update { it.copy(loading = false, assistantSaving = false, error = err, assistantError = err) }
            }
        }
    }

    fun updateAssistantName(assistantName: String, onSuccess: () -> Unit = {}) {
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, assistantSaving = true, message = null, error = null, assistantFeedback = null, assistantError = null) }
            try {
                val nextName = assistantName.trim().ifEmpty { "Whitz" }
                val updated = container.network.api.updateAssistantProfile(UpdateAssistantRequest(nextName))
                container.authManager.updateUser(updated)
                _ui.update { it.copy(loading = false, assistantSaving = false, message = "助手信息已保存") }
                onSuccess()
            } catch (t: Throwable) {
                val err = extractErrorMessage(t, "保存失败")
                _ui.update { it.copy(loading = false, assistantSaving = false, error = err, assistantError = err) }
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

    fun selectMemoryCollection(slug: String?) {
        _ui.update { it.copy(selectedMemoryCollection = slug) }
    }

    fun createMemoryCollection(
        name: String,
        slug: String? = null,
        description: String = "",
        onSuccess: () -> Unit = {},
    ) {
        if (name.isBlank()) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                val m = container.network.api.createMemoryCollection(
                    MemoryCollectionCreateRequest(
                        name = name.trim(),
                        slug = slug?.trim()?.takeIf { it.isNotEmpty() },
                        description = description.trim(),
                    )
                )
                _ui.update { it.copy(loading = false, memory = m, message = "已新建记忆集") }
                onSuccess()
            } catch (t: Throwable) {
                _ui.update { it.copy(loading = false, error = extractErrorMessage(t, "创建记忆集失败")) }
            }
        }
    }

    fun toggleMemoryCollection(id: String, enabled: Boolean) {
        viewModelScope.launch {
            try {
                val m = container.network.api.updateMemoryCollection(
                    id,
                    MemoryCollectionUpdateRequest(enabled = enabled),
                )
                _ui.update { it.copy(memory = m) }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "更新记忆集失败")) }
            }
        }
    }

    fun deleteMemoryCollection(id: String) {
        viewModelScope.launch {
            try {
                val m = container.network.api.deleteMemoryCollection(id)
                _ui.update { state ->
                    val stillExists = state.selectedMemoryCollection != null &&
                        m.collections.any { it.slug == state.selectedMemoryCollection }
                    state.copy(
                        memory = m,
                        selectedMemoryCollection = if (stillExists) state.selectedMemoryCollection else null,
                        message = "已删除记忆集",
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "删除记忆集失败")) }
            }
        }
    }

    fun searchMemory(query: String) {
        val cleaned = query.trim()
        if (cleaned.isEmpty()) {
            _ui.update { it.copy(memorySearchResults = null, memorySearching = false) }
            return
        }
        viewModelScope.launch {
            _ui.update { it.copy(memorySearching = true, error = null) }
            try {
                val resp = container.network.api.searchMemory(
                    MemorySearchRequest(
                        query = cleaned,
                        collection = _ui.value.selectedMemoryCollection,
                    )
                )
                _ui.update { it.copy(memorySearching = false, memorySearchResults = resp.results) }
            } catch (t: Throwable) {
                _ui.update { it.copy(memorySearching = false, error = extractErrorMessage(t, "检索记忆失败")) }
            }
        }
    }

    fun clearMemorySearch() {
        _ui.update { it.copy(memorySearchResults = null, memorySearching = false) }
    }

    fun addMemoryEntry(
        content: String,
        target: String = "memory",
        title: String = "",
        onSuccess: () -> Unit = {},
    ) {
        if (content.isBlank()) return
        viewModelScope.launch {
            _ui.update { it.copy(loading = true, message = null, error = null) }
            try {
                container.network.api.createMemoryEntry(
                    MemoryEntryRequest(content.trim(), target = target, title = title.trim())
                )
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

    fun togglePinMemoryEntry(entry: MemoryEntry) {
        if (_ui.value.pinningMemoryId != null) return
        val nextPinned = !entry.isPinned
        val nextPriority = if (nextPinned) maxOf(entry.priority, 8) else entry.priority
        viewModelScope.launch {
            _ui.update { it.copy(pinningMemoryId = entry.id, error = null, message = null) }
            try {
                val overview = container.network.api.patchMemoryEntry(
                    entry.id,
                    MemoryEntryPatchRequest(isPinned = nextPinned, priority = nextPriority),
                )
                _ui.update {
                    it.copy(
                        pinningMemoryId = null,
                        memory = overview,
                        message = if (nextPinned) "已设为 L0 常驻核心记忆" else "已取消常驻核心",
                    )
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        pinningMemoryId = null,
                        error = extractErrorMessage(t, "更新常驻状态失败"),
                    )
                }
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

    fun clearAllMemory(collectionId: String? = null) {
        viewModelScope.launch {
            try {
                container.network.api.clearMemory(collectionId)
                loadMemory()
                _ui.update { it.copy(message = if (collectionId != null) "已清空当前记忆集" else "已清空全部记忆") }
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

    // --- Feedback & AI Positive Reactions ---
    fun toggleAiReactions(enabled: Boolean) {
        if (_ui.value.aiReactionSaving) return
        viewModelScope.launch {
            _ui.update { it.copy(aiReactionSaving = true, error = null, message = null) }
            try {
                val updated = container.network.api.updateAiReactions(UpdateAiReactionsRequest(enabled))
                container.authManager.updateUser(updated)
                _ui.update {
                    it.copy(
                        aiReactionSaving = false,
                        message = if (enabled) "已开启 AI 正向点赞互动" else "已关闭 AI 正向点赞互动",
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(aiReactionSaving = false, error = extractErrorMessage(t, "更新偏好失败")) }
            }
        }
    }

    fun toggleAiPosts(enabled: Boolean) {
        if (_ui.value.aiPostsSaving) return
        viewModelScope.launch {
            _ui.update { it.copy(aiPostsSaving = true, error = null, message = null) }
            try {
                val updated = container.network.api.updateAiPosts(UpdateAiPostsRequest(enabled))
                container.authManager.updateUser(updated)
                _ui.update {
                    it.copy(
                        aiPostsSaving = false,
                        message = if (enabled) "已开启 AI 每日联网动态（正常消耗积分）" else "已关闭 AI 每日联网动态",
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(aiPostsSaving = false, error = extractErrorMessage(t, "更新偏好失败")) }
            }
        }
    }

    fun loadFeedbacks() {
        viewModelScope.launch {
            try {
                val items = container.network.api.getMyFeedback()
                _ui.update { it.copy(feedbacks = items) }
            } catch (_: Throwable) {
            }
        }
    }

    fun submitFeedback(rating: Int, category: String, content: String, onSuccess: () -> Unit = {}) {
        val cleaned = content.trim()
        if (cleaned.isEmpty() || _ui.value.feedbackSubmitting) return
        viewModelScope.launch {
            _ui.update { it.copy(feedbackSubmitting = true, error = null, message = null) }
            try {
                val created = container.network.api.createMyFeedback(
                    UserFeedbackCreateRequest(rating = rating, category = category, content = cleaned)
                )
                _ui.update {
                    it.copy(
                        feedbackSubmitting = false,
                        feedbacks = listOf(created) + it.feedbacks,
                        message = "感谢你的评价与反馈！我们会持续改进产品体验。",
                    )
                }
                onSuccess()
            } catch (t: Throwable) {
                _ui.update { it.copy(feedbackSubmitting = false, error = extractErrorMessage(t, "提交失败，请稍后重试")) }
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
