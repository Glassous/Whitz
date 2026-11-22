import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";
import { chatTicketHeaders } from "../api/chatTickets";
import { streamSSE, streamSSEGet, type SSEEvent } from "../api/sse";
import type {
  ClarifyDetail,
  ClarifyQuestionItem,
  ClarifySubmitPayload,
  ConversationDetail,
  ConversationFile,
  MemoryOverview,
  MemoryPendingItem,
  Message,
  MessageReaction,
  PendingControl,
  Plan,
  PlanItem,
  ReasoningBlock,
  ScheduledTaskPendingItem,
  SkillPendingItem,
  ToolPayload,
  UserReactionType,
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
  const waitingFirstByte = ref(false);
  const stopping = ref(false);
  const reconnecting = ref(false);
  const approvingChoice = ref<"once" | "deny" | null>(null);
  const submittingClarify = ref(false);
  const activeAssistantId = ref<string | null>(null);
  const activeRunId = ref<string | null>(null);
  const plan = ref<Plan | null>(null);
  const reasoning = ref<ReasoningBlock[]>([]);
  const pendingControl = ref<PendingControl | null>(null);
  const pendingMemory = ref<MemoryPendingItem[]>([]);
  const pendingSkills = ref<SkillPendingItem[]>([]);
  const pendingSchedules = ref<ScheduledTaskPendingItem[]>([]);
  const error = ref<string | null>(null);
  const selectedTurnId = ref<string | null>(null);
  let controller: AbortController | null = null;
  let pendingUserTargetId: string | null = null;
  let lastEventId: string | null = null;
  let pendingPollTimer: ReturnType<typeof setTimeout> | null = null;

  const currentStep = computed(() => {
    const items = plan.value?.items ?? [];
    const idx = items.findIndex((i) => i.status === "in_progress");
    if (idx < 0) return null;
    return { index: idx + 1, total: items.length, title: items[idx].content };
  });

  const runningTool = computed(() => {
    const row = messages.value.findLast((m) => m.role === "tool" && m.status === "running");
    if (!row?.tool_name) return null;
    if (pendingControl.value && (pendingControl.value.tool === row.tool_name || row.tool_name === "clarify" || row.tool_name === "execute_code")) {
      return null;
    }
    return row.tool_name;
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
                call_id: t.call_id != null ? String(t.call_id) : null,
                args: typeof t.args === "string" ? t.args : undefined,
                result: typeof t.result === "string" ? t.result : undefined,
                status: typeof t.status === "string" ? t.status : undefined,
                duration_ms: typeof t.duration_ms === "number" ? t.duration_ms : null,
                error: typeof t.error === "string" ? t.error : null,
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
      const [memRes, skillRes, schedRes] = await Promise.allSettled([
        api.get<MemoryOverview>("/users/me/memory"),
        api.get<SkillPendingItem[]>("/skills/pending"),
        api.get<ScheduledTaskPendingItem[]>("/schedules/pending"),
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
      if (schedRes.status === "fulfilled" && Array.isArray(schedRes.value)) {
        pendingSchedules.value = schedRes.value.filter(
          (item) => (!item.conversation_id || item.conversation_id === targetConvId) && (item.status ?? "pending") === "pending",
        );
      }
    } catch {
      /* ignore pending load failures */
    }
  }

  const ACTIVE_STATUS_SET = new Set([
    "starting",
    "queued",
    "running",
    "waiting",
    "waiting_for_approval",
    "waiting_for_clarify",
  ]);

  function clearPendingPoll() {
    if (pendingPollTimer) {
      clearTimeout(pendingPollTimer);
      pendingPollTimer = null;
    }
  }

  function looksLikeSubquestions(items: string[]): boolean {
    if (items.length < 2) return false;
    const qMarks = items.filter((item) => item.includes("?") || item.includes("？")).length;
    if (qMarks >= Math.max(2, Math.ceil(items.length / 2))) return true;
    const numbered = items.filter((item) => /^\s*\d+[.、)）]\s*/.test(item)).length;
    const longItems = items.filter((item) => item.length >= 24).length;
    return numbered >= 2 && longItems >= 2;
  }

  function normalizeClarifyDetail(raw: Record<string, any>): ClarifyDetail {
    const det = raw.detail && typeof raw.detail === "object" ? (raw.detail as Record<string, any>) : raw;
    const previewObj = raw.preview && typeof raw.preview === "object" ? (raw.preview as Record<string, any>) : null;
    const rawTopQuestion =
      (typeof det.question === "string" && det.question.trim()) ||
      (typeof raw.question === "string" && raw.question.trim()) ||
      (previewObj && typeof previewObj.question === "string" && previewObj.question.trim()) ||
      (typeof raw.preview === "string" && raw.preview.trim()) ||
      "";
    const topMultiple = Boolean(det.multiple ?? raw.multiple);
    const rawOptsSource = Array.isArray(det.options)
      ? det.options
      : Array.isArray(raw.options)
        ? raw.options
        : previewObj && Array.isArray(previewObj.options)
          ? previewObj.options
          : [];
    let topOptions = rawOptsSource.map((o: unknown) => String(o ?? "").trim()).filter(Boolean);

    const rawQuestionsSource = Array.isArray(det.questions)
      ? det.questions
      : Array.isArray(raw.questions)
        ? raw.questions
        : previewObj && Array.isArray(previewObj.questions)
          ? previewObj.questions
          : [];

    const questions: ClarifyQuestionItem[] = [];
    if (rawQuestionsSource.length > 0) {
      rawQuestionsSource.forEach((item: any, idx: number) => {
        if (item && typeof item === "object") {
          const qText = String(item.question ?? item.title ?? item.prompt ?? "").trim();
          if (!qText) return;
          const opts = Array.isArray(item.options)
            ? item.options.map((o: unknown) => String(o ?? "").trim()).filter(Boolean)
            : [];
          questions.push({
            id: String(item.id || `q${idx + 1}`),
            question: qText,
            options: opts,
            multiple: Boolean(item.multiple),
            allow_custom: item.allow_custom !== false,
            placeholder: typeof item.placeholder === "string" && item.placeholder.trim() ? item.placeholder.trim() : null,
          });
        } else if (typeof item === "string" && item.trim()) {
          questions.push({
            id: `q${idx + 1}`,
            question: item.trim(),
            options: [],
            multiple: false,
            allow_custom: true,
            placeholder: null,
          });
        }
      });
    } else if (topOptions.length > 0 && looksLikeSubquestions(topOptions)) {
      topOptions.forEach((text: string, idx: number) => {
        questions.push({
          id: `q${idx + 1}`,
          question: text,
          options: [],
          multiple: false,
          allow_custom: true,
          placeholder: null,
        });
      });
      topOptions = [];
    }

    if (questions.length === 0) {
      questions.push({
        id: "q1",
        question: rawTopQuestion || "请补充更多信息以便继续。",
        options: topOptions,
        multiple: topMultiple,
        allow_custom: det.allow_custom !== false,
        placeholder: null,
      });
    }

    return {
      question: rawTopQuestion || (questions.length === 1 ? questions[0].question : "请补充以下信息以便继续："),
      options: topOptions,
      multiple: topMultiple,
      questions,
    };
  }

  function hydratePendingControl(raw: any) {
    if (!raw || typeof raw !== "object") {
      pendingControl.value = null;
      return;
    }
    const kind = raw.kind === "approval" || raw.tool === "execute_code" ? "approval" : "clarify";
    const detail = raw.detail && typeof raw.detail === "object" ? (raw.detail as Record<string, any>) : null;
    pendingControl.value = {
      kind,
      request_id: raw.request_id ?? raw.prompt_id ?? null,
      execution_generation: raw.execution_generation ?? null,
      tool: raw.tool,
      preview: formatControlPreview(raw),
      detail,
      clarify: kind === "clarify" ? normalizeClarifyDetail(raw) : null,
    };
  }

  function pollPendingRun(targetConvId: string, attemptsLeft = 8) {
    clearPendingPoll();
    if (attemptsLeft <= 0 || convId.value !== targetConvId) return;
    pendingPollTimer = setTimeout(async () => {
      pendingPollTimer = null;
      if (convId.value !== targetConvId) return;
      try {
        const detail = await useConversationsStore().open(targetConvId);
        if (convId.value !== targetConvId) return;
        if (detail.active_run_id && detail.active_run_id !== "pending") {
          loadFromConversation(detail);
        } else if (detail.active_run_id === "pending") {
          pollPendingRun(targetConvId, attemptsLeft - 1);
        } else {
          loadFromConversation(detail);
        }
      } catch {
        /* ignore */
      }
    }, 600);
  }

  function loadFromConversation(detail: ConversationDetail) {
    clearPendingPoll();
    controller?.abort();
    controller = null;
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
    lastEventId = null;
    hydratePendingControl(detail.pending_control);
    pendingMemory.value = [];
    pendingSkills.value = [];
    pendingSchedules.value = [];
    pendingUserTargetId = null;
    error.value = null;
    streaming.value = false;
    waitingFirstByte.value = false;
    stopping.value = false;
    reconnecting.value = false;
    approvingChoice.value = null;
    submittingClarify.value = false;
    activeAssistantId.value = lastAssistant?.id ?? null;
    if (detail.active_run_id === "pending") {
      streaming.value = true;
      waitingFirstByte.value = true;
      pollPendingRun(detail.id);
    } else if (detail.active_run_id && detail.active_run_status && ACTIVE_STATUS_SET.has(detail.active_run_status)) {
      void reconnect(detail.active_run_id);
    }
    void loadConversationPending(detail.id);
  }

  function reset() {
    clearPendingPoll();
    controller?.abort();
    controller = null;
    convId.value = null;
    messages.value = [];
    streaming.value = false;
    waitingFirstByte.value = false;
    stopping.value = false;
    reconnecting.value = false;
    approvingChoice.value = null;
    submittingClarify.value = false;
    activeAssistantId.value = null;
    activeRunId.value = null;
    lastEventId = null;
    plan.value = null;
    reasoning.value = [];
    selectedTurnId.value = null;
    pendingControl.value = null;
    pendingMemory.value = [];
    pendingSkills.value = [];
    pendingSchedules.value = [];
    pendingUserTargetId = null;
    error.value = null;
  }

  function clearPendingControlFromSync() {
    pendingControl.value = null;
    approvingChoice.value = null;
    submittingClarify.value = false;
    const a = assistant();
    if (a && a.status === "waiting") a.status = "streaming";
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

  function stringifyToolVal(val: unknown): string {
    if (val == null) return "";
    if (typeof val === "string") return val;
    try {
      return JSON.stringify(val);
    } catch {
      return String(val);
    }
  }

  function formatControlPreview(d: Record<string, any>): string | null {
    if (typeof d.code === "string" && d.code.trim()) {
      const header = [d.language ? `[${d.language}]` : "", d.description].filter(Boolean).join(" ");
      return header ? `${header}\n${d.code}` : d.code;
    }
    if (typeof d.preview === "string") return d.preview;
    if (d.preview && typeof d.preview === "object") {
      const p = d.preview as Record<string, unknown>;
      if (typeof p.question === "string" && p.question) return p.question;
      if (typeof p.code === "string" && p.code) {
        const header = [p.language ? `[${p.language}]` : "", p.reason].filter(Boolean).join(" ");
        return header ? `${header}\n${p.code}` : p.code;
      }
      return stringifyToolVal(d.preview);
    }
    if (d.detail && typeof d.detail === "object") {
      const det = d.detail as Record<string, unknown>;
      if (typeof det.question === "string" && det.question) return det.question;
      if (typeof det.code === "string" && det.code) return det.code;
    }
    return null;
  }

  function handleEvent(ev: SSEEvent) {
    const d = ev.data as Record<string, any>;
    if (ev.id && ev.id !== "0-0") {
      lastEventId = ev.id;
    }
    if (ev.event !== "run.started" && ev.event !== "message.created" && ev.event !== "run.reconnected") {
      waitingFirstByte.value = false;
    }
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
      case "message.reaction": {
        const mid = typeof d.message_id === "string" ? d.message_id : "";
        if (mid && Array.isArray(d.reactions)) {
          applyMessageReactions(mid, d.reactions as MessageReaction[]);
        }
        break;
      }
      case "title.updated":
      case "conversation.title_updated": {
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
        reconnecting.value = false;
        break;
      case "run.snapshot": {
        // Atomic state reconciliation for refresh / tab-switch / multi-device join — ZERO duplication!
        if (d.assistant_message_id) {
          activeAssistantId.value = d.assistant_message_id;
          selectedTurnId.value = d.assistant_message_id;
        }
        if (d.run_id) activeRunId.value = d.run_id;
        if (typeof d.last_event_id === "string" && d.last_event_id !== "0-0") {
          lastEventId = d.last_event_id;
        }
        const a = assistant();
        if (a) {
          if (typeof d.output === "string") a.content = d.output;
          if (typeof d.status === "string") {
            a.status =
              d.status === "waiting_for_approval" || d.status === "waiting_for_clarify"
                ? "waiting"
                : d.status === "running" || d.status === "queued"
                  ? "streaming"
                  : (d.status as any);
          }
        }
        if (Array.isArray(d.reasoning)) {
          reasoning.value = normalizeReasoning(d.reasoning);
        }
        if (d.plan && typeof d.plan === "object") {
          plan.value = d.plan;
        }
        if (Array.isArray(d.artifacts)) {
          for (const art of d.artifacts) {
            if (art && typeof art === "object" && art.id && art.filename) {
              appendArtifactToAssistant(art as WorkspaceArtifactMeta);
            }
          }
        }
        if (d.pending_control) {
          hydratePendingControl(d.pending_control);
        } else if (Array.isArray(d.pending_controls) && d.pending_controls.length) {
          hydratePendingControl(d.pending_controls[0]);
        } else {
          pendingControl.value = null;
        }
        syncTurnToMessage();
        reconnecting.value = false;
        waitingFirstByte.value = false;
        break;
      }
      case "control.resolved":
      case "run.resumed": {
        clearPendingControlFromSync();
        break;
      }
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
      case "graph.node":
        break;
      case "tool.started": {
        const rawArgs = stringifyToolVal(d.args ?? d.preview);
        const existingMsg = d.message_id
          ? findMessage(d.message_id)
          : d.call_id
            ? messages.value.find((m) => m.role === "tool" && m.tool_payload?.call_id === d.call_id)
            : undefined;
        if (!existingMsg) {
          messages.value.push({
            id: d.message_id ?? tempId("tool"),
            role: "tool",
            content: "",
            tool_name: d.tool ?? "tool",
            tool_payload: { args: rawArgs || d.preview, call_id: d.call_id ?? null, status: "running" },
            status: "running",
            run_id: activeRunId.value,
            created_at: new Date().toISOString(),
          });
        }
        const blk = reasoningBlock(null, "");
        const toolsList = (blk.tools ??= []);
        const alreadyInTools = d.call_id && toolsList.some((t) => t.call_id === d.call_id);
        if (!alreadyInTools) {
          toolsList.push({
            name: d.tool ?? "tool",
            call_id: d.call_id ?? null,
            args: rawArgs,
            status: "running",
          });
        }
        syncTurnToMessage();
        break;
      }
      case "tool.completed": {
        const rawResult = stringifyToolVal(d.result ?? d.preview);
        const row =
          findMessage(d.message_id) ??
          messages.value.findLast((m) => m.role === "tool" && m.tool_name === d.tool && m.status === "running");
        if (row) {
          row.tool_payload = {
            ...(row.tool_payload ?? {}),
            result: rawResult || d.preview,
            duration: d.duration,
            error: d.error,
            status: d.error ? "failed" : "completed",
          };
          row.status = d.error ? "failed" : "completed";
        }
        for (let i = reasoning.value.length - 1; i >= 0; i--) {
          const tList = reasoning.value[i].tools;
          if (!tList?.length) continue;
          const match = tList.findLast(
            (t) =>
              (d.call_id && t.call_id === d.call_id) ||
              (!d.call_id && t.name === (d.tool ?? "tool") && t.status === "running"),
          );
          if (match) {
            match.status = d.error ? "failed" : "completed";
            match.result = rawResult;
            if (d.error) match.error = d.error;
            if (typeof d.duration_ms === "number") match.duration_ms = d.duration_ms;
            break;
          }
        }
        syncTurnToMessage();
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
          preview: formatControlPreview(d),
        };
        { const a = assistant(); if (a) a.status = "waiting"; }
        break;
      case "clarify.request":
        hydratePendingControl({ ...d, kind: "clarify" });
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
      case "schedules.pending":
      case "schedule.pending": {
        const items = extractPendingItems<ScheduledTaskPendingItem>(d, "schedules");
        pendingSchedules.value = mergePending(pendingSchedules.value, items);
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
    waitingFirstByte.value = false;
    stopping.value = false;
    reconnecting.value = false;
    approvingChoice.value = null;
    submittingClarify.value = false;
    activeRunId.value = null;
    pendingControl.value = null;
    pendingUserTargetId = null;
    lastEventId = null;
  }

  async function consume(
    gen: AsyncGenerator<SSEEvent>,
    targetConvId: string,
    myController: AbortController,
  ): Promise<"done" | "aborted" | "dropped"> {
    try {
      for await (const ev of gen) {
        if (convId.value !== targetConvId || myController.signal.aborted) {
          return "aborted";
        }
        handleEvent(ev);
      }
      if (convId.value !== targetConvId || myController.signal.aborted) return "aborted";
      return streaming.value ? "dropped" : "done";
    } catch (e: any) {
      if (e?.name === "AbortError" || convId.value !== targetConvId || myController.signal.aborted) {
        return "aborted";
      }
      // Fatal HTTP 4xx errors (credits exhausted, rate limited, conflict, etc.) should not auto-retry
      if (typeof e?.status === "number" && e.status >= 400 && e.status < 500 && e.status !== 408) {
        error.value = apiErrorMessage(e, "请求失败");
        const a = assistant();
        if (a && a.status === "streaming") a.status = "failed";
        finishRun();
        return "done";
      }
      return "dropped";
    }
  }

  async function autoReconnectLoop(targetConvId: string, runId: string) {
    const delays = [1000, 2000, 4000, 8000, 12000];
    reconnecting.value = true;
    for (let attempt = 0; attempt < delays.length; attempt++) {
      if (convId.value !== targetConvId || !streaming.value) {
        reconnecting.value = false;
        return;
      }
      await new Promise((r) => setTimeout(r, delays[attempt]));
      if (convId.value !== targetConvId || !streaming.value) {
        reconnecting.value = false;
        return;
      }
      const myController = new AbortController();
      controller = myController;
      try {
        const headers = await chatTicketHeaders(targetConvId, "reconnect");
        if (lastEventId) headers["Last-Event-ID"] = lastEventId;
        const outcome = await consume(
          streamSSEGet(`/conversations/${targetConvId}/runs/${runId}/events`, myController.signal, headers),
          targetConvId,
          myController,
        );
        if (outcome === "done" || outcome === "aborted") {
          reconnecting.value = false;
          return;
        }
      } catch (e: any) {
        if (e?.name === "AbortError" || convId.value !== targetConvId) {
          reconnecting.value = false;
          return;
        }
        // If run already finished on server while we were offline, reload conversation cleanly!
        if (e?.status === 404) {
          try {
            const detail = await useConversationsStore().open(targetConvId);
            if (convId.value === targetConvId) loadFromConversation(detail);
          } catch {
            /* ignore */
          }
          reconnecting.value = false;
          return;
        }
      }
    }
    if (convId.value === targetConvId && streaming.value) {
      reconnecting.value = false;
      error.value = "网络连接中断，请检查网络或刷新页面同步最新状态";
      const a = assistant();
      if (a && a.status === "streaming") a.status = "failed";
      finishRun();
    }
  }

  async function recoverIfNeeded() {
    const cid = convId.value;
    if (!cid) return;
    if (streaming.value && activeRunId.value && activeRunId.value !== "pending" && !controller) {
      void reconnect(activeRunId.value);
      return;
    }
    if (!streaming.value) {
      try {
        const detail = await useConversationsStore().open(cid);
        if (convId.value === cid) {
          const hasNewMsgs = detail.messages.length !== messages.value.length;
          const hasLiveRun = Boolean(detail.active_run_id && detail.active_run_status && ACTIVE_STATUS_SET.has(detail.active_run_status));
          if (hasNewMsgs || hasLiveRun) {
            loadFromConversation(detail);
          }
        }
      } catch {
        /* ignore */
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
      run_id: null,
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
    const targetConvId = convId.value;
    if (!targetConvId) return;
    streaming.value = true;
    waitingFirstByte.value = true;
    lastEventId = null;
    const myController = new AbortController();
    controller = myController;
    try {
      const headers = await chatTicketHeaders(targetConvId, "send");
      headers["Idempotency-Key"] =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      if (convId.value !== targetConvId || myController.signal.aborted) return;
      const outcome = await consume(
        streamSSE(path, body, myController.signal, headers),
        targetConvId,
        myController,
      );
      if (outcome === "dropped" && convId.value === targetConvId && streaming.value) {
        if (activeRunId.value && activeRunId.value !== "pending") {
          await autoReconnectLoop(targetConvId, activeRunId.value);
        } else {
          // Run may have been created right as connection dropped -> reload & auto-attach
          try {
            const detail = await useConversationsStore().open(targetConvId);
            if (convId.value === targetConvId) loadFromConversation(detail);
          } catch {
            error.value = "连接中断，请刷新查看最新状态";
            finishRun();
          }
        }
      }
    } catch (e: any) {
      if (convId.value !== targetConvId || myController.signal.aborted) return;
      error.value = apiErrorMessage(e, fallbackError);
      const a = assistant();
      if (a && a.status === "streaming") a.status = "failed";
      finishRun();
    } finally {
      if (controller === myController) controller = null;
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
      run_id: null,
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

  async function resolvePendingSchedule(id: string, action: "approve" | "reject") {
    await api.post(`/schedules/pending/${id}`, { action });
    pendingSchedules.value = pendingSchedules.value.filter((item) => item.id !== id);
  }

  async function reconnect(runId: string) {
    const targetConvId = convId.value;
    if (!targetConvId || !runId || runId === "pending") return;
    controller?.abort();
    streaming.value = true;
    reconnecting.value = true;
    const myController = new AbortController();
    controller = myController;
    try {
      const headers = await chatTicketHeaders(targetConvId, "reconnect");
      if (lastEventId) headers["Last-Event-ID"] = lastEventId;
      if (convId.value !== targetConvId || myController.signal.aborted) return;
      const outcome = await consume(
        streamSSEGet(`/conversations/${targetConvId}/runs/${runId}/events`, myController.signal, headers),
        targetConvId,
        myController,
      );
      if (outcome === "dropped" && convId.value === targetConvId && streaming.value) {
        await autoReconnectLoop(targetConvId, runId);
      }
    } catch (e: any) {
      if (convId.value !== targetConvId || myController.signal.aborted) return;
      if (e?.status === 404) {
        try {
          const detail = await useConversationsStore().open(targetConvId);
          if (convId.value === targetConvId) loadFromConversation(detail);
        } catch {
          finishRun();
        }
        return;
      }
      await autoReconnectLoop(targetConvId, runId);
    } finally {
      reconnecting.value = false;
      if (controller === myController) controller = null;
    }
  }

  async function stop() {
    const targetConvId = convId.value;
    if (!targetConvId || stopping.value) return;
    stopping.value = true;
    try {
      const headers = await chatTicketHeaders(targetConvId, "stop");
      await api.post(`/conversations/${targetConvId}/stop`, {}, { headers });
      // Optimistically finalize local state in case SSE stream is slow/unresponsive
      setTimeout(() => {
        if (convId.value === targetConvId && stopping.value && streaming.value) {
          controller?.abort();
          const a = assistant();
          if (a && (a.status === "streaming" || a.status === "waiting")) a.status = "cancelled";
          finishRun();
        }
      }, 2500);
    } catch (e: any) {
      stopping.value = false;
      error.value = apiErrorMessage(e, "停止失败");
    }
  }

  async function approve(choice: "once" | "deny"): Promise<boolean> {
    const targetConvId = convId.value;
    if (!targetConvId || !pendingControl.value || approvingChoice.value) return false;
    const c = pendingControl.value;
    approvingChoice.value = choice;
    try {
      const headers = await chatTicketHeaders(targetConvId, "approval");
      await api.post(
        `/conversations/${targetConvId}/approval`,
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
      return true;
    } catch (e: any) {
      error.value = apiErrorMessage(e, "审批提交失败");
      return false;
    } finally {
      approvingChoice.value = null;
    }
  }

  async function clarify(payload: string | ClarifySubmitPayload): Promise<boolean> {
    const targetConvId = convId.value;
    if (!targetConvId || !pendingControl.value || submittingClarify.value) return false;
    const body = typeof payload === "string" ? { answer: payload } : payload;
    const c = pendingControl.value;
    submittingClarify.value = true;
    try {
      const headers = await chatTicketHeaders(targetConvId, "clarify");
      await api.post(
        `/conversations/${targetConvId}/clarify`,
        {
          request_id: c.request_id,
          execution_generation: c.execution_generation,
          answer: body.answer,
          ...(body.answers?.length ? { answers: body.answers } : {}),
        },
        { headers },
      );
      pendingControl.value = null;
      const a = assistant();
      if (a) a.status = "streaming";
      return true;
    } catch (e: any) {
      error.value = apiErrorMessage(e, "提交失败");
      return false;
    } finally {
      submittingClarify.value = false;
    }
  }

  function applyMessageReactions(messageId: string, reactionsList: MessageReaction[]) {
    const idx = messages.value.findIndex((m) => m.id === messageId);
    if (idx < 0) return;
    messages.value[idx] = { ...messages.value[idx], reactions: [...reactionsList] };
  }

  async function reactToMessage(
    messageId: string,
    reaction: UserReactionType,
    reasonCode?: string,
    comment?: string,
  ): Promise<void> {
    const targetConvId = convId.value;
    if (!targetConvId) return;
    const msg = messages.value.find((m) => m.id === messageId);
    if (!msg) return;
    const existing = (msg.reactions ?? []).find((r) => r.author_type === "user");
    // Toggle off when clicking the exact same reaction without adding a new reason
    if (existing && existing.reaction === reaction && !reasonCode && !comment) {
      await removeReaction(messageId);
      return;
    }
    try {
      const saved = await api.post<MessageReaction>(
        `/conversations/${targetConvId}/messages/${messageId}/reactions`,
        {
          reaction,
          reason_code: reasonCode ?? null,
          comment: comment ?? null,
        },
      );
      const others = (msg.reactions ?? []).filter((r) => r.author_type !== "user");
      applyMessageReactions(messageId, [...others, saved]);
    } catch (e: any) {
      error.value = apiErrorMessage(e, "评价提交失败");
    }
  }

  async function removeReaction(messageId: string): Promise<void> {
    const targetConvId = convId.value;
    if (!targetConvId) return;
    const msg = messages.value.find((m) => m.id === messageId);
    if (!msg) return;
    try {
      await api.delete(`/conversations/${targetConvId}/messages/${messageId}/reactions`);
      const others = (msg.reactions ?? []).filter((r) => r.author_type !== "user");
      applyMessageReactions(messageId, others);
    } catch (e: any) {
      error.value = apiErrorMessage(e, "取消评价失败");
    }
  }

  function abort() {
    clearPendingPoll();
    controller?.abort();
    controller = null;
  }

  return {
    convId, messages, streaming, waitingFirstByte, stopping, reconnecting, approvingChoice, submittingClarify,
    activeAssistantId, activeRunId, plan, reasoning, currentStep, runningTool,
    selectedTurnId, selectedTurn, assistantTurns, viewPlan, viewReasoning, viewStreaming, viewCurrentStep,
    viewRunningTool, selectTurn,
    pendingControl, pendingMemory, pendingSkills, pendingSchedules, error,
    loadFromConversation, reset, send, regenerate, editAndResend, reconnect, recoverIfNeeded,
    stop, approve, clarify, abort, clearPendingControlFromSync,
    resolvePendingMemory, resolvePendingSkill, resolvePendingSchedule,
    applyMessageReactions, reactToMessage, removeReaction,
  };
});