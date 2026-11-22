package com.glassous.whitz.feature.chat

import com.glassous.whitz.core.model.Message
import com.glassous.whitz.core.model.Plan
import com.glassous.whitz.core.model.PlanItem
import com.glassous.whitz.core.model.ReasoningBlock
import com.glassous.whitz.core.model.ReasoningTool
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

data class CurrentStepInfo(
    val index: Int,
    val total: Int,
    val title: String,
)

data class ResolvedTurnDetails(
    val turnId: String?,
    val plan: Plan?,
    val reasoning: List<ReasoningBlock>,
    val isLive: Boolean,
    val runningTool: String?,
)

data class ResolvedStepItem(
    val key: String,
    val index: Int,
    val item: PlanItem,
    val blocks: List<ReasoningBlock>,
)

data class PlanSections(
    val items: List<PlanItem>,
    val steps: List<ResolvedStepItem>,
    val planningBlocks: List<ReasoningBlock>,
    val summaryBlocks: List<ReasoningBlock>,
    val looseBlocks: List<ReasoningBlock>,
    val doneCount: Int,
    val progressPct: Float,
)

data class ToolWebResultItem(
    val title: String,
    val url: String,
    val snippet: String,
)

private val PRETTY_JSON = Json {
    ignoreUnknownKeys = true
    prettyPrint = true
}

private val TOOL_LABELS: Map<String, String> = mapOf(
    "todo_list" to "更新任务清单",
    "tool_search" to "检索工具",
    "tool_describe" to "查看工具说明",
    "skill_view" to "查看技能",
    "web_search" to "联网搜索",
    "web_extract" to "读取网页",
    "memory" to "记忆",
    "skill" to "技能",
    "rag_search_workspace" to "检索工作区",
    "memory_search" to "检索长期记忆",
    "memory_propose" to "提议写入记忆",
    "execute_code" to "沙盒代码执行",
    "delegate_subtask" to "子智能体协作",
    "request_deep_thinking" to "开启深度思考",
    "list_workspace_files" to "查看工作区文件",
    "read_workspace_file" to "读取工作区文件",
    "search_workspace_files" to "检索工作区文件",
    "write_workspace_file" to "写入工作区文件",
    "edit_workspace_file" to "编辑工作区文件",
    "list_user_skills" to "查看可用技能",
    "preview_github_skill" to "预览 GitHub 技能",
    "install_github_skill" to "安装 GitHub 技能",
    "create_user_skill" to "创建自定义技能",
    "mcp__whitz_files__list_workspace_files" to "查看工作区文件",
    "mcp__whitz_files__read_workspace_file" to "读取工作区文件",
    "mcp__whitz_files__search_workspace_files" to "检索工作区文件",
    "mcp__whitz_files__write_workspace_file" to "写入工作区文件",
    "mcp__whitz_files__edit_workspace_file" to "编辑工作区文件",
    "mcp__whitz_skills__list_user_skills" to "查看可用技能",
    "mcp__whitz_skills__preview_github_skill" to "预览 GitHub 技能",
    "mcp__whitz_skills__install_github_skill" to "安装 GitHub 技能",
    "mcp__whitz_skills__create_user_skill" to "创建自定义技能",
)

private val PLAN_STATUS_LABELS: Map<String, String> = mapOf(
    "completed" to "已完成",
    "in_progress" to "进行中",
    "pending" to "待执行",
)

fun filterVisibleMessages(messages: List<Message>): List<Message> =
    messages.filter { it.role != "tool" }

fun derivePlanFromReasoning(blocks: List<ReasoningBlock>): Plan? {
    val items = LinkedHashMap<String, PlanItem>()
    for (block in blocks) {
        val stepNum = block.step ?: continue
        val key = block.stepId ?: "step-$stepNum"
        if (!items.containsKey(key)) {
            items[key] = PlanItem(
                id = JsonPrimitive(key),
                content = block.title.ifBlank { "步骤 $stepNum" },
                status = "completed",
                parent = null,
            )
        }
    }
    return if (items.isNotEmpty()) Plan(items = items.values.toList()) else null
}

fun computeRunningTool(messages: List<Message>): String? =
    messages.lastOrNull { it.role == "tool" && it.status == "running" }?.toolName

fun computeCurrentStep(plan: Plan?): CurrentStepInfo? {
    val items = plan?.items.orEmpty()
    val idx = items.indexOfFirst { it.status == "in_progress" }
    if (idx < 0) return null
    return CurrentStepInfo(index = idx + 1, total = items.size, title = items[idx].content)
}

