package com.glassous.whitz.core.network

import com.glassous.whitz.core.model.AgentStatus
import com.glassous.whitz.core.model.AuthResponse
import com.glassous.whitz.core.model.ClarifyAnswerItem
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.ConversationContextState
import com.glassous.whitz.core.model.ConversationDetail
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.ConversationSearchHit
import com.glassous.whitz.core.model.ConversationWorkingState
import com.glassous.whitz.core.model.CreditStatus
import com.glassous.whitz.core.model.DownloadUrlResponse
import com.glassous.whitz.core.model.EmailCodeResponse
import com.glassous.whitz.core.model.GithubSkillPreviewResponse
import com.glassous.whitz.core.model.LibraryContentSearchResponse
import com.glassous.whitz.core.model.MemoryOverview
import com.glassous.whitz.core.model.MemorySearchResponse
import com.glassous.whitz.core.model.MessageReaction
import com.glassous.whitz.core.model.PostCommentCreateResponse
import com.glassous.whitz.core.model.PostDiscussResponse
import com.glassous.whitz.core.model.PostItem
import com.glassous.whitz.core.model.PostListResponse
import com.glassous.whitz.core.model.PostQuotaSummary
import com.glassous.whitz.core.model.PresignResponse
import com.glassous.whitz.core.model.ScheduleOverview
import com.glassous.whitz.core.model.SchedulePendingResolveResponse
import com.glassous.whitz.core.model.SchedulePreviewResponse
import com.glassous.whitz.core.model.ScheduledTask
import com.glassous.whitz.core.model.ScheduledTaskPendingItem
import com.glassous.whitz.core.model.ScheduledTaskRun
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.core.model.TicketResponse
import com.glassous.whitz.core.model.UnifiedSearchResponse
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.model.UserFeedbackItem
import com.glassous.whitz.core.model.UserSessionItem
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.HeaderMap
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

@Serializable
data class EmailCodeRequest(val email: String, val purpose: String)

@Serializable
data class LoginRequest(val identifier: String, val password: String)

@Serializable
data class LoginCodeRequest(val email: String, val code: String)

@Serializable
data class RegisterRequest(
    val email: String,
    val code: String,
    val password: String,
    @SerialName("display_name") val displayName: String,
)

@Serializable
data class ResetPasswordRequest(
    val email: String,
    val code: String,
    @SerialName("new_password") val newPassword: String,
)

