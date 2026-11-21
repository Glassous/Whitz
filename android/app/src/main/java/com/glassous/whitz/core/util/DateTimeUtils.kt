package com.glassous.whitz.core.util

import com.glassous.whitz.core.model.Conversation
import java.time.Instant

object DateTimeUtils {
    fun parseInstantMs(iso: String?): Long {
        if (iso.isNullOrBlank()) return 0L
        return try {
            Instant.parse(iso).toEpochMilli()
        } catch (_: Exception) {
            try {
                java.time.OffsetDateTime.parse(iso).toInstant().toEpochMilli()
            } catch (_: Exception) {
                0L
            }
        }
    }

    fun formatShort(iso: String?): String {
        val ms = parseInstantMs(iso)
        if (ms <= 0L) return ""
        val zdt = Instant.ofEpochMilli(ms).atZone(java.time.ZoneId.systemDefault())
        val now = java.time.ZonedDateTime.now()
        return if (zdt.toLocalDate() == now.toLocalDate()) {
            String.format("%02d:%02d", zdt.hour, zdt.minute)
        } else if (zdt.year == now.year) {
            String.format("%02d-%02d %02d:%02d", zdt.monthValue, zdt.dayOfMonth, zdt.hour, zdt.minute)
        } else {
            String.format("%04d-%02d-%02d", zdt.year, zdt.monthValue, zdt.dayOfMonth)
        }
    }
}

object ConversationSorter {
    fun sort(list: List<Conversation>): List<Conversation> {
        return list.sortedWith { a, b ->
            val aMain = a.kind == "main"
            val bMain = b.kind == "main"
            if (aMain != bMain) {
                return@sortedWith if (aMain) -1 else 1
            }
            if (a.isPinned != b.isPinned) {
                return@sortedWith if (a.isPinned) -1 else 1
            }
            if (a.isPinned && b.isPinned) {
                val pinDiff = DateTimeUtils.parseInstantMs(b.pinnedAt)
                    .compareTo(DateTimeUtils.parseInstantMs(a.pinnedAt))
                if (pinDiff != 0) return@sortedWith pinDiff
            }
            val ta = DateTimeUtils.parseInstantMs(a.lastMessageAt ?: a.updatedAt.ifBlank { a.createdAt })
            val tb = DateTimeUtils.parseInstantMs(b.lastMessageAt ?: b.updatedAt.ifBlank { b.createdAt })
            tb.compareTo(ta)
        }
    }
}
