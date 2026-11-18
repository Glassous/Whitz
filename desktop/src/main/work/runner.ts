import crypto from "node:crypto";
import { getStatus, startRuntime } from "../runtime/hermesRuntime";
import {
  addMessage,
  appendMessageContent,
  findRunningTool,
  getConversationMeta,
  getMessage,
  setHermesSession,
  touchConversation,
  updateMessage,
} from "./repository";
import { LocalHermesClient } from "./hermesClient";
import { scoped } from "../logger";
import type { WorkEvent, WorkRole } from "../../shared/work-types";

const logger = scoped("work:runner");

type EventSink = (payload: { conversationId: string; event: WorkEvent }) => void;
let sink: EventSink | null = null;

export function setWorkEventSink(fn: EventSink): void {
  sink = fn;
}

interface ActiveRun {
  runId: string | null;
  controller: AbortController;
  assistantId: string;
  content: string;
  reasoning: Array<Record<string, unknown>>;
  plan: Record<string, unknown> | null;
  pendingControl: { requestId: string; generation: number } | null;
  flushedAt: number;
  stopped: boolean;
  finished?: boolean;
}

const active = new Map<string, ActiveRun>();

const emitQueue: Array<{ conversationId: string; event: WorkEvent }> = [];
let emitTimer: NodeJS.Timeout | null = null;

function emit(conversationId: string, event: WorkEvent): void {
  emitQueue.push({ conversationId, event });
  if (emitTimer) return;
  emitTimer = setTimeout(() => {
    emitTimer = null;
    const batch = emitQueue.splice(0, emitQueue.length);
    for (const item of batch) sink?.(item);
  }, 30);
  emitTimer.unref?.();
}

function isTerminal(name: string): boolean {
  return ["run.completed", "run.failed", "run.cancelled", "run.interrupted"].includes(name);
}

async function ensureReady(): Promise<void> {
  const status = getStatus();
  if (status.running) return;
  if (!status.installed) throw new Error("尚未安装本地 Hermes 运行时，请先在 Work 设置中完成安装");
  if (status.state === "disabled") throw new Error("Whitz Work 已被禁用");
  await startRuntime();
}

function parseTodos(preview: unknown): Record<string, unknown> | null {
  let value = preview;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  const search = (node: unknown): Array<Record<string, unknown>> | null => {
    if (Array.isArray(node)) {
      if (
        node.length &&
        node.every((x) => x && typeof x === "object") &&
        node.some((x) => typeof (x as Record<string, unknown>).status === "string")
      ) {
        return node as Array<Record<string, unknown>>;
      }
      for (const item of node) {
        const found = search(item);
        if (found) return found;
      }
      return null;
    }
    if (node && typeof node === "object") {
      for (const key of ["todos", "items", "tasks", "plan", "steps"]) {
        if (key in (node as Record<string, unknown>)) {
          const found = search((node as Record<string, unknown>)[key]);
          if (found) return found;
        }
      }
    }
    return null;
  };
  const items = search(value);
  return items ? { items } : null;
}

function flush(run: ActiveRun, force = false): void {
  const now = Date.now();
  if (!force && now - run.flushedAt < 500) return;
  run.flushedAt = now;
  updateMessage(run.assistantId, {
    content: run.content,
    tool_payload: {
      reasoning: run.reasoning,
      plan: run.plan,
    },
  });
}

function resolveRunRef(conversationId: string): ActiveRun | undefined {
  return active.get(conversationId);
}

export async function sendMessage(conversationId: string, content: string): Promise<{ run_id: string | null }> {
  const conversation = getConversationMeta(conversationId);
  if (!conversation) throw new Error("对话不存在");
  if (active.has(conversationId)) throw new Error("当前对话仍有进行中的任务");
  await ensureReady();

  let sessionId = conversation.hermes_session_id;
  const client = new LocalHermesClient();
  if (!sessionId) {
    sessionId = await client.createSession(conversation.title);
    if (sessionId) setHermesSession(conversationId, sessionId);
  }

  const userMessage = addMessage({ conversation_id: conversationId, role: "user", content, status: "completed" });
  const assistant = addMessage({
    conversation_id: conversationId,
    role: "assistant",
    content: "",
    status: "streaming",
  });
  emit(conversationId, {
    event: "message.created",
    data: { user_message_id: userMessage.id, assistant_message_id: assistant.id },
  });

  const run: ActiveRun = {
    runId: null,
    controller: new AbortController(),
    assistantId: assistant.id,
    content: "",
    reasoning: [],
    plan: null,
    pendingControl: null,
    flushedAt: 0,
    stopped: false,
  };
  active.set(conversationId, run);

  try {
    const runId = await client.createRun(content, sessionId);
    run.runId = runId;
    updateMessage(assistant.id, { hermes_run_id: runId });
    emit(conversationId, { event: "run.started", data: { run_id: runId } });
    void pump(conversationId, client, run);
    return { run_id: runId };
  } catch (err) {
    active.delete(conversationId);
    const message = err instanceof Error ? err.message : "创建运行失败";
    updateMessage(assistant.id, { status: "failed", content: message });
    emit(conversationId, { event: "run.failed", data: { error: message } });
    throw new Error(message);
  }
}

async function pump(conversationId: string, client: LocalHermesClient, run: ActiveRun): Promise<void> {
  if (!run.runId) return;
  try {
    for await (const event of client.streamRun(run.runId, run.controller.signal)) {
      await handleEvent(conversationId, run, event);
      if (isTerminal(event.event)) break;
    }
  } catch (err) {
    if (!run.stopped) {
      const message = err instanceof Error ? err.message : "事件流中断";
      logger.warn("run stream failed", message);
      updateMessage(run.assistantId, { status: "failed", content: run.content || message });
      emit(conversationId, { event: "run.failed", data: { error: message, output: run.content } });
    }
  } finally {
    if (!run.finished) flush(run, true);
    active.delete(conversationId);
    touchConversation(conversationId);
  }
}

async function handleEvent(conversationId: string, run: ActiveRun, event: WorkEvent): Promise<void> {
  const data = event.data;
  switch (event.event) {
    case "reasoning.delta":
    case "thinking.delta": {
      const text = String(data.delta ?? data.text ?? "");
      if (!text) return;
      const last = run.reasoning[run.reasoning.length - 1];
      if (last && last.step === data.step) last.text = String(last.text ?? "") + text;
      else run.reasoning.push({ step: data.step ?? null, title: data.title ?? "", text, tools: [] });
      flush(run);
      emit(conversationId, { event: "reasoning.delta", data });
      return;
    }
    case "reasoning.available": {
      const text = String(data.text ?? "");
      if (text) {
        run.reasoning.push({ step: null, title: "", text, tools: [] });
        flush(run, true);
        emit(conversationId, { event: "reasoning.block", data });
      }
      return;
    }
    case "message.delta": {
      const text = String(data.delta ?? data.text ?? "");
      if (!text) return;
      run.content += text;
      appendMessageContent(run.assistantId, text);
      emit(conversationId, { event: "message.delta", data: { text } });
      return;
    }
    case "message.interim": {
      const text = String(data.text ?? data.delta ?? "").trim();
      if (text) {
        const step = data.step ?? null;
        const last = run.reasoning[run.reasoning.length - 1];
        if (last && last.step === step) {
          last.content = `${String(last.content ?? "")}\n\n${text}`.trim();
        } else {
          run.reasoning.push({ step, title: data.title ?? "", text: "", content: text, tools: [] });
        }
        flush(run, true);
        emit(conversationId, { event: "commentary", data: { text, step, title: data.title ?? "" } });
      } else {
        emit(conversationId, { event: "message.interim", data });
      }
      return;
    }
    case "tool.started": {
      const tool = String(data.tool ?? "tool");
      const message = addMessage({
        conversation_id: conversationId,
        role: "tool" as WorkRole,
        tool_name: tool,
        status: "running",
        tool_payload: { args: data.preview, status: "running" },
        hermes_run_id: run.runId,
      });
      emit(conversationId, {
        event: "tool.started",
        data: { tool, preview: data.preview, message_id: message.id },
      });
      if (tool === "todo_list") {
        const plan = parseTodos(data.preview);
        if (plan) {
          run.plan = plan;
          flush(run, true);
          emit(conversationId, { event: "plan.updated", data: plan });
        }
      }
      return;
    }
    case "tool.completed": {
      const tool = String(data.tool ?? "tool");
      const row = findRunningTool(conversationId, tool);
      if (row) {
        updateMessage(row.id, {
          status: data.error ? "failed" : "completed",
          tool_payload: {
            ...(row.tool_payload ?? {}),
            result: data.preview,
            duration: data.duration,
            error: data.error,
            status: data.error ? "failed" : "completed",
          },
        });
      }
      emit(conversationId, {
        event: "tool.completed",
        data: { ...data, tool, message_id: row?.id ?? null },
      });
      if (tool === "todo_list") {
        const plan = parseTodos(data.preview);
        if (plan) {
          run.plan = plan;
          flush(run, true);
          emit(conversationId, { event: "plan.updated", data: plan });
        }
      }
      return;
    }
    case "approval.request":
    case "clarify.request": {
      let requestId = String(data.request_id ?? data.prompt_id ?? "");
      let generation = Number(data.execution_generation ?? 0);
      if ((!requestId || !generation) && run.runId) {
        // Hermes occasionally omits control ids; fall back to run snapshot.
        try {
          const client = new LocalHermesClient();
          const snap = await client.getRun(run.runId);
          const controls = (snap.pending_controls as Array<Record<string, unknown>>) ?? [];
          if (controls.length) {
            requestId = requestId || String(controls[0].prompt_id ?? controls[0].request_id ?? "");
            generation = generation || Number(controls[0].execution_generation ?? 0);
          }
        } catch {
          /* ignore */
        }
      }
      run.pendingControl = { requestId, generation };
      updateMessage(run.assistantId, { status: "waiting" });
      emit(conversationId, {
        event: event.event,
        data: {
          request_id: requestId,
          execution_generation: generation,
          tool: data.tool,
          preview: data.preview,
          detail: data,
        },
      });
      return;
    }
    case "run.completed": {
      run.finished = true;
      const output = typeof data.output === "string" && data.output ? data.output : run.content;
      run.content = output;
      updateMessage(run.assistantId, {
        status: "completed",
        content: output,
        tool_payload: { reasoning: run.reasoning, plan: run.plan, usage: data.usage ?? null },
      });
      emit(conversationId, {
        event: "run.completed",
        data: { output, plan: run.plan, reasoning: run.reasoning, usage: data.usage ?? null },
      });
      return;
    }
    case "run.failed":
    case "run.cancelled":
    case "run.interrupted": {
      run.finished = true;
      const output = typeof data.output === "string" && data.output ? data.output : run.content;
      run.content = output;
      updateMessage(run.assistantId, {
        status: event.event === "run.failed" ? "failed" : "cancelled",
        content: output,
        tool_payload: { reasoning: run.reasoning, plan: run.plan },
      });
      emit(conversationId, {
        event: event.event,
        data: { error: data.error ?? null, output, plan: run.plan, reasoning: run.reasoning },
      });
      return;
    }
    case "plan.updated": {
      run.plan = (data as Record<string, unknown>) ?? null;
      flush(run, true);
      emit(conversationId, { event: "plan.updated", data });
      return;
    }
    default:
      emit(conversationId, { event: event.event, data });
  }
}

