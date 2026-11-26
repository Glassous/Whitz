package com.glassous.whitz.core.model

import com.glassous.whitz.core.files.LocalPickedFile
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

@Serializable
data class User(
    val id: String,
    val email: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("avatar_url") val avatarUrl: String? = null,
    @SerialName("assistant_name") val assistantName: String = "Whitz",
    @SerialName("assistant_avatar_url") val assistantAvatarUrl: String? = null,
    val bio: String = "",
    val gender: String? = null,
    val birthday: String? = null,
    val phone: String? = null,
    val location: String? = null,
    val occupation: String? = null,
    val website: String? = null,
    @SerialName("preferred_language") val preferredLanguage: String = "zh-CN",
    val timezone: String = "Asia/Shanghai",
    val role: String = "user",
    @SerialName("is_active") val isActive: Boolean = true,
    val persona: String = "",
    @SerialName("email_verified_at") val emailVerifiedAt: String? = null,
    @SerialName("membership_tier") val membershipTier: String = "free",
    @SerialName("membership_expires_at") val membershipExpiresAt: String? = null,
    @SerialName("profile_context_enabled") val profileContextEnabled: Boolean = false,
    @SerialName("profile_context_consented_at") val profileContextConsentedAt: String? = null,
    @SerialName("memory_enabled") val memoryEnabled: Boolean = true,
    @SerialName("memory_consented_at") val memoryConsentedAt: String? = null,
    @SerialName("memory_require_confirm") val memoryRequireConfirm: Boolean = false,
    @SerialName("ai_reactions_enabled") val aiReactionsEnabled: Boolean = true,
    @SerialName("ai_posts_enabled") val aiPostsEnabled: Boolean = false,
    @SerialName("ai_posts_consented_at") val aiPostsConsentedAt: String? = null,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class CreditWindow(
    val limit: Long? = null,
    val used: Double = 0.0,
    val remaining: Double? = null,
    @SerialName("reset_at") val resetAt: String = "",
)

@Serializable
data class MembershipPlan(
    val tier: String,
    val label: String,
    @SerialName("weekly_credits") val weeklyCredits: Long = 0,
    @SerialName("five_hour_credits") val fiveHourCredits: Long? = null,
    @SerialName("max_runs_per_user") val maxRunsPerUser: Int = 1,
    @SerialName("chat_per_minute") val chatPerMinute: Int = 30,
    @SerialName("run_max_seconds") val runMaxSeconds: Int = 900,
    @SerialName("max_tool_iterations") val maxToolIterations: Int = 30,
    val summary: String = "",
)

@Serializable
data class CreditStatus(
    val tier: String = "free",
    @SerialName("tier_label") val tierLabel: String = "Free",
    @SerialName("expires_at") val expiresAt: String? = null,
    @SerialName("anchor_at") val anchorAt: String = "",
    @SerialName("tokens_per_credit") val tokensPerCredit: Long = 5000,
    val weekly: CreditWindow = CreditWindow(),
    @SerialName("five_hour") val fiveHour: CreditWindow = CreditWindow(),
    @SerialName("bonus_credits") val bonusCredits: Double = 0.0,
    val remaining: Double = 0.0,
    val overdrawn: Boolean = false,
    val plan: MembershipPlan = MembershipPlan(tier = "free", label = "Free"),
    val plans: List<MembershipPlan> = emptyList(),
)

@Serializable
data class AuthResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String = "",
    @SerialName("token_type") val tokenType: String = "bearer",
    @SerialName("expires_in") val expiresIn: Long? = null,
    @SerialName("refresh_expires_in") val refreshExpiresIn: Long? = null,
    val user: User,
)

@Serializable
data class EmailCodeResponse(
    val message: String,
    @SerialName("expires_in") val expiresIn: Int = 600,
    val cooldown: Int = 60,
)

@Serializable
data class PlanItem(
    val id: JsonElement? = null,
    val content: String = "",
    val status: String = "pending",
    val parent: JsonElement? = null,
)

@Serializable
data class Plan(
    val items: List<PlanItem> = emptyList(),
)

