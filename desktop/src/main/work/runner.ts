import crypto from "node:crypto";
import fs from "node:fs";
import { scoped } from "../logger";
import { ensureBuiltinKey } from "../runtime/localOpenAIGateway";
import { readOpenCodeJsonDoc } from "../runtime/opencodeConfig";
import { getStatus, startRuntime } from "../runtime/opencodeRuntime";
import { OpenCodeClient } from "./opencodeClient";
import { getWorkSettings } from "./settings";
import {
  addMessage,
  findRunningTool,
  getActiveWorkspacePath,
  getConversationMeta,
  renameConversation,
  setOpenCodeSession,
  touchConversation,
  updateMessage,
} from "./repository";
import type { WorkApprovalChoice, WorkAttachment, WorkEvent, WorkRole } from "../../shared/work-types";

const logger = scoped("work:runner");

interface PendingQuestionState {
  requestId: string;
  header: string;
}

interface ActiveRun {
  runId: string;
  sessionId: string;
  directory: string | null;
  controller: AbortController;
  assistantId: string;
  content: string;
  reasoning: Array<Record<string, unknown>>;
  plan: Record<string, unknown> | null;
  userMessageIds: Set<string>;
  assistantMessageIds: Set<string>;
  partTexts: Map<string, string>;
  partReasons: Map<string, string>;
  toolStates: Map<string, string>;
  pendingPermissionId: string | null;
  pendingQuestion: PendingQuestionState | null;
  flushedAt: number;
  stopped: boolean;
  finished: boolean;
  promptSent: boolean;
}

type EventSink = (payload: { conversationId: string; event: WorkEvent }) => void;

const active = new Map<string, ActiveRun>();
let sink: EventSink | null = null;

export function setWorkEventSink(next: EventSink): void {
  sink = next;
}

export function hasAnyActiveRun(): boolean {
  return active.size > 0;
}

function emit(conversationId: string, event: WorkEvent): void {
  sink?.({ conversationId, event });
}

async function ensureReady(): Promise<void> {
  const status = getStatus();
  if (status.running) return;
  if (!status.installed) throw new Error("未检测到本机 OpenCode CLI，请先安装 OpenCode 或在设置中指定可执行路径");
  if (status.state === "disabled") throw new Error("Whitz Work 已被禁用");
  await startRuntime();
}

function flush(run: ActiveRun, force = false): void {
  const now = Date.now();
  if (!force && now - run.flushedAt < 450) return;
  run.flushedAt = now;
  updateMessage(run.assistantId, {
    content: run.content,
    tool_payload: {
      reasoning: run.reasoning,
      plan: run.plan,
    },
  });
}

function buildSystemInstructions(
  workspacePath: string | null,
  skillNames?: string[],
  attachments?: WorkAttachment[],
): string | undefined {
  const parts: string[] = [];
  if (workspacePath) {
    parts.push(
      `当前选定的本地工作区根目录为：${workspacePath}\n请优先围绕该工作区进行代码阅读、检索、修改、测试与命令执行。`,
    );
  }
  if (skillNames?.length) {
    parts.push(`用户本次指定优先使用技能：${skillNames.map((s) => `/${s}`).join("、")}。如可用请先参考对应技能规则。`);
  }
  if (attachments?.length) {
    const list = attachments
      .map((a) => `- [${a.kind === "image" ? "图片" : "文件"}] ${a.name} (${a.path})`)
      .join("\n");
    parts.push(`用户附加了以下本机参考路径：\n${list}`);
  }
  return parts.length ? parts.join("\n\n") : undefined;
}

function autoTitleFrom(content: string): string {
  const clean = content.replace(/\s+/g, " ").trim();
  if (!clean) return "新的工作区对话";
  return clean.length > 26 ? `${clean.slice(0, 26)}…` : clean;
}

function parseModelRef(ref: string): { providerID: string; modelID: string } | undefined {
  const idx = ref.indexOf("/");
  if (idx <= 0 || idx >= ref.length - 1) return undefined;
  return { providerID: ref.slice(0, idx).trim(), modelID: ref.slice(idx + 1).trim() };
}

