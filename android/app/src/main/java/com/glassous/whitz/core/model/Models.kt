package com.glassous.whitz.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class User(
    val id: String,
    val email: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("avatar_url") val avatarUrl: String? = null,
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
    @SerialName("memory_enabled") val memoryEnabled: Boolean = false,
    @SerialName("memory_consented_at") val memoryConsentedAt: String? = null,
    @SerialName("memory_require_confirm") val memoryRequireConfirm: Boolean = true,
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
    val title: String = "新对话",
    val plan: Plan? = null,
    @SerialName("active_run_id") val activeRunId: String? = null,
    @SerialName("active_run_status") val activeRunStatus: String? = null,
    @SerialName("is_pinned") val isPinned: Boolean = false,
    @SerialName("pinned_at") val pinnedAt: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("last_message_at") val lastMessageAt: String? = null,
)

@Serializable
data class ConversationDetail(
    val id: String,
    val title: String = "新对话",
    val plan: Plan? = null,
    @SerialName("active_run_id") val activeRunId: String? = null,
    @SerialName("active_run_status") val activeRunStatus: String? = null,
    @SerialName("is_pinned") val isPinned: Boolean = false,
    @SerialName("pinned_at") val pinnedAt: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("last_message_at") val lastMessageAt: String? = null,
    val messages: List<Message> = emptyList(),
)

@Serializable
data class ConversationSearchHit(
    @SerialName("conversation_id") val conversationId: String,
    @SerialName("conversation_title") val conversationTitle: String = "",
    @SerialName("message_id") val messageId: String? = null,
    val role: String? = null,
    val snippet: String = "",
    @SerialName("match_in") val matchIn: String = "title",
    @SerialName("created_at") val createdAt: String = "",
)

@Serializable
data class ReasoningTool(
    val name: String,
    @SerialName("call_id") val callId: String? = null,
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
    val source: String = "user",
    @SerialName("is_global") val isGlobal: Boolean = false,
    @SerialName("message_id") val messageId: String? = null,
    @SerialName("preview_url") val previewUrl: String? = null,
    @SerialName("thumb_url") val thumbUrl: String? = null,
    @SerialName("preview_expires_at") val previewExpiresAt: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("conversation_title") val conversationTitle: String? = null,
)

@Serializable
data class ToolPayload(
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
)

@Serializable
data class AgentStatus(
    val ready: Boolean = false,
    val status: String = "unknown",
    val version: String? = null,
    val model: String? = null,
    @SerialName("enabled_toolsets") val enabledToolsets: List<String> = emptyList(),
)

data class PendingControl(
    val kind: String, // "approval" | "clarify"
    val requestId: String? = null,
    val executionGeneration: Int? = null,
    val tool: String? = null,
    val preview: String? = null,
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
data class MemoryEntry(
    val id: String,
    val content: String,
    val target: String? = "memory",
    val category: String? = null,
    val source: String? = null,
    @SerialName("char_count") val charCount: Int? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class MemoryPendingItem(
    val id: String,
    val action: String = "add",
    val target: String? = "memory",
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
    @SerialName("memory_enabled") val memoryEnabled: Boolean = false,
    @SerialName("memory_consented_at") val memoryConsentedAt: String? = null,
    @SerialName("memory_require_confirm") val memoryRequireConfirm: Boolean = true,
    @SerialName("profile_context_enabled") val profileContextEnabled: Boolean? = null,
    @SerialName("profile_context_consented_at") val profileContextConsentedAt: String? = null,
    val entries: List<MemoryEntry> = emptyList(),
    val pending: List<MemoryPendingItem> = emptyList(),
    @SerialName("char_count") val charCount: Int? = null,
    @SerialName("char_limit") val charLimit: Int? = null,
    @SerialName("memory_char_count") val memoryCharCount: Int? = null,
    @SerialName("memory_char_limit") val memoryCharLimit: Int? = null,
    @SerialName("user_char_count") val userCharCount: Int? = null,
    @SerialName("user_char_limit") val userCharLimit: Int? = null,
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
)
