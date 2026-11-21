package com.glassous.whitz.core.network

import com.glassous.whitz.core.model.AuthResponse
import com.glassous.whitz.core.model.User
import com.glassous.whitz.core.storage.TokenStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

enum class LogoutReason { MANUAL, EXPIRED }

data class LogoutNotice(
    val reason: LogoutReason,
    val message: String,
)

enum class RefreshResult { OK, UNAUTHORIZED, ERROR }

class AuthManager(
    val storage: TokenStorage,
    private val onClearSession: () -> Unit = {},
) {
    private val refreshMutex = Mutex()
    private val rawClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()

    private val _user = MutableStateFlow<User?>(storage.getUser())
    val user: StateFlow<User?> = _user.asStateFlow()

    private val _ready = MutableStateFlow(false)
    val ready: StateFlow<Boolean> = _ready.asStateFlow()

    private val _logoutNotice = MutableStateFlow<LogoutNotice?>(null)
    val logoutNotice: StateFlow<LogoutNotice?> = _logoutNotice.asStateFlow()

    val isAuthenticated: Boolean
        get() = _user.value != null

    fun applySession(auth: AuthResponse) {
        _logoutNotice.value = null
        storage.setAccessToken(auth.accessToken)
        if (auth.refreshToken.isNotBlank()) {
            storage.saveRefreshToken(auth.refreshToken)
        }
        storage.saveUser(auth.user)
        _user.value = auth.user
    }

    fun updateUser(user: User) {
        storage.saveUser(user)
        _user.value = user
    }

    fun clearLogoutNotice() {
        _logoutNotice.value = null
    }

    fun forceLogout(reason: LogoutReason? = null, customMessage: String? = null) {
        storage.clearSession()
        onClearSession()
        _user.value = null
        if (reason != null) {
            val defaultMsg = when (reason) {
                LogoutReason.MANUAL -> "你已安全退出登录，如需继续使用请重新登录。"
                LogoutReason.EXPIRED -> "登录状态已过期，请重新登录。"
            }
            _logoutNotice.value = LogoutNotice(reason, customMessage ?: defaultMsg)
        }
    }

    suspend fun init(fetchMe: suspend () -> User) {
        if (storage.hasStoredSession()) {
            val res = refreshOnce()
            when (res) {
                RefreshResult.OK -> {
                    try {
                        val fresh = fetchMe()
                        updateUser(fresh)
                        _logoutNotice.value = null
                    } catch (_: Exception) {
                        if (storage.accessToken.isNullOrBlank()) {
                            forceLogout(LogoutReason.EXPIRED)
                        } else {
                            _user.value = storage.getUser()
                        }
                    }
                }
                RefreshResult.UNAUTHORIZED -> {
                    forceLogout(LogoutReason.EXPIRED)
                }
                RefreshResult.ERROR -> {
                    _user.value = null
                }
            }
        } else {
            _user.value = null
        }
        _ready.value = true
    }

    suspend fun refreshOnce(force: Boolean = false): RefreshResult = refreshMutex.withLock {
        if (!force && !storage.isAccessTokenExpiringSoon()) {
            return@withLock RefreshResult.OK
        }
        withContext(Dispatchers.IO) {
            val refreshToken = storage.getRefreshToken()
            if (refreshToken.isNullOrBlank()) {
                return@withContext RefreshResult.UNAUTHORIZED
            }
            val url = "${storage.getApiBaseUrl()}/auth/refresh"
            val bodyJson = WhitzJson.encodeToString(RefreshRequest.serializer(), RefreshRequest(refreshToken))
            val req = Request.Builder()
                .url(url)
                .post(bodyJson.toRequestBody("application/json; charset=utf-8".toMediaType()))
                .build()
            try {
                rawClient.newCall(req).execute().use { resp ->
                    if (resp.code == 401 || resp.code == 403) {
                        return@withContext RefreshResult.UNAUTHORIZED
                    }
                    if (!resp.isSuccessful) {
                        return@withContext RefreshResult.ERROR
                    }
                    val bodyStr = resp.body?.string() ?: return@withContext RefreshResult.ERROR
                    val auth = WhitzJson.decodeFromString(AuthResponse.serializer(), bodyStr)
                    applySession(auth)
                    return@withContext RefreshResult.OK
                }
            } catch (_: Exception) {
                return@withContext RefreshResult.ERROR
            }
        }
    }

    suspend fun revokeSession() {
        withContext(Dispatchers.IO) {
            val refreshToken = storage.getRefreshToken()
            if (!refreshToken.isNullOrBlank()) {
                try {
                    val url = "${storage.getApiBaseUrl()}/auth/logout"
                    val bodyJson = WhitzJson.encodeToString(RefreshRequest.serializer(), RefreshRequest(refreshToken))
                    val req = Request.Builder()
                        .url(url)
                        .post(bodyJson.toRequestBody("application/json; charset=utf-8".toMediaType()))
                        .build()
                    rawClient.newCall(req).execute().close()
                } catch (_: Exception) {
                    /* ignore */
                }
            }
        }
        forceLogout(LogoutReason.MANUAL)
    }
}
