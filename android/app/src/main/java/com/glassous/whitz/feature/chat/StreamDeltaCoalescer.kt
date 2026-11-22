package com.glassous.whitz.feature.chat

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Represents a coalesced reasoning delta chunk ready to apply to UI state.
 */
data class CoalescedReasoningDelta(
    val step: Int?,
    val title: String,
    val text: String,
)

/**
 * Snapshot of buffered streaming deltas flushed in one batch.
 */
data class CoalescedDeltaBatch(
    val contentDelta: String,
    val reasoningDeltas: List<CoalescedReasoningDelta>,
) {
    val isEmpty: Boolean
        get() = contentDelta.isEmpty() && reasoningDeltas.isEmpty()
}

/**
 * Frame-paced coalescer for high-frequency SSE `message.delta` and `reasoning.delta` events.
 *
 * Accumulates incoming deltas into lightweight mutable buffers and flushes them on a fixed
 * cadence ([flushIntervalMs], default 32ms ≈ 30 Hz) to prevent main-thread StateFlow and
 * Markdown recomposition storms.
 *
 * Call [flushNow] synchronously before processing any structural or terminal SSE event
 * (`commentary`, `run.completed`, `run.snapshot`, `approval.request`, etc.) so strict
 * event ordering is always preserved with zero dropped characters.
 */
class StreamDeltaCoalescer(
    private val scope: CoroutineScope,
    private val flushIntervalMs: Long = 32L,
    private val onFlush: (CoalescedDeltaBatch) -> Unit,
) {
    private val lock = Any()
    private val contentBuffer = StringBuilder()
    private val reasoningBuffer = mutableListOf<PendingReasoningChunk>()
    private var flushJob: Job? = null

    private data class PendingReasoningChunk(
        val step: Int?,
        val title: String,
        val text: StringBuilder,
    )

    fun appendContent(delta: String) {
        if (delta.isEmpty()) return
        synchronized(lock) {
            contentBuffer.append(delta)
            scheduleFlushLocked()
        }
    }

    fun appendReasoning(step: Int?, title: String, delta: String) {
        if (delta.isEmpty()) return
        synchronized(lock) {
            val last = reasoningBuffer.lastOrNull()
            if (last != null && last.step == step) {
                last.text.append(delta)
            } else {
                reasoningBuffer.add(PendingReasoningChunk(step, title, StringBuilder(delta)))
            }
            scheduleFlushLocked()
        }
    }

    /**
     * Synchronously drains any buffered deltas and invokes [onFlush] immediately if non-empty.
     */
    fun flushNow() {
        val batch = drainBatch() ?: return
        onFlush(batch)
    }

    /**
     * Discards all buffered deltas and cancels any scheduled flush (e.g., on conversation switch).
     */
    fun clear() {
        synchronized(lock) {
            contentBuffer.setLength(0)
            reasoningBuffer.clear()
            flushJob?.cancel()
            flushJob = null
        }
    }

    fun hasPending(): Boolean = synchronized(lock) {
        contentBuffer.isNotEmpty() || reasoningBuffer.isNotEmpty()
    }

    private fun scheduleFlushLocked() {
        if (flushJob?.isActive == true) return
        flushJob = scope.launch {
            delay(flushIntervalMs)
            val batch = drainBatch()
            if (batch != null) {
                onFlush(batch)
            }
        }
    }

    private fun drainBatch(): CoalescedDeltaBatch? = synchronized(lock) {
        flushJob?.cancel()
        flushJob = null
        if (contentBuffer.isEmpty() && reasoningBuffer.isEmpty()) {
            return null
        }
        val content = if (contentBuffer.isNotEmpty()) {
            val s = contentBuffer.toString()
            contentBuffer.setLength(0)
            s
        } else {
            ""
        }
        val reasoning = if (reasoningBuffer.isNotEmpty()) {
            val list = reasoningBuffer.map {
                CoalescedReasoningDelta(
                    step = it.step,
                    title = it.title,
                    text = it.text.toString(),
                )
            }
            reasoningBuffer.clear()
            list
        } else {
            emptyList()
        }
        CoalescedDeltaBatch(contentDelta = content, reasoningDeltas = reasoning)
    }
}