@Serializable
data class RefreshRequest(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class CreateConversationRequest(val title: String = "新旁聊")

@Serializable
data class PatchConversationRequest(
    val title: String? = null,
    @SerialName("is_pinned") val isPinned: Boolean? = null,
)

@Serializable
data class TicketRequest(val action: String, val nonce: String)

@Serializable
data class ApprovalRequest(
    @SerialName("request_id") val requestId: String?,
    @SerialName("execution_generation") val executionGeneration: Int?,
    val choice: String,
)

@Serializable
data class ClarifyRequest(
    @SerialName("request_id") val requestId: String?,
    @SerialName("execution_generation") val executionGeneration: Int?,
    val answer: String,
    val answers: List<ClarifyAnswerItem>? = null,
)

@Serializable
data class PresignRequest(
    val filename: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long,
)

@Serializable
data class CompleteUploadRequest(val etag: String? = null)

@Serializable
data class AttachFilesRequest(@SerialName("file_ids") val fileIds: List<String>)

@Serializable
data class CreateTextFileRequest(
    val filename: String,
    val content: String = "",
    val overwrite: Boolean = false,
)

@Serializable
data class UpdateFileContentRequest(
    val content: String,
)

@Serializable
data class RenameFileRequest(
    val filename: String,
)

@Serializable
data class RedeemRequest(val code: String)

@Serializable
data class UpdateProfileRequest(
    @SerialName("display_name") val displayName: String,
    val bio: String = "",
    val gender: String? = null,
    val birthday: String? = null,
    val phone: String? = null,
    val location: String? = null,
    val occupation: String? = null,
    val website: String? = null,
    @SerialName("preferred_language") val preferredLanguage: String = "zh-CN",
    val timezone: String = "Asia/Shanghai",
)

@Serializable
data class ProfileContextRequest(
    val enabled: Boolean,
    val consent: Boolean = false,
)

@Serializable
data class UpdatePasswordRequest(
    @SerialName("old_password") val oldPassword: String,
    @SerialName("new_password") val newPassword: String,
)

@Serializable
data class AvatarUploadRequest(@SerialName("data_url") val dataUrl: String)

@Serializable
data class UpdatePersonaRequest(val persona: String)

@Serializable
data class UpdateAssistantRequest(@SerialName("assistant_name") val assistantName: String? = null)

@Serializable
data class MemorySettingsRequest(
    val enabled: Boolean? = null,
    @SerialName("require_confirm") val requireConfirm: Boolean? = null,
    val consent: Boolean = false,
)

@Serializable
data class MemoryCollectionCreateRequest(
    val name: String,
    val slug: String? = null,
    val description: String = "",
    @SerialName("char_limit") val charLimit: Int = 12000,
)

@Serializable
data class MemoryCollectionUpdateRequest(
    val name: String? = null,
    val description: String? = null,
    val enabled: Boolean? = null,
    @SerialName("char_limit") val charLimit: Int? = null,
)

@Serializable
data class MemorySearchRequest(
    val query: String,
    val collection: String? = null,
    val limit: Int = 20,
)

@Serializable
data class MemoryEntryRequest(
    val content: String,
    val target: String? = null,
    val title: String = "",
    val tags: List<String> = emptyList(),
    val category: String? = null,
)

@Serializable
data class MemoryEntryPatchRequest(
    val content: String? = null,
    val target: String? = null,
    val title: String? = null,
    val tags: List<String>? = null,
    val category: String? = null,
    @SerialName("is_pinned") val isPinned: Boolean? = null,
    val priority: Int? = null,
)

@Serializable
data class WorkingStateUpdateRequest(
    @SerialName("working_state") val workingState: ConversationWorkingState,
)

@Serializable
data class PendingActionRequest(
    val action: String,
    val content: String? = null,
)

@Serializable
data class SkillPatchRequest(val enabled: Boolean)

@Serializable
data class CreateSkillRequest(
    val name: String,
    val description: String = "",
    val category: String? = null,
    val content: String,
    val enabled: Boolean = true,
)

@Serializable
data class GithubPreviewRequest(
    val url: String,
    val ref: String? = null,
    val path: String? = null,
)

@Serializable
data class GithubInstallRequest(
    val url: String,
    val name: String? = null,
    val ref: String? = null,
    val path: String? = null,
    val enabled: Boolean = true,
)

@Serializable
data class LibraryFilePatchRequest(@SerialName("is_global") val isGlobal: Boolean)

@Serializable
data class UpdateAiReactionsRequest(
    @SerialName("ai_reactions_enabled") val aiReactionsEnabled: Boolean,
)

@Serializable
data class UpdateAiPostsRequest(
    @SerialName("ai_posts_enabled") val aiPostsEnabled: Boolean,
)

@Serializable
data class PostCreateRequest(
    val title: String = "",
    val content: String,
    val tags: List<String> = emptyList(),
)

@Serializable
data class PostCommentCreateRequest(
    val content: String,
    @SerialName("reply_to_id") val replyToId: String? = null,
    @SerialName("trigger_ai_reply") val triggerAiReply: Boolean = true,
)

@Serializable
data class UserFeedbackCreateRequest(
    val rating: Int,
    val category: String,
    val content: String,
)

@Serializable
data class MessageReactionCreateRequest(
    val reaction: String,
    @SerialName("reason_code") val reasonCode: String? = null,
    val comment: String? = null,
)

@Serializable
data class SchedulePreviewRequest(
    @SerialName("schedule_type") val scheduleType: String,
    @SerialName("schedule_config") val scheduleConfig: JsonObject,
    val timezone: String? = null,
    val count: Int = 5,
)

@Serializable
data class ScheduledTaskCreateRequest(
    val name: String,
    val prompt: String,
    @SerialName("schedule_type") val scheduleType: String,
    @SerialName("schedule_config") val scheduleConfig: JsonObject,
    val timezone: String? = null,
    @SerialName("target_mode") val targetMode: String = "dedicated",
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("model_route") val modelRoute: String = "auto",
    @SerialName("skill_names") val skillNames: List<String> = emptyList(),
    val enabled: Boolean = true,
)

@Serializable
data class ScheduledTaskUpdateRequest(
    val name: String? = null,
    val prompt: String? = null,
    @SerialName("schedule_type") val scheduleType: String? = null,
    @SerialName("schedule_config") val scheduleConfig: JsonObject? = null,
    val timezone: String? = null,
    @SerialName("target_mode") val targetMode: String? = null,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("model_route") val modelRoute: String? = null,
    @SerialName("skill_names") val skillNames: List<String>? = null,
    val enabled: Boolean? = null,
)

@Serializable
data class SchedulePendingResolveRequest(val action: String)

interface WhitzApi {
    // --- Auth ---
    @POST("auth/email-code")
    suspend fun sendEmailCode(@Body body: EmailCodeRequest): EmailCodeResponse

    @POST("auth/login")
    suspend fun login(@Body body: LoginRequest): AuthResponse

    @POST("auth/login/code")
    suspend fun loginWithCode(@Body body: LoginCodeRequest): AuthResponse

    @POST("auth/register")
    suspend fun register(@Body body: RegisterRequest): AuthResponse

    @POST("auth/reset-password")
    suspend fun resetPassword(@Body body: ResetPasswordRequest): Response<Unit>

    @POST("auth/refresh")
    suspend fun refresh(@Body body: RefreshRequest): Response<AuthResponse>

    @POST("auth/logout")
    suspend fun logout(@Body body: RefreshRequest): Response<Unit>

    // --- User & Settings ---
    @GET("users/me")
    suspend fun getMe(): User

    @PATCH("users/me")
    suspend fun updateMe(@Body body: UpdateProfileRequest): User

    @PATCH("users/me/profile-context")
    suspend fun updateProfileContext(@Body body: ProfileContextRequest): User

    @PUT("users/me/password")
    suspend fun updatePassword(@Body body: UpdatePasswordRequest): Response<Unit>

    @PUT("users/me/persona")
    suspend fun updatePersona(@Body body: UpdatePersonaRequest): User

    @PUT("users/me/avatar")
    suspend fun uploadAvatar(@Body body: AvatarUploadRequest): User

    @DELETE("users/me/avatar")
    suspend fun deleteAvatar(): User

    @PATCH("users/me/assistant")
    suspend fun updateAssistantProfile(@Body body: UpdateAssistantRequest): User

    @PUT("users/me/assistant/avatar")
    suspend fun uploadAssistantAvatar(@Body body: AvatarUploadRequest): User

    @DELETE("users/me/assistant/avatar")
    suspend fun deleteAssistantAvatar(): User

    @GET("users/me/credits")
    suspend fun getCredits(): CreditStatus

    @POST("users/me/redeem")
    suspend fun redeemCode(@Body body: RedeemRequest): CreditStatus

    @PUT("users/me/ai-reactions")
    suspend fun updateAiReactions(@Body body: UpdateAiReactionsRequest): User

    @GET("users/me/feedback")
    suspend fun getMyFeedback(): List<UserFeedbackItem>

    @POST("users/me/feedback")
    suspend fun createMyFeedback(@Body body: UserFeedbackCreateRequest): UserFeedbackItem

    // --- Sessions / Devices ---
    @GET("users/me/sessions")
    suspend fun getSessions(): List<UserSessionItem>

    @DELETE("users/me/sessions/{id}")
    suspend fun deleteSession(@Path("id") id: String): Response<Unit>

    @DELETE("users/me/sessions")
    suspend fun deleteOtherSessions(): Response<Unit>

    // --- Memory ---
    @GET("users/me/memory")
    suspend fun getMemory(): MemoryOverview

    @PUT("users/me/memory/settings")
    suspend fun updateMemorySettings(@Body body: MemorySettingsRequest): MemoryOverview

    @POST("users/me/memory/collections")
    suspend fun createMemoryCollection(@Body body: MemoryCollectionCreateRequest): MemoryOverview

    @PATCH("users/me/memory/collections/{id}")
    suspend fun updateMemoryCollection(@Path("id") id: String, @Body body: MemoryCollectionUpdateRequest): MemoryOverview

    @DELETE("users/me/memory/collections/{id}")
    suspend fun deleteMemoryCollection(@Path("id") id: String): MemoryOverview

    @POST("users/me/memory/search")
    suspend fun searchMemory(@Body body: MemorySearchRequest): MemorySearchResponse

    @POST("users/me/memory/entries")
    suspend fun createMemoryEntry(@Body body: MemoryEntryRequest): JsonElement

    @PATCH("users/me/memory/entries/{id}")
    suspend fun updateMemoryEntry(@Path("id") id: String, @Body body: MemoryEntryRequest): JsonElement

    @PATCH("users/me/memory/entries/{id}")
    suspend fun patchMemoryEntry(@Path("id") id: String, @Body body: MemoryEntryPatchRequest): MemoryOverview

    @DELETE("users/me/memory/entries/{id}")
    suspend fun deleteMemoryEntry(@Path("id") id: String): Response<Unit>

    @POST("users/me/memory/pending/{id}")
    suspend fun resolveMemoryPending(@Path("id") id: String, @Body body: PendingActionRequest): Response<Unit>

    @DELETE("users/me/memory")
    suspend fun clearMemory(@Query("collection_id") collectionId: String? = null): Response<Unit>

    // --- Skills ---
    @GET("skills")
    suspend fun getSkills(): List<SkillItem>

    @GET("skills/pending")
    suspend fun getPendingSkills(): List<SkillPendingItem>

    @POST("skills")
    suspend fun createSkill(@Body body: CreateSkillRequest): JsonElement

    @PATCH("skills/{name}")
    suspend fun patchSkill(@Path("name", encoded = true) name: String, @Body body: SkillPatchRequest): JsonElement

    @DELETE("skills/{name}")
    suspend fun deleteSkill(@Path("name", encoded = true) name: String): Response<Unit>

    @POST("skills/pending/{id}")
    suspend fun resolveSkillPending(@Path("id") id: String, @Body body: PendingActionRequest): Response<Unit>

    @POST("skills/preview-github")
    suspend fun previewGithubSkill(@Body body: GithubPreviewRequest): GithubSkillPreviewResponse

    @POST("skills/install-github")
    suspend fun installGithubSkill(@Body body: GithubInstallRequest): SkillItem

    // --- Agent ---
    @GET("agent/status")
    suspend fun getAgentStatus(): AgentStatus

    // --- Conversations ---
    @GET("conversations")
    suspend fun getConversations(): List<Conversation>

    @GET("conversations/main")
    suspend fun getMainConversation(): ConversationDetail

    @POST("conversations")
    suspend fun createConversation(@Body body: CreateConversationRequest): Conversation

    @GET("conversations/search")
    suspend fun searchConversations(
        @Query("q") q: String,
        @Query("limit") limit: Int = 30,
    ): List<ConversationSearchHit>

    @GET("search/unified")
    suspend fun unifiedSearch(
        @Query("q") q: String,
        @Query("sources") sources: String = "all",
        @Query("limit") limit: Int = 12,
    ): UnifiedSearchResponse

    @GET("conversations/{id}")
    suspend fun getConversation(@Path("id") id: String): ConversationDetail

    @GET("conversations/{id}/context-state")
    suspend fun getConversationContextState(@Path("id") id: String): ConversationContextState

    @PATCH("conversations/{id}/working-state")
    suspend fun updateConversationWorkingState(
        @Path("id") id: String,
        @Body body: WorkingStateUpdateRequest,
    ): ConversationContextState

    @POST("conversations/{id}/archive-episode")
    suspend fun archiveConversationEpisode(@Path("id") id: String): ConversationContextState

    @PATCH("conversations/{id}")
    suspend fun patchConversation(@Path("id") id: String, @Body body: PatchConversationRequest): Conversation

    @DELETE("conversations/{id}")
    suspend fun deleteConversation(@Path("id") id: String): Response<Unit>

    @POST("conversations/{id}/tickets")
    suspend fun createTicket(@Path("id") id: String, @Body body: TicketRequest): TicketResponse

    @POST("conversations/{id}/stop")
    suspend fun stopRun(
        @Path("id") id: String,
        @HeaderMap headers: Map<String, String>,
    ): Response<Unit>

    @POST("conversations/{id}/approval")
    suspend fun submitApproval(
        @Path("id") id: String,
        @Body body: ApprovalRequest,
        @HeaderMap headers: Map<String, String>,
    ): Response<Unit>

    @POST("conversations/{id}/clarify")
    suspend fun submitClarify(
        @Path("id") id: String,
        @Body body: ClarifyRequest,
        @HeaderMap headers: Map<String, String>,
    ): Response<Unit>

    @POST("conversations/{id}/messages/{messageId}/reactions")
    suspend fun reactToMessage(
        @Path("id") id: String,
        @Path("messageId") messageId: String,
        @Body body: MessageReactionCreateRequest,
    ): MessageReaction

    @DELETE("conversations/{id}/messages/{messageId}/reactions")
    suspend fun deleteMessageReaction(
        @Path("id") id: String,
        @Path("messageId") messageId: String,
    ): Response<Unit>

    // --- Files & Library ---
    @GET("conversations/{id}/files")
    suspend fun getConversationFiles(
        @Path("id") id: String,
        @Query("scope") scope: String = "conversation",
    ): List<ConversationFile>

    @POST("conversations/{id}/files/presign")
    suspend fun presignUpload(@Path("id") id: String, @Body body: PresignRequest): PresignResponse

    @POST("conversations/{id}/files/text")
    suspend fun createTextFile(
        @Path("id") id: String,
        @Body body: CreateTextFileRequest,
    ): ConversationFile

    @POST("conversations/{id}/files/{fileId}/complete")
    suspend fun completeUpload(
        @Path("id") id: String,
        @Path("fileId") fileId: String,
        @Body body: CompleteUploadRequest,
    ): ConversationFile

    @PUT("conversations/{id}/files/{fileId}/content")
    suspend fun updateFileContent(
        @Path("id") id: String,
        @Path("fileId") fileId: String,
        @Body body: UpdateFileContentRequest,
    ): ConversationFile

    @PATCH("conversations/{id}/files/{fileId}")
    suspend fun renameConversationFile(
        @Path("id") id: String,
        @Path("fileId") fileId: String,
        @Body body: RenameFileRequest,
    ): ConversationFile

    @DELETE("conversations/{id}/files/{fileId}")
    suspend fun deleteConversationFile(@Path("id") id: String, @Path("fileId") fileId: String): Response<Unit>

    @GET("conversations/{id}/files/{fileId}/download-url")
    suspend fun getDownloadUrl(
        @Path("id") id: String,
        @Path("fileId") fileId: String,
        @Query("inline") inline: Boolean = false,
    ): DownloadUrlResponse

    @GET("conversations/{id}/files/{fileId}/preview-content")
    suspend fun getPreviewContent(
        @Path("id") id: String,
        @Path("fileId") fileId: String,
    ): ResponseBody

    @POST("conversations/{id}/files/attach")
    suspend fun attachFiles(
        @Path("id") id: String,
        @Body body: AttachFilesRequest,
    ): JsonElement

    @GET("library/files")
    suspend fun getLibraryFiles(
        @Query("q") q: String? = null,
        @Query("category") category: String? = null,
        @Query("source") source: String? = null,
        @Query("is_global") isGlobal: Boolean? = null,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 40,
    ): JsonElement

    @GET("library/search")
    suspend fun searchLibraryContent(
        @Query("q") q: String,
        @Query("limit") limit: Int = 15,
    ): LibraryContentSearchResponse

    @POST("library/files/{fileId}/reindex")
    suspend fun reindexLibraryFile(
        @Path("fileId") fileId: String,
    ): ConversationFile

    @POST("library/files/presign")
    suspend fun presignLibraryUpload(@Body body: PresignRequest): PresignResponse

    @POST("library/files/{fileId}/complete")
    suspend fun completeLibraryUpload(
        @Path("fileId") fileId: String,
        @Body body: CompleteUploadRequest,
    ): ConversationFile

    @GET("library/files/{fileId}/download-url")
    suspend fun getLibraryDownloadUrl(
        @Path("fileId") fileId: String,
        @Query("inline") inline: Boolean = false,
    ): DownloadUrlResponse

    @GET("library/files/{fileId}/preview-content")
    suspend fun getLibraryPreviewContent(
        @Path("fileId") fileId: String,
    ): ResponseBody

    @PATCH("library/files/{id}")
    suspend fun patchLibraryFile(@Path("id") id: String, @Body body: LibraryFilePatchRequest): ConversationFile

    @DELETE("library/files/{id}")
    suspend fun deleteLibraryFile(@Path("id") id: String): Response<Unit>

    // --- Scheduled Tasks ---
    @GET("schedules")
    suspend fun getSchedules(): ScheduleOverview

    @POST("schedules/preview")
    suspend fun previewSchedule(@Body body: SchedulePreviewRequest): SchedulePreviewResponse

    @GET("schedules/pending")
    suspend fun getPendingSchedules(): List<ScheduledTaskPendingItem>

    @POST("schedules/pending/{id}")
    suspend fun resolveSchedulePending(
        @Path("id") id: String,
        @Body body: SchedulePendingResolveRequest,
    ): SchedulePendingResolveResponse

    @POST("schedules")
    suspend fun createSchedule(@Body body: ScheduledTaskCreateRequest): ScheduledTask

    @GET("schedules/{id}")
    suspend fun getScheduleDetail(
        @Path("id") id: String,
        @Query("runs_limit") runsLimit: Int = 20,
    ): ScheduledTask

    @PATCH("schedules/{id}")
    suspend fun updateSchedule(
        @Path("id") id: String,
        @Body body: ScheduledTaskUpdateRequest,
    ): ScheduledTask

    @DELETE("schedules/{id}")
    suspend fun deleteSchedule(@Path("id") id: String): Response<Unit>

    @POST("schedules/{id}/run-now")
    suspend fun runScheduleNow(@Path("id") id: String): ScheduledTaskRun

    // --- Private AI & User Posts ---
    @PUT("users/me/ai-posts")
    suspend fun updateAiPosts(@Body body: UpdateAiPostsRequest): User

    @GET("posts")
    suspend fun getPosts(
        @Query("author_type") authorType: String? = null,
        @Query("bookmarked_only") bookmarkedOnly: Boolean = false,
        @Query("collection_id") collectionId: String? = null,
        @Query("post_kind") postKind: String? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int = 20,
    ): PostListResponse

    @GET("posts/quota")
    suspend fun getPostQuota(): PostQuotaSummary

    @POST("posts")
    suspend fun createPost(@Body body: PostCreateRequest): PostItem

    @GET("posts/{id}")
    suspend fun getPostDetail(@Path("id") id: String): PostItem

    @DELETE("posts/{id}")
    suspend fun deletePost(@Path("id") id: String): Response<Unit>

    @POST("posts/{id}/like")
    suspend fun togglePostLike(@Path("id") id: String): PostItem

    @POST("posts/{id}/bookmark")
    suspend fun togglePostBookmark(@Path("id") id: String): PostItem

    @POST("posts/{id}/comments")
    suspend fun createPostComment(
        @Path("id") id: String,
        @Body body: PostCommentCreateRequest,
    ): PostCommentCreateResponse

    @DELETE("posts/{postId}/comments/{commentId}")
    suspend fun deletePostComment(
        @Path("postId") postId: String,
        @Path("commentId") commentId: String,
    ): Response<Unit>

    @POST("posts/{id}/discuss")
    suspend fun discussPostInChat(@Path("id") id: String): PostDiscussResponse
}
