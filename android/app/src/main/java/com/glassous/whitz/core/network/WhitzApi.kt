package com.glassous.whitz.core.network

import com.glassous.whitz.core.model.AgentStatus
import com.glassous.whitz.core.model.AuthResponse
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.ConversationDetail
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.ConversationSearchHit
import com.glassous.whitz.core.model.CreditStatus
import com.glassous.whitz.core.model.DownloadUrlResponse
import com.glassous.whitz.core.model.EmailCodeResponse
import com.glassous.whitz.core.model.GithubSkillPreviewResponse
import com.glassous.whitz.core.model.MemoryOverview
import com.glassous.whitz.core.model.PresignResponse
import com.glassous.whitz.core.model.SkillItem
import com.glassous.whitz.core.model.SkillPendingItem
import com.glassous.whitz.core.model.TicketResponse
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.model.UserSessionItem
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.HeaderMap
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
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
data class CreateConversationRequest(val title: String = "新对话")

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
data class ProfileContextRequest(val enabled: Boolean)

@Serializable
data class UpdatePasswordRequest(
    @SerialName("current_password") val currentPassword: String,
    @SerialName("new_password") val newPassword: String,
)

@Serializable
data class UpdatePersonaRequest(val persona: String)

@Serializable
data class MemorySettingsRequest(
    @SerialName("memory_enabled") val memoryEnabled: Boolean? = null,
    @SerialName("memory_require_confirm") val memoryRequireConfirm: Boolean? = null,
)

@Serializable
data class MemoryEntryRequest(
    val content: String,
    val target: String? = null,
    val category: String? = null,
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
data class GithubPreviewRequest(@SerialName("repo_url") val repoUrl: String)

@Serializable
data class GithubInstallRequest(
    @SerialName("repo_url") val repoUrl: String,
    val paths: List<String>? = null,
)

@Serializable
data class LibraryFilePatchRequest(@SerialName("is_global") val isGlobal: Boolean)

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
    suspend fun updatePersona(@Body body: UpdatePersonaRequest): Response<Unit>

    @Multipart
    @PUT("users/me/avatar")
    suspend fun uploadAvatar(@Part file: MultipartBody.Part): User

    @DELETE("users/me/avatar")
    suspend fun deleteAvatar(): Response<Unit>

    @GET("users/me/credits")
    suspend fun getCredits(): CreditStatus

    @POST("users/me/redeem")
    suspend fun redeemCode(@Body body: RedeemRequest): CreditStatus

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

    @POST("users/me/memory/entries")
    suspend fun createMemoryEntry(@Body body: MemoryEntryRequest): JsonElement

    @PATCH("users/me/memory/entries/{id}")
    suspend fun updateMemoryEntry(@Path("id") id: String, @Body body: MemoryEntryRequest): JsonElement

    @DELETE("users/me/memory/entries/{id}")
    suspend fun deleteMemoryEntry(@Path("id") id: String): Response<Unit>

    @POST("users/me/memory/pending/{id}")
    suspend fun resolveMemoryPending(@Path("id") id: String, @Body body: PendingActionRequest): Response<Unit>

    @DELETE("users/me/memory")
    suspend fun clearMemory(): Response<Unit>

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

    @POST("skills/github/preview")
    suspend fun previewGithubSkill(@Body body: GithubPreviewRequest): GithubSkillPreviewResponse

    @POST("skills/install-github")
    suspend fun installGithubSkill(@Body body: GithubInstallRequest): JsonElement

    // --- Agent ---
    @GET("agent/status")
    suspend fun getAgentStatus(): AgentStatus

    // --- Conversations ---
    @GET("conversations")
    suspend fun getConversations(): List<Conversation>

    @POST("conversations")
    suspend fun createConversation(@Body body: CreateConversationRequest): Conversation

    @GET("conversations/search")
    suspend fun searchConversations(
        @Query("q") q: String,
        @Query("limit") limit: Int = 30,
    ): List<ConversationSearchHit>

    @GET("conversations/{id}")
    suspend fun getConversation(@Path("id") id: String): ConversationDetail

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

    // --- Files & Library ---
    @GET("conversations/{id}/files")
    suspend fun getConversationFiles(@Path("id") id: String): List<ConversationFile>

    @POST("conversations/{id}/files/presign")
    suspend fun presignUpload(@Path("id") id: String, @Body body: PresignRequest): PresignResponse

    @POST("conversations/{id}/files/{fileId}/complete")
    suspend fun completeUpload(
        @Path("id") id: String,
        @Path("fileId") fileId: String,
        @Body body: CompleteUploadRequest,
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
        @Query("is_global") isGlobal: Boolean? = null,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 40,
    ): JsonElement

    @PATCH("library/files/{id}")
    suspend fun patchLibraryFile(@Path("id") id: String, @Body body: LibraryFilePatchRequest): ConversationFile

    @DELETE("library/files/{id}")
    suspend fun deleteLibraryFile(@Path("id") id: String): Response<Unit>
}