fun resolveTurnDetails(
    messages: List<Message>,
    selectedTurnId: String?,
    activeAssistantId: String?,
    streaming: Boolean,
    livePlan: Plan?,
    liveReasoning: List<ReasoningBlock>,
    turnIdOverride: String? = null,
): ResolvedTurnDetails {
    val assistantTurns = messages.filter { it.role == "assistant" }
    val targetId = turnIdOverride ?: selectedTurnId
    val selectedMsg = assistantTurns.firstOrNull { it.id == targetId } ?: assistantTurns.lastOrNull()
    if (selectedMsg == null) {
        return ResolvedTurnDetails(
            turnId = null,
            plan = null,
            reasoning = emptyList(),
            isLive = false,
            runningTool = null,
        )
    }

    val isActive = selectedMsg.id == activeAssistantId
    val reasoning = if (isActive) {
        liveReasoning
    } else {
        selectedMsg.toolPayload?.reasoning.orEmpty()
    }

    val lastAssistantId = assistantTurns.lastOrNull()?.id
    val storedPlan = selectedMsg.toolPayload?.plan
    val plan = when {
        isActive -> livePlan ?: storedPlan
        storedPlan != null -> storedPlan
        selectedMsg.id == lastAssistantId && livePlan != null -> livePlan
        else -> derivePlanFromReasoning(reasoning)
    }

    val isLive = streaming && isActive
    val runningTool = if (isLive) computeRunningTool(messages) else null
    return ResolvedTurnDetails(
        turnId = selectedMsg.id,
        plan = plan,
        reasoning = reasoning,
        isLive = isLive,
        runningTool = runningTool,
    )
}

fun computeStepsCount(plan: Plan?, reasoning: List<ReasoningBlock>): Int {
    val items = plan?.items.orEmpty()
    if (items.isNotEmpty()) return items.size
    return reasoning
        .asSequence()
        .filter { it.step != null }
        .map { it.stepId ?: "step-${it.step}" }
        .distinct()
        .count()
}

enum class StreamingPhase {
    CONNECTING,
    RECONNECTING,
    STOPPING,
    WAITING_APPROVAL,
    WAITING_CLARIFY,
    RUNNING_STEP,
    RUNNING_TOOL,
    THINKING,
    GENERATING,
}

fun resolveStreamingPhase(
    currentStep: CurrentStepInfo?,
    runningTool: String?,
    plan: Plan?,
    stopping: Boolean = false,
    reconnecting: Boolean = false,
    waitingFirstByte: Boolean = false,
    pendingControlKind: String? = null,
    hasContent: Boolean = false,
): StreamingPhase = when {
    stopping -> StreamingPhase.STOPPING
    reconnecting -> StreamingPhase.RECONNECTING
    pendingControlKind == "approval" -> StreamingPhase.WAITING_APPROVAL
    pendingControlKind == "clarify" -> StreamingPhase.WAITING_CLARIFY
    currentStep != null -> StreamingPhase.RUNNING_STEP
    !runningTool.isNullOrBlank() -> StreamingPhase.RUNNING_TOOL
    waitingFirstByte -> StreamingPhase.CONNECTING
    hasContent -> StreamingPhase.GENERATING
    plan?.items.orEmpty().let { it.isNotEmpty() && it.all { item -> item.status == "completed" } } ->
        StreamingPhase.GENERATING
    else -> StreamingPhase.THINKING
}

fun computeLiveStepLabel(
    currentStep: CurrentStepInfo?,
    runningTool: String?,
    plan: Plan?,
    stopping: Boolean = false,
    reconnecting: Boolean = false,
    waitingFirstByte: Boolean = false,
    pendingControlKind: String? = null,
    hasContent: Boolean = false,
): String {
    return when (
        resolveStreamingPhase(
            currentStep = currentStep,
            runningTool = runningTool,
            plan = plan,
            stopping = stopping,
            reconnecting = reconnecting,
            waitingFirstByte = waitingFirstByte,
            pendingControlKind = pendingControlKind,
            hasContent = hasContent,
        )
    ) {
        StreamingPhase.STOPPING -> "正在停止生成…"
        StreamingPhase.RECONNECTING -> "网络重连中，正在恢复进度…"
        StreamingPhase.WAITING_APPROVAL -> "等待你的批准"
        StreamingPhase.WAITING_CLARIFY -> "等待你补充信息"
        StreamingPhase.RUNNING_STEP -> {
            val step = currentStep!!
            if (step.title.isNotBlank()) {
                "步骤 ${step.index}/${step.total} · ${step.title}"
            } else {
                "步骤 ${step.index}/${step.total}"
            }
        }
        StreamingPhase.RUNNING_TOOL -> "正在使用 ${toolDisplayName(runningTool!!)}"
        StreamingPhase.CONNECTING -> "正在连接助理…"
        StreamingPhase.GENERATING -> "正在生成回答…"
        StreamingPhase.THINKING -> "正在思考…"
    }
}

