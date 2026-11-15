import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";
import { streamSSE, streamSSEGet, type SSEEvent } from "../api/sse";
import type { ConversationDetail, Message, PendingControl, Plan, PlanItem, ReasoningBlock } from "../types";
import { useConversationsStore } from "./conversations";

let seq = 0;
const tempId = (prefix: string) => `${prefix}-${Date.now()}-${seq++}`;

export const useChatStore = defineStore("chat", () => {
  const convId = ref<string | null>(null);
  const messages = ref<Message[]>([]);
  const streaming = ref(false);
  const activeAssistantId = ref<string | null>(null);
  const activeRunId = ref<string | null>(null);
  const plan = ref<Plan | null>(null);
  const reasoning = ref<ReasoningBlock[]>([]);
  const pendingControl = ref<PendingControl | null>(null);
  const error = ref<string | null>(null);
  const selectedTurnId = ref<string | null>(null);
  let controller: AbortController | null = null;

  const currentStep = computed(() => {
    const items = plan.value?.items ?? [];
    const idx = items.findIndex((i) => i.status === "in_progress");
    if (idx < 0) return null;
    return { index: idx + 1, total: items.length, title: items[idx].content };
  });

  const runningTool = computed(() => {
    const row = [...messages.value].reverse().find((m) => m.role === "tool" && m.status === "running");
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

  function loadFromConversation(detail: ConversationDetail) {
    convId.value = detail.id;
    messages.value = detail.messages.map((m) => ({ ...m }));
    plan.value = detail.plan;
    const lastReasoned = [...detail.messages]
      .reverse()
      .find((m) => m.role === "assistant" && Array.isArray(m.tool_payload?.reasoning) && m.tool_payload.reasoning.length);
    reasoning.value = normalizeReasoning(lastReasoned?.tool_payload?.reasoning);
    const lastAssistant = [...detail.messages].reverse().find((m) => m.role === "assistant");
    selectedTurnId.value = lastAssistant?.id ?? null;
    activeRunId.value = detail.active_run_id;
    pendingControl.value = null;
    error.value = null;
    streaming.value = false;
    activeAssistantId.value = null;
    if (detail.active_run_id && detail.active_run_status && detail.active_run_status !== "completed") {
      void reconnect(detail.active_run_id);
    }
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

  function handleEvent(ev: SSEEvent) {
    const d = ev.data as Record<string, any>;
    switch (ev.event) {
      case "message.created": {
        const userMsg = messages.value.find((m) => m.id.startsWith("temp-user"));
        if (userMsg && d.user_message_id) userMsg.id = d.user_message_id;
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
        const row = findMessage(d.message_id) ?? [...messages.value].reverse().find((m) => m.role === "tool" && m.tool_name === d.tool && m.status === "running");
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
      case "run.completed": {
        const a = assistant();
        if (a) {
          if (typeof d.output === "string" && d.output) a.content = d.output;
          a.status = "completed";
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
      error.value = e?.message ?? "连接中断";
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

  async function send(content: string) {
    if (!convId.value || streaming.value) return;
    error.value = null;
    reasoning.value = [];
    plan.value = null;
    const userId = tempId("temp-user");
    const assistantId = tempId("temp-assistant");
    messages.value.push({
      id: userId,
      role: "user",
      content,
      tool_name: null,
      tool_payload: null,
      status: "completed",
      hermes_run_id: null,
      created_at: new Date().toISOString(),
    });
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
    streaming.value = true;
    controller = new AbortController();
    await consume(streamSSE(`/conversations/${convId.value}/messages`, { content }, controller.signal));
  }

  async function reconnect(runId: string) {
    if (!convId.value) return;
    streaming.value = true;
    controller = new AbortController();
    await consume(streamSSEGet(`/conversations/${convId.value}/runs/${runId}/events`, controller.signal));
  }

  async function stop() {
    if (!convId.value) return;
    try {
      await api.post(`/conversations/${convId.value}/stop`, {});
    } catch (e: any) {
      error.value = e?.message ?? "停止失败";
    }
  }

  async function approve(choice: "once" | "deny") {
    if (!convId.value || !pendingControl.value) return;
    const c = pendingControl.value;
    try {
      await api.post(`/conversations/${convId.value}/approval`, {
        request_id: c.request_id,
        execution_generation: c.execution_generation,
        choice,
      });
      pendingControl.value = null;
      const a = assistant();
      if (a) a.status = "streaming";
    } catch (e: any) {
      error.value = e?.message ?? "审批提交失败";
    }
  }

  async function clarify(answer: string) {
    if (!convId.value || !pendingControl.value) return;
    const c = pendingControl.value;
    try {
      await api.post(`/conversations/${convId.value}/clarify`, {
        request_id: c.request_id,
        execution_generation: c.execution_generation,
        answer,
      });
      pendingControl.value = null;
      const a = assistant();
      if (a) a.status = "streaming";
    } catch (e: any) {
      error.value = e?.message ?? "提交失败";
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
    pendingControl, error, loadFromConversation, reset, send, reconnect, stop, approve, clarify, abort,
  };
});