async function resolvePromptModel(): Promise<{ providerID: string; modelID: string } | undefined> {
  const settings = getWorkSettings();
  if (settings.model.mode === "builtin") {
    await ensureBuiltinKey();
    return {
      providerID: "whitz",
      modelID: settings.model.builtin_model || "whitz-default",
    };
  }
  const { doc } = readOpenCodeJsonDoc();
  if (typeof doc.model === "string" && doc.model.trim()) {
    const parsed = parseModelRef(doc.model.trim());
    if (parsed?.providerID === "whitz") {
      await ensureBuiltinKey();
    }
    return parsed;
  }
  return undefined;
}

function safeWorkspaceDir(workspacePath: string | null): string | null {
  if (!workspacePath) return null;
  try {
    if (fs.existsSync(workspacePath) && fs.statSync(workspacePath).isDirectory()) return workspacePath;
  } catch {
    /* ignore */
  }
  return null;
}

export async function sendMessage(
  conversationId: string,
  content: string,
  options?: { skillNames?: string[]; attachments?: WorkAttachment[] },
): Promise<{ run_id: string | null }> {
  const conversation = getConversationMeta(conversationId);
  if (!conversation) throw new Error("对话不存在");
  if (active.has(conversationId)) throw new Error("当前对话仍有进行中的任务");
  await ensureReady();

  const workspaceDir = safeWorkspaceDir(conversation.workspace_path || getActiveWorkspacePath());
  const selectedModel = await resolvePromptModel();
  const client = new OpenCodeClient();

  let sessionId = conversation.opencode_session_id;
  if (!sessionId) {
    sessionId = await client.createSession(conversation.title, workspaceDir);
    if (!sessionId) throw new Error("创建 OpenCode 会话失败");
    setOpenCodeSession(conversationId, sessionId);
  }

  if (conversation.title === "新的工作区对话" || conversation.title === "新的本地对话") {
    renameConversation(conversationId, autoTitleFrom(content));
  }

  const attachmentPayload = options?.attachments?.length
    ? {
        attachments: options.attachments.map((a) => ({
          id: a.id,
          name: a.name,
          path: a.path,
          kind: a.kind,
          size: a.size,
        })),
        skills: options.skillNames ?? [],
      }
    : options?.skillNames?.length
      ? { skills: options.skillNames }
      : null;

  const userMessage = addMessage({
    conversation_id: conversationId,
    role: "user",
    content,
    status: "completed",
    tool_payload: attachmentPayload,
  });
  const runId = `run_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`;
  const assistant = addMessage({
    conversation_id: conversationId,
    role: "assistant",
    content: "",
    status: "streaming",
    run_id: runId,
  });
  emit(conversationId, {
    event: "message.created",
    data: { user_message_id: userMessage.id, assistant_message_id: assistant.id },
  });

  const run: ActiveRun = {
    runId,
    sessionId,
    directory: workspaceDir,
    controller: new AbortController(),
    assistantId: assistant.id,
    content: "",
    reasoning: [],
    plan: null,
    userMessageIds: new Set(),
    assistantMessageIds: new Set(),
    partTexts: new Map(),
    partReasons: new Map(),
    toolStates: new Map(),
    pendingPermissionId: null,
    pendingQuestion: null,
    flushedAt: 0,
    stopped: false,
    finished: false,
    promptSent: false,
  };
  active.set(conversationId, run);
  emit(conversationId, { event: "run.started", data: { run_id: runId } });

  const system = buildSystemInstructions(workspaceDir, options?.skillNames, options?.attachments);

  try {
    // Open SSE subscription before issuing prompt_async so early deltas are never missed.
    let resolveConnected!: () => void;
    const connected = new Promise<void>((resolve) => {
      resolveConnected = resolve;
    });
    const fallbackTick = setTimeout(() => resolveConnected(), 500);

    void pump(conversationId, client, run, () => {
      clearTimeout(fallbackTick);
      resolveConnected();
    });

    await connected;
    await client.promptAsync(sessionId, workspaceDir, {
      model: selectedModel,
      system,
      parts: [{ type: "text", text: content }],
    });
    run.promptSent = true;
    return { run_id: runId };
  } catch (err) {
    run.finished = true;
    run.controller.abort();
    active.delete(conversationId);
    const message = err instanceof Error ? err.message : "发送 OpenCode 任务失败";
    updateMessage(assistant.id, { status: "failed", content: message });
    emit(conversationId, { event: "run.failed", data: { error: message } });
    throw new Error(message);
  }
}