fun planStatusLabel(status: String): String =
    PLAN_STATUS_LABELS[status] ?: "待执行"

fun toolDisplayName(name: String): String =
    TOOL_LABELS[name] ?: name

private val SEARCH_PROVIDER_LABELS = mapOf(
    "bocha" to "博查",
    "tavily" to "Tavily",
    "duckduckgo" to "DuckDuckGo",
)

fun toolDisplayName(tool: ReasoningTool): String {
    val base = toolDisplayName(tool.name)
    if (tool.name != "web_search") return base
    val resultObj = parsePayloadJson(tool.result) as? JsonObject
    val resProvider = (resultObj?.get("provider") as? JsonPrimitive)?.contentOrNull?.lowercase().orEmpty()
    val argObj = parseArgsJson(tool.args) as? JsonObject
    val argProvider = (argObj?.get("provider") as? JsonPrimitive)?.contentOrNull?.lowercase().orEmpty()
    val providerLabel = SEARCH_PROVIDER_LABELS[resProvider] ?: SEARCH_PROVIDER_LABELS[argProvider]
    return if (providerLabel != null) "$base · $providerLabel" else base
}

private fun JsonElement?.asIdString(): String? =
    (this as? JsonPrimitive)?.contentOrNull ?: this?.toString()?.takeIf { it != "null" }

fun blocksForPlanItem(
    reasoning: List<ReasoningBlock>,
    item: PlanItem,
    oneBasedIndex: Int,
): List<ReasoningBlock> {
    val itemId = item.id.asIdString()
    return reasoning.filter { block ->
        val step = block.step ?: return@filter false
        if (block.stepId != null && itemId != null) {
            block.stepId == itemId
        } else {
            step == oneBasedIndex
        }
    }
}

fun partitionPlanSteps(plan: Plan?, reasoning: List<ReasoningBlock>): PlanSections {
    val items = plan?.items.orEmpty()
    val steps = items.mapIndexed { idx, item ->
        val oneBased = idx + 1
        ResolvedStepItem(
            key = item.id.asIdString() ?: "idx-$oneBased",
            index = oneBased,
            item = item,
            blocks = blocksForPlanItem(reasoning, item, oneBased),
        )
    }
    val matchedRefs = IdentityHashMapSet<ReasoningBlock>()
    steps.forEach { step -> step.blocks.forEach { matchedRefs.add(it) } }

    val planningBlocks = reasoning.filter { it.step == null && it.title != "总结" }
    val summaryBlocks = reasoning.filter { it.step == null && it.title == "总结" }
    val looseBlocks = if (items.isNotEmpty()) {
        reasoning.filter { it.step != null && !matchedRefs.contains(it) }
    } else {
        reasoning
    }

    val done = items.count { it.status == "completed" }
    val pct = if (items.isNotEmpty()) done.toFloat() / items.size.toFloat() else 0f
    return PlanSections(
        items = items,
        steps = steps,
        planningBlocks = planningBlocks,
        summaryBlocks = summaryBlocks,
        looseBlocks = looseBlocks,
        doneCount = done,
        progressPct = pct,
    )
}

private class IdentityHashMapSet<T : Any> {
    private val map = java.util.IdentityHashMap<T, Boolean>()
    fun add(item: T) {
        map[item] = true
    }
    fun contains(item: T): Boolean = map.containsKey(item)
}

fun stripToolWrapper(raw: String?): String {
    if (raw.isNullOrBlank()) return ""
    var text = raw.trim()
    if (text.startsWith("<untrusted_tool_result")) {
        val close = text.indexOf('>')
        if (close >= 0) text = text.substring(close + 1)
    }
    val suffix = "</untrusted_tool_result>"
    if (text.trimEnd().endsWith(suffix)) {
        text = text.trimEnd().dropLast(suffix.length)
    }
    return text.trim()
}

private fun parsePayloadJson(raw: String?): JsonElement? {
    val text = stripToolWrapper(raw)
    if (text.isEmpty()) return null
    val objStart = text.indexOf('{')
    val arrStart = text.indexOf('[')
    val start = listOf(objStart, arrStart).filter { it >= 0 }.minOrNull() ?: return null
    return try {
        PRETTY_JSON.parseToJsonElement(text.substring(start))
    } catch (_: Exception) {
        null
    }
}

