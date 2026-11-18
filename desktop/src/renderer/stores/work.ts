import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { WorkConversation, WorkConversationDetail, WorkEvent, WorkMessage } from "@shared/work-types";

function bridge() {
  const api = window.whitzDesktop;
  if (!api) throw new Error("桌面桥接不可用");
  return api;
}

function uid(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `temp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

interface PendingControl {
  kind: "approval" | "clarify";
  requestId: string;
  generation: number;
  tool: string | null;
  preview: unknown;
}

export const useWorkStore = defineStore("work", () => {
  const conversations = ref<WorkConversation[]>([]);
  const current = ref<WorkConversationDetail | null>(null);
  const streaming = ref(false);
  const sending = ref(false);
  const error = ref<string | null>(null);
  const pendingControl = ref<PendingControl | null>(null);
  const activeAssistantId = ref<string | null>(null);
  const plan = ref<Record<string, unknown> | null>(null);
  let started = false;

  const messages = computed<WorkMessage[]>(() => current.value?.messages ?? []);
  const activeConversationId = computed(() => current.value?.conversation.id ?? null);

  function bindEvents() {
    if (started) return;
    started = true;
    bridge().onWorkEvent(({ conversationId, event }) => {
      if (conversationId !== activeConversationId.value) return;
      handleEvent(event);
    });
  }

  async function loadList() {
    conversations.value = await bridge().work.list();
  }

  async function create(title?: string) {
    const conversation = await bridge().work.create(title);
    await loadList();
    await select(conversation.id);
    return conversation;
  }

  async function ensureConversation() {
    if (current.value) return current.value;
    const existing = conversations.value[0];
    if (existing) return select(existing.id);
    return create();
  }

  async function select(id: string) {
    const detail = await bridge().work.get(id);
    current.value = detail;
    error.value = null;
    pendingControl.value = null;
    const waiting = [...detail.messages].reverse().find((m) => m.status === "waiting" || m.status === "streaming");
    activeAssistantId.value = waiting?.id ?? null;
    streaming.value = Boolean(waiting);
    const lastPlan = [...detail.messages].reverse().find((m) => m.tool_payload?.plan)?.tool_payload?.plan;
    plan.value = (lastPlan as Record<string, unknown>) ?? null;
    return detail;
  }

  async function rename(id: string, title: string) {
    await bridge().work.rename(id, title);
    await loadList();
    if (current.value?.conversation.id === id) current.value.conversation.title = title;
  }

  async function remove(id: string) {
    await bridge().work.delete(id);
    if (current.value?.conversation.id === id) current.value = null;
    await loadList();
  }

  function patchActive(patch: Partial<WorkMessage>) {
    if (!current.value) return;
    const message =
      current.value.messages.find((m) => m.id === activeAssistantId.value) ??
      [...current.value.messages].reverse().find((m) => m.role === "assistant");
    if (!message) return;
    Object.assign(message, patch);
  }

  function reasoningBlocks(): Array<Record<string, unknown>> {
    if (!current.value) return [];
    const message = current.value.messages.find((m) => m.id === activeAssistantId.value);
    const payload = message?.tool_payload ?? {};
    const blocks = payload.reasoning;
    return Array.isArray(blocks) ? (blocks as Array<Record<string, unknown>>) : [];
  }

  function saveReasoning(blocks: Array<Record<string, unknown>>) {
    const message = current.value?.messages.find((m) => m.id === activeAssistantId.value);
    if (!message) return;
    message.tool_payload = { ...(message.tool_payload ?? {}), reasoning: blocks, plan: plan.value };
  }

  async function send(content: string) {
    const text = content.trim();
    if (!text || sending.value) return;
    await ensureConversation();
    if (!current.value) return;
    const conversationId = current.value.conversation.id;
    error.value = null;
    pendingControl.value = null;
    plan.value = null;

    const userMessage: WorkMessage = {
      id: uid(),
      conversation_id: conversationId,
      role: "user",
      content: text,
      status: "completed",
      tool_name: null,
      tool_payload: null,
      hermes_run_id: null,
      created_at: new Date().toISOString(),
    };
    const assistantMessage: WorkMessage = {
      id: uid(),
      conversation_id: conversationId,
      role: "assistant",
      content: "",
      status: "streaming",
      tool_name: null,
      tool_payload: { reasoning: [] },
      hermes_run_id: null,
      created_at: new Date().toISOString(),
    };
    current.value.messages.push(userMessage, assistantMessage);
    activeAssistantId.value = assistantMessage.id;
    streaming.value = true;
    sending.value = true;
    try {
      await bridge().work.send(conversationId, text);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "发送失败";
      assistantMessage.status = "failed";
      streaming.value = false;
    } finally {
      sending.value = false;
    }
  }

  function handleEvent(event: WorkEvent) {
    const data = event.data;
    switch (event.event) {
      case "message.created": {
        if (current.value) {
          const tempUser = [...current.value.messages].reverse().find((m) => m.role === "user" && m.id.startsWith("temp-"));
          if (tempUser && typeof data.user_message_id === "string") tempUser.id = data.user_message_id;
          const assistant = current.value.messages.find((m) => m.id === activeAssistantId.value);
          if (assistant && typeof data.assistant_message_id === "string") {
            assistant.id = data.assistant_message_id;
            activeAssistantId.value = data.assistant_message_id;
          }
        }
        return;
      }
      case "run.started": {
        const assistant = current.value?.messages.find((m) => m.id === activeAssistantId.value);
        if (assistant && typeof data.run_id === "string") assistant.hermes_run_id = data.run_id;
        return;
      }
      case "message.delta": {
        const text = String(data.text ?? "");
        const assistant = current.value?.messages.find((m) => m.id === activeAssistantId.value);
        if (assistant) assistant.content += text;
        return;
      }
      case "reasoning.delta":
      case "reasoning.block": {
        const text = String(data.text ?? "");
        const blocks = reasoningBlocks();
        const step = data.step ?? null;
        const last = blocks[blocks.length - 1];
        if (event.event === "reasoning.block") {
          if (last && last.step === step) last.text = text;
          else blocks.push({ step, title: data.title ?? "", text, tools: [] });
        } else if (last && last.step === step) {
          last.text = String(last.text ?? "") + text;
        } else {
          blocks.push({ step, title: data.title ?? "", text, tools: [] });
        }
        saveReasoning(blocks);
        return;
      }
      case "commentary": {
        const text = String(data.text ?? "").trim();
        if (!text) return;
        const blocks = reasoningBlocks();
        const last = blocks[blocks.length - 1];
        if (last) last.content = `${String(last.content ?? "")}\n\n${text}`.trim();
        else blocks.push({ step: data.step ?? null, title: data.title ?? "", text: "", content: text, tools: [] });
        saveReasoning(blocks);
        return;
      }
      case "tool.started": {
        if (!current.value) return;
        current.value.messages.push({
          id: String(data.message_id ?? uid()),
          conversation_id: current.value.conversation.id,
          role: "tool",
          content: "",
          status: "running",
          tool_name: String(data.tool ?? "tool"),
          tool_payload: { args: data.preview, status: "running" },
          hermes_run_id: null,
          created_at: new Date().toISOString(),
        });
        return;
      }
      case "tool.completed": {
        const message = current.value?.messages.find((m) => m.id === data.message_id);
        if (message) {
          message.status = data.error ? "failed" : "completed";
          message.tool_payload = {
            ...(message.tool_payload ?? {}),
            result: data.preview,
            error: data.error,
            duration: data.duration,
            status: message.status,
          };
        }
        return;
      }
      case "plan.updated": {
        plan.value = data as Record<string, unknown>;
        const assistant = current.value?.messages.find((m) => m.id === activeAssistantId.value);
        if (assistant) assistant.tool_payload = { ...(assistant.tool_payload ?? {}), plan: plan.value };
        return;
      }
      case "approval.request":
      case "clarify.request": {
        pendingControl.value = {
          kind: event.event === "approval.request" ? "approval" : "clarify",
          requestId: String(data.request_id ?? ""),
          generation: Number(data.execution_generation ?? 0),
          tool: data.tool ? String(data.tool) : null,
          preview: data.preview ?? null,
        };
        patchActive({ status: "waiting" });
        return;
      }
      case "run.completed":
      case "run.failed":
      case "run.cancelled":
      case "run.interrupted": {
        const status =
          event.event === "run.completed" ? "completed" : event.event === "run.failed" ? "failed" : "cancelled";
        patchActive({ status, content: typeof data.output === "string" ? data.output : undefined });
        if (event.event === "run.failed" && data.error) {
          error.value = typeof data.error === "string" ? data.error : "任务执行失败";
        }
        streaming.value = false;
        pendingControl.value = null;
        void refreshCurrent();
        return;
      }
      case "error": {
        error.value = String(data.detail ?? "发生错误");
        streaming.value = false;
        patchActive({ status: "failed" });
        return;
      }
      default:
        return;
    }
  }

  async function refreshCurrent() {
    if (!current.value) return;
    const id = current.value.conversation.id;
    const detail = await bridge().work.get(id);
    if (current.value?.conversation.id === id) {
      current.value = detail;
      const lastAssistant = [...detail.messages].reverse().find((m) => m.role === "assistant");
      activeAssistantId.value = lastAssistant?.id ?? null;
      await loadList();
    }
  }

  async function stop() {
    if (!current.value) return;
    await bridge().work.stop(current.value.conversation.id);
  }

  async function approve(choice: "once" | "always" | "deny") {
    if (!current.value || !pendingControl.value) return;
    const control = pendingControl.value;
    await bridge().work.approve(current.value.conversation.id, control.requestId, control.generation, choice);
    pendingControl.value = null;
    patchActive({ status: "streaming" });
  }

  async function clarify(answer: string) {
    if (!current.value || !pendingControl.value) return;
    const control = pendingControl.value;
    await bridge().work.clarify(current.value.conversation.id, control.requestId, control.generation, answer);
    pendingControl.value = null;
    patchActive({ status: "streaming" });
  }

  function reset() {
    current.value = null;
    conversations.value = [];
    streaming.value = false;
    pendingControl.value = null;
    activeAssistantId.value = null;
    error.value = null;
  }

  return {
    conversations,
    current,
    messages,
    streaming,
    sending,
    error,
    pendingControl,
    plan,
    activeAssistantId,
    activeConversationId,
    bindEvents,
    loadList,
    create,
    select,
    rename,
    remove,
    send,
    stop,
    approve,
    clarify,
    reset,
  };
});