async function pump(
  conversationId: string,
  client: OpenCodeClient,
  run: ActiveRun,
  onConnected: () => void,
): Promise<void> {
  try {
    onConnected();
    for await (const ev of client.streamEvents(run.directory, run.controller.signal)) {
      if (run.finished || run.stopped) break;
      const evSessionId = extractSessionId(ev.properties);
      if (ev.type === "server.connected") {
        onConnected();
        continue;
      }
      if (evSessionId && evSessionId !== run.sessionId) continue;
      handleOpenCodeEvent(conversationId, run, ev.type, ev.properties);
      if (run.finished) break;
    }
  } catch (err) {
    if (!run.stopped && !run.finished) {
      const message = err instanceof Error ? err.message : "OpenCode 事件流中断";
      logger.warn("opencode event stream failed", message);
      run.finished = true;
      updateMessage(run.assistantId, { status: "failed", content: run.content || message });
      emit(conversationId, { event: "run.failed", data: { error: message, output: run.content } });
    }
  } finally {
    if (!run.finished) flush(run, true);
    active.delete(conversationId);
    touchConversation(conversationId);
  }
}

function extractSessionId(props: Record<string, unknown>): string {
  if (typeof props.sessionID === "string") return props.sessionID;
  const info = props.info as Record<string, unknown> | undefined;
  if (info && typeof info.sessionID === "string") return info.sessionID;
  const part = props.part as Record<string, unknown> | undefined;
  if (part && typeof part.sessionID === "string") return part.sessionID;
  return "";
}

function extractErrorText(errorObj: unknown): string {
  if (!errorObj) return "OpenCode 执行出错";
  if (typeof errorObj === "string") return errorObj;
  if (typeof errorObj === "object") {
    const obj = errorObj as Record<string, unknown>;
    const data = obj.data as Record<string, unknown> | undefined;
    if (data && typeof data.message === "string" && data.message) return data.message;
    if (typeof obj.message === "string" && obj.message) return obj.message;
    if (typeof obj.name === "string" && obj.name) return obj.name;
  }
  return "OpenCode 执行出错";
}

function appendReasoningDelta(conversationId: string, run: ActiveRun, partId: string, delta: string): void {
  if (!delta) return;
  let block = run.reasoning.find((r) => r.step === partId);
  if (!block) {
    block = { step: partId, title: "", text: "", tools: [] };
    run.reasoning.push(block);
  }
  block.text = String(block.text ?? "") + delta;
  flush(run);
  emit(conversationId, { event: "reasoning.delta", data: { step: partId, delta } });
}

function appendTextDelta(conversationId: string, run: ActiveRun, delta: string): void {
  if (!delta) return;
  run.content += delta;
  updateMessage(run.assistantId, { content: run.content });
  emit(conversationId, { event: "message.delta", data: { text: delta } });
}

