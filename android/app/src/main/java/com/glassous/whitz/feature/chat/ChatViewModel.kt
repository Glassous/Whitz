package com.glassous.whitz.feature.chat

import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.glassous.whitz.AppContainer
import com.glassous.whitz.core.files.AvatarEncoder
import com.glassous.whitz.core.files.FileValidator
import com.glassous.whitz.core.files.LibraryController
import com.glassous.whitz.core.files.LocalPickedFile
import com.glassous.whitz.core.files.UriFileReader
import com.glassous.whitz.core.model.AgentStatus
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.ConversationDetail
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.ConversationSearchHit
import com.glassous.whitz.core.model.CreditStatus
import com.glassous.whitz.core.model.FileAttachmentMeta
import com.glassous.whitz.core.model.MemoryPendingItem
import com.glassous.whitz.core.model.Message
import com.glassous.whitz.core.model.PendingControl
import com.glassous.whitz.core.model.Plan
import com.glassous.whitz.core.model.PlanItem
import com.glassous.whitz.core.model.ReasoningBlock
import com.glassous.whitz.core.model.ReasoningTool
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.core.model.ToolPayload
import com.glassous.whitz.core.model.UploadTask
import com.glassous.whitz.core.model.UploadTaskStatus
import com.glassous.whitz.core.model.WorkspaceArtifactMeta
import com.glassous.whitz.core.network.ApiException
import com.glassous.whitz.core.network.ApprovalRequest
import com.glassous.whitz.core.network.AttachFilesRequest
import com.glassous.whitz.core.network.AvatarUploadRequest
import com.glassous.whitz.core.network.ClarifyRequest
import com.glassous.whitz.core.network.CompleteUploadRequest
import com.glassous.whitz.core.network.CreateConversationRequest
import com.glassous.whitz.core.network.PatchConversationRequest
import com.glassous.whitz.core.network.PendingActionRequest
import com.glassous.whitz.core.network.PresignRequest
import com.glassous.whitz.core.network.SseEvent
import com.glassous.whitz.core.network.TicketRequest
import com.glassous.whitz.core.network.UpdateAssistantRequest
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.core.network.extractErrorMessage
import com.glassous.whitz.core.util.ConversationSorter
import com.glassous.whitz.core.util.DateTimeUtils
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Instant
import java.util.UUID

data class PreviewTarget(
    val file: ConversationFile,
    val previewUrl: String? = null,
    val content: String? = null,
    val truncated: Boolean = false,
    val loading: Boolean = false,
    val error: String? = null,
)

data class ChatUiState(
    val conversations: List<Conversation> = emptyList(),
    val conversationsLoading: Boolean = false,
    val conversationsRefreshing: Boolean = false,
    val currentConvId: String? = null,
    val currentConvKind: String = "side",
    val currentConvTitle: String = "新旁聊",
    val isNewSideDraft: Boolean = false,
    val messages: List<Message> = emptyList(),
    val streaming: Boolean = false,
    val sendingMessage: Boolean = false,
    val waitingFirstByte: Boolean = false,
    val stopping: Boolean = false,
    val reconnecting: Boolean = false,
    val approvingChoice: String? = null,
    val submittingClarify: Boolean = false,
    val resolvingMemoryIds: Set<String> = emptySet(),
    val resolvingSkillIds: Set<String> = emptySet(),
    val activeAssistantId: String? = null,
    val activeRunId: String? = null,
    val selectedTurnId: String? = null,
    val plan: Plan? = null,
    val reasoning: List<ReasoningBlock> = emptyList(),
    val pendingControl: PendingControl? = null,
    val pendingMemory: List<MemoryPendingItem> = emptyList(),
    val pendingSkills: List<SkillPendingItem> = emptyList(),
    val error: String? = null,
    val agentStatus: AgentStatus? = null,
    val credits: CreditStatus? = null,
    // Files
    val files: List<ConversationFile> = emptyList(),
    val uploads: List<UploadTask> = emptyList(),
    val attachedIds: List<String> = emptyList(),
    val filesLoading: Boolean = false,
    val deletingFileId: String? = null,
    val downloadingFileId: String? = null,
    val fileError: String? = null,
    // Skills picker
    val enabledSkills: List<SkillItem> = emptyList(),
    val selectedSkillNames: List<String> = emptyList(),
    // Search
    val searchResults: List<ConversationSearchHit> = emptyList(),
    val searching: Boolean = false,
    // Preview
    val previewTarget: PreviewTarget? = null,
    // Assistant Profile dialog
    val assistantSaving: Boolean = false,
    val assistantFeedback: String? = null,
    val assistantError: String? = null,
) {
    val isMainChat: Boolean get() = currentConvKind == "main"
    val mainConversation: Conversation? get() = conversations.firstOrNull { it.kind == "main" }
    val sideConversations: List<Conversation> get() = conversations.filter { it.kind != "main" }
    val hasActiveUploads: Boolean get() = uploads.any { it.status != UploadTaskStatus.ERROR }
}

