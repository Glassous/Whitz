package com.glassous.whitz.core.network

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import retrofit2.HttpException
import java.io.IOException

class ApiException(
    val statusCode: Int,
    val detail: String,
    cause: Throwable? = null,
) : Exception(detail, cause)

fun parseApiErrorBody(raw: String?, fallback: String): String {
    if (raw.isNullOrBlank()) return fallback
    return try {
        val elem = WhitzJson.parseToJsonElement(raw)
        extractDetailFromJson(elem) ?: raw.take(300)
    } catch (_: Exception) {
        raw.take(300)
    }
}

private fun extractDetailFromJson(elem: JsonElement): String? {
    return when (elem) {
        is JsonPrimitive -> elem.contentOrNull
        is JsonObject -> {
            val d = elem["detail"] ?: elem["message"] ?: elem["error"]
            when (d) {
                is JsonPrimitive -> d.contentOrNull
                is JsonObject -> extractDetailFromJson(d)
                else -> elem.toString()
            }
        }
        else -> null
    }
}

fun extractErrorMessage(t: Throwable?, fallback: String = "操作失败"): String {
    return when (t) {
        null -> fallback
        is ApiException -> t.detail.ifBlank { fallback }
        is HttpException -> {
            val body = t.response()?.errorBody()?.string()
            parseApiErrorBody(body, "请求失败 (${t.code()})")
        }
        is IOException -> "网络连接异常，请检查网络后重试"
        else -> t.message?.takeIf { it.isNotBlank() } ?: fallback
    }
}