export async function stopRun(conversationId: string): Promise<void> {
  const run = resolveRunRef(conversationId);
  if (!run) return;
  run.stopped = true;
  run.controller.abort();
  if (run.runId) {
    try {
      await new LocalHermesClient().stopRun(run.runId);
    } catch (err) {
      logger.warn("stop run failed", err);
    }
  }
  updateMessage(run.assistantId, { status: "cancelled", content: run.content });
  emit(conversationId, { event: "run.cancelled", data: { output: run.content } });
  active.delete(conversationId);
}

export async function approveRun(
  conversationId: string,
  requestId: string,
  generation: number,
  choice: "once" | "always" | "deny",
): Promise<void> {
  const run = active.get(conversationId);
  if (!run?.runId) throw new Error("没有等待审批的任务");
  await new LocalHermesClient().approve(run.runId, requestId, generation, choice);
  run.pendingControl = null;
  updateMessage(run.assistantId, { status: "streaming" });
}

export async function clarifyRun(
  conversationId: string,
  requestId: string,
  generation: number,
  answer: string,
): Promise<void> {
  const run = active.get(conversationId);
  if (!run?.runId) throw new Error("没有等待回答的任务");
  await new LocalHermesClient().clarify(run.runId, requestId, generation, answer);
  run.pendingControl = null;
  updateMessage(run.assistantId, { status: "streaming" });
}

export function isRunActive(conversationId: string): boolean {
  const run = active.get(conversationId);
  if (!run) return false;
  const message = getMessage(run.assistantId);
  return message?.status === "streaming" || message?.status === "waiting";
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
