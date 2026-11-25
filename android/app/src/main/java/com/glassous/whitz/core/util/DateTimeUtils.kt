package com.glassous.whitz.core.util

import com.glassous.whitz.core.model.Conversation
import java.time.DayOfWeek
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.temporal.ChronoUnit

object DateTimeUtils {
    const val CHAT_TIME_GAP_MS = 5L * 60L * 1000L

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
        val zdt = Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault())
        val now = ZonedDateTime.now()
        return if (zdt.toLocalDate() == now.toLocalDate()) {
            String.format("%02d:%02d", zdt.hour, zdt.minute)
        } else if (zdt.year == now.year) {
            String.format("%02d-%02d %02d:%02d", zdt.monthValue, zdt.dayOfMonth, zdt.hour, zdt.minute)
        } else {
            String.format("%04d-%02d-%02d", zdt.year, zdt.monthValue, zdt.dayOfMonth)
        }
    }

    fun shouldShowChatTimeDivider(
        prevIso: String?,
        currIso: String?,
        zoneId: ZoneId = ZoneId.systemDefault(),
    ): Boolean {
        val currMs = parseInstantMs(currIso)
        if (currMs <= 0L) return false
        val prevMs = parseInstantMs(prevIso)
        if (prevMs <= 0L) return true

        val prevDate = Instant.ofEpochMilli(prevMs).atZone(zoneId).toLocalDate()
        val currDate = Instant.ofEpochMilli(currMs).atZone(zoneId).toLocalDate()
        if (prevDate != currDate) return true

        return currMs - prevMs >= CHAT_TIME_GAP_MS
    }

    fun formatChatDivider(
        iso: String?,
        nowZdt: ZonedDateTime = ZonedDateTime.now(ZoneId.systemDefault()),
    ): String {
        val ms = parseInstantMs(iso)
        if (ms <= 0L) return ""
        val zdt = Instant.ofEpochMilli(ms).atZone(nowZdt.zone)
        val timePart = String.format("%02d:%02d", zdt.hour, zdt.minute)
        val dayDiff = ChronoUnit.DAYS.between(zdt.toLocalDate(), nowZdt.toLocalDate())

        return when {
            dayDiff == 0L -> timePart
            dayDiff == 1L -> "昨天 $timePart"
            dayDiff in 2L..6L -> "${weekdayLabelZh(zdt.dayOfWeek)} $timePart"
            zdt.year == nowZdt.year -> "${zdt.monthValue}月${zdt.dayOfMonth}日 $timePart"
            else -> "${zdt.year}年${zdt.monthValue}月${zdt.dayOfMonth}日 $timePart"
        }
    }

    private fun weekdayLabelZh(dayOfWeek: DayOfWeek): String = when (dayOfWeek) {
        DayOfWeek.MONDAY -> "星期一"
        DayOfWeek.TUESDAY -> "星期二"
        DayOfWeek.WEDNESDAY -> "星期三"
        DayOfWeek.THURSDAY -> "星期四"
        DayOfWeek.FRIDAY -> "星期五"
        DayOfWeek.SATURDAY -> "星期六"
        DayOfWeek.SUNDAY -> "星期日"
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