@Serializable
data class Conversation(
    val id: String,
    val kind: String = "side",
    val title: String = "新旁聊",
    val plan: Plan? = null,
    @SerialName("active_run_id") val activeRunId: String? = null,
    @SerialName("active_run_status") val activeRunStatus: String? = null,
    @SerialName("pending_control") val pendingControl: JsonObject? = null,
    @SerialName("is_pinned") val isPinned: Boolean = false,
    @SerialName("pinned_at") val pinnedAt: String? = null,
    @SerialName("is_scheduled") val isScheduled: Boolean = false,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("last_message_at") val lastMessageAt: String? = null,
)

@Serializable
data class ConversationDetail(
    val id: String,
    val kind: String = "side",
    val title: String = "新旁聊",
    val plan: Plan? = null,
    @SerialName("active_run_id") val activeRunId: String? = null,
    @SerialName("active_run_status") val activeRunStatus: String? = null,
    @SerialName("pending_control") val pendingControl: JsonObject? = null,
    @SerialName("is_pinned") val isPinned: Boolean = false,
    @SerialName("pinned_at") val pinnedAt: String? = null,
    @SerialName("is_scheduled") val isScheduled: Boolean = false,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("last_message_at") val lastMessageAt: String? = null,
    val messages: List<Message> = emptyList(),
)