private fun parseArgsJson(raw: String?): JsonElement? {
    if (raw.isNullOrBlank()) return null
    return try {
        PRETTY_JSON.parseToJsonElement(raw)
    } catch (_: Exception) {
        parsePayloadJson(raw)
    }
}

fun isWebTool(tool: ReasoningTool): Boolean =
    tool.name == "web_search" || tool.name == "web_extract"

fun parseWebSearchQuery(tool: ReasoningTool): String {
    if (tool.name != "web_search") return ""
    val obj = parseArgsJson(tool.args) as? JsonObject ?: return ""
    return (obj["query"] as? JsonPrimitive)?.contentOrNull.orEmpty()
}

fun parseWebSearchItems(tool: ReasoningTool): List<ToolWebResultItem> {
    val root = parsePayloadJson(tool.result) as? JsonObject ?: return emptyList()
    val dataObj = root["data"] as? JsonObject
    val arr = (root["results"] as? JsonArray)
        ?: (dataObj?.get("web") as? JsonArray)
        ?: (root["web"] as? JsonArray)
        ?: (dataObj?.get("results") as? JsonArray)
        ?: return emptyList()
    return arr.asSequence()
        .take(8)
        .mapNotNull { elem ->
            val obj = elem as? JsonObject ?: return@mapNotNull null
            val title = (obj["title"] as? JsonPrimitive)?.contentOrNull
                ?: (obj["name"] as? JsonPrimitive)?.contentOrNull
                ?: ""
            val url = (obj["url"] as? JsonPrimitive)?.contentOrNull
                ?: (obj["link"] as? JsonPrimitive)?.contentOrNull
                ?: ""
            val snippet = ((obj["description"] as? JsonPrimitive)?.contentOrNull
                ?: (obj["snippet"] as? JsonPrimitive)?.contentOrNull
                ?: (obj["content"] as? JsonPrimitive)?.contentOrNull
                ?: "").take(500)
            if (title.isBlank() && url.isBlank()) null else ToolWebResultItem(title, url, snippet)
        }
        .toList()
}

fun parseTodoChanges(tool: ReasoningTool): List<String> {
    val obj = parseArgsJson(tool.args) as? JsonObject ?: return emptyList()
    val arr = obj["todos"] as? JsonArray ?: return emptyList()
    return arr.mapNotNull { elem ->
        val item = elem as? JsonObject ?: return@mapNotNull null
        val content = (item["content"] as? JsonPrimitive)?.contentOrNull?.trim().orEmpty()
        val rawStatus = (item["status"] as? JsonPrimitive)?.contentOrNull.orEmpty()
        val status = PLAN_STATUS_LABELS[rawStatus] ?: rawStatus
        when {
            content.isNotEmpty() && status.isNotEmpty() -> "$content（$status）"
            content.isNotEmpty() -> content
            else -> null
        }
    }
}

fun formatToolSummary(tool: ReasoningTool): String {
    return when (tool.name) {
        "web_search" -> parseWebSearchQuery(tool)
        "web_extract" -> parseWebSearchItems(tool).firstOrNull()?.title.orEmpty()
        "todo_list" -> parseTodoChanges(tool).firstOrNull().orEmpty()
        "tool_describe" -> {
            val obj = parseArgsJson(tool.args) as? JsonObject
            val names = obj?.get("names") as? JsonArray
            names?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }?.joinToString("、").orEmpty()
        }
        "skill_view" -> {
            val obj = parseArgsJson(tool.args) as? JsonObject
            (obj?.get("name") as? JsonPrimitive)?.contentOrNull.orEmpty()
        }
        else -> {
            val args = stripToolWrapper(tool.args)
            val fallback = args.ifBlank { stripToolWrapper(tool.result) }
            fallback.lineSequence().firstOrNull().orEmpty().take(80)
        }
    }
}

fun prettyToolPayload(raw: String?): String {
    val text = stripToolWrapper(raw)
    if (text.isEmpty()) return ""
    return try {
        val elem = PRETTY_JSON.parseToJsonElement(text)
        val formatted = PRETTY_JSON.encodeToString(JsonElement.serializer(), elem)
        if (formatted.length > 1800) formatted.take(1800) + "…" else formatted
    } catch (_: Exception) {
        if (text.length > 1200) text.take(1200) + "…" else text
    }
}