class ChatViewModel(
    private val container: AppContainer,
) : ViewModel() {
    private val _ui = MutableStateFlow(ChatUiState())
    val ui: StateFlow<ChatUiState> = _ui.asStateFlow()

    val user = container.authManager.user
    val authReady = container.authManager.ready
    val library = LibraryController(viewModelScope, container)

    fun resolveAssetUrl(pathOrUrl: String?): String? = container.resolveAssetUrl(pathOrUrl)

    private var streamJob: Job? = null
    private var pendingPollJob: Job? = null
    private var realtimeJob: Job? = null
    private val uploadJobs = mutableMapOf<String, Job>()
    private var pendingUserTargetId: String? = null
    private var lastEventId: String? = null
    private var openSeq = 0
    private var seq = 0
    private var initialLoaded = false

    private val activeStatusSet = setOf(
        "starting",
        "queued",
        "running",
        "waiting",
        "waiting_for_approval",
        "waiting_for_clarify",
    )

    private fun tempId(prefix: String): String = "$prefix-${System.currentTimeMillis()}-${seq++}"

    fun loadInitialData() {
        if (initialLoaded) return
        initialLoaded = true
        startRealtimeSync()
        viewModelScope.launch {
            fetchConversations()
            if (_ui.value.currentConvId == null && !_ui.value.isNewSideDraft) {
                openMainConversation()
            }
        }
        viewModelScope.launch { fetchAgentStatus() }
        viewModelScope.launch { fetchCredits() }
        viewModelScope.launch { fetchEnabledSkills() }
    }

    suspend fun fetchConversations() {
        _ui.update { it.copy(conversationsLoading = true) }
        try {
            val list = container.network.api.getConversations()
            _ui.update { it.copy(conversations = ConversationSorter.sort(list), conversationsLoading = false) }
        } catch (_: Throwable) {
            _ui.update { it.copy(conversationsLoading = false) }
        }
    }

    fun refreshConversations() {
        if (_ui.value.conversationsRefreshing) return
        viewModelScope.launch {
            _ui.update { it.copy(conversationsRefreshing = true) }
            try {
                val list = container.network.api.getConversations()
                _ui.update {
                    it.copy(
                        conversations = ConversationSorter.sort(list),
                        conversationsRefreshing = false,
                        conversationsLoading = false,
                    )
                }
            } catch (_: Throwable) {
                _ui.update { it.copy(conversationsRefreshing = false) }
            }
        }
    }

    private fun syncConversationsFromServer() {
        viewModelScope.launch {
            try {
                val list = container.network.api.getConversations()
                _ui.update { it.copy(conversations = ConversationSorter.sort(list)) }
            } catch (_: Throwable) {
                /* ignore */
            }
        }
    }

    suspend fun fetchAgentStatus() {
        try {
            val st = container.network.api.getAgentStatus()
            _ui.update { it.copy(agentStatus = st) }
        } catch (_: Throwable) {
            /* ignore */
        }
    }

    suspend fun fetchCredits() {
        try {
            val c = container.network.api.getCredits()
            _ui.update { it.copy(credits = c) }
        } catch (_: Throwable) {
            /* ignore */
        }
    }

    suspend fun fetchEnabledSkills() {
        try {
            val list = container.network.api.getSkills().filter { it.enabled }
            _ui.update { it.copy(enabledSkills = list) }
        } catch (_: Throwable) {
            /* ignore */
        }
    }

    fun startNewConversation() {
        createSideConversation()
    }

    fun createSideConversation() {
        pendingPollJob?.cancel()
        pendingPollJob = null
        streamJob?.cancel()
        streamJob = null
        pendingUserTargetId = null
        lastEventId = null
        _ui.update {
            it.copy(
                isNewSideDraft = true,
                currentConvId = null,
                currentConvKind = "side",
                currentConvTitle = "新旁聊",
                messages = emptyList(),
                streaming = false,
                sendingMessage = false,
                waitingFirstByte = false,
                stopping = false,
                reconnecting = false,
                approvingChoice = null,
                submittingClarify = false,
                activeAssistantId = null,
                activeRunId = null,
                selectedTurnId = null,
                plan = null,
                reasoning = emptyList(),
                pendingControl = null,
                pendingMemory = emptyList(),
                pendingSkills = emptyList(),
                error = null,
                files = emptyList(),
                uploads = emptyList(),
                attachedIds = emptyList(),
                selectedSkillNames = emptyList(),
                fileError = null,
            )
        }
    }

    fun openMainConversation() {
        val state = _ui.value
        val knownMainId = state.mainConversation?.id
        if (knownMainId != null &&
            state.currentConvId == knownMainId &&
            state.currentConvKind == "main"
        ) {
            return
        }
        val mySeq = ++openSeq
        pendingPollJob?.cancel()
        pendingPollJob = null
        streamJob?.cancel()
        streamJob = null
        _ui.update {
            it.copy(
                isNewSideDraft = false,
                previewTarget = null,
                selectedSkillNames = emptyList(),
            )
        }
        viewModelScope.launch {
            try {
                val detail = if (knownMainId != null) {
                    container.network.api.getConversation(knownMainId)
                } else {
                    container.network.api.getMainConversation()
                }
                if (mySeq != openSeq) return@launch
                loadFromConversation(detail)
                _ui.update { it.copy(files = emptyList(), filesLoading = false) }
            } catch (t: Throwable) {
                if (mySeq != openSeq) return@launch
                _ui.update { it.copy(error = extractErrorMessage(t, "加载主要聊天失败")) }
            }
        }
    }

    fun openConversation(convId: String) {
        val state = _ui.value
        if (state.currentConvId == convId && state.messages.isNotEmpty()) {
            return
        }
        val mySeq = ++openSeq
        pendingPollJob?.cancel()
        pendingPollJob = null
        streamJob?.cancel()
        streamJob = null
        _ui.update {
            it.copy(
                isNewSideDraft = false,
                previewTarget = null,
            )
        }
        viewModelScope.launch {
            try {
                val detail = container.network.api.getConversation(convId)
                if (mySeq != openSeq) return@launch
                loadFromConversation(detail)
                if (detail.kind != "main") {
                    loadFiles(convId)
                } else {
                    _ui.update { it.copy(files = emptyList(), filesLoading = false) }
                }
            } catch (t: Throwable) {
                if (mySeq != openSeq) return@launch
                _ui.update { it.copy(error = extractErrorMessage(t, "加载对话失败")) }
            }
        }
    }

    private fun loadFromConversation(detail: ConversationDetail) {
        pendingPollJob?.cancel()
        pendingPollJob = null
        streamJob?.cancel()
        streamJob = null
        lastEventId = null
        val lastReasoned = detail.messages.lastOrNull {
            it.role == "assistant" && !it.toolPayload?.reasoning.isNullOrEmpty()
        }
        val lastAssistant = detail.messages.lastOrNull { it.role == "assistant" }
        pendingUserTargetId = null
        val hydratedControl = hydratePendingControl(detail.pendingControl)
        _ui.update {
            it.copy(
                currentConvId = detail.id,
                currentConvKind = detail.kind,
                currentConvTitle = detail.title,
                isNewSideDraft = false,
                messages = detail.messages,
                plan = detail.plan,
                reasoning = lastReasoned?.toolPayload?.reasoning ?: emptyList(),
                selectedTurnId = lastAssistant?.id,
                activeRunId = detail.activeRunId,
                pendingControl = hydratedControl,
                pendingMemory = emptyList(),
                pendingSkills = emptyList(),
                error = null,
                streaming = false,
                sendingMessage = false,
                waitingFirstByte = false,
                stopping = false,
                reconnecting = false,
                approvingChoice = null,
                submittingClarify = false,
                activeAssistantId = lastAssistant?.id,
                attachedIds = emptyList(),
            )
        }
        if (detail.activeRunId == "pending") {
            _ui.update { it.copy(streaming = true, waitingFirstByte = true) }
            pollPendingRun(detail.id, attemptsLeft = 8)
        } else if (!detail.activeRunId.isNullOrBlank() &&
            !detail.activeRunStatus.isNullOrBlank() &&
            detail.activeRunStatus in activeStatusSet
        ) {
            reconnect(detail.id, detail.activeRunId)
        }
        loadConversationPending(detail.id)
    }

    private fun pollPendingRun(targetConvId: String, attemptsLeft: Int) {
        pendingPollJob?.cancel()
        if (attemptsLeft <= 0 || _ui.value.currentConvId != targetConvId) return
        pendingPollJob = viewModelScope.launch {
            delay(600L)
            if (_ui.value.currentConvId != targetConvId) return@launch
            try {
                val detail = container.network.api.getConversation(targetConvId)
                if (_ui.value.currentConvId != targetConvId) return@launch
                if (!detail.activeRunId.isNullOrBlank() && detail.activeRunId != "pending") {
                    loadFromConversation(detail)
                } else if (detail.activeRunId == "pending") {
                    pollPendingRun(targetConvId, attemptsLeft - 1)
                } else {
                    loadFromConversation(detail)
                }
            } catch (_: Throwable) {
                /* ignore */
            }
        }
    }

    private fun loadConversationPending(targetConvId: String) {
        viewModelScope.launch {
            try {
                val mem = container.network.api.getMemory()
                if (_ui.value.currentConvId == targetConvId) {
                    val filtered = mem.pending.filter {
                        (it.conversationId == null || it.conversationId == targetConvId) &&
                            (it.status ?: "pending") == "pending"
                    }
                    _ui.update { it.copy(pendingMemory = filtered) }
                }
            } catch (_: Throwable) {
                /* ignore */
            }
            try {
                val skills = container.network.api.getPendingSkills()
                if (_ui.value.currentConvId == targetConvId) {
                    val filtered = skills.filter {
                        (it.conversationId == null || it.conversationId == targetConvId) &&
                            (it.status ?: "pending") == "pending"
                    }
                    _ui.update { it.copy(pendingSkills = filtered) }
                }
            } catch (_: Throwable) {
                /* ignore */
            }
        }
    }

    fun renameConversation(id: String, title: String) {
        val target = _ui.value.conversations.firstOrNull { it.id == id }
        if (target?.kind == "main") return
        val trimmed = title.trim()
        if (trimmed.isEmpty()) return
        viewModelScope.launch {
            try {
                val updated = container.network.api.patchConversation(id, PatchConversationRequest(title = trimmed))
                _ui.update { state ->
                    val nextList = state.conversations.map { if (it.id == id) updated else it }
                    state.copy(
                        conversations = ConversationSorter.sort(nextList),
                        currentConvTitle = if (state.currentConvId == id) updated.title else state.currentConvTitle,
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "重命名失败")) }
            }
        }
    }

    fun togglePin(id: String, isPinned: Boolean) {
        val target = _ui.value.conversations.firstOrNull { it.id == id }
        if (target?.kind == "main") return
        val prevSnapshot = _ui.value.conversations
        // Optimistic immediate sort
        _ui.update { state ->
            val nextList = state.conversations.map {
                if (it.id == id) {
                    it.copy(
                        isPinned = isPinned,
                        pinnedAt = if (isPinned) Instant.now().toString() else null,
                    )
                } else it
            }
            state.copy(conversations = ConversationSorter.sort(nextList))
        }
        viewModelScope.launch {
            try {
                val updated = container.network.api.patchConversation(id, PatchConversationRequest(isPinned = isPinned))
                _ui.update { state ->
                    val nextList = state.conversations.map { if (it.id == id) updated else it }
                    state.copy(conversations = ConversationSorter.sort(nextList))
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        conversations = prevSnapshot,
                        error = extractErrorMessage(t, "置顶操作失败"),
                    )
                }
            }
        }
    }

    fun deleteConversation(id: String) {
        val target = _ui.value.conversations.firstOrNull { it.id == id }
        if (target?.kind == "main") return
        viewModelScope.launch {
            try {
                container.network.api.deleteConversation(id)
                val wasCurrent = _ui.value.currentConvId == id
                _ui.update { state ->
                    state.copy(conversations = state.conversations.filterNot { it.id == id })
                }
                if (wasCurrent) {
                    val fallback = _ui.value.sideConversations.firstOrNull() ?: _ui.value.mainConversation
                    if (fallback != null) {
                        openConversation(fallback.id)
                    } else {
                        openMainConversation()
                    }
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "删除失败")) }
            }
        }
    }

    fun searchConversations(query: String) {
        val q = query.trim()
        if (q.isEmpty()) {
            _ui.update { it.copy(searchResults = emptyList(), searching = false) }
            return
        }
        viewModelScope.launch {
            _ui.update { it.copy(searching = true) }
            try {
                val hits = container.network.api.searchConversations(q)
                _ui.update { it.copy(searchResults = hits, searching = false) }
            } catch (_: Throwable) {
                _ui.update { it.copy(searching = false) }
            }
        }
    }

    fun toggleSkillSelection(skillName: String) {
        _ui.update { state ->
            val current = state.selectedSkillNames
            val next = if (skillName in current) current - skillName else current + skillName
            state.copy(selectedSkillNames = next)
        }
    }

    fun clearError() {
        _ui.update { it.copy(error = null, fileError = null) }
    }

    fun selectTurn(messageId: String) {
        _ui.update { it.copy(selectedTurnId = messageId) }
    }

    private suspend fun ensureConversation(): String {
        _ui.value.currentConvId?.let { return it }
        val conv = container.network.api.createConversation(CreateConversationRequest("新旁聊"))
        _ui.update { state ->
            state.copy(
                currentConvId = conv.id,
                currentConvKind = conv.kind,
                currentConvTitle = conv.title,
                isNewSideDraft = false,
                conversations = ConversationSorter.sort(listOf(conv) + state.conversations.filterNot { it.id == conv.id }),
            )
        }
        return conv.id
    }

    private suspend fun chatTicketHeaders(convId: String, action: String): Map<String, String> {
        val nonce = UUID.randomUUID().toString()
        val res = container.network.api.createTicket(convId, TicketRequest(action, nonce))
        return mapOf("X-Chat-Ticket" to res.ticket, "X-Chat-Nonce" to nonce)
    }

    fun sendMessage(content: String) {
        val trimmed = content.trim()
        val state = _ui.value
        if (state.streaming || state.sendingMessage || state.hasActiveUploads) return
        val attachedIds = state.attachedIds
        val attachedFiles = state.files.filter { it.id in attachedIds }
        val skillNames = state.selectedSkillNames
        if (trimmed.isEmpty()) return

        _ui.update { it.copy(sendingMessage = true, error = null) }
        viewModelScope.launch {
            val convId = try {
                ensureConversation()
            } catch (t: Throwable) {
                _ui.update { it.copy(sendingMessage = false, error = extractErrorMessage(t, "创建对话失败")) }
                return@launch
            }
            _ui.update { it.copy(sendingMessage = false, attachedIds = emptyList(), selectedSkillNames = emptyList()) }
            sendInternal(convId, trimmed, attachedFiles, skillNames)
        }
    }

    private fun sendInternal(
        convId: String,
        content: String,
        attachedFiles: List<ConversationFile>,
        skillNames: List<String>,
    ) {
        pendingUserTargetId = null
        val userId = tempId("temp-user")
        val assistantId = tempId("temp-assistant")
        val now = Instant.now().toString()
        val payload = buildUserPayload(attachedFiles, skillNames)

        val userMsg = Message(
            id = userId,
            role = "user",
            content = content,
            toolPayload = payload,
            status = "completed",
            createdAt = now,
        )
        val assistantMsg = Message(
            id = assistantId,
            role = "assistant",
            content = "",
            status = "streaming",
            createdAt = now,
        )

        _ui.update {
            it.copy(
                error = null,
                reasoning = emptyList(),
                plan = null,
                pendingControl = null,
                messages = it.messages + userMsg + assistantMsg,
                activeAssistantId = assistantId,
                selectedTurnId = assistantId,
                streaming = true,
                waitingFirstByte = true,
                stopping = false,
                reconnecting = false,
            )
        }

        val bodyObj = buildJsonObject {
            put("content", JsonPrimitive(content))
            if (attachedFiles.isNotEmpty()) {
                put("file_ids", buildJsonArray { attachedFiles.forEach { add(JsonPrimitive(it.id)) } })
            }
            if (skillNames.isNotEmpty()) {
                put("skill_names", buildJsonArray { skillNames.forEach { add(JsonPrimitive(it)) } })
            }
        }
        streamTurn(convId, "/conversations/$convId/messages", bodyObj.toString(), "发送失败")
    }

    fun regenerate(assistantMessageId: String) {
        val state = _ui.value
        val convId = state.currentConvId ?: return
        if (state.streaming) return
        val idx = state.messages.indexOfFirst { it.id == assistantMessageId && it.role == "assistant" }
        if (idx < 0) return

        var prevUserIdx = -1
        for (i in idx - 1 downTo 0) {
            if (state.messages[i].role == "user") {
                prevUserIdx = i
                break
            }
        }

        if (assistantMessageId.startsWith("temp-") && prevUserIdx >= 0 && state.messages[prevUserIdx].id.startsWith("temp-")) {
            val prevUser = state.messages[prevUserIdx]
            val attached = (prevUser.toolPayload?.attachments ?: emptyList()).map { att ->
                state.files.firstOrNull { it.id == att.id } ?: ConversationFile(
                    id = att.id,
                    conversationId = convId,
                    filename = att.filename,
                    ext = att.ext,
                    category = att.category,
                    sizeBytes = att.sizeBytes,
                )
            }
            val skills = prevUser.toolPayload?.skills ?: emptyList()
            _ui.update { it.copy(messages = it.messages.take(prevUserIdx)) }
            sendInternal(convId, prevUser.content, attached, skills)
            return
        }

        val assistantId = tempId("temp-assistant")
        val cutMessages = state.messages.take(if (prevUserIdx >= 0) prevUserIdx + 1 else idx)
        val assistantMsg = Message(
            id = assistantId,
            role = "assistant",
            content = "",
            status = "streaming",
            createdAt = Instant.now().toString(),
        )
        pendingUserTargetId = null
        _ui.update {
            it.copy(
                error = null,
                reasoning = emptyList(),
                plan = null,
                pendingControl = null,
                messages = cutMessages + assistantMsg,
                activeAssistantId = assistantId,
                selectedTurnId = assistantId,
                streaming = true,
                waitingFirstByte = true,
                stopping = false,
                reconnecting = false,
            )
        }
        streamTurn(convId, "/conversations/$convId/messages/$assistantMessageId/regenerate", "{}", "重新生成失败")
    }

    fun editAndResend(userMessageId: String, newContent: String) {
        val trimmed = newContent.trim()
        val state = _ui.value
        val convId = state.currentConvId ?: return
        if (state.streaming || trimmed.isEmpty()) return
        val idx = state.messages.indexOfFirst { it.id == userMessageId && it.role == "user" }
        if (idx < 0) return

        val targetUser = state.messages[idx]
        val attached = (targetUser.toolPayload?.attachments ?: emptyList()).map { att ->
            state.files.firstOrNull { it.id == att.id } ?: ConversationFile(
                id = att.id,
                conversationId = convId,
                filename = att.filename,
                ext = att.ext,
                category = att.category,
                sizeBytes = att.sizeBytes,
            )
        }
        val skills = targetUser.toolPayload?.skills ?: emptyList()

        if (userMessageId.startsWith("temp-")) {
            _ui.update { it.copy(messages = it.messages.take(idx)) }
            sendInternal(convId, trimmed, attached, skills)
            return
        }

        pendingUserTargetId = userMessageId
        val assistantId = tempId("temp-assistant")
        val updatedUser = targetUser.copy(content = trimmed)
        val assistantMsg = Message(
            id = assistantId,
            role = "assistant",
            content = "",
            status = "streaming",
            createdAt = Instant.now().toString(),
        )
        _ui.update {
            it.copy(
                error = null,
                reasoning = emptyList(),
                plan = null,
                pendingControl = null,
                messages = state.messages.take(idx) + updatedUser + assistantMsg,
                activeAssistantId = assistantId,
                selectedTurnId = assistantId,
                streaming = true,
                waitingFirstByte = true,
                stopping = false,
                reconnecting = false,
            )
        }
        val bodyObj = buildJsonObject {
            put("content", JsonPrimitive(trimmed))
            put("file_ids", buildJsonArray { attached.forEach { add(JsonPrimitive(it.id)) } })
            put("skill_names", buildJsonArray { skills.forEach { add(JsonPrimitive(it)) } })
        }
        streamTurn(convId, "/conversations/$convId/messages/$userMessageId/edit", bodyObj.toString(), "保存并重发失败")
    }

    private fun streamTurn(convId: String, path: String, bodyJson: String, fallbackError: String) {
        streamJob?.cancel()
        lastEventId = null
        streamJob = viewModelScope.launch {
            try {
                val ticketHeaders = chatTicketHeaders(convId, "send")
                val headers = ticketHeaders + ("Idempotency-Key" to UUID.randomUUID().toString())
                if (_ui.value.currentConvId != convId) return@launch
                container.network.sseClient.streamPost(path, bodyJson, headers).collect { ev ->
                    if (_ui.value.currentConvId != convId) return@collect
                    handleSseEvent(ev)
                }
                if (_ui.value.currentConvId == convId && _ui.value.streaming) {
                    val runId = _ui.value.activeRunId
                    if (!runId.isNullOrBlank() && runId != "pending") {
                        autoReconnectLoop(convId, runId)
                    } else {
                        try {
                            val detail = container.network.api.getConversation(convId)
                            if (_ui.value.currentConvId == convId) loadFromConversation(detail)
                        } catch (_: Throwable) {
                            finishRun(markFailedIfStreaming = true, errMsg = "连接中断，请刷新查看最新状态")
                        }
                    }
                }
            } catch (_: CancellationException) {
                /* aborted by user or navigation */
            } catch (t: Throwable) {
                if (_ui.value.currentConvId != convId) return@launch
                val apiErr = t as? ApiException
                if (apiErr != null && apiErr.statusCode in 400..499 && apiErr.statusCode != 408) {
                    finishRun(markFailedIfStreaming = true, errMsg = extractErrorMessage(t, fallbackError))
                } else if (_ui.value.streaming) {
                    val runId = _ui.value.activeRunId
                    if (!runId.isNullOrBlank() && runId != "pending") {
                        autoReconnectLoop(convId, runId)
                    } else {
                        try {
                            val detail = container.network.api.getConversation(convId)
                            if (_ui.value.currentConvId == convId) loadFromConversation(detail)
                        } catch (_: Throwable) {
                            finishRun(markFailedIfStreaming = true, errMsg = extractErrorMessage(t, fallbackError))
                        }
                    }
                }
            }
        }
    }

    private suspend fun autoReconnectLoop(targetConvId: String, runId: String) {
        val delays = listOf(1000L, 2000L, 4000L, 8000L, 12000L)
        _ui.update { it.copy(reconnecting = true) }
        for (waitMs in delays) {
            if (_ui.value.currentConvId != targetConvId || !_ui.value.streaming) {
                _ui.update { it.copy(reconnecting = false) }
                return
            }
            delay(waitMs)
            if (_ui.value.currentConvId != targetConvId || !_ui.value.streaming) {
                _ui.update { it.copy(reconnecting = false) }
                return
            }
            try {
                val headers = chatTicketHeaders(targetConvId, "reconnect").toMutableMap()
                lastEventId?.let { headers["Last-Event-ID"] = it }
                container.network.sseClient.streamGet("/conversations/$targetConvId/runs/$runId/events", headers)
                    .collect { ev ->
                        if (_ui.value.currentConvId != targetConvId) return@collect
                        handleSseEvent(ev)
                    }
                if (_ui.value.currentConvId != targetConvId || !_ui.value.streaming) {
                    _ui.update { it.copy(reconnecting = false) }
                    return
                }
            } catch (_: CancellationException) {
                _ui.update { it.copy(reconnecting = false) }
                return
            } catch (t: Throwable) {
                if (_ui.value.currentConvId != targetConvId) {
                    _ui.update { it.copy(reconnecting = false) }
                    return
                }
                val apiErr = t as? ApiException
                if (apiErr?.statusCode == 404) {
                    try {
                        val detail = container.network.api.getConversation(targetConvId)
                        if (_ui.value.currentConvId == targetConvId) loadFromConversation(detail)
                    } catch (_: Throwable) {
                        /* ignore */
                    }
                    _ui.update { it.copy(reconnecting = false) }
                    return
                }
                if (apiErr != null && apiErr.statusCode in 400..499 && apiErr.statusCode != 408) {
                    finishRun(markFailedIfStreaming = true, errMsg = extractErrorMessage(t, "请求失败"))
                    return
                }
            }
        }
        if (_ui.value.currentConvId == targetConvId && _ui.value.streaming) {
            _ui.update { it.copy(reconnecting = false) }
            finishRun(markFailedIfStreaming = true, errMsg = "网络连接中断，请检查网络或下拉刷新同步最新状态")
        }
    }

    private fun reconnect(convId: String, runId: String) {
        if (runId.isBlank() || runId == "pending") return
        streamJob?.cancel()
        _ui.update { it.copy(streaming = true, reconnecting = true) }
        streamJob = viewModelScope.launch {
            try {
                val headers = chatTicketHeaders(convId, "reconnect").toMutableMap()
                lastEventId?.let { headers["Last-Event-ID"] = it }
                container.network.sseClient.streamGet("/conversations/$convId/runs/$runId/events", headers)
                    .collect { ev ->
                        if (_ui.value.currentConvId != convId) return@collect
                        handleSseEvent(ev)
                    }
                if (_ui.value.currentConvId == convId && _ui.value.streaming) {
                    autoReconnectLoop(convId, runId)
                }
            } catch (_: CancellationException) {
                /* ignore */
            } catch (t: Throwable) {
                if (_ui.value.currentConvId != convId) return@launch
                val apiErr = t as? ApiException
                if (apiErr?.statusCode == 404) {
                    try {
                        val detail = container.network.api.getConversation(convId)
                        if (_ui.value.currentConvId == convId) loadFromConversation(detail)
                    } catch (_: Throwable) {
                        finishRun(markFailedIfStreaming = false, errMsg = null)
                    }
                    return@launch
                }
                autoReconnectLoop(convId, runId)
            } finally {
                _ui.update { it.copy(reconnecting = false) }
            }
        }
    }

    fun recoverIfNeeded() {
        val state = _ui.value
        val cid = state.currentConvId ?: return
        if (state.streaming && !state.activeRunId.isNullOrBlank() && state.activeRunId != "pending" && streamJob?.isActive != true) {
            reconnect(cid, state.activeRunId)
            return
        }
        if (!state.streaming) {
            viewModelScope.launch {
                try {
                    val detail = container.network.api.getConversation(cid)
                    if (_ui.value.currentConvId == cid) {
                        val hasNewMsgs = detail.messages.size != _ui.value.messages.size
                        val hasLiveRun = !detail.activeRunId.isNullOrBlank() &&
                            !detail.activeRunStatus.isNullOrBlank() &&
                            detail.activeRunStatus in activeStatusSet
                        if (hasNewMsgs || hasLiveRun) {
                            loadFromConversation(detail)
                        }
                    }
                } catch (_: Throwable) {
                    /* ignore */
                }
            }
        }
    }

    fun stopRun() {
        val convId = _ui.value.currentConvId ?: return
        if (_ui.value.stopping) return
        _ui.update { it.copy(stopping = true) }
        viewModelScope.launch {
            try {
                val headers = chatTicketHeaders(convId, "stop")
                container.network.api.stopRun(convId, headers)
                delay(2500L)
                val cur = _ui.value
                if (cur.currentConvId == convId && cur.stopping && cur.streaming) {
                    streamJob?.cancel()
                    _ui.update { st ->
                        st.copy(
                            messages = st.messages.map { m ->
                                if (m.id == st.activeAssistantId && (m.status == "streaming" || m.status == "waiting")) {
                                    m.copy(status = "cancelled")
                                } else m
                            }
                        )
                    }
                    finishRun(markFailedIfStreaming = false, errMsg = null)
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(stopping = false, error = extractErrorMessage(t, "停止失败")) }
            }
        }
    }

    fun approveControl(choice: String) {
        val convId = _ui.value.currentConvId ?: return
        val ctrl = _ui.value.pendingControl ?: return
        if (_ui.value.approvingChoice != null) return
        _ui.update { it.copy(approvingChoice = choice) }
        viewModelScope.launch {
            try {
                val headers = chatTicketHeaders(convId, "approval")
                container.network.api.submitApproval(
                    convId,
                    ApprovalRequest(ctrl.requestId, ctrl.executionGeneration, choice),
                    headers,
                )
                _ui.update { state ->
                    state.copy(
                        pendingControl = null,
                        approvingChoice = null,
                        messages = state.messages.map {
                            if (it.id == state.activeAssistantId) it.copy(status = "streaming") else it
                        },
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(approvingChoice = null, error = extractErrorMessage(t, "审批提交失败")) }
            }
        }
    }

    fun clarifyControl(answer: String) {
        val convId = _ui.value.currentConvId ?: return
        val ctrl = _ui.value.pendingControl ?: return
        val trimmed = answer.trim()
        if (trimmed.isEmpty() || _ui.value.submittingClarify) return
        _ui.update { it.copy(submittingClarify = true) }
        viewModelScope.launch {
            try {
                val headers = chatTicketHeaders(convId, "clarify")
                container.network.api.submitClarify(
                    convId,
                    ClarifyRequest(ctrl.requestId, ctrl.executionGeneration, trimmed),
                    headers,
                )
                _ui.update { state ->
                    state.copy(
                        pendingControl = null,
                        submittingClarify = false,
                        messages = state.messages.map {
                            if (it.id == state.activeAssistantId) it.copy(status = "streaming") else it
                        },
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(submittingClarify = false, error = extractErrorMessage(t, "提交失败")) }
            }
        }
    }

    fun resolvePendingMemory(id: String, action: String, content: String? = null) {
        if (id in _ui.value.resolvingMemoryIds) return
        _ui.update { it.copy(resolvingMemoryIds = it.resolvingMemoryIds + id) }
        viewModelScope.launch {
            try {
                container.network.api.resolveMemoryPending(id, PendingActionRequest(action, content))
                _ui.update { state ->
                    state.copy(
                        pendingMemory = state.pendingMemory.filterNot { it.id == id },
                        resolvingMemoryIds = state.resolvingMemoryIds - id,
                    )
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        resolvingMemoryIds = it.resolvingMemoryIds - id,
                        error = extractErrorMessage(t, "处理记忆请求失败"),
                    )
                }
            }
        }
    }

    fun resolvePendingSkill(id: String, action: String, content: String? = null) {
        if (id in _ui.value.resolvingSkillIds) return
        _ui.update { it.copy(resolvingSkillIds = it.resolvingSkillIds + id) }
        viewModelScope.launch {
            try {
                container.network.api.resolveSkillPending(id, PendingActionRequest(action, content))
                _ui.update { state ->
                    state.copy(
                        pendingSkills = state.pendingSkills.filterNot { it.id == id },
                        resolvingSkillIds = state.resolvingSkillIds - id,
                    )
                }
                if (action == "approve") fetchEnabledSkills()
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        resolvingSkillIds = it.resolvingSkillIds - id,
                        error = extractErrorMessage(t, "处理技能请求失败"),
                    )
                }
            }
        }
    }

    // --- SSE Event Dispatcher ---
    private fun handleSseEvent(ev: SseEvent) {
        val d = ev.data
        if (!ev.id.isNullOrBlank() && ev.id != "0-0") {
            lastEventId = ev.id
        }
        if (ev.event !in setOf("run.started", "message.created", "run.reconnected")) {
            if (_ui.value.waitingFirstByte) {
                _ui.update { it.copy(waitingFirstByte = false) }
            }
        }
        when (ev.event) {
            "message.created" -> {
                val userMsgId = d.str("user_message_id")
                val asstMsgId = d.str("assistant_message_id")
                _ui.update { state ->
                    var updatedUser = false
                    val nextMsgs = state.messages.map { m ->
                        if (!updatedUser && userMsgId != null &&
                            (m.id.startsWith("temp-user") || (pendingUserTargetId != null && m.id == pendingUserTargetId))
                        ) {
                            updatedUser = true
                            m.copy(id = userMsgId)
                        } else if (asstMsgId != null && m.id == state.activeAssistantId) {
                            m.copy(id = asstMsgId)
                        } else {
                            m
                        }
                    }
                    pendingUserTargetId = null
                    val prevAsst = state.activeAssistantId
                    val nextAsst = asstMsgId ?: prevAsst
                    val nextSel = if (state.selectedTurnId == prevAsst) nextAsst else state.selectedTurnId
                    state.copy(messages = nextMsgs, activeAssistantId = nextAsst, selectedTurnId = nextSel)
                }
            }
            "run.started" -> {
                _ui.update { it.copy(activeRunId = d.str("run_id")) }
            }
            "title.updated", "conversation.title_updated" -> {
                val id = d.str("conversation_id") ?: _ui.value.currentConvId
                val title = d.str("title")?.trim()
                if (!id.isNullOrBlank() && !title.isNullOrBlank()) {
                    applyTitleUpdate(id, title)
                }
            }
            "run.reconnected" -> {
                val asstId = d.str("assistant_message_id")
                val runId = d.str("run_id")
                _ui.update { state ->
                    state.copy(
                        activeAssistantId = asstId ?: state.activeAssistantId,
                        selectedTurnId = asstId ?: state.selectedTurnId,
                        activeRunId = runId ?: state.activeRunId,
                        streaming = true,
                        reconnecting = false,
                    )
                }
            }
            "run.snapshot" -> {
                val asstId = d.str("assistant_message_id")
                val runId = d.str("run_id")
                val snapLastId = d.str("last_event_id")
                if (!snapLastId.isNullOrBlank() && snapLastId != "0-0") {
                    lastEventId = snapLastId
                }
                val output = d.str("output")
                val statusStr = d.str("status")
                val reasoningArr = d["reasoning"] as? JsonArray
                val parsedReasoning = reasoningArr?.mapNotNull {
                    try {
                        WhitzJson.decodeFromJsonElement(ReasoningBlock.serializer(), it)
                    } catch (_: Exception) {
                        null
                    }
                }
                val parsedPlan = (d["plan"] as? JsonObject)?.let {
                    try {
                        WhitzJson.decodeFromJsonElement(Plan.serializer(), it)
                    } catch (_: Exception) {
                        null
                    }
                }
                val parsedArtifacts = (d["artifacts"] as? JsonArray)?.mapNotNull {
                    try {
                        WhitzJson.decodeFromJsonElement(WorkspaceArtifactMeta.serializer(), it)
                    } catch (_: Exception) {
                        null
                    }
                } ?: emptyList()

                val ctrlObj = (d["pending_control"] as? JsonObject)
                    ?: (d["pending_controls"] as? JsonArray)?.firstOrNull() as? JsonObject
                val hydratedCtrl = hydratePendingControl(ctrlObj)

                _ui.update { state ->
                    val nextAsst = asstId ?: state.activeAssistantId
                    val nextSel = asstId ?: state.selectedTurnId
                    val nextReasoning = parsedReasoning ?: state.reasoning
                    val nextPlan = parsedPlan ?: state.plan
                    val mappedStatus = when (statusStr) {
                        "waiting_for_approval", "waiting_for_clarify" -> "waiting"
                        "running", "queued" -> "streaming"
                        else -> statusStr
                    }
                    val nextMsgs = state.messages.map { m ->
                        if (m.id == nextAsst) {
                            val prevPayload = m.toolPayload ?: ToolPayload()
                            val mergedArtifacts = mergeById(prevPayload.artifacts ?: emptyList(), parsedArtifacts) { it.id }
                            m.copy(
                                content = output ?: m.content,
                                status = mappedStatus ?: m.status,
                                toolPayload = prevPayload.copy(
                                    reasoning = nextReasoning,
                                    plan = nextPlan,
                                    artifacts = mergedArtifacts.ifEmpty { null },
                                ),
                            )
                        } else m
                    }
                    state.copy(
                        activeAssistantId = nextAsst,
                        selectedTurnId = nextSel,
                        activeRunId = runId ?: state.activeRunId,
                        reasoning = nextReasoning,
                        plan = nextPlan,
                        pendingControl = hydratedCtrl,
                        messages = nextMsgs,
                        reconnecting = false,
                        waitingFirstByte = false,
                    )
                }
            }
            "control.resolved", "run.resumed" -> {
                clearPendingControlFromSync()
            }
            "reasoning.delta" -> {
                val step = d.int("step")
                val title = d.str("title") ?: ""
                val delta = d.str("text") ?: ""
                updateReasoningBlock(step, title) { it.copy(text = it.text + delta) }
            }
            "reasoning.block" -> {
                val step = d.int("step")
                val title = d.str("title") ?: ""
                val text = d.str("text") ?: ""
                updateReasoningBlock(step, title) { it.copy(text = text) }
            }
            "reasoning.sync" -> {
                val arr = d["blocks"] as? JsonArray ?: return
                val blocks = arr.mapNotNull { elem ->
                    try {
                        WhitzJson.decodeFromJsonElement(ReasoningBlock.serializer(), elem)
                    } catch (_: Exception) {
                        null
                    }
                }
                _ui.update { state ->
                    syncReasoningToState(state, blocks)
                }
            }
            "message.delta" -> {
                val delta = d.str("text") ?: ""
                if (delta.isEmpty()) return
                _ui.update { state ->
                    val asstId = state.activeAssistantId
                    state.copy(
                        messages = state.messages.map {
                            if (it.id == asstId) it.copy(content = it.content + delta) else it
                        }
                    )
                }
            }
            "commentary" -> {
                val text = d.str("text")?.trim() ?: ""
                if (text.isEmpty()) return
                val step = d.int("step")
                val title = d.str("title") ?: ""
                val alreadyStreamed = d.bool("already_streamed") == true
                updateReasoningBlock(step, title) { blk ->
                    val nextContent = when {
                        blk.content.contains(text) -> blk.content
                        blk.content.isEmpty() -> text
                        else -> "${blk.content}\n\n$text"
                    }
                    blk.copy(content = nextContent)
                }
                if (alreadyStreamed) {
                    _ui.update { state ->
                        val asstId = state.activeAssistantId
                        state.copy(
                            messages = state.messages.map { m ->
                                if (m.id == asstId) {
                                    val trimmed = m.content.trimEnd()
                                    if (trimmed.endsWith(text)) {
                                        m.copy(content = trimmed.dropLast(text.length).trimEnd())
                                    } else m
                                } else m
                            }
                        )
                    }
                }
            }
            "tool.started" -> {
                val toolName = d.str("tool") ?: "tool"
                val rawArgs = d["args"]?.let { jsonToPlainString(it) } ?: d.str("preview") ?: ""
                val explicitMsgId = d.str("message_id")
                val callId = d.str("call_id")
                _ui.update { state ->
                    val existingMsg = when {
                        explicitMsgId != null -> state.messages.any { it.id == explicitMsgId }
                        callId != null -> state.messages.any { it.role == "tool" && it.toolPayload?.callId == callId }
                        else -> false
                    }
                    val nextMessages = if (existingMsg) {
                        state.messages
                    } else {
                        val toolMsg = Message(
                            id = explicitMsgId ?: tempId("tool"),
                            role = "tool",
                            toolName = toolName,
                            toolPayload = ToolPayload(
                                callId = callId,
                                args = d["args"] ?: d["preview"],
                                status = "running",
                            ),
                            status = "running",
                            runId = state.activeRunId,
                            createdAt = Instant.now().toString(),
                        )
                        state.messages + toolMsg
                    }
                    val blocks = state.reasoning.toMutableList()
                    val last = blocks.lastOrNull()
                    val alreadyInTools = callId != null && (last?.tools?.any { it.callId == callId } == true)
                    if (!alreadyInTools) {
                        val newTool = ReasoningTool(name = toolName, callId = callId, args = rawArgs, status = "running")
                        if (last != null && last.step == null) {
                            blocks[blocks.lastIndex] = last.copy(tools = last.tools + newTool)
                        } else {
                            blocks.add(ReasoningBlock(step = null, tools = listOf(newTool)))
                        }
                    }
                    syncReasoningToState(state.copy(messages = nextMessages), blocks)
                }
            }
            "tool.completed" -> {
                val toolName = d.str("tool") ?: "tool"
                val msgId = d.str("message_id")
                val callId = d.str("call_id")
                val err = d.str("error")
                val duration = d.double("duration")
                val durationMs = d.double("duration_ms")
                val rawResult = d["result"]?.let { jsonToPlainString(it) } ?: d.str("preview") ?: ""
                val nextStatus = if (!err.isNullOrBlank()) "failed" else "completed"

                _ui.update { state ->
                    var matchedMsg = false
                    val nextMsgs = state.messages.map { m ->
                        val isMatch = !matchedMsg && (
                            (msgId != null && m.id == msgId) ||
                                (msgId == null && m.role == "tool" && m.toolName == toolName && m.status == "running")
                            )
                        if (isMatch) {
                            matchedMsg = true
                            val prevPayload = m.toolPayload ?: ToolPayload()
                            m.copy(
                                status = nextStatus,
                                toolPayload = prevPayload.copy(
                                    result = d["result"] ?: d["preview"],
                                    duration = duration,
                                    error = err,
                                    status = nextStatus,
                                ),
                            )
                        } else m
                    }

                    val blocks = state.reasoning.toMutableList()
                    outer@ for (i in blocks.indices.reversed()) {
                        val tList = blocks[i].tools
                        for (j in tList.indices.reversed()) {
                            val t = tList[j]
                            val match = (callId != null && t.callId == callId) ||
                                (callId == null && t.name == toolName && t.status == "running")
                            if (match) {
                                val updatedTools = tList.toMutableList()
                                updatedTools[j] = t.copy(
                                    status = nextStatus,
                                    result = rawResult,
                                    error = err,
                                    durationMs = durationMs ?: t.durationMs,
                                )
                                blocks[i] = blocks[i].copy(tools = updatedTools)
                                break@outer
                            }
                        }
                    }
                    syncReasoningToState(state.copy(messages = nextMsgs), blocks)
                }
            }
            "plan.updated" -> {
                val itemsArr = d["items"] as? JsonArray ?: JsonArray(emptyList())
                val items = itemsArr.mapNotNull { elem ->
                    try {
                        WhitzJson.decodeFromJsonElement(PlanItem.serializer(), elem)
                    } catch (_: Exception) {
                        null
                    }
                }
                val newPlan = Plan(items = items)
                _ui.update { state ->
                    val asstId = state.activeAssistantId
                    state.copy(
                        plan = newPlan,
                        messages = state.messages.map { m ->
                            if (m.id == asstId) {
                                val payload = (m.toolPayload ?: ToolPayload()).copy(plan = newPlan)
                                m.copy(toolPayload = payload)
                            } else m
                        },
                    )
                }
            }
            "approval.request" -> {
                val ctrl = PendingControl(
                    kind = "approval",
                    requestId = d.str("request_id"),
                    executionGeneration = d.int("execution_generation"),
                    tool = d.str("tool"),
                    preview = formatControlPreview(d),
                )
                _ui.update { state ->
                    state.copy(
                        pendingControl = ctrl,
                        messages = state.messages.map {
                            if (it.id == state.activeAssistantId) it.copy(status = "waiting") else it
                        },
                    )
                }
            }
            "clarify.request" -> {
                val ctrl = PendingControl(
                    kind = "clarify",
                    requestId = d.str("request_id"),
                    executionGeneration = d.int("execution_generation"),
                    tool = d.str("tool"),
                    preview = formatControlPreview(d),
                )
                _ui.update { state ->
                    state.copy(
                        pendingControl = ctrl,
                        messages = state.messages.map {
                            if (it.id == state.activeAssistantId) it.copy(status = "waiting") else it
                        },
                    )
                }
            }
            "workspace.file_created" -> {
                val fileObj = (d["file"] as? JsonObject) ?: d
                try {
                    val f = WhitzJson.decodeFromJsonElement(ConversationFile.serializer(), fileObj)
                    upsertFile(f)
                    appendArtifactToAssistant(
                        WorkspaceArtifactMeta(
                            id = f.id,
                            filename = f.filename,
                            ext = f.ext,
                            category = f.category,
                            sizeBytes = f.sizeBytes,
                            mimeType = f.mimeType,
                            source = f.source,
                            isGlobal = f.isGlobal,
                            messageId = f.messageId,
                            previewUrl = f.previewUrl,
                            thumbUrl = f.thumbUrl,
                            previewExpiresAt = f.previewExpiresAt,
                        )
                    )
                } catch (_: Exception) {
                    /* ignore */
                }
            }
            "memory.pending" -> {
                val items = extractPendingList<MemoryPendingItem>(d, "memory") {
                    WhitzJson.decodeFromJsonElement(MemoryPendingItem.serializer(), it)
                }
                if (items.isNotEmpty()) {
                    _ui.update { state ->
                        val merged = mergeById(state.pendingMemory, items) { it.id }
                        state.copy(pendingMemory = merged)
                    }
                }
            }
            "skills.pending", "skill.pending" -> {
                val items = extractPendingList<SkillPendingItem>(d, "skills") {
                    WhitzJson.decodeFromJsonElement(SkillPendingItem.serializer(), it)
                }
                if (items.isNotEmpty()) {
                    _ui.update { state ->
                        val merged = mergeById(state.pendingSkills, items) { it.id }
                        state.copy(pendingSkills = merged)
                    }
                }
            }
            "run.completed" -> {
                applyTerminalPayload(d, status = "completed", errorMsg = null)
                finishRun(markFailedIfStreaming = false, errMsg = null)
                viewModelScope.launch { fetchCredits() }
            }
            "run.failed" -> {
                val errMsg = d.str("error") ?: "任务执行失败"
                applyTerminalPayload(d, status = "failed", errorMsg = errMsg)
                finishRun(markFailedIfStreaming = false, errMsg = errMsg)
            }
            "run.cancelled", "run.interrupted" -> {
                applyTerminalPayload(d, status = "cancelled", errorMsg = null)
                finishRun(markFailedIfStreaming = false, errMsg = null)
            }
            "error" -> {
                val code = d.str("code")
                val errMsg = d.str("detail") ?: if (code == "agent_warming_up") "助理初始化中，请稍后重试" else "发生错误"
                finishRun(markFailedIfStreaming = true, errMsg = errMsg)
            }
        }
    }

    private fun applyTerminalPayload(d: JsonObject, status: String, errorMsg: String?) {
        val output = d.str("output")
        val artifactsArr = d["artifacts"] as? JsonArray
        val reasoningArr = d["reasoning"] as? JsonArray
        val planElem = d["plan"]

        val parsedReasoning = reasoningArr?.mapNotNull {
            try {
                WhitzJson.decodeFromJsonElement(ReasoningBlock.serializer(), it)
            } catch (_: Exception) {
                null
            }
        }
        val parsedPlan = planElem?.let {
            try {
                WhitzJson.decodeFromJsonElement(Plan.serializer(), it)
            } catch (_: Exception) {
                null
            }
        }
        val parsedArtifacts = artifactsArr?.mapNotNull {
            try {
                WhitzJson.decodeFromJsonElement(WorkspaceArtifactMeta.serializer(), it)
            } catch (_: Exception) {
                null
            }
        } ?: emptyList()

        _ui.update { state ->
            val nextReasoning = parsedReasoning ?: state.reasoning
            val nextPlan = parsedPlan ?: state.plan
            val asstId = state.activeAssistantId
            val nextMsgs = state.messages.map { m ->
                if (m.id == asstId) {
                    val prevPayload = m.toolPayload ?: ToolPayload()
                    val mergedArtifacts = mergeById(prevPayload.artifacts ?: emptyList(), parsedArtifacts) { it.id }
                    m.copy(
                        content = if (!output.isNullOrEmpty()) output else m.content,
                        status = status,
                        toolPayload = prevPayload.copy(
                            reasoning = nextReasoning,
                            plan = nextPlan,
                            artifacts = mergedArtifacts.ifEmpty { null },
                        ),
                    )
                } else m
            }
            state.copy(
                messages = nextMsgs,
                reasoning = nextReasoning,
                plan = nextPlan,
                error = errorMsg ?: state.error,
            )
        }
    }

    private fun finishRun(markFailedIfStreaming: Boolean, errMsg: String?) {
        pendingUserTargetId = null
        lastEventId = null
        _ui.update { state ->
            val asstId = state.activeAssistantId
            val nextMsgs = if (markFailedIfStreaming && asstId != null) {
                state.messages.map {
                    if (it.id == asstId && it.status == "streaming") it.copy(status = "failed") else it
                }
            } else state.messages
            state.copy(
                streaming = false,
                waitingFirstByte = false,
                stopping = false,
                reconnecting = false,
                approvingChoice = null,
                submittingClarify = false,
                activeRunId = null,
                pendingControl = null,
                messages = nextMsgs,
                error = errMsg ?: state.error,
            )
        }
        syncConversationsFromServer()
    }

    private fun updateReasoningBlock(
        step: Int?,
        title: String,
        transform: (ReasoningBlock) -> ReasoningBlock,
    ) {
        _ui.update { state ->
            val list = state.reasoning.toMutableList()
            val last = list.lastOrNull()
            if (last != null && last.step == step) {
                list[list.lastIndex] = transform(last)
            } else {
                list.add(transform(ReasoningBlock(step = step, title = title)))
            }
            syncReasoningToState(state, list)
        }
    }

    private fun syncReasoningToState(state: ChatUiState, blocks: List<ReasoningBlock>): ChatUiState {
        val asstId = state.activeAssistantId
        val nextMsgs = if (asstId != null) {
            state.messages.map { m ->
                if (m.id == asstId) {
                    val payload = (m.toolPayload ?: ToolPayload()).copy(
                        reasoning = blocks,
                        plan = state.plan ?: m.toolPayload?.plan,
                    )
                    m.copy(toolPayload = payload)
                } else m
            }
        } else state.messages
        return state.copy(reasoning = blocks, messages = nextMsgs)
    }

    private fun appendArtifactToAssistant(meta: WorkspaceArtifactMeta) {
        _ui.update { state ->
            val asstId = state.activeAssistantId ?: return@update state
            state.copy(
                messages = state.messages.map { m ->
                    if (m.id == asstId) {
                        val prevPayload = m.toolPayload ?: ToolPayload()
                        val merged = mergeById(prevPayload.artifacts ?: emptyList(), listOf(meta)) { it.id }
                        m.copy(toolPayload = prevPayload.copy(artifacts = merged))
                    } else m
                }
            )
        }
    }

    // --- Files & Uploads ---
    private suspend fun loadFiles(convId: String) {
        _ui.update { it.copy(filesLoading = true) }
        try {
            val list = container.network.api.getConversationFiles(convId)
            if (_ui.value.currentConvId == convId) {
                _ui.update { it.copy(files = list, filesLoading = false) }
            }
        } catch (t: Throwable) {
            _ui.update { it.copy(filesLoading = false, fileError = extractErrorMessage(t, "加载对话文件失败")) }
        }
    }

    fun enqueuePickedUris(uris: List<Uri>) {
        if (uris.isEmpty()) return
        val cr = container.appContext.contentResolver
        val picked = mutableListOf<LocalPickedFile>()
        val rejected = mutableListOf<String>()

        for (uri in uris) {
            val info = UriFileReader.inspect(cr, uri)
            if (info == null) {
                rejected.add("未知文件（无法读取）")
                continue
            }
            val err = FileValidator.validateFile(info.filename, info.mimeType, info.sizeBytes)
            if (err != null) {
                rejected.add("${info.filename}（$err）")
            } else {
                picked.add(info)
            }
        }

        if (rejected.isNotEmpty()) {
            _ui.update {
                it.copy(
                    fileError = "部分文件无法上传：${rejected.take(3).joinToString("；")}。${FileValidator.SUPPORTED_TYPES_SUMMARY}"
                )
            }
        }
        if (picked.isEmpty()) return

        val state = _ui.value
        val activeCount = state.uploads.count { it.status != UploadTaskStatus.ERROR }
        val remainingSlots = (FileValidator.MAX_FILES_PER_CONVERSATION - state.files.size - activeCount).coerceAtLeast(0)
        if (remainingSlots <= 0) {
            _ui.update { it.copy(fileError = "当前对话最多保留 ${FileValidator.MAX_FILES_PER_CONVERSATION} 个文件，请先删除部分文件") }
            return
        }
        val queue = picked.take(remainingSlots)

        viewModelScope.launch {
            val targetConvId = try {
                ensureConversation()
            } catch (t: Throwable) {
                _ui.update { it.copy(fileError = extractErrorMessage(t, "无法创建对话以保存文件")) }
                return@launch
            }

            val tasks = queue.map { file ->
                val spec = FileValidator.getFileSpec(file.filename)
                val task = UploadTask(
                    localId = tempId("up"),
                    filename = file.filename,
                    ext = spec?.ext ?: FileValidator.getFileExt(file.filename),
                    category = spec?.category ?: "document",
                    sizeBytes = file.sizeBytes,
                    progress = 0,
                    status = UploadTaskStatus.SIGNING,
                    localFile = file,
                )
                task to file
            }
            _ui.update { it.copy(uploads = it.uploads + tasks.map { p -> p.first }) }

            val sem = Semaphore(3)
            coroutineScope {
                tasks.map { (task, file) ->
                    val job = async {
                        sem.withPermit {
                            runUploadTask(targetConvId, task.localId, file)
                        }
                    }
                    uploadJobs[task.localId] = job
                    job
                }.awaitAll()
            }
        }
    }

    private suspend fun runUploadTask(convId: String, taskId: String, file: LocalPickedFile) {
        try {
            val presign = container.network.api.presignUpload(
                convId,
                PresignRequest(file.filename, file.mimeType, file.sizeBytes),
            )
            updateUploadTask(taskId) { it.copy(status = UploadTaskStatus.UPLOADING, progress = 1) }

            val etag = container.cosUploader.putFile(presign.uploadUrl, presign.headers, file) { pct ->
                updateUploadTask(taskId) { it.copy(progress = pct) }
            }

            updateUploadTask(taskId) { it.copy(status = UploadTaskStatus.COMPLETING, progress = 100) }

            val completed = container.network.api.completeUpload(
                convId,
                presign.fileId,
                CompleteUploadRequest(etag),
            )
            if (_ui.value.currentConvId == convId) {
                _ui.update { state ->
                    val nextFiles = state.files.filterNot { it.id == completed.id } + completed
                    val nextAttached = if (completed.id in state.attachedIds) state.attachedIds else state.attachedIds + completed.id
                    state.copy(
                        files = nextFiles,
                        attachedIds = nextAttached,
                        uploads = state.uploads.filterNot { it.localId == taskId },
                    )
                }
            }
        } catch (_: CancellationException) {
            _ui.update { state -> state.copy(uploads = state.uploads.filterNot { it.localId == taskId }) }
        } catch (t: Throwable) {
            val msg = extractErrorMessage(t, "上传失败")
            updateUploadTask(taskId) { it.copy(status = UploadTaskStatus.ERROR, error = msg) }
            _ui.update { it.copy(fileError = "${file.filename}：$msg") }
        } finally {
            uploadJobs.remove(taskId)
        }
    }

    private fun updateUploadTask(taskId: String, transform: (UploadTask) -> UploadTask) {
        _ui.update { state ->
            state.copy(uploads = state.uploads.map { if (it.localId == taskId) transform(it) else it })
        }
    }

    fun cancelOrDismissUpload(localId: String) {
        uploadJobs[localId]?.cancel()
        uploadJobs.remove(localId)
        _ui.update { state -> state.copy(uploads = state.uploads.filterNot { it.localId == localId }) }
    }

    fun retryUpload(localId: String) {
        val task = _ui.value.uploads.firstOrNull { it.localId == localId } ?: return
        val file = task.localFile ?: return
        viewModelScope.launch {
            val targetConvId = try {
                ensureConversation()
            } catch (t: Throwable) {
                updateUploadTask(localId) {
                    it.copy(status = UploadTaskStatus.ERROR, error = extractErrorMessage(t, "创建对话失败"))
                }
                return@launch
            }
            updateUploadTask(localId) { it.copy(status = UploadTaskStatus.SIGNING, progress = 0, error = null) }
            val job = async { runUploadTask(targetConvId, localId, file) }
            uploadJobs[localId] = job
            job.await()
        }
    }

    fun detachFile(fileId: String) {
        _ui.update { state -> state.copy(attachedIds = state.attachedIds.filterNot { it == fileId }) }
    }

    fun attachExistingFile(fileId: String) {
        _ui.update { state ->
            if (fileId in state.attachedIds) state else state.copy(attachedIds = state.attachedIds + fileId)
        }
    }

    fun attachFromLibrary(fileIds: List<String>) {
        if (fileIds.isEmpty()) return
        viewModelScope.launch {
            val convId = try {
                ensureConversation()
            } catch (t: Throwable) {
                _ui.update { it.copy(fileError = extractErrorMessage(t, "创建对话失败")) }
                return@launch
            }
            try {
                val res = container.network.api.attachFiles(convId, AttachFilesRequest(fileIds))
                val arr = when (res) {
                    is JsonArray -> res
                    is JsonObject -> res["files"] as? JsonArray
                    else -> null
                }
                val attached = arr?.mapNotNull {
                    try {
                        WhitzJson.decodeFromJsonElement(ConversationFile.serializer(), it)
                    } catch (_: Exception) {
                        null
                    }
                } ?: emptyList()

                if (attached.isNotEmpty()) {
                    attached.forEach { upsertFile(it) }
                    _ui.update { state ->
                        val nextIds = (state.attachedIds + attached.map { it.id }).distinct()
                        state.copy(attachedIds = nextIds)
                    }
                } else {
                    loadFiles(convId)
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(fileError = extractErrorMessage(t, "附加文件失败")) }
            }
        }
    }

    fun deleteFile(fileId: String) {
        val convId = _ui.value.currentConvId ?: return
        if (_ui.value.deletingFileId == fileId) return
        _ui.update { it.copy(deletingFileId = fileId) }
        viewModelScope.launch {
            try {
                container.network.api.deleteConversationFile(convId, fileId)
                _ui.update { state ->
                    state.copy(
                        deletingFileId = null,
                        files = state.files.filterNot { it.id == fileId },
                        attachedIds = state.attachedIds.filterNot { it == fileId },
                    )
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        deletingFileId = null,
                        fileError = extractErrorMessage(t, "删除文件失败"),
                    )
                }
            }
        }
    }

    suspend fun fetchLibraryFiles(query: String = ""): List<ConversationFile> {
        return try {
            val res = container.network.api.getLibraryFiles(q = query.trim().ifBlank { null })
            val arr = when (res) {
                is JsonArray -> res
                is JsonObject -> res["items"] as? JsonArray
                else -> null
            }
            arr?.mapNotNull {
                try {
                    WhitzJson.decodeFromJsonElement(ConversationFile.serializer(), it)
                } catch (_: Exception) {
                    null
                }
            } ?: emptyList()
        } catch (_: Throwable) {
            emptyList()
        }
    }

    fun openFilePreview(file: ConversationFile) {
        val convId = file.conversationId ?: _ui.value.currentConvId
        _ui.update { it.copy(previewTarget = PreviewTarget(file = file, loading = true)) }
        viewModelScope.launch {
            try {
                if (file.category == "image") {
                    val url = resolveFreshPreviewUrl(convId, file)
                    _ui.update {
                        it.copy(previewTarget = PreviewTarget(file = file, previewUrl = url, loading = false))
                    }
                } else {
                    val isTextLike = file.category == "code" ||
                        file.ext.lowercase() in setOf(".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".xml")
                    if (isTextLike) {
                        val body = if (convId != null) {
                            container.network.api.getPreviewContent(convId, file.id).string()
                        } else {
                            container.network.api.getLibraryPreviewContent(file.id).string()
                        }
                        var text = body
                        var truncated = false
                        try {
                            val elem = WhitzJson.parseToJsonElement(body)
                            if (elem is JsonObject) {
                                text = (elem["content"] as? JsonPrimitive)?.contentOrNull
                                    ?: (elem["text"] as? JsonPrimitive)?.contentOrNull
                                    ?: body
                                truncated = (elem["truncated"] as? JsonPrimitive)?.booleanOrNull ?: false
                            }
                        } catch (_: Exception) {
                            /* plain text */
                        }
                        _ui.update {
                            it.copy(previewTarget = PreviewTarget(file = file, content = text, truncated = truncated, loading = false))
                        }
                    } else {
                        val url = if (convId != null) {
                            container.network.api.getDownloadUrl(convId, file.id, inline = false).url
                        } else {
                            container.network.api.getLibraryDownloadUrl(file.id, inline = false).url
                        }
                        _ui.update {
                            it.copy(previewTarget = PreviewTarget(file = file, previewUrl = url, loading = false))
                        }
                    }
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(previewTarget = PreviewTarget(file = file, loading = false, error = extractErrorMessage(t, "预览加载失败")))
                }
            }
        }
    }

    fun closeFilePreview() {
        _ui.update { it.copy(previewTarget = null) }
    }

    suspend fun getDownloadUrl(file: ConversationFile): String? {
        val convId = file.conversationId ?: _ui.value.currentConvId
        return try {
            if (convId != null) {
                container.network.api.getDownloadUrl(convId, file.id, inline = false).url
            } else {
                container.network.api.getLibraryDownloadUrl(file.id, inline = false).url
            }
        } catch (_: Throwable) {
            null
        }
    }

    private suspend fun resolveFreshPreviewUrl(convId: String?, file: ConversationFile): String? {
        val existing = _ui.value.files.firstOrNull { it.id == file.id } ?: file
        val expMs = DateTimeUtils.parseInstantMs(existing.previewExpiresAt)
        if (!existing.previewUrl.isNullOrBlank() && (expMs == 0L || System.currentTimeMillis() < expMs - 30_000L)) {
            return existing.previewUrl
        }
        val res = if (convId != null) {
            container.network.api.getDownloadUrl(convId, existing.id, inline = true)
        } else {
            container.network.api.getLibraryDownloadUrl(existing.id, inline = true)
        }
        upsertFile(existing.copy(previewUrl = res.url))
        return res.url
    }

    private fun upsertFile(file: ConversationFile) {
        _ui.update { state ->
            if (state.currentConvId != null && file.conversationId != null && file.conversationId != state.currentConvId) {
                return@update state
            }
            val next = state.files.filterNot { it.id == file.id } + file
            state.copy(files = next)
        }
    }

    private fun buildUserPayload(files: List<ConversationFile>, skills: List<String>): ToolPayload? {
        if (files.isEmpty() && skills.isEmpty()) return null
        return ToolPayload(
            attachments = files.takeIf { it.isNotEmpty() }?.map {
                FileAttachmentMeta(it.id, it.filename, it.ext, it.category, it.sizeBytes)
            },
            skills = skills.takeIf { it.isNotEmpty() },
        )
    }

    private fun formatControlPreview(d: JsonObject): String? {
        val code = d.str("code")
        if (!code.isNullOrBlank()) {
            val lang = d.str("language")
            val desc = d.str("description")
            val header = listOfNotNull(lang?.let { "[$it]" }, desc).joinToString(" ")
            return if (header.isNotBlank()) "$header\n$code" else code
        }
        val preview = d["preview"]
        if (preview is JsonPrimitive) return preview.contentOrNull
        if (preview is JsonObject) {
            val q = preview.str("question")
            if (!q.isNullOrBlank()) return q
            val pCode = preview.str("code")
            if (!pCode.isNullOrBlank()) return pCode
            return preview.toString()
        }
        val detail = d["detail"] as? JsonObject
        if (detail != null) {
            return detail.str("question") ?: detail.str("code")
        }
        return null
    }

    private fun <T> extractPendingList(
        d: JsonObject,
        primaryKey: String,
        decode: (JsonElement) -> T,
    ): List<T> {
        val arr = (d[primaryKey] as? JsonArray)
            ?: (d["items"] as? JsonArray)
            ?: (d["pending"] as? JsonArray)
        if (arr != null) {
            return arr.mapNotNull {
                try {
                    decode(it)
                } catch (_: Exception) {
                    null
                }
            }
        }
        val itemObj = d["item"] as? JsonObject
        if (itemObj != null) {
            return listOfNotNull(
                try {
                    decode(itemObj)
                } catch (_: Exception) {
                    null
                }
            )
        }
        if (d.str("id") != null) {
            return listOfNotNull(
                try {
                    decode(d)
                } catch (_: Exception) {
                    null
                }
            )
        }
        return emptyList()
    }

    private fun <T> mergeById(existing: List<T>, incoming: List<T>, idOf: (T) -> String): List<T> {
        if (incoming.isEmpty()) return existing
        val map = LinkedHashMap<String, T>()
        existing.forEach { map[idOf(it)] = it }
        incoming.forEach { map[idOf(it)] = it }
        return map.values.toList()
    }

    private fun jsonToPlainString(elem: JsonElement): String {
        return if (elem is JsonPrimitive) elem.contentOrNull ?: elem.toString() else elem.toString()
    }

    private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull
    private fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.intOrNull
    private fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.longOrNull
    private fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull
    private fun JsonObject.double(key: String): Double? = (this[key] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()

    // --- Assistant Profile Dialog ---
    fun clearAssistantDialogFeedback() {
        _ui.update { it.copy(assistantFeedback = null, assistantError = null) }
    }

    fun uploadAssistantAvatar(uri: Uri) {
        viewModelScope.launch {
            _ui.update { it.copy(assistantSaving = true, assistantFeedback = null, assistantError = null) }
            try {
                val dataUrl = AvatarEncoder.encodeToDataUrl(container.appContext.contentResolver, uri)
                val updated = container.network.api.uploadAssistantAvatar(AvatarUploadRequest(dataUrl))
                container.authManager.updateUser(updated)
                _ui.update { it.copy(assistantSaving = false, assistantFeedback = "助手头像已更新") }
            } catch (t: Throwable) {
                _ui.update { it.copy(assistantSaving = false, assistantError = extractErrorMessage(t, "助手头像上传失败")) }
            }
        }
    }

    fun deleteAssistantAvatar() {
        viewModelScope.launch {
            _ui.update { it.copy(assistantSaving = true, assistantFeedback = null, assistantError = null) }
            try {
                val updated = container.network.api.deleteAssistantAvatar()
                container.authManager.updateUser(updated)
                _ui.update { it.copy(assistantSaving = false, assistantFeedback = "已恢复默认 Whitz 图标") }
            } catch (t: Throwable) {
                _ui.update { it.copy(assistantSaving = false, assistantError = extractErrorMessage(t, "恢复默认图标失败")) }
            }
        }
    }

    fun updateAssistantName(assistantName: String, onSuccess: () -> Unit = {}) {
        viewModelScope.launch {
            _ui.update { it.copy(assistantSaving = true, assistantFeedback = null, assistantError = null) }
            try {
                val nextName = assistantName.trim().ifEmpty { "Whitz" }
                val updated = container.network.api.updateAssistantProfile(UpdateAssistantRequest(nextName))
                container.authManager.updateUser(updated)
                _ui.update { it.copy(assistantSaving = false) }
                onSuccess()
            } catch (t: Throwable) {
                _ui.update { it.copy(assistantSaving = false, assistantError = extractErrorMessage(t, "保存失败")) }
            }
        }
    }

    // --- Per-User Multi-Device Realtime Sync (/events/stream) ---
    fun startRealtimeSync() {
        if (realtimeJob?.isActive == true) return
        realtimeJob = viewModelScope.launch {
            var backoffMs = 1000L
            while (true) {
                try {
                    container.network.sseClient.streamGet("/events/stream", idleTimeoutMs = 55_000L)
                        .collect { ev ->
                            if (ev.event == "sync.connected") {
                                backoffMs = 1000L
                            } else {
                                handleSyncEvent(ev.event, ev.data)
                            }
                        }
                } catch (c: CancellationException) {
                    throw c
                } catch (t: Throwable) {
                    val apiErr = t as? ApiException
                    if (apiErr != null && (apiErr.statusCode == 401 || apiErr.statusCode == 403)) {
                        break
                    }
                }
                delay(backoffMs)
                backoffMs = (backoffMs * 2L).coerceAtMost(15_000L)
            }
        }
    }

    private fun handleSyncEvent(event: String, d: JsonObject) {
        when (event) {
            "conversation.run_updated" -> {
                val cid = d.str("conversation_id") ?: return
                val runId = d.str("active_run_id")
                val runStatus = d.str("active_run_status")
                val pendingCtrl = d["pending_control"] as? JsonObject
                _ui.update { state ->
                    state.copy(
                        conversations = state.conversations.map { c ->
                            if (c.id == cid) {
                                c.copy(
                                    activeRunId = runId,
                                    activeRunStatus = runStatus,
                                    pendingControl = pendingCtrl,
                                )
                            } else c
                        }
                    )
                }
                val cur = _ui.value
                if (cur.currentConvId == cid) {
                    if (!runId.isNullOrBlank() && runId != "pending" && !cur.streaming) {
                        viewModelScope.launch {
                            try {
                                val detail = container.network.api.getConversation(cid)
                                val latest = _ui.value
                                if (latest.currentConvId == cid && !latest.streaming) {
                                    loadFromConversation(detail)
                                }
                            } catch (_: Throwable) {
                            }
                        }
                    } else if (runId.isNullOrBlank() && cur.streaming && !cur.activeRunId.isNullOrBlank()) {
                        viewModelScope.launch {
                            try {
                                val detail = container.network.api.getConversation(cid)
                                if (_ui.value.currentConvId == cid && detail.activeRunId.isNullOrBlank()) {
                                    loadFromConversation(detail)
                                }
                            } catch (_: Throwable) {
                            }
                        }
                    }
                }
            }
            "control.resolved" -> {
                val cid = d.str("conversation_id")
                if (cid != null && cid == _ui.value.currentConvId) {
                    clearPendingControlFromSync()
                }
            }
            "conversation.updated" -> {
                val cid = d.str("conversation_id")
                val action = d.str("action") ?: ""
                val title = d.str("title")
                if (action == "deleted" && cid != null) {
                    val wasCurrent = _ui.value.currentConvId == cid
                    _ui.update { state ->
                        state.copy(conversations = state.conversations.filterNot { it.id == cid })
                    }
                    if (wasCurrent) {
                        val fallback = _ui.value.sideConversations.firstOrNull() ?: _ui.value.mainConversation
                        if (fallback != null) openConversation(fallback.id) else openMainConversation()
                    }
                } else if (title != null && cid != null) {
                    applyTitleUpdate(cid, title)
                    val isPinned = d.bool("is_pinned")
                    if (isPinned != null) {
                        val pinnedAt = d.str("pinned_at")
                        _ui.update { state ->
                            val next = state.conversations.map { c ->
                                if (c.id == cid) c.copy(isPinned = isPinned, pinnedAt = pinnedAt) else c
                            }
                            state.copy(conversations = ConversationSorter.sort(next))
                        }
                    }
                } else {
                    syncConversationsFromServer()
                }
            }
            "library.updated" -> {
                val fileId = d.str("file_id")
                val action = d.str("action") ?: ""
                val idxStatus = d.str("index_status")
                val idxChunks = d.int("indexed_chunks")
                if (action == "deleted" && fileId != null) {
                    _ui.update { state ->
                        state.copy(
                            files = state.files.filterNot { it.id == fileId },
                            attachedIds = state.attachedIds.filterNot { it == fileId },
                        )
                    }
                } else if (action == "indexed" && fileId != null) {
                    _ui.update { state ->
                        state.copy(
                            files = state.files.map { f ->
                                if (f.id == fileId) {
                                    f.copy(
                                        indexStatus = idxStatus ?: "ready",
                                        indexedChunks = idxChunks ?: f.indexedChunks,
                                    )
                                } else f
                            }
                        )
                    }
                }
                library.handleRealtimeLibraryEvent(action, fileId, idxStatus, idxChunks)
            }
        }
    }

    private fun applyTitleUpdate(id: String, title: String) {
        _ui.update { state ->
            val target = state.conversations.firstOrNull { it.id == id }
            if (target?.kind == "main") return@update state
            state.copy(
                conversations = state.conversations.map {
                    if (it.id == id && it.kind != "main") it.copy(title = title) else it
                },
                currentConvTitle = if (state.currentConvId == id && state.currentConvKind != "main") {
                    title
                } else state.currentConvTitle,
            )
        }
    }

    private fun clearPendingControlFromSync() {
        _ui.update { state ->
            state.copy(
                pendingControl = null,
                approvingChoice = null,
                submittingClarify = false,
                messages = state.messages.map { m ->
                    if (m.id == state.activeAssistantId && m.status == "waiting") {
                        m.copy(status = "streaming")
                    } else m
                },
            )
        }
    }

    private fun hydratePendingControl(raw: JsonObject?): PendingControl? {
        if (raw == null) return null
        val rawKind = raw.str("kind")
        val rawTool = raw.str("tool")
        val kind = if (rawKind == "approval" || rawTool == "execute_code") "approval" else "clarify"
        return PendingControl(
            kind = kind,
            requestId = raw.str("request_id") ?: raw.str("prompt_id"),
            executionGeneration = raw.int("execution_generation"),
            tool = rawTool,
            preview = formatControlPreview(raw),
        )
    }

    override fun onCleared() {
        super.onCleared()
        pendingPollJob?.cancel()
        realtimeJob?.cancel()
        streamJob?.cancel()
        uploadJobs.values.forEach { it.cancel() }
    }
}
