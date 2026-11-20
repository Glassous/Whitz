package com.glassous.whitz.core.network

import com.glassous.whitz.core.storage.TokenStorage
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit

class NetworkModule(
    val storage: TokenStorage,
    val authManager: AuthManager,
) {
    private val authInterceptor = Interceptor { chain ->
        val original = chain.request()
        val path = original.url.encodedPath
        val isAuthPath = path.contains("/auth/login") ||
            path.contains("/auth/register") ||
            path.contains("/auth/email-code") ||
            path.contains("/auth/reset-password") ||
            path.contains("/auth/refresh")

        if (!isAuthPath && (storage.accessToken != null || storage.hasStoredSession()) && storage.isAccessTokenExpiringSoon()) {
            runBlocking { authManager.refreshOnce() }
        }

        val reqWithAuth = original.withBearer(storage.accessToken)
        var response = chain.proceed(reqWithAuth)

        if (response.code == 401 && !isAuthPath) {
            response.close()
            val result = runBlocking { authManager.refreshOnce() }
            if (result == RefreshResult.OK) {
                val retryReq = original.withBearer(storage.accessToken)
                response = chain.proceed(retryReq)
            } else if (result == RefreshResult.UNAUTHORIZED) {
                authManager.forceLogout(LogoutReason.EXPIRED)
            }
        } else if (response.code == 401 && !isAuthPath) {
            authManager.forceLogout(LogoutReason.EXPIRED)
        }

        response
    }

    val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(authInterceptor)
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    val sseOkHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS) // SSE long-lived stream
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    val cosOkHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    fun createApi(): WhitzApi {
        val baseUrl = storage.getApiBaseUrl().trimEnd('/') + "/"
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(WhitzJson.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(WhitzApi::class.java)
    }

    @Volatile
    var api: WhitzApi = createApi()
        private set

    fun rebuildApi() {
        api = createApi()
    }

    val sseClient: SseClient = SseClient(sseOkHttpClient, authManager)

    private fun Request.withBearer(token: String?): Request {
        if (token.isNullOrBlank()) return this
        return newBuilder()
            .header("Authorization", "Bearer $token")
            .build()
    }
}
