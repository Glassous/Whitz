package com.glassous.whitz.feature.schedules

import com.glassous.whitz.AppContainer
import com.glassous.whitz.core.model.ScheduleQuota
import com.glassous.whitz.core.model.ScheduledTask
import com.glassous.whitz.core.model.ScheduledTaskPendingItem
import com.glassous.whitz.core.model.ScheduledTaskRun
import com.glassous.whitz.core.network.SchedulePendingResolveRequest
import com.glassous.whitz.core.network.SchedulePreviewRequest
import com.glassous.whitz.core.network.ScheduledTaskCreateRequest
import com.glassous.whitz.core.network.ScheduledTaskUpdateRequest
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.core.network.extractErrorMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

data class SchedulesUiState(
    val tasks: List<ScheduledTask> = emptyList(),
    val pending: List<ScheduledTaskPendingItem> = emptyList(),
    val quota: ScheduleQuota = ScheduleQuota(),
    val runsByTask: Map<String, List<ScheduledTaskRun>> = emptyMap(),
    val loading: Boolean = false,
    val loadingRunsTaskId: String? = null,
    val busyTaskId: String? = null,
    val busyProposalId: String? = null,
    val saving: Boolean = false,
    val error: String? = null,
    val feedback: String? = null,
)

class ScheduleController(
    private val scope: CoroutineScope,
    private val container: AppContainer,
) {
    private val _ui = MutableStateFlow(SchedulesUiState())
    val ui: StateFlow<SchedulesUiState> = _ui.asStateFlow()

    fun clearMessages() {
        _ui.update { it.copy(error = null, feedback = null) }
    }

    fun loadAll(silent: Boolean = false) {
        scope.launch {
            if (!silent) _ui.update { it.copy(loading = true, error = null) }
            try {
                val res = container.network.api.getSchedules()
                _ui.update {
                    it.copy(
                        tasks = res.tasks,
                        pending = res.pending,
                        quota = res.quota,
                        loading = false,
                    )
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        loading = false,
                        error = extractErrorMessage(t, "加载定时任务失败"),
                    )
                }
            }
        }
    }

    fun loadTaskRuns(taskId: String) {
        scope.launch {
            _ui.update { it.copy(loadingRunsTaskId = taskId, error = null) }
            try {
                val detail = container.network.api.getScheduleDetail(taskId, runsLimit = 30)
                _ui.update { state ->
                    state.copy(
                        tasks = state.tasks.map { if (it.id == taskId) detail else it },
                        runsByTask = state.runsByTask + (taskId to detail.runs),
                        loadingRunsTaskId = if (state.loadingRunsTaskId == taskId) null else state.loadingRunsTaskId,
                    )
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        loadingRunsTaskId = if (it.loadingRunsTaskId == taskId) null else it.loadingRunsTaskId,
                        error = extractErrorMessage(t, "加载执行历史失败"),
                    )
                }
            }
        }
    }

    suspend fun previewSchedule(
        scheduleType: String,
        scheduleConfig: JsonObject,
        timezone: String?,
    ) = container.network.api.previewSchedule(
        SchedulePreviewRequest(
            scheduleType = scheduleType,
            scheduleConfig = scheduleConfig,
            timezone = timezone,
            count = 5,
        )
    )

    fun saveTask(
        editingId: String?,
        name: String,
        prompt: String,
        scheduleType: String,
        scheduleConfig: JsonObject,
        timezone: String?,
        targetMode: String,
        conversationId: String?,
        modelRoute: String,
        skillNames: List<String>,
        onSuccess: () -> Unit,
        onError: (String) -> Unit,
    ) {
        scope.launch {
            _ui.update { it.copy(saving = true, error = null) }
            try {
                val saved = if (editingId == null) {
                    container.network.api.createSchedule(
                        ScheduledTaskCreateRequest(
                            name = name,
                            prompt = prompt,
                            scheduleType = scheduleType,
                            scheduleConfig = scheduleConfig,
                            timezone = timezone,
                            targetMode = targetMode,
                            conversationId = conversationId,
                            modelRoute = modelRoute,
                            skillNames = skillNames,
                            enabled = true,
                        )
                    )
                } else {
                    container.network.api.updateSchedule(
                        editingId,
                        ScheduledTaskUpdateRequest(
                            name = name,
                            prompt = prompt,
                            scheduleType = scheduleType,
                            scheduleConfig = scheduleConfig,
                            timezone = timezone,
                            targetMode = targetMode,
                            conversationId = conversationId,
                            modelRoute = modelRoute,
                            skillNames = skillNames,
                        )
                    )
                }
                upsertTask(saved)
                _ui.update {
                    it.copy(
                        saving = false,
                        feedback = if (editingId == null) "已创建并启用定时任务" else "已保存定时任务修改",
                    )
                }
                onSuccess()
            } catch (t: Throwable) {
                val msg = extractErrorMessage(t, "保存定时任务失败")
                _ui.update { it.copy(saving = false) }
                onError(msg)
            }
        }
    }

    fun toggleEnabled(task: ScheduledTask) {
        if (_ui.value.busyTaskId != null) return
        scope.launch {
            _ui.update { it.copy(busyTaskId = task.id, error = null) }
            try {
                val updated = container.network.api.updateSchedule(
                    task.id,
                    ScheduledTaskUpdateRequest(enabled = !task.enabled),
                )
                upsertTask(updated)
                _ui.update { it.copy(busyTaskId = null) }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        busyTaskId = null,
                        error = extractErrorMessage(t, "切换任务状态失败"),
                    )
                }
            }
        }
    }

    fun runNow(task: ScheduledTask, onRunStarted: (ScheduledTaskRun) -> Unit = {}) {
        if (_ui.value.busyTaskId != null) return
        scope.launch {
            _ui.update { it.copy(busyTaskId = task.id, error = null, feedback = null) }
            try {
                val run = container.network.api.runScheduleNow(task.id)
                upsertRun(task.id, run)
                _ui.update {
                    it.copy(
                        busyTaskId = null,
                        feedback = "已触发「${task.name}」立即执行",
                    )
                }
                loadTaskRuns(task.id)
                onRunStarted(run)
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        busyTaskId = null,
                        error = extractErrorMessage(t, "立即执行失败"),
                    )
                }
            }
        }
    }

    fun deleteTask(taskId: String) {
        if (_ui.value.busyTaskId != null) return
        scope.launch {
            _ui.update { it.copy(busyTaskId = taskId, error = null) }
            try {
                container.network.api.deleteSchedule(taskId)
                removeTask(taskId)
                _ui.update { it.copy(busyTaskId = null, feedback = "已删除定时任务") }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        busyTaskId = null,
                        error = extractErrorMessage(t, "删除定时任务失败"),
                    )
                }
            }
        }
    }

    fun resolvePending(proposalId: String, action: String) {
        if (_ui.value.busyProposalId != null) return
        scope.launch {
            _ui.update { it.copy(busyProposalId = proposalId, error = null) }
            try {
                val res = container.network.api.resolveSchedulePending(
                    proposalId,
                    SchedulePendingResolveRequest(action),
                )
                _ui.update { state ->
                    state.copy(
                        pending = state.pending.filterNot { it.id == proposalId },
                        busyProposalId = null,
                        feedback = if (action == "approve") "已确认定时任务变更" else "已拒绝定时任务提案",
                    )
                }
                if (res.task != null) {
                    upsertTask(res.task)
                } else if (action == "approve") {
                    loadAll(silent = true)
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        busyProposalId = null,
                        error = extractErrorMessage(t, "处理提案失败"),
                    )
                }
            }
        }
    }

    fun handleRealtimeEvent(event: String, data: JsonObject) {
        when (event) {
            "schedule.updated" -> {
                val action = (data["action"] as? kotlinx.serialization.json.JsonPrimitive)?.content
                val taskId = (data["task_id"] as? kotlinx.serialization.json.JsonPrimitive)?.content
                if (action == "deleted" && taskId != null) {
                    removeTask(taskId)
                } else {
                    val taskObj = data["task"] as? JsonObject ?: return
                    runCatching {
                        WhitzJson.decodeFromJsonElement(ScheduledTask.serializer(), taskObj)
                    }.getOrNull()?.let { upsertTask(it) }
                }
            }
            "schedule.run_updated" -> {
                val taskId = (data["task_id"] as? kotlinx.serialization.json.JsonPrimitive)?.content
                val taskObj = data["task"] as? JsonObject
                if (taskObj != null) {
                    runCatching {
                        WhitzJson.decodeFromJsonElement(ScheduledTask.serializer(), taskObj)
                    }.getOrNull()?.let { upsertTask(it) }
                }
                val runObj = data["run"] as? JsonObject
                if (taskId != null && runObj != null) {
                    runCatching {
                        WhitzJson.decodeFromJsonElement(ScheduledTaskRun.serializer(), runObj)
                    }.getOrNull()?.let { upsertRun(taskId, it) }
                }
            }
            "schedule.pending_updated" -> {
                val action = (data["action"] as? kotlinx.serialization.json.JsonPrimitive)?.content
                val proposalId = (data["proposal_id"] as? kotlinx.serialization.json.JsonPrimitive)?.content
                if (action == "created") {
                    val propObj = data["proposal"] as? JsonObject ?: return
                    runCatching {
                        WhitzJson.decodeFromJsonElement(ScheduledTaskPendingItem.serializer(), propObj)
                    }.getOrNull()?.let { prop ->
                        _ui.update { state ->
                            if (state.pending.any { it.id == prop.id }) state
                            else state.copy(pending = state.pending + prop)
                        }
                    }
                } else if ((action == "approved" || action == "rejected") && proposalId != null) {
                    _ui.update { state ->
                        state.copy(pending = state.pending.filterNot { it.id == proposalId })
                    }
                }
            }
        }
    }

    private fun upsertTask(task: ScheduledTask) {
        _ui.update { state ->
            val exists = state.tasks.any { it.id == task.id }
            val nextTasks = if (exists) {
                state.tasks.map { if (it.id == task.id) task.copy(runs = it.runs) else it }
            } else {
                listOf(task) + state.tasks
            }
            val activeCount = nextTasks.count { it.enabled }
            state.copy(
                tasks = nextTasks,
                quota = state.quota.copy(activeCount = activeCount),
            )
        }
    }

    private fun removeTask(taskId: String) {
        _ui.update { state ->
            val nextTasks = state.tasks.filterNot { it.id == taskId }
            state.copy(
                tasks = nextTasks,
                runsByTask = state.runsByTask - taskId,
                quota = state.quota.copy(activeCount = nextTasks.count { it.enabled }),
            )
        }
    }

    private fun upsertRun(taskId: String, run: ScheduledTaskRun) {
        _ui.update { state ->
            val current = state.runsByTask[taskId].orEmpty()
            val exists = current.any { it.id == run.id }
            val nextRuns = if (exists) {
                current.map { if (it.id == run.id) run else it }
            } else {
                (listOf(run) + current).take(30)
            }
            state.copy(runsByTask = state.runsByTask + (taskId to nextRuns))
        }
    }
}
