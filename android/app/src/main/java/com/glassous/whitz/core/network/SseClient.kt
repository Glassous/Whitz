package com.glassous.whitz.core.network

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.DisposableHandle
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSource
import java.io.IOException
import java.util.concurrent.TimeUnit

data class SseEvent(
    val id: String? = null,
    val event: String,
    val data: JsonObject,
)

object SseParser {
    fun parseBlock(block: String): SseEvent? {
        var eventType = ""
        var eventId: String? = null
        val dataLines = mutableListOf<String>()
        for (rawLine in block.split('\n')) {
            val line = rawLine.trimEnd('\r')
            if (line.isBlank() || line.startsWith(':')) continue
            when {
                line.startsWith("event:") -> eventType = line.substring(6).trim()
                line.startsWith("id:") -> {
                    val parsed = line.substring(3).trim()
                    if (parsed.isNotEmpty()) eventId = parsed
                }
                line.startsWith("data:") -> dataLines.add(line.substring(5).trim())
            }
        }
        if (dataLines.isEmpty()) return null
        val dataStr = dataLines.joinToString("\n")
        val dataObj: JsonObject = try {
            val elem = WhitzJson.parseToJsonElement(dataStr)
            elem as? JsonObject ?: buildJsonObject { put("raw", JsonPrimitive(dataStr)) }
        } catch (_: Exception) {
            buildJsonObject { put("raw", JsonPrimitive(dataStr)) }
        }
        val typeFromData = (dataObj["type"] as? JsonPrimitive)?.contentOrNull
        val name = eventType.ifBlank { typeFromData ?: "message" }
        return SseEvent(id = eventId, event = name, data = dataObj)
    }
}

class SseClient(
    private val client: OkHttpClient,
    private val authManager: AuthManager,
) {
    fun streamPost(
        path: String,
        bodyJson: String,
        extraHeaders: Map<String, String> = emptyMap(),
        idleTimeoutMs: Long = 45_000L,
    ): Flow<SseEvent> = streamRequest(
        method = "POST",
        path = path,
        bodyJson = bodyJson,
        extraHeaders = extraHeaders,
        idleTimeoutMs = idleTimeoutMs,
    )

    fun streamGet(
        path: String,
        extraHeaders: Map<String, String> = emptyMap(),
        idleTimeoutMs: Long = 45_000L,
    ): Flow<SseEvent> = streamRequest(
        method = "GET",
        path = path,
        bodyJson = null,
        extraHeaders = extraHeaders,
        idleTimeoutMs = idleTimeoutMs,
    )

    private fun streamRequest(
        method: String,
        path: String,
        bodyJson: String?,
        extraHeaders: Map<String, String>,
        idleTimeoutMs: Long,
    ): Flow<SseEvent> = flow {
        if (authManager.storage.isAccessTokenExpiringSoon()) {
            authManager.refreshOnce()
        }

        val baseUrl = authManager.storage.getApiBaseUrl().trimEnd('/')
        val cleanPath = if (path.startsWith("/")) path else "/$path"

        fun buildRequest(): Request {
            val builder = Request.Builder()
                .url(baseUrl + cleanPath)
                .header("Accept", "text/event-stream")
            extraHeaders.forEach { (k, v) -> builder.header(k, v) }
            authManager.storage.accessToken?.let { token ->
                builder.header("Authorization", "Bearer $token")
            }
            if (method == "POST") {
                val rb = (bodyJson ?: "{}").toRequestBody("application/json; charset=utf-8".toMediaType())
                builder.post(rb)
            } else {
                builder.get()
            }
            return builder.build()
        }

        val callClient = if (idleTimeoutMs > 0L) {
            client.newBuilder().readTimeout(idleTimeoutMs, TimeUnit.MILLISECONDS).build()
        } else {
            client
        }

        val parentJob = currentCoroutineContext()[Job]
        var cancelHandle: DisposableHandle? = null

        fun startCall(): Call {
            cancelHandle?.dispose()
            val nextCall = callClient.newCall(buildRequest())
            cancelHandle = parentJob?.invokeOnCompletion { cause ->
                if (cause != null) {
                    nextCall.cancel()
                }
            }
            return nextCall
        }

        try {
            var call = startCall()
            var response = call.execute()

            if (response.code == 401) {
                response.close()
                val refreshed = authManager.refreshOnce()
                if (refreshed == RefreshResult.OK) {
                    call = startCall()
                    response = call.execute()
                } else {
                    authManager.forceLogout(LogoutReason.EXPIRED)
                    throw ApiException(401, "登录已过期，请重新登录")
                }
            }

            response.use { resp ->
                if (!resp.isSuccessful) {
                    val errBody = resp.body?.string()
                    throw ApiException(resp.code, parseApiErrorBody(errBody, resp.message.ifBlank { "请求失败" }))
                }
                val source: BufferedSource = resp.body?.source()
                    ?: throw ApiException(resp.code, "空响应体")

                val blockLines = mutableListOf<String>()
                while (currentCoroutineContext().isActive) {
                    val line = source.readUtf8Line() ?: break
                    if (line.isEmpty()) {
                        if (blockLines.isNotEmpty()) {
                            val ev = SseParser.parseBlock(blockLines.joinToString("\n"))
                            blockLines.clear()
                            if (ev != null) emit(ev)
                        }
                    } else {
                        blockLines.add(line)
                    }
                }
                if (currentCoroutineContext().isActive && blockLines.isNotEmpty()) {
                    val ev = SseParser.parseBlock(blockLines.joinToString("\n"))
                    if (ev != null) emit(ev)
                }
            }
        } catch (io: IOException) {
            if (!currentCoroutineContext().isActive) {
                throw CancellationException("SSE stream cancelled", io)
            }
            throw io
        } finally {
            cancelHandle?.dispose()
        }
    }.flowOn(Dispatchers.IO)
}