function handleOpenCodeEvent(
  conversationId: string,
  run: ActiveRun,
  type: string,
  props: Record<string, unknown>,
): void {
  switch (type) {
    case "message.updated": {
      const info = props.info as Record<string, unknown> | undefined;
      if (!info) return;
      const msgId = String(info.id ?? "");
      if (info.role === "user" && msgId) {
        run.userMessageIds.add(msgId);
        return;
      }
      if (info.role === "assistant" && msgId) {
        run.assistantMessageIds.add(msgId);
        if (info.error) {
          const errMsg = extractErrorText(info.error);
          run.finished = true;
          updateMessage(run.assistantId, { status: "failed", content: run.content || errMsg });
          emit(conversationId, { event: "run.failed", data: { error: errMsg, output: run.content } });
          run.controller.abort();
        }
      }
      return;
    }

    case "message.part.delta": {
      const msgId = String(props.messageID ?? "");
      if (run.userMessageIds.has(msgId) || !run.assistantMessageIds.has(msgId)) return;
      const partId = String(props.partID ?? "part");
      const field = String(props.field ?? "text");
      const delta = String(props.delta ?? "");
      if (!delta) return;
      if (field === "text") {
        const prev = run.partTexts.get(partId) ?? "";
        run.partTexts.set(partId, prev + delta);
        appendTextDelta(conversationId, run, delta);
      } else if (field === "reasoning") {
        const prev = run.partReasons.get(partId) ?? "";
        run.partReasons.set(partId, prev + delta);
        appendReasoningDelta(conversationId, run, partId, delta);
      }
      return;
    }

    case "message.part.updated": {
      const part = props.part as Record<string, unknown> | undefined;
      if (!part) return;
      const msgId = String(part.messageID ?? "");
      if (run.userMessageIds.has(msgId) || !run.assistantMessageIds.has(msgId)) return;

      const partId = String(part.id ?? "");
      const partType = String(part.type ?? "");
      if (partType === "text" && !part.synthetic && !part.ignored) {
        const full = String(part.text ?? "");
        const prev = run.partTexts.get(partId) ?? "";
        if (full.length > prev.length && full.startsWith(prev)) {
          const diff = full.slice(prev.length);
          run.partTexts.set(partId, full);
          appendTextDelta(conversationId, run, diff);
        }
        return;
      }
      if (partType === "reasoning") {
        const full = String(part.text ?? "");
        const prev = run.partReasons.get(partId) ?? "";
        if (full.length > prev.length && full.startsWith(prev)) {
          const diff = full.slice(prev.length);
          run.partReasons.set(partId, full);
          appendReasoningDelta(conversationId, run, partId, diff);
        }
        return;
      }
      if (partType === "tool") {
        const toolName = String(part.tool ?? "tool");
        const callId = String(part.callID ?? partId);
        const stateObj = (part.state as Record<string, unknown> | undefined) ?? {};
        const status = String(stateObj.status ?? "pending");
        const prevStatus = run.toolStates.get(callId);
        if (status === "running" && prevStatus !== "running") {
          run.toolStates.set(callId, "running");
          const msg = addMessage({
            conversation_id: conversationId,
            role: "tool" as WorkRole,
            tool_name: toolName,
            status: "running",
            tool_payload: {
              args: stateObj.input ?? null,
              title: stateObj.title ?? null,
              tool_call_id: callId,
              status: "running",
            },
            run_id: run.runId,
          });
          emit(conversationId, {
            event: "tool.started",
            data: { tool: toolName, preview: stateObj.input ?? null, tool_call_id: callId, message_id: msg.id },
          });
          return;
        }
        if ((status === "completed" || status === "error") && prevStatus !== status) {
          run.toolStates.set(callId, status);
          let row = findRunningTool(conversationId, toolName, callId);
          const timeObj = stateObj.time as Record<string, number> | undefined;
          const duration =
            timeObj && typeof timeObj.end === "number" && typeof timeObj.start === "number"
              ? Math.max(0, (timeObj.end - timeObj.start) / 1000)
              : null;
          const errorText = status === "error" ? String(stateObj.error ?? "工具执行失败") : null;
          const resultPreview = stateObj.output ?? stateObj.error ?? stateObj.title ?? null;

          if (!row) {
            row = addMessage({
              conversation_id: conversationId,
              role: "tool" as WorkRole,
              tool_name: toolName,
              status: errorText ? "failed" : "completed",
              tool_payload: {
                args: stateObj.input ?? null,
                result: resultPreview,
                duration,
                error: errorText,
                tool_call_id: callId,
                status: errorText ? "failed" : "completed",
              },
              run_id: run.runId,
            });
          } else {
            updateMessage(row.id, {
              status: errorText ? "failed" : "completed",
              tool_payload: {
                ...(row.tool_payload ?? {}),
                args: stateObj.input ?? row.tool_payload?.args ?? null,
                result: resultPreview,
                duration,
                error: errorText,
                status: errorText ? "failed" : "completed",
              },
            });
          }
          emit(conversationId, {
            event: "tool.completed",
            data: {
              tool: toolName,
              tool_call_id: callId,
              preview: resultPreview,
              duration,
              error: errorText,
              message_id: row.id,
            },
          });
        }
      }
      return;
    }

    case "todo.updated": {
      const todos = Array.isArray(props.todos) ? props.todos : [];
      const plan = { items: todos };
      run.plan = plan;
      flush(run, true);
      emit(conversationId, { event: "plan.updated", data: plan });
      return;
    }

    case "permission.asked": {
      const requestId = String(props.id ?? "");
      if (!requestId) return;
      run.pendingPermissionId = requestId;
      updateMessage(run.assistantId, { status: "waiting" });
      const patterns = Array.isArray(props.patterns) ? props.patterns : [];
      const metadata = props.metadata ?? null;
      emit(conversationId, {
        event: "approval.request",
        data: {
          request_id: requestId,
          execution_generation: 1,
          tool: String(props.permission ?? "tool"),
          preview: patterns.length ? { patterns, metadata } : metadata,
          choices: ["once", "always", "deny"],
          detail: props,
        },
      });
      return;
    }

    case "question.asked": {
      const requestId = String(props.id ?? "");
      const questions = Array.isArray(props.questions) ? (props.questions as Array<Record<string, unknown>>) : [];
      const first = questions[0] ?? {};
      const opts = Array.isArray(first.options) ? (first.options as Array<Record<string, unknown>>) : [];
      const choiceLabels = opts.map((o) => String(o.label ?? "")).filter(Boolean);
      run.pendingQuestion = { requestId, header: String(first.header ?? "") };
      updateMessage(run.assistantId, { status: "waiting" });
      emit(conversationId, {
        event: "clarify.request",
        data: {
          request_id: requestId,
          execution_generation: 1,
          tool: "question",
          preview: String(first.question ?? "OpenCode 需要你的补充说明"),
          choices: choiceLabels.length ? choiceLabels : null,
          detail: props,
        },
      });
      return;
    }

    case "session.error": {
      const errMsg = extractErrorText(props.error);
      run.finished = true;
      updateMessage(run.assistantId, { status: "failed", content: run.content || errMsg });
      emit(conversationId, { event: "run.failed", data: { error: errMsg, output: run.content } });
      run.controller.abort();
      return;
    }

    case "session.idle": {
      if (!run.promptSent || run.pendingPermissionId || run.pendingQuestion) return;
      run.finished = true;
      updateMessage(run.assistantId, {
        status: "completed",
        content: run.content,
        tool_payload: { reasoning: run.reasoning, plan: run.plan },
      });
      emit(conversationId, {
        event: "run.completed",
        data: { output: run.content, plan: run.plan, reasoning: run.reasoning },
      });
      run.controller.abort();
      return;
    }

    default:
      return;
  }
}