@Serializable
data class ConversationSearchHit(
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("conversation_kind") val conversationKind: String = "side",
    @SerialName("conversation_title") val conversationTitle: String = "",
    @SerialName("is_scheduled") val isScheduled: Boolean = false,
    @SerialName("message_id") val messageId: String? = null,
    val role: String? = null,
    val snippet: String = "",
    @SerialName("match_in") val matchIn: String = "title",
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class ReasoningTool(
    val name: String,
    val label: String? = null,
    @SerialName("ui_kind") val uiKind: String? = null,
    val summary: String? = null,
    @SerialName("call_id") val callId: String? = null,
    @SerialName("parent_call_id") val parentCallId: String? = null,
    @SerialName("subagent_role") val subagentRole: String? = null,
    val args: String? = null,
    val result: String? = null,
    val status: String? = null,
    @SerialName("duration_ms") val durationMs: Double? = null,
    val error: String? = null,
)

@Serializable
data class ReasoningBlock(
    val step: Int? = null,
    @SerialName("step_id") val stepId: String? = null,
    val title: String = "",
    val text: String = "",
    val content: String = "",
    val tools: List<ReasoningTool> = emptyList(),
)

@Serializable
data class FileAttachmentMeta(
    val id: String,
    val filename: String,
    val ext: String = "",
    val category: String = "document",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
)

@Serializable
data class WorkspaceArtifactMeta(
    val id: String,
    val filename: String,
    val ext: String = "",
    val category: String = "document",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    @SerialName("mime_type") val mimeType: String? = null,
    val source: String? = "assistant",
    @SerialName("is_global") val isGlobal: Boolean? = null,
    @SerialName("message_id") val messageId: String? = null,
    @SerialName("preview_url") val previewUrl: String? = null,
    @SerialName("thumb_url") val thumbUrl: String? = null,
    @SerialName("preview_expires_at") val previewExpiresAt: String? = null,
)

@Serializable
data class ConversationFile(
    val id: String,
    @SerialName("conversation_id") val conversationId: String? = null,
    val filename: String,
    val ext: String = "",
    @SerialName("mime_type") val mimeType: String = "",
    val category: String = "document",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val status: String = "ready",
    @SerialName("index_status") val indexStatus: String = "ready",
    @SerialName("indexed_chunks") val indexedChunks: Int = 0,
    val summary: String = "",
    @SerialName("index_error") val indexError: String? = null,
    @SerialName("indexed_at") val indexedAt: String? = null,
    val source: String = "user",
    @SerialName("is_global") val isGlobal: Boolean = true,
    @SerialName("message_id") val messageId: String? = null,
    @SerialName("preview_url") val previewUrl: String? = null,
    @SerialName("thumb_url") val thumbUrl: String? = null,
    @SerialName("preview_expires_at") val previewExpiresAt: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("conversation_title") val conversationTitle: String? = null,
    @SerialName("conversation_kind") val conversationKind: String? = null,
    @SerialName("qa_snippet") val qaSnippet: String? = null,
    @SerialName("turn_role") val turnRole: String? = null,
)

enum class RagMode(val wireValue: String, val label: String, val description: String) {
    AUTO("auto", "智能融合", "自动检索资料库、长期记忆与相关历史对话"),
    FILES_ONLY("files_only", "严选资料", "仅检索已上传和资料库文件，不混合记忆与历史对话"),
    OFF("off", "关闭检索", "本轮跳过 RAG 自动预检索，直接回答"),
    ;

    companion object {
        fun fromWire(value: String?): RagMode =
            entries.firstOrNull { it.wireValue == value } ?: AUTO
    }
}

@Serializable
data class RagScope(
    val mode: String = "auto",
    @SerialName("include_memory") val includeMemory: Boolean = true,
    @SerialName("include_chats") val includeChats: Boolean = true,
    @SerialName("file_ids") val fileIds: List<String>? = null,
    val collections: List<String>? = null,
)

@Serializable
data class CitationItem(
    @SerialName("citation_id") val citationId: String,
    @SerialName("source_type") val sourceType: String = "file",
    @SerialName("source_id") val sourceId: String = "",
    @SerialName("chunk_id") val chunkId: String? = null,
    val title: String = "",
    val subtitle: String = "",
    val snippet: String = "",
    val score: Double? = null,
    val confidence: String? = null,
    val metadata: JsonObject? = null,
)

@Serializable
data class UnifiedFileSearchHit(
    val type: String = "file",
    @SerialName("file_id") val fileId: String,
    val filename: String = "",
    val locator: String = "",
    @SerialName("section_path") val sectionPath: String = "",
    @SerialName("chunk_type") val chunkType: String = "",
    val snippet: String = "",
    val score: Double = 0.0,
    val confidence: String? = null,
    @SerialName("conversation_id") val conversationId: String? = null,
)

@Serializable
data class UnifiedMemorySearchHit(
    val type: String = "memory",
    @SerialName("entry_id") val entryId: String,
    val title: String = "",
    val collection: String = "memory",
    @SerialName("collection_name") val collectionName: String = "",
    val tags: List<String> = emptyList(),
    val snippet: String = "",
    val content: String = "",
    val score: Double = 0.0,
    val confidence: String? = null,
    val timestamp: String? = null,
)

@Serializable
data class UnifiedChatSearchHit(
    val type: String = "chat",
    @SerialName("match_in") val matchIn: String = "message",
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("conversation_kind") val conversationKind: String = "side",
    @SerialName("conversation_title") val conversationTitle: String = "",
    @SerialName("message_id") val messageId: String? = null,
    val role: String? = null,
    val snippet: String = "",
    val score: Double = 0.0,
    val confidence: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class UnifiedSearchResponse(
    val query: String = "",
    val files: List<UnifiedFileSearchHit> = emptyList(),
    val memories: List<UnifiedMemorySearchHit> = emptyList(),
    val chats: List<UnifiedChatSearchHit> = emptyList(),
    val total: Int = 0,
)

@Serializable
data class LibraryContentSearchHit(
    @SerialName("file_id") val fileId: String,
    val filename: String = "",
    val locator: String = "",
    @SerialName("section_path") val sectionPath: String = "",
    @SerialName("chunk_type") val chunkType: String = "",
    val snippet: String = "",
    val content: String = "",
    val score: Double = 0.0,
    val confidence: String? = null,
)

@Serializable
data class LibraryContentSearchResponse(
    val query: String = "",
    val count: Int = 0,
    val results: List<LibraryContentSearchHit> = emptyList(),
)

data class DeliverableTarget(
    val fileId: String = "",
    val filename: String,
    val title: String? = null,
    val summary: String? = null,
    val conversationId: String? = null,
    val ext: String = "",
    val mimeType: String = "",
)

@Serializable
data class ToolPayload(
    @SerialName("call_id") val callId: String? = null,
    val args: JsonElement? = null,
    val result: JsonElement? = null,
    val duration: Double? = null,
    val error: String? = null,
    val status: String? = null,
    val usage: JsonElement? = null,
    val runtime: JsonElement? = null,
    val reasoning: List<ReasoningBlock>? = null,
    val plan: Plan? = null,
    val attachments: List<FileAttachmentMeta>? = null,
    val skills: List<String>? = null,
    val artifacts: List<WorkspaceArtifactMeta>? = null,
    val citations: List<CitationItem>? = null,
    @SerialName("rag_metrics") val ragMetrics: JsonElement? = null,
    @SerialName("scheduled_task") val scheduledTask: JsonElement? = null,
)

@Serializable
data class MessageReaction(
    val id: String,
    @SerialName("message_id") val messageId: String,
    @SerialName("author_type") val authorType: String = "user",
    val reaction: String,
    @SerialName("reason_code") val reasonCode: String? = null,
    val comment: String? = null,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class UserFeedbackItem(
    val id: String,
    @SerialName("user_id") val userId: String = "",
    val rating: Int = 5,
    val sentiment: String = "positive",
    val category: String = "general",
    val content: String = "",
    val status: String = "new",
    @SerialName("admin_note") val adminNote: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
)

@Serializable
data class Message(
    val id: String,
    val role: String,
    val content: String = "",
    @SerialName("tool_name") val toolName: String? = null,
    @SerialName("tool_payload") val toolPayload: ToolPayload? = null,
    val status: String = "completed",
    @SerialName("run_id") val runId: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    val reactions: List<MessageReaction> = emptyList(),
)

@Serializable
data class AgentStatus(
    val ready: Boolean = false,
    val status: String = "unknown",
    val version: String? = null,
    val model: String? = null,
    @SerialName("enabled_toolsets") val enabledToolsets: List<String> = emptyList(),
)

data class ClarifyQuestionItem(
    val id: String,
    val question: String,
    val options: List<String> = emptyList(),
    val multiple: Boolean = false,
    val allowCustom: Boolean = true,
    val placeholder: String? = null,
)

data class ClarifyDetail(
    val question: String? = null,
    val options: List<String> = emptyList(),
    val multiple: Boolean = false,
    val questions: List<ClarifyQuestionItem> = emptyList(),
)

@Serializable
data class ClarifyAnswerItem(
    val id: String? = null,
    val question: String? = null,
    val selected: List<String> = emptyList(),
    val text: String = "",
)

data class ClarifySubmitPayload(
    val answer: String,
    val answers: List<ClarifyAnswerItem> = emptyList(),
)

data class PendingControl(
    val kind: String, // "approval" | "clarify"
    val requestId: String? = null,
    val executionGeneration: Int? = null,
    val tool: String? = null,
    val preview: String? = null,
    val clarify: ClarifyDetail? = null,
)

@Serializable
data class SkillItem(
    val name: String,
    val title: String? = null,
    val description: String = "",
    val category: String? = null,
    val enabled: Boolean = true,
    val source: String? = null,
    val content: String? = null,
    val tags: List<String> = emptyList(),
    @SerialName("repo_url") val repoUrl: String? = null,
    val path: String? = null,
    val editable: Boolean? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class SkillPendingItem(
    val id: String,
    val name: String,
    val action: String = "create",
    val source: String? = null,
    val description: String? = null,
    val category: String? = null,
    val content: String = "",
    val reason: String? = null,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("message_id") val messageId: String? = null,
    val status: String? = "pending",
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("resolved_at") val resolvedAt: String? = null,
)

@Serializable
data class MemoryCollection(
    val id: String,
    val slug: String,
    val name: String,
    val description: String = "",
    val kind: String = "custom",
    val enabled: Boolean = true,
    @SerialName("entry_count") val entryCount: Int = 0,
    @SerialName("char_count") val charCount: Int = 0,
    @SerialName("char_limit") val charLimit: Int = 12000,
    @SerialName("max_entries") val maxEntries: Int = 200,
    @SerialName("sort_order") val sortOrder: Int = 100,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class MemoryEntry(
    val id: String,
    @SerialName("collection_id") val collectionId: String? = null,
    @SerialName("collection_name") val collectionName: String? = null,
    val title: String = "",
    val content: String,
    val tags: List<String> = emptyList(),
    val target: String? = "memory",
    val category: String? = null,
    val source: String? = null,
    @SerialName("is_pinned") val isPinned: Boolean = false,
    val priority: Int = 5,
    @SerialName("access_count") val accessCount: Int = 0,
    @SerialName("last_accessed_at") val lastAccessedAt: String? = null,
    @SerialName("supersedes_id") val supersedesId: String? = null,
    @SerialName("char_count") val charCount: Int? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class ConversationWorkingGoal(
    val title: String = "",
    val status: String = "in_progress",
    val updated: String? = null,
)

@Serializable
data class ConversationWorkingDecision(
    val decision: String = "",
    val date: String? = null,
    val reason: String? = null,
)

@Serializable
data class ConversationWorkingState(
    @SerialName("active_goals") val activeGoals: List<ConversationWorkingGoal> = emptyList(),
    @SerialName("recent_decisions") val recentDecisions: List<ConversationWorkingDecision> = emptyList(),
    @SerialName("open_questions") val openQuestions: List<String> = emptyList(),
    @SerialName("key_entities") val keyEntities: Map<String, String> = emptyMap(),
)

@Serializable
data class ConversationEpisodeItem(
    val id: String,
    @SerialName("conversation_id") val conversationId: String = "",
    @SerialName("conversation_kind") val conversationKind: String = "side",
    @SerialName("episode_index") val episodeIndex: Int = 1,
    val topic: String = "",
    val summary: String = "",
    @SerialName("key_facts") val keyFacts: List<String> = emptyList(),
    val entities: List<String> = emptyList(),
    @SerialName("start_msg_id") val startMsgId: String? = null,
    @SerialName("end_msg_id") val endMsgId: String? = null,
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("ended_at") val endedAt: String? = null,
    @SerialName("message_count") val messageCount: Int = 0,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class ConversationContextState(
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("conversation_kind") val conversationKind: String = "side",
    @SerialName("working_state") val workingState: ConversationWorkingState? = null,
    @SerialName("rolling_summary") val rollingSummary: String? = null,
    @SerialName("working_state_updated_at") val workingStateUpdatedAt: String? = null,
    val episodes: List<ConversationEpisodeItem> = emptyList(),
    @SerialName("pinned_memories_count") val pinnedMemoriesCount: Int = 0,
)

@Serializable
data class MemorySearchHit(
    val id: String,
    @SerialName("collection_id") val collectionId: String? = null,
    val target: String = "memory",
    @SerialName("collection_name") val collectionName: String = "",
    val title: String = "",
    val content: String,
    val tags: List<String> = emptyList(),
    val source: String = "manual",
    val score: Double = 0.0,
)

@Serializable
data class MemorySearchResponse(
    val query: String = "",
    val collection: String? = null,
    val count: Int = 0,
    val results: List<MemorySearchHit> = emptyList(),
)

@Serializable
data class MemoryPendingItem(
    val id: String,
    @SerialName("collection_id") val collectionId: String? = null,
    val action: String = "add",
    val target: String? = "memory",
    val title: String = "",
    val tags: List<String> = emptyList(),
    val content: String = "",
    @SerialName("old_content") val oldContent: String? = null,
    val category: String? = null,
    val reason: String? = null,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("message_id") val messageId: String? = null,
    val status: String? = "pending",
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("resolved_at") val resolvedAt: String? = null,
)

@Serializable
data class MemoryOverview(
    @SerialName("memory_enabled") val memoryEnabled: Boolean = true,
    @SerialName("memory_consented_at") val memoryConsentedAt: String? = null,
    @SerialName("memory_require_confirm") val memoryRequireConfirm: Boolean = false,
    @SerialName("profile_context_enabled") val profileContextEnabled: Boolean? = null,
    @SerialName("profile_context_consented_at") val profileContextConsentedAt: String? = null,
    val collections: List<MemoryCollection> = emptyList(),
    val entries: List<MemoryEntry> = emptyList(),
    val pending: List<MemoryPendingItem> = emptyList(),
    @SerialName("char_count") val charCount: Int? = null,
    @SerialName("char_limit") val charLimit: Int? = null,
    @SerialName("memory_char_count") val memoryCharCount: Int? = null,
    @SerialName("memory_char_limit") val memoryCharLimit: Int? = null,
    @SerialName("user_char_count") val userCharCount: Int? = null,
    @SerialName("user_char_limit") val userCharLimit: Int? = null,
    @SerialName("total_char_count") val totalCharCount: Int? = null,
    @SerialName("total_char_limit") val totalCharLimit: Int? = null,
    @SerialName("collection_limit") val collectionLimit: Int? = null,
    @SerialName("pinned_count") val pinnedCount: Int? = null,
    @SerialName("pinned_limit") val pinnedLimit: Int? = null,
)

@Serializable
data class UserSessionItem(
    @SerialName("session_id") val sessionId: String,
    @SerialName("user_agent") val userAgent: String? = null,
    @SerialName("client_ip") val clientIp: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("last_used_at") val lastUsedAt: String? = null,
    @SerialName("expires_at") val expiresAt: String = "",
    @SerialName("is_current") val isCurrent: Boolean = false,
)

@Serializable
data class TicketResponse(
    val ticket: String,
    @SerialName("expires_in") val expiresIn: Int = 60,
)

@Serializable
data class PresignResponse(
    @SerialName("file_id") val fileId: String,
    val filename: String,
    val ext: String = "",
    val category: String = "document",
    @SerialName("mime_type") val mimeType: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    @SerialName("upload_url") val uploadUrl: String,
    val method: String = "PUT",
    val headers: Map<String, String> = emptyMap(),
    @SerialName("expires_in") val expiresIn: Int = 600,
)

@Serializable
data class DownloadUrlResponse(
    val url: String,
    @SerialName("expires_in") val expiresIn: Int = 300,
)

@Serializable
data class GithubSkillPreviewResponse(
    val name: String = "",
    val description: String = "",
    val content: String = "",
    @SerialName("repo_url") val repoUrl: String = "",
    val ref: String? = null,
    val path: String? = null,
)

@Serializable
data class ScheduledTaskRun(
    val id: String,
    @SerialName("task_id") val taskId: String,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("assistant_message_id") val assistantMessageId: String? = null,
    @SerialName("run_id") val runId: String? = null,
    @SerialName("trigger_type") val triggerType: String = "scheduled",
    val status: String = "queued",
    @SerialName("scheduled_for") val scheduledFor: String? = null,
    @SerialName("started_at") val startedAt: String = "",
    @SerialName("finished_at") val finishedAt: String? = null,
    val summary: String? = null,
    val error: String? = null,
    @SerialName("tokens_used") val tokensUsed: Int = 0,
)

@Serializable
data class ScheduledTask(
    val id: String,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("target_mode") val targetMode: String = "dedicated",
    val name: String,
    val prompt: String,
    @SerialName("schedule_type") val scheduleType: String = "daily",
    @SerialName("schedule_config") val scheduleConfig: JsonObject = JsonObject(emptyMap()),
    @SerialName("schedule_description") val scheduleDescription: String = "",
    val timezone: String = "Asia/Shanghai",
    @SerialName("model_route") val modelRoute: String = "auto",
    @SerialName("skill_names") val skillNames: List<String> = emptyList(),
    val enabled: Boolean = true,
    val status: String = "active",
    @SerialName("next_run_at") val nextRunAt: String? = null,
    @SerialName("last_run_at") val lastRunAt: String? = null,
    @SerialName("last_run_status") val lastRunStatus: String? = null,
    @SerialName("last_error") val lastError: String? = null,
    @SerialName("run_count") val runCount: Int = 0,
    @SerialName("consecutive_failures") val consecutiveFailures: Int = 0,
    @SerialName("max_runs") val maxRuns: Int? = null,
    val source: String = "manual",
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    val runs: List<ScheduledTaskRun> = emptyList(),
)

@Serializable
data class ScheduledTaskPendingItem(
    val id: String,
    @SerialName("target_task_id") val targetTaskId: String? = null,
    @SerialName("conversation_id") val conversationId: String? = null,
    val action: String = "create",
    val payload: JsonObject = JsonObject(emptyMap()),
    @SerialName("schedule_description") val scheduleDescription: String = "",
    val reason: String? = null,
    val status: String? = "pending",
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class ScheduleQuota(
    val tier: String = "free",
    @SerialName("max_active_tasks") val maxActiveTasks: Int = 3,
    @SerialName("active_count") val activeCount: Int = 0,
    @SerialName("min_interval_minutes") val minIntervalMinutes: Int = 60,
)

@Serializable
data class ScheduleOverview(
    val tasks: List<ScheduledTask> = emptyList(),
    val pending: List<ScheduledTaskPendingItem> = emptyList(),
    val quota: ScheduleQuota = ScheduleQuota(),
)

@Serializable
data class SchedulePreviewResponse(
    val valid: Boolean = false,
    @SerialName("schedule_description") val scheduleDescription: String = "",
    @SerialName("next_runs") val nextRuns: List<String> = emptyList(),
    val error: String? = null,
)

@Serializable
data class SchedulePendingResolveResponse(
    val status: String = "approved",
    @SerialName("proposal_id") val proposalId: String? = null,
    val task: ScheduledTask? = null,
)

fun formatCredits(value: Double): String {
    if (!value.isFinite()) return "0"
    val rounded = kotlin.math.round(value * 100.0) / 100.0
    if (rounded % 1.0 == 0.0) return rounded.toLong().toString()
    return String.format(java.util.Locale.US, "%.2f", rounded)
        .trimEnd('0')
        .trimEnd('.')
}

/**
 * Remaining quota of one window as a percentage (0–100), mirroring the web client.
 * Returns null when the window has no limit (unlimited).
 */
fun CreditWindow.remainingPercent(): Int? {
    val cap = limit ?: return null
    if (cap <= 0L) return null
    val pct = ((cap - used) / cap.toDouble()) * 100.0
    return kotlin.math.round(pct).toInt().coerceIn(0, 100)
}

fun CreditStatus.weeklyPercent(): Int? = weekly.remainingPercent()

fun CreditStatus.fiveHourPercent(): Int? = fiveHour.remainingPercent()

/**
 * Headline percentage: Pro only relies on the weekly window, other tiers are capped by both windows.
 */
fun CreditStatus.availablePercent(): Int? {
    val weeklyPct = weeklyPercent()
    if (tier == "pro") return weeklyPct
    val fiveHourPct = fiveHourPercent()
    return when {
        weeklyPct == null -> fiveHourPct
        fiveHourPct == null -> weeklyPct
        else -> minOf(weeklyPct, fiveHourPct)
    }
}

/**
 * Compact quota summary using percentages instead of raw credit amounts, e.g. 「本周 62% · 5 小时 80%」.
 * Matches the wording used on the web sidebar quick card.
 */
fun CreditStatus.quotaPercentLabel(): String {
    val parts = buildList {
        add(weeklyPercent()?.let { "本周 $it%" } ?: "本周不限")
        if (tier != "pro") {
            fiveHourPercent()?.let { add("5 小时 $it%") }
        }
    }
    return parts.joinToString(" · ")
}

enum class ThemePreference {
    SYSTEM, LIGHT, DARK
}

enum class UploadTaskStatus {
    SIGNING, UPLOADING, COMPLETING, ERROR
}

data class UploadTask(
    val localId: String,
    val filename: String,
    val ext: String,
    val category: String,
    val sizeBytes: Long,
    val progress: Int = 0,
    val status: UploadTaskStatus = UploadTaskStatus.SIGNING,
    val error: String? = null,
    val localFile: LocalPickedFile? = null,
)

fun User.resolvedAssistantName(): String = assistantName.trim().ifEmpty { "Whitz" }

fun Conversation.isScheduledSide(): Boolean =
    kind != "main" && (isScheduled || title.startsWith("[定时]"))

fun Conversation.displaySideTitle(): String {
    val raw = title.ifBlank { "新旁聊" }
    if (!isScheduledSide()) return raw
    return raw.replace(Regex("^\\[定时\\]\\s*"), "").trim().ifEmpty { raw }
}

fun ConversationSearchHit.isScheduledSide(): Boolean =
    conversationKind != "main" && (isScheduled || conversationTitle.startsWith("[定时]"))

fun ConversationSearchHit.displayTitle(assistantName: String): String {
    if (conversationKind == "main") return assistantName
    val raw = conversationTitle.ifBlank { "无标题聊天" }
    if (!isScheduledSide()) return raw
    return raw.replace(Regex("^\\[定时\\]\\s*"), "").trim().ifEmpty { raw }
}

fun resolveServerAssetUrl(apiBaseUrl: String, pathOrUrl: String?): String? {
    val raw = pathOrUrl?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    if (raw.startsWith("http://") || raw.startsWith("https://") || raw.startsWith("data:")) {
        return raw
    }
    return try {
        java.net.URI(apiBaseUrl.trimEnd('/') + "/").resolve(raw).toString()
    } catch (_: Exception) {
        raw
    }
}

@Serializable
data class PostWebSource(
    val title: String = "",
    val url: String = "",
    @SerialName("site_name") val siteName: String = "",
    @SerialName("published_at") val publishedAt: String = "",
)

@Serializable
data class PostCommentItem(
    val id: String,
    @SerialName("post_id") val postId: String,
    @SerialName("author_type") val authorType: String = "user",
    val content: String = "",
    @SerialName("reply_to_id") val replyToId: String? = null,
    @SerialName("reply_to_author_type") val replyToAuthorType: String? = null,
    @SerialName("reply_to_excerpt") val replyToExcerpt: String? = null,
    @SerialName("ai_liked") val aiLiked: Boolean = false,
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class PostItem(
    val id: String,
    @SerialName("author_type") val authorType: String = "ai",
    @SerialName("post_kind") val postKind: String = "opinion",
    val title: String = "",
    val content: String = "",
    val tags: List<String> = emptyList(),
    @SerialName("web_sources") val webSources: List<PostWebSource> = emptyList(),
    @SerialName("source_collection_id") val sourceCollectionId: String? = null,
    @SerialName("source_collection_name") val sourceCollectionName: String? = null,
    @SerialName("source_memory_ids") val sourceMemoryIds: List<String> = emptyList(),
    @SerialName("memory_entry_id") val memoryEntryId: String? = null,
    @SerialName("is_liked") val isLiked: Boolean = false,
    @SerialName("ai_liked") val aiLiked: Boolean = false,
    @SerialName("is_bookmarked") val isBookmarked: Boolean = false,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("comment_count") val commentCount: Int = 0,
    val comments: List<PostCommentItem> = emptyList(),
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
)

@Serializable
data class PostQuotaSummary(
    @SerialName("ai_posts_enabled") val aiPostsEnabled: Boolean = false,
    @SerialName("ai_posts_consented_at") val aiPostsConsentedAt: String? = null,
    @SerialName("memory_enabled") val memoryEnabled: Boolean = true,
    val tier: String = "free",
    @SerialName("tier_label") val tierLabel: String = "Free",
    @SerialName("max_daily_cap") val maxDailyCap: Int = 2,
    @SerialName("memory_entry_count") val memoryEntryCount: Int = 0,
    @SerialName("active_collection_count") val activeCollectionCount: Int = 0,
    @SerialName("estimated_daily_count") val estimatedDailyCount: Int = 0,
    @SerialName("today_generated_count") val todayGeneratedCount: Int = 0,
    @SerialName("today_status") val todayStatus: String? = null,
    @SerialName("local_date") val localDate: String = "",
)

@Serializable
data class PostListResponse(
    val items: List<PostItem> = emptyList(),
    @SerialName("next_cursor") val nextCursor: String? = null,
    val quota: PostQuotaSummary = PostQuotaSummary(),
)

@Serializable
data class PostCommentCreateResponse(
    val comment: PostCommentItem,
    @SerialName("ai_reply_scheduled") val aiReplyScheduled: Boolean = false,
)

@Serializable
data class PostDiscussResponse(
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("prefill_prompt") val prefillPrompt: String = "",
)
