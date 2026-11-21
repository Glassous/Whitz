package com.glassous.whitz.core.storage

import android.content.Context
import com.glassous.whitz.core.model.Conversation
import com.glassous.whitz.core.model.ConversationDetail
import com.glassous.whitz.core.network.WhitzJson
import kotlinx.serialization.Serializable
import java.io.File

@Serializable
data class HomeChatCache(
    val userId: String,
    val conversations: List<Conversation> = emptyList(),
    val mainConversation: ConversationDetail? = null,
    val savedAtMs: Long = 0L,
)

class ChatCacheStorage(context: Context) {
    private val cacheFile = File(context.filesDir, "whitz_home_chat_cache.json")
    private val lock = Any()

    fun load(userId: String): HomeChatCache? {
        if (userId.isBlank()) return null
        return synchronized(lock) {
            if (!cacheFile.exists()) return@synchronized null
            runCatching {
                val raw = cacheFile.readText(Charsets.UTF_8)
                val parsed = WhitzJson.decodeFromString(HomeChatCache.serializer(), raw)
                if (parsed.userId == userId) parsed else null
            }.getOrNull()
        }
    }

    fun save(
        userId: String,
        conversations: List<Conversation>? = null,
        mainConversation: ConversationDetail? = null,
    ) {
        if (userId.isBlank()) return
        synchronized(lock) {
            runCatching {
                val existing = if (cacheFile.exists()) {
                    runCatching {
                        WhitzJson.decodeFromString(
                            HomeChatCache.serializer(),
                            cacheFile.readText(Charsets.UTF_8),
                        )
                    }.getOrNull()?.takeIf { it.userId == userId }
                } else {
                    null
                }
                val merged = HomeChatCache(
                    userId = userId,
                    conversations = conversations ?: existing?.conversations.orEmpty(),
                    mainConversation = mainConversation ?: existing?.mainConversation,
                    savedAtMs = System.currentTimeMillis(),
                )
                val json = WhitzJson.encodeToString(HomeChatCache.serializer(), merged)
                val tmp = File(cacheFile.parentFile, "${cacheFile.name}.tmp")
                tmp.writeText(json, Charsets.UTF_8)
                if (!tmp.renameTo(cacheFile)) {
                    cacheFile.writeText(json, Charsets.UTF_8)
                    tmp.delete()
                }
            }
        }
    }

    fun clear() {
        synchronized(lock) {
            runCatching {
                if (cacheFile.exists()) cacheFile.delete()
            }
        }
    }
}