export async function steerRun(conversationId: string, content: string): Promise<void> {
  const run = active.get(conversationId);
  if (!run) throw new Error("当前没有运行中的任务");
  const model = await resolvePromptModel();
  await new OpenCodeClient().promptAsync(run.sessionId, run.directory, {
    model,
    parts: [{ type: "text", text: content }],
  });
}

export async function stopRun(conversationId: string): Promise<void> {
  const run = active.get(conversationId);
  if (!run) return;
  run.stopped = true;
  run.finished = true;
  run.controller.abort();
  try {
    await new OpenCodeClient().abortSession(run.sessionId, run.directory);
  } catch (err) {
    logger.warn("abort opencode session failed", err instanceof Error ? err.message : String(err));
  }
  updateMessage(run.assistantId, { status: "cancelled", content: run.content });
  emit(conversationId, { event: "run.cancelled", data: { output: run.content } });
  active.delete(conversationId);
}

export async function approveRun(
  conversationId: string,
  requestId: string,
  _generation: number,
  choice: WorkApprovalChoice,
): Promise<void> {
  const run = active.get(conversationId);
  if (!run) throw new Error("当前没有等待审批的任务");
  const reqId = requestId || run.pendingPermissionId || "";
  if (!reqId) throw new Error("缺少权限审批编号");
  const reply = choice === "deny" ? "reject" : choice === "always" ? "always" : "once";
  await new OpenCodeClient().replyPermission(reqId, run.directory, reply);
  run.pendingPermissionId = null;
  updateMessage(run.assistantId, { status: "streaming" });
  emit(conversationId, { event: "approval.resolved", data: { choice } });
}

export async function clarifyRun(
  conversationId: string,
  requestId: string,
  _generation: number,
  answer: string,
): Promise<void> {
  const run = active.get(conversationId);
  if (!run) throw new Error("当前没有等待确认的任务");
  const reqId = requestId || run.pendingQuestion?.requestId || "";
  if (!reqId) throw new Error("缺少提问请求编号");
  await new OpenCodeClient().replyQuestion(reqId, run.directory, [[answer]]);
  run.pendingQuestion = null;
  updateMessage(run.assistantId, { status: "streaming" });
  emit(conversationId, { event: "clarify.resolved", data: { answer } });
}
