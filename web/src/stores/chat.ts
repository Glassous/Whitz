import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";
import { chatTicketHeaders } from "../api/chatTickets";
import { streamSSE, streamSSEGet, type SSEEvent } from "../api/sse";
import type {
  ConversationDetail,
  ConversationFile,
  MemoryOverview,
  MemoryPendingItem,
  Message,
  PendingControl,
  Plan,
  PlanItem,
  ReasoningBlock,
  SkillPendingItem,
  ToolPayload,
  WorkspaceArtifactMeta,
} from "../types";
import { useConversationsStore } from "./conversations";
import { useFilesStore } from "./files";

let seq = 0;
const tempId = (prefix: string) => `${prefix}-${Date.now()}-${seq++}`;

function apiErrorMessage(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

export const useChatStore = defineStore("chat", () => {
  const convId = ref<string | null>(null);
  const messages = ref<Message[]>([]);
  const streaming = ref(false);
  const activeAssistantId = ref<string | null>(null);
  const activeRunId = ref<string | null>(null);
  const plan = ref<Plan | null>(null);
  const reasoning = ref<ReasoningBlock[]>([]);
  const pendingControl = ref<PendingControl | null>(null);
  const pendingMemory = ref<MemoryPendingItem[]>([]);
  const pendingSkills = ref<SkillPendingItem[]>([]);
  const error = ref<string | null>(null);
  const selectedTurnId = ref<string | null>(null);
  let controller: AbortController | null = null;
  let pendingUserTargetId: string | null = null;

  const currentStep = computed(() => {
    const items = plan.value?.items ?? [];
    const idx = items.findIndex((i) => i.status === "in_progress");
    if (idx < 0) return null;
    return { index: idx + 1, total: items.length, title: items[idx].content };
  });

  const runningTool = computed(() => {
    const row = messages.value.findLast((m) => m.role === "tool" && m.status === "running");
    return row?.tool_name ?? null;
  });

  function findMessage(id: string | null): Message | undefined {
    if (!id) return undefined;
    return messages.value.find((m) => m.id === id);
  }

  function assistant(): Message | undefined {
    return findMessage(activeAssistantId.value);
  }

  function normalizeReasoning(input: unknown): ReasoningBlock[] {
    if (!Array.isArray(input)) return [];
    return input
      .filter((b) => b && (typeof b.text === "string" || Array.isArray(b.tools)))
      .map((b) => ({
        step: typeof b.step === "number" ? b.step : null,
        step_id: b.step_id != null ? String(b.step_id) : null,
        title: b.title ?? "",
        text: typeof b.text === "string" ? b.text : "",
        content: typeof b.content === "string" ? b.content : "",
        tools: Array.isArray(b.tools)
          ? b.tools
              .filter((t: any) => t && typeof t.name === "string")
              .map((t: any) => ({
                name: t.name,
                args: typeof t.args === "string" ? t.args : undefined,
                result: typeof t.result === "string" ? t.result : undefined,
                status: typeof t.status === "string" ? t.status : undefined,
              }))
          : [],
      }));
  }

  const assistantTurns = computed(() => messages.value.filter((m) => m.role === "assistant"));

  const selectedTurn = computed<Message | null>(() => {
    const turns = assistantTurns.value;
    return turns.find((m) => m.id === selectedTurnId.value) ?? turns[turns.length - 1] ?? null;
  });

  const selectedIsActive = computed(
    () => !!selectedTurn.value && selectedTurn.value.id === activeAssistantId.value,
  );

  function derivePlan(blocks: ReasoningBlock[]): Plan | null {
    const items = new Map<string, PlanItem>();
    for (const block of blocks) {
      if (block.step == null) continue;
      const key = block.step_id ?? `step-${block.step}`;
      if (!items.has(key)) {
        items.set(key, {
          id: key,
          content: block.title || `步骤 ${block.step}`,
          status: "completed",
          parent: null,
        });
      }
    }
    return items.size ? { items: [...items.values()] } : null;
  }

  const viewReasoning = computed<ReasoningBlock[]>(() =>
    selectedIsActive.value
      ? reasoning.value
      : normalizeReasoning(selectedTurn.value?.tool_payload?.reasoning),
  );

  const viewPlan = computed<Plan | null>(() => {
    const turn = selectedTurn.value;
    if (!turn) return null;
    if (selectedIsActive.value) return plan.value ?? turn.tool_payload?.plan ?? null;
    const stored = turn.tool_payload?.plan;
    if (stored) return stored;
    const turns = assistantTurns.value;
    if (turns[turns.length - 1] === turn && plan.value) return plan.value;
    return derivePlan(viewReasoning.value);
  });

  const viewStreaming = computed(() => streaming.value && selectedIsActive.value);
  const viewCurrentStep = computed(() => (selectedIsActive.value ? currentStep.value : null));
  const viewRunningTool = computed(() => (selectedIsActive.value ? runningTool.value : null));

  function selectTurn(id: string) {
    selectedTurnId.value = id;
  }

  async function loadConversationPending(targetConvId: string) {
    try {
      const [memRes, skillRes] = await Promise.allSettled([
        api.get<MemoryOverview>("/users/me/memory"),
        api.get<SkillPendingItem[]>("/skills/pending"),
      ]);
      if (convId.value !== targetConvId) return;
      if (memRes.status === "fulfilled" && Array.isArray(memRes.value?.pending)) {
        pendingMemory.value = memRes.value.pending.filter(
          (item) => (!item.conversation_id || item.conversation_id === targetConvId) && (item.status ?? "pending") === "pending",
        );
      }
      if (skillRes.status === "fulfilled" && Array.isArray(skillRes.value)) {
        pendingSkills.value = skillRes.value.filter(
          (item) => (!item.conversation_id || item.conversation_id === targetConvId) && (item.status ?? "pending") === "pending",
        );
      }
    } catch {
      /* ignore pending load failures */
    }
  }

  function loadFromConversation(detail: ConversationDetail) {
    convId.value = detail.id;
    messages.value = detail.messages.map((m) => ({ ...m }));
    plan.value = detail.plan;
    const lastReasoned = detail.messages.findLast(
      (m) => m.role === "assistant" && Array.isArray(m.tool_payload?.reasoning) && m.tool_payload.reasoning.length,
    );
    reasoning.value = normalizeReasoning(lastReasoned?.tool_payload?.reasoning);
    const lastAssistant = detail.messages.findLast((m) => m.role === "assistant");
    selectedTurnId.value = lastAssistant?.id ?? null;
    activeRunId.value = detail.active_run_id;
    pendingControl.value = null;
    pendingMemory.value = [];
    pendingSkills.value = [];
    pendingUserTargetId = null;
    error.value = null;
    streaming.value = false;
    activeAssistantId.value = null;
    if (detail.active_run_id && detail.active_run_status && detail.active_run_status !== "completed") {
      void reconnect(detail.active_run_id);
    }
    void loadConversationPending(detail.id);
  }

  function reset() {
    controller?.abort();
    controller = null;
    convId.value = null;
    messages.value = [];
    streaming.value = false;
    activeAssistantId.value = null;
    activeRunId.value = null;
    plan.value = null;
    reasoning.value = [];
    selectedTurnId.value = null;
    pendingControl.value = null;
    pendingMemory.value = [];
    pendingSkills.value = [];
    pendingUserTargetId = null;
    error.value = null;
  }

  function reasoningBlock(step: number | null, title: string): ReasoningBlock {
    const last = reasoning.value[reasoning.value.length - 1];
    if (last && last.step === step) return last;
    const block: ReasoningBlock = { step, step_id: null, title, text: "", content: "", tools: [] };
    reasoning.value.push(block);
    return block;
  }

  function syncTurnToMessage() {
    const a = assistant();
    if (!a) return;
    const payload = { ...(a.tool_payload ?? {}) };
    payload.reasoning = reasoning.value.map((b) => ({ ...b }));
    if (plan.value) payload.plan = plan.value;
    a.tool_payload = payload;
  }

  function extractPendingItems<T extends { id: string }>(d: Record<string, any>, primaryKey: string): T[] {
    if (Array.isArray(d[primaryKey])) return d[primaryKey];
    if (Array.isArray(d.items)) return d.items;
    if (Array.isArray(d.pending)) return d.pending;
    if (d.item && typeof d.item === "object" && typeof d.item.id === "string") return [d.item as T];
    if (typeof d.id === "string") return [d as T];
    return [];
  }

  function mergePending<T extends { id: string }>(target: T[], incoming: T[]): T[] {
    if (!incoming.length) return target;
    const next = [...target];
    for (const item of incoming) {
      if (!item?.id) continue;
      const idx = next.findIndex((existing) => existing.id === item.id);
      if (idx >= 0) next[idx] = { ...next[idx], ...item };
      else next.push(item);
    }
    return next;
  }

  function appendArtifactToAssistant(rawFile: ConversationFile | WorkspaceArtifactMeta) {
    const a = assistant();
    if (!a) return;
    const payload: ToolPayload = { ...(a.tool_payload ?? {}) };
    const prev = Array.isArray(payload.artifacts) ? [...payload.artifacts] : [];
    const meta: WorkspaceArtifactMeta = {
      id: rawFile.id,
      filename: rawFile.filename,
      ext: rawFile.ext,
      category: rawFile.category,
      size_bytes: rawFile.size_bytes,
      mime_type: rawFile.mime_type,
      source: rawFile.source ?? "assistant",
      is_global: rawFile.is_global,
      message_id: rawFile.message_id ?? a.id,
      preview_url: rawFile.preview_url,
      thumb_url: rawFile.thumb_url,
      preview_expires_at: rawFile.preview_expires_at,
    };
    const idx = prev.findIndex((item) => item.id === meta.id);
    if (idx >= 0) prev[idx] = { ...prev[idx], ...meta };
    else prev.push(meta);
    payload.artifacts = prev;
    a.tool_payload = payload;
  }

  function handleEvent(ev: SSEEvent) {
    const d = ev.data as Record<string, any>;
    switch (ev.event) {
      case "message.created": {
        const userMsg = messages.value.find(
          (m) => m.id.startsWith("temp-user") || (pendingUserTargetId !== null && m.id === pendingUserTargetId),
        );
        if (userMsg && d.user_message_id) userMsg.id = d.user_message_id;
        pendingUserTargetId = null;
        const a = assistant();
        if (a && d.assistant_message_id) {
          const previousId = a.id;
          a.id = d.assistant_message_id;
          activeAssistantId.value = d.assistant_message_id;
          if (selectedTurnId.value === previousId) selectedTurnId.value = d.assistant_message_id;
        }
        break;
      }
      case "run.started":
        activeRunId.value = d.run_id ?? null;
        break;
      case "title.updated": {
        const id = typeof d.conversation_id === "string" ? d.conversation_id : convId.value;
        const title = typeof d.title === "string" ? d.title.trim() : "";
        if (id && title) useConversationsStore().applyTitle(id, title);
        break;
      }
      case "run.reconnected":
        activeAssistantId.value = d.assistant_message_id ?? activeAssistantId.value;
        if (d.assistant_message_id) selectedTurnId.value = d.assistant_message_id;
        activeRunId.value = d.run_id ?? activeRunId.value;
        streaming.value = true;
        break;
      case "reasoning.delta": {
        const step = typeof d.step === "number" ? d.step : null;
        const block = reasoningBlock(step, typeof d.title === "string" ? d.title : "");
        block.text += d.text ?? "";
        syncTurnToMessage();
        break;
      }
      case "reasoning.block": {
        const step = typeof d.step === "number" ? d.step : null;
        const block = reasoningBlock(step, typeof d.title === "string" ? d.title : "");
        block.text = d.text ?? "";
        syncTurnToMessage();
        break;
      }
      case "reasoning.sync": {
        if (!Array.isArray(d.blocks)) break;
        reasoning.value = normalizeReasoning(d.blocks).map((b) => ({ ...b }));
        syncTurnToMessage();
        break;
      }
      case "message.delta": {
        const a = assistant();
        if (a) a.content += d.text ?? "";
        break;
      }
      case "commentary": {
        const text = typeof d.text === "string" ? d.text.trim() : "";
        if (!text) break;
        const step = typeof d.step === "number" ? d.step : null;
        const block = reasoningBlock(step, typeof d.title === "string" ? d.title : "");
        const existing = block.content ?? "";
        if (!existing.includes(text)) {
          block.content = existing ? `${existing}\n\n${text}` : text;
        }
        if (d.already_streamed) {
          const a = assistant();
          if (a) {
            const trimmed = a.content.trimEnd();
            if (trimmed.endsWith(text)) a.content = trimmed.slice(0, -text.length).trimEnd();
          }
        }
        syncTurnToMessage();
        break;
      }
      case "message.interim":
        break;
      case "tool.started": {
        messages.value.push({
          id: d.message_id ?? tempId("tool"),
          role: "tool",
          content: "",
          tool_name: d.tool ?? "tool",
          tool_payload: { args: d.preview, status: "running" },
          status: "running",
          hermes_run_id: activeRunId.value,
          created_at: new Date().toISOString(),
        });
        break;
      }
      case "tool.completed": {
        const row =
          findMessage(d.message_id) ??
          messages.value.findLast((m) => m.role === "tool" && m.tool_name === d.tool && m.status === "running");
        if (row) {
          row.tool_payload = {
            ...(row.tool_payload ?? {}),
            result: d.preview,
            duration: d.duration,
            error: d.error,
            status: d.error ? "failed" : "completed",
          };
          row.status = d.error ? "failed" : "completed";
        }
        break;
      }
      case "plan.updated":
        plan.value = { items: d.items ?? [] };
        syncTurnToMessage();
        break;
      case "approval.request":
        pendingControl.value = {
          kind: "approval",
          request_id: d.request_id ?? null,
          execution_generation: d.execution_generation ?? null,
          tool: d.tool,
          preview: d.preview,
        };
        { const a = assistant(); if (a) a.status = "waiting"; }
        break;
      case "clarify.request":
        pendingControl.value = {
          kind: "clarify",
          request_id: d.request_id ?? null,
          execution_generation: d.execution_generation ?? null,
          tool: d.tool,
          preview: d.preview,
        };
        { const a = assistant(); if (a) a.status = "waiting"; }
        break;
      case "workspace.file_created": {
        const rawFile = (d.file && typeof d.file === "object" ? d.file : d) as ConversationFile | undefined;
        if (!rawFile?.id || !rawFile?.filename) break;
        useFilesStore().upsertFile(rawFile);
        appendArtifactToAssistant(rawFile);
        break;
      }
      case "memory.pending": {
        const items = extractPendingItems<MemoryPendingItem>(d, "memory");
        pendingMemory.value = mergePending(pendingMemory.value, items);
        break;
      }
      case "skills.pending":
      case "skill.pending": {
        const items = extractPendingItems<SkillPendingItem>(d, "skills");
        pendingSkills.value = mergePending(pendingSkills.value, items);
        break;
      }
      case "run.completed": {
        const a = assistant();
        if (a) {
          if (typeof d.output === "string" && d.output) a.content = d.output;
          a.status = "completed";
        }
        if (Array.isArray(d.artifacts)) {
          for (const art of d.artifacts) {
            if (art && typeof art === "object" && art.id && art.filename) {
              appendArtifactToAssistant(art as WorkspaceArtifactMeta);
            }
          }
        }
        if (Array.isArray(d.reasoning)) reasoning.value = normalizeReasoning(d.reasoning);
        if (d.plan) plan.value = d.plan;
        syncTurnToMessage();
        finishRun();
        break;
      }
      case "run.failed": {
        const a = assistant();
        if (a) {
          if (typeof d.output === "string" && d.output) a.content = d.output;
          a.status = "failed";
        }
        if (Array.isArray(d.reasoning)) reasoning.value = normalizeReasoning(d.reasoning);
        if (d.plan) plan.value = d.plan;
        syncTurnToMessage();
        error.value = typeof d.error === "string" ? d.error : "任务执行失败";
        finishRun();
        break;
      }
      case "run.cancelled":
      case "run.interrupted": {
        const a = assistant();
        if (a) a.status = "cancelled";
        if (Array.isArray(d.reasoning)) reasoning.value = normalizeReasoning(d.reasoning);
        if (d.plan) plan.value = d.plan;
        syncTurnToMessage();
        finishRun();
        break;
      }
      case "error": {
        const a = assistant();
        if (a && a.status === "streaming") a.status = "failed";
        error.value = typeof d.detail === "string" ? d.detail : d.code === "agent_warming_up" ? "助理初始化中，请稍后重试" : "发生错误";
        finishRun();
        break;
      }
      default:
        break;
    }
  }

  function finishRun() {
    streaming.value = false;
    activeRunId.value = null;
    pendingControl.value = null;
    pendingUserTargetId = null;
  }

  async function consume(gen: AsyncGenerator<SSEEvent>) {
    let aborted = false;
    try {
      for await (const ev of gen) {
        handleEvent(ev);
      }
    } catch (e: any) {
      if (e?.name === "AbortError") {
        aborted = true;
        return;
      }
      error.value = apiErrorMessage(e, "连接中断");
      const a = assistant();
      if (a && a.status === "streaming") a.status = "failed";
      streaming.value = false;
    } finally {
      if (!aborted && streaming.value) {
        const a = assistant();
        if (a && a.status === "streaming") a.status = "failed";
        if (!error.value) error.value = "连接已结束，未收到完成事件";
        finishRun();
      }
    }
  }

  function buildUserToolPayload(attachedFiles: ConversationFile[], skillNames: string[]): ToolPayload | null {
    const payload: ToolPayload = {};
    if (attachedFiles.length) {
      payload.attachments = attachedFiles.map((f) => ({
        id: f.id,
        filename: f.filename,
        ext: f.ext,
        category: f.category,
        size_bytes: f.size_bytes,
      }));
    }
    if (skillNames.length) {
      payload.skills = [...skillNames];
    }
    return Object.keys(payload).length ? payload : null;
  }

  function pushAssistantPlaceholder(): string {
    const assistantId = tempId("temp-assistant");
    messages.value.push({
      id: assistantId,
      role: "assistant",
      content: "",
      tool_name: null,
      tool_payload: null,
      status: "streaming",
      hermes_run_id: null,
      created_at: new Date().toISOString(),
    });
    activeAssistantId.value = assistantId;
    selectedTurnId.value = assistantId;
    return assistantId;
  }

  async function streamTurn(
    path: string,
    body: Record<string, unknown>,
    fallbackError: string,
  ) {
    if (!convId.value) return;
    streaming.value = true;
    controller = new AbortController();
    try {
      const headers = await chatTicketHeaders(convId.value, "send");
      await consume(streamSSE(path, body, controller.signal, headers));
    } catch (e: any) {
      error.value = apiErrorMessage(e, fallbackError);
      const a = assistant();
      if (a && a.status === "streaming") a.status = "failed";
      finishRun();
    }
  }

  async function send(content: string, attachedFiles: ConversationFile[] = [], skillNames: string[] = []) {
    if (!convId.value || streaming.value) return;
    error.value = null;
    reasoning.value = [];
    plan.value = null;
    pendingControl.value = null;
    pendingUserTargetId = null;
    const userId = tempId("temp-user");
    const fileIds = attachedFiles.map((f) => f.id);
    messages.value.push({
      id: userId,
      role: "user",
      content,
      tool_name: null,
      tool_payload: buildUserToolPayload(attachedFiles, skillNames),
      status: "completed",
      hermes_run_id: null,
      created_at: new Date().toISOString(),
    });
    pushAssistantPlaceholder();
    const body: Record<string, unknown> = { content };
    if (fileIds.length) body.file_ids = fileIds;
    if (skillNames.length) body.skill_names = skillNames;
    await streamTurn(`/conversations/${convId.value}/messages`, body, "发送失败");
  }

  async function regenerate(assistantMessageId: string) {
    if (!convId.value || streaming.value) return;
    const idx = messages.value.findIndex((m) => m.id === assistantMessageId && m.role === "assistant");
    if (idx < 0) return;

    let prevUserIdx = -1;
    for (let i = idx - 1; i >= 0; i--) {
      if (messages.value[i].role === "user") {
        prevUserIdx = i;
        break;
      }
    }

    if (assistantMessageId.startsWith("temp-") && prevUserIdx >= 0 && messages.value[prevUserIdx].id.startsWith("temp-")) {
      const prevUser = messages.value[prevUserIdx];
      const filesStore = useFilesStore();
      const attached = (prevUser.tool_payload?.attachments ?? []).map((att) => {
        const found = filesStore.files.find((f) => f.id === att.id);
        if (found) return found;
        return {
          id: att.id,
          conversation_id: convId.value,
          filename: att.filename,
          ext: att.ext,
          mime_type: "",
          category: att.category,
          size_bytes: att.size_bytes,
          status: "ready",
          source: "user",
          is_global: false,
          created_at: prevUser.created_at,
          updated_at: prevUser.created_at,
        } satisfies ConversationFile;
      });
      const skills = prevUser.tool_payload?.skills ?? [];
      messages.value = messages.value.slice(0, prevUserIdx);
      await send(prevUser.content, attached, skills);
      return;
    }

    error.value = null;
    reasoning.value = [];
    plan.value = null;
    pendingControl.value = null;
    pendingUserTargetId = null;
    messages.value = messages.value.slice(0, prevUserIdx >= 0 ? prevUserIdx + 1 : idx);
    pushAssistantPlaceholder();
    await streamTurn(`/conversations/${convId.value}/messages/${assistantMessageId}/regenerate`, {}, "重新生成失败");
  }

  async function editAndResend(
    userMessageId: string,
    content: string,
    attachedFiles: ConversationFile[] = [],
    skillNames: string[] = [],
  ) {
    if (!convId.value || streaming.value) return;
    const idx = messages.value.findIndex((m) => m.id === userMessageId && m.role === "user");
    if (idx < 0) return;

    if (userMessageId.startsWith("temp-")) {
      messages.value = messages.value.slice(0, idx);
      await send(content, attachedFiles, skillNames);
      return;
    }

    error.value = null;
    reasoning.value = [];
    plan.value = null;
    pendingControl.value = null;
    pendingUserTargetId = userMessageId;

    const targetUser = messages.value[idx];
    messages.value = [
      ...messages.value.slice(0, idx),
      {
        ...targetUser,
        content,
        tool_payload: buildUserToolPayload(attachedFiles, skillNames),
      },
    ];
    pushAssistantPlaceholder();

    const fileIds = attachedFiles.map((f) => f.id);
    await streamTurn(
      `/conversations/${convId.value}/messages/${userMessageId}/edit`,
      { content, file_ids: fileIds, skill_names: skillNames },
      "保存并重发失败",
    );
  }

  async function resolvePendingMemory(id: string, action: "approve" | "reject", content?: string) {
    const body = content !== undefined ? { action, content } : { action };
    await api.post(`/users/me/memory/pending/${id}`, body);
    pendingMemory.value = pendingMemory.value.filter((item) => item.id !== id);
  }

  async function resolvePendingSkill(id: string, action: "approve" | "reject", content?: string) {
    const body = content !== undefined ? { action, content } : { action };
    await api.post(`/skills/pending/${id}`, body);
    pendingSkills.value = pendingSkills.value.filter((item) => item.id !== id);
  }

  async function reconnect(runId: string) {
    if (!convId.value) return;
    streaming.value = true;
    controller = new AbortController();
    try {
      const headers = await chatTicketHeaders(convId.value, "reconnect");
      await consume(
        streamSSEGet(`/conversations/${convId.value}/runs/${runId}/events`, controller.signal, headers),
      );
    } catch (e: any) {
      error.value = apiErrorMessage(e, "连接中断");
      streaming.value = false;
      finishRun();
    }
  }

  async function stop() {
    if (!convId.value) return;
    try {
      const headers = await chatTicketHeaders(convId.value, "stop");
      await api.post(`/conversations/${convId.value}/stop`, {}, { headers });
    } catch (e: any) {
      error.value = apiErrorMessage(e, "停止失败");
    }
  }

  async function approve(choice: "once" | "deny") {
    if (!convId.value || !pendingControl.value) return;
    const c = pendingControl.value;
    try {
      const headers = await chatTicketHeaders(convId.value, "approval");
      await api.post(
        `/conversations/${convId.value}/approval`,
        {
          request_id: c.request_id,
          execution_generation: c.execution_generation,
          choice,
        },
        { headers },
      );
      pendingControl.value = null;
      const a = assistant();
      if (a) a.status = "streaming";
    } catch (e: any) {
      error.value = apiErrorMessage(e, "审批提交失败");
    }
  }

  async function clarify(answer: string) {
    if (!convId.value || !pendingControl.value) return;
    const c = pendingControl.value;
    try {
      const headers = await chatTicketHeaders(convId.value, "clarify");
      await api.post(
        `/conversations/${convId.value}/clarify`,
        {
          request_id: c.request_id,
          execution_generation: c.execution_generation,
          answer,
        },
        { headers },
      );
      pendingControl.value = null;
      const a = assistant();
      if (a) a.status = "streaming";
    } catch (e: any) {
      error.value = apiErrorMessage(e, "提交失败");
    }
  }

  function abort() {
    controller?.abort();
    controller = null;
  }

  return {
    convId, messages, streaming, activeAssistantId, activeRunId, plan, reasoning, currentStep, runningTool,
    selectedTurnId, selectedTurn, assistantTurns, viewPlan, viewReasoning, viewStreaming, viewCurrentStep,
    viewRunningTool, selectTurn,
    pendingControl, pendingMemory, pendingSkills, error,
    loadFromConversation, reset, send, regenerate, editAndResend, reconnect, stop, approve, clarify, abort,
    resolvePendingMemory, resolvePendingSkill,
  };
});