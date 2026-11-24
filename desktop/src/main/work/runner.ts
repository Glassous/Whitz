import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { scoped } from "../logger";
import { ensureBuiltinKey } from "../runtime/localOpenAIGateway";
import { readOpenCodeJsonDoc } from "../runtime/opencodeConfig";
import { getStatus, startRuntime } from "../runtime/opencodeRuntime";
import { OpenCodeClient, type PromptPartInput } from "./opencodeClient";
import { notifyWorkEvent } from "./notifications";
import { getWorkSettings } from "./settings";
import {
  addMessage,
  copyMessagesUpTo,
  createConversation,
  getActiveWorkspacePath,
  getConversation,
  getConversationMeta,
  getMessageRow,
  markMessagesRevertedFrom,
  renameConversation,
  setConversationPrefs,
  setOpenCodeSession,
  touchConversation,
  unrevertAllMessages,
  updateMessage,
} from "./repository";
import type {
  WorkActiveRunSnapshot,
  WorkApprovalChoice,
  WorkAttachment,
  WorkClarifyQuestion,
  WorkConversation,
  WorkConversationDetail,
  WorkEvent,
  WorkPendingControl,
  WorkSessionDiffItem,
  WorkSessionRetryState,
  WorkTimelineItem,
  WorkTokenUsage,
} from "../../shared/work-types";

const logger = scoped("work:runner");

type PartKind = "text" | "reasoning";

interface ThinkParseState {
  inThink: boolean;
  pending: string;
}

const modelContextLimitCache = new Map<string, number>();

export function updateModelContextLimits(limits: Map<string, number>): void {
  for (const [ref, limit] of limits.entries()) {
    if (limit > 0) modelContextLimitCache.set(ref, limit);
  }
}

function lookupContextLimit(modelRef?: string | null): number | null {
  if (!modelRef) return null;
  return modelContextLimitCache.get(modelRef) ?? null;
}

interface ActiveRun {
  runId: string;
  sessionId: string;
  childSessionIds: Set<string>;
  subagentToolCounts: Map<string, number>;
  directory: string | null;
  modelRef: string | null;
  controller: AbortController;
  userId: string;
  assistantId: string | null;
  userMapped: boolean;
  latestOcAssistantId: string | null;
  content: string;
  lastTextOutput: string;
  timeline: WorkTimelineItem[];
  reasoning: Array<Record<string, unknown>>;
  plan: Record<string, unknown> | null;
  usage: WorkTokenUsage | null;
  retry: WorkSessionRetryState | null;
  userMessageIds: Set<string>;
  assistantMessageIds: Set<string>;
  partTypes: Map<string, PartKind>;
  pendingPartDeltas: Map<string, string>;
  partThinkStates: Map<string, ThinkParseState>;
  partTexts: Map<string, string>;
  partReasons: Map<string, string>;
  segmentTextPartIds: Set<string>;
  toolStates: Map<string, string>;
  pendingControls: WorkPendingControl[];
  flushedAt: number;
  lastEventAt: number;
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

export function getActiveRunSnapshots(): WorkActiveRunSnapshot[] {
  const out: WorkActiveRunSnapshot[] = [];
  for (const [conversationId, run] of active.entries()) {
    if (run.finished || run.stopped) continue;
    out.push({
      conversation_id: conversationId,
      run_id: run.runId,
      assistant_id: run.assistantId ?? "",
      status: run.pendingControls.length ? "waiting" : "streaming",
      content: run.content,
      reasoning: run.reasoning,
      timeline: [...run.timeline],
      plan: run.plan,
      pending_control: run.pendingControls[0] ?? null,
      pending_controls: [...run.pendingControls],
      usage: run.usage,
      retry: run.retry,
    });
  }
  return out;
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

function buildPersistedPayload(run: ActiveRun, existing?: Record<string, unknown> | null): Record<string, unknown> {
  return {
    ...(existing ?? {}),
    reasoning: run.reasoning,
    timeline: run.timeline,
    plan: run.plan,
    ...(run.latestOcAssistantId ? { opencode_message_id: run.latestOcAssistantId } : {}),
    ...(run.usage ? { usage: run.usage } : {}),
  };
}

function flush(run: ActiveRun, force = false): void {
  if (!run.assistantId) return;
  const now = Date.now();
  if (!force && now - run.flushedAt < 450) return;
  run.flushedAt = now;
  const existing = getMessageRow(run.assistantId)?.tool_payload ?? {};
  updateMessage(run.assistantId, {
    content: run.content,
    tool_payload: buildPersistedPayload(run, existing),
  });
}

function ensureAssistantRow(conversationId: string, run: ActiveRun): string {
  if (run.assistantId) return run.assistantId;
  const msg = addMessage({
    conversation_id: conversationId,
    role: "assistant",
    content: "",
    status: "streaming",
    run_id: run.runId,
    tool_payload: run.latestOcAssistantId ? { opencode_message_id: run.latestOcAssistantId } : null,
  });
  run.assistantId = msg.id;
  emit(conversationId, {
    event: "message.created",
    data: { assistant_message_id: msg.id },
  });
  return msg.id;
}

function completeOpenThinkingItems(run: ActiveRun): void {
  for (const item of run.timeline) {
    if (item.kind === "thinking" && item.status === "running") {
      item.status = "completed";
    }
  }
}

function upsertTimelineItem(conversationId: string, run: ActiveRun, item: WorkTimelineItem): void {
  const targetId = ensureAssistantRow(conversationId, run);
  const idx = run.timeline.findIndex((entry) => entry.id === item.id);
  if (idx >= 0) {
    run.timeline[idx] = item;
  } else {
    run.timeline.push(item);
  }
  flush(run, true);
  emit(conversationId, {
    event: "timeline.item",
    data: { item, message_id: targetId },
  });
}

function promotePreToolContent(conversationId: string, run: ActiveRun): void {
  completeOpenThinkingItems(run);
  const trimmed = run.content.trim();
  if (!trimmed) return;
  const targetId = ensureAssistantRow(conversationId, run);
  const commentaryItem: WorkTimelineItem = {
    id: `comment:${crypto.randomUUID()}`,
    kind: "commentary",
    text: trimmed,
    status: "completed",
  };
  run.timeline.push(commentaryItem);
  run.lastTextOutput = run.content;
  run.content = "";
  run.segmentTextPartIds.clear();
  flush(run, true);
  emit(conversationId, {
    event: "timeline.item",
    data: { item: commentaryItem, message_id: targetId },
  });
  emit(conversationId, {
    event: "content.reset",
    data: { message_id: targetId },
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
    parts.push(`用户附加了以下本机文件（已作为原生 Part 或工作区引用附带）：\n${list}`);
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

async function resolvePromptModel(
  overrideModelRef?: string | null,
  fallbackModelRef?: string | null,
): Promise<{ providerID: string; modelID: string } | undefined> {
  const candidate = overrideModelRef?.trim() || fallbackModelRef?.trim() || "";
  if (candidate) {
    const parsed = parseModelRef(candidate);
    if (parsed) {
      if (parsed.providerID === "whitz") await ensureBuiltinKey();
      return parsed;
    }
  }
  const settings = getWorkSettings();
  if (settings.model.default_composer_model) {
    const parsed = parseModelRef(settings.model.default_composer_model);
    if (parsed) {
      if (parsed.providerID === "whitz") await ensureBuiltinKey();
      return parsed;
    }
  }
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

function guessMimeType(filePath: string, kind: WorkAttachment["kind"]): string {
  const ext = path.extname(filePath).toLowerCase();
  const map: Record<string, string> = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
  };
  if (map[ext]) return map[ext];
  return kind === "image" ? "image/png" : "text/plain";
}

function buildPromptParts(
  content: string,
  attachments?: WorkAttachment[],
  knownSubagents?: Set<string>,
): PromptPartInput[] {
  const parts: PromptPartInput[] = [{ type: "text", text: content }];
  if (attachments?.length) {
    for (const att of attachments) {
      if (!att.path || !fs.existsSync(att.path)) continue;
      const mime = guessMimeType(att.path, att.kind);
      if (att.kind === "image" || mime === "application/pdf") {
        try {
          const stat = fs.statSync(att.path);
          if (att.kind === "image" && stat.size <= 8 * 1024 * 1024) {
            const b64 = fs.readFileSync(att.path).toString("base64");
            parts.push({ type: "file", mime, filename: att.name, url: `data:${mime};base64,${b64}` });
            continue;
          }
        } catch {
          /* fall through to file URL */
        }
      }
      parts.push({ type: "file", mime, filename: att.name, url: pathToFileURL(att.path).href });
    }
  }
  if (knownSubagents?.size) {
    const mentioned = new Set<string>();
    const re = /(?:^|\s)@([a-zA-Z0-9._-]+)/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(content)) !== null) {
      if (knownSubagents.has(m[1])) mentioned.add(m[1]);
    }
    for (const name of mentioned) {
      parts.push({ type: "agent", name });
    }
  }
  return parts;
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

async function startRunWithPump(
  conversationId: string,
  userDisplayContent: string,
  options: {
    attachmentPayload?: Record<string, unknown> | null;
    modelRef?: string | null;
    agentName?: string | null;
    variant?: string | null;
  },
  executor: (ctx: {
    client: OpenCodeClient;
    sessionId: string;
    workspaceDir: string | null;
    run: ActiveRun;
  }) => Promise<void>,
): Promise<{ run_id: string | null }> {
  const conversation = getConversationMeta(conversationId);
  if (!conversation) throw new Error("对话不存在");
  if (active.has(conversationId)) throw new Error("当前对话仍有进行中的任务");
  await ensureReady();

  const workspaceDir = safeWorkspaceDir(conversation.workspace_path || getActiveWorkspacePath());
  const client = new OpenCodeClient();

  let sessionId = conversation.opencode_session_id;
  if (!sessionId) {
    sessionId = await client.createSession(conversation.title, workspaceDir);
    if (!sessionId) throw new Error("创建 OpenCode 会话失败");
    setOpenCodeSession(conversationId, sessionId);
  }

  if (options.modelRef !== undefined || options.agentName !== undefined || options.variant !== undefined) {
    setConversationPrefs(conversationId, {
      ...(options.modelRef !== undefined ? { model_ref: options.modelRef } : {}),
      ...(options.agentName !== undefined ? { agent_name: options.agentName } : {}),
      ...(options.variant !== undefined ? { variant: options.variant } : {}),
    });
  }

  if (conversation.title === "新的工作区对话" || conversation.title === "新的本地对话") {
    renameConversation(conversationId, autoTitleFrom(userDisplayContent));
  }

  const userMessage = addMessage({
    conversation_id: conversationId,
    role: "user",
    content: userDisplayContent,
    status: "completed",
    tool_payload: options.attachmentPayload ?? null,
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
    childSessionIds: new Set(),
    subagentToolCounts: new Map(),
    directory: workspaceDir,
    modelRef: options.modelRef ?? conversation.model_ref ?? null,
    controller: new AbortController(),
    userId: userMessage.id,
    assistantId: assistant.id,
    userMapped: false,
    latestOcAssistantId: null,
    content: "",
    lastTextOutput: "",
    timeline: [],
    reasoning: [],
    plan: null,
    usage: null,
    retry: null,
    userMessageIds: new Set(),
    assistantMessageIds: new Set(),
    partTypes: new Map(),
    pendingPartDeltas: new Map(),
    partThinkStates: new Map(),
    partTexts: new Map(),
    partReasons: new Map(),
    segmentTextPartIds: new Set(),
    toolStates: new Map(),
    pendingControls: [],
    flushedAt: 0,
    lastEventAt: Date.now(),
    stopped: false,
    finished: false,
    promptSent: false,
  };
  active.set(conversationId, run);
  emit(conversationId, { event: "run.started", data: { run_id: runId } });

  try {
    let settled = false;
    let resolveConnected!: () => void;
    const connected = new Promise<void>((resolve) => {
      resolveConnected = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
    });
    const fallbackTick = setTimeout(() => resolveConnected(), 1200);

    void pump(conversationId, client, run, () => {
      clearTimeout(fallbackTick);
      resolveConnected();
    });

    await connected;
    await executor({ client, sessionId, workspaceDir, run });
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

export async function sendMessage(
  conversationId: string,
  content: string,
  options?: {
    skillNames?: string[];
    attachments?: WorkAttachment[];
    modelRef?: string | null;
    agentName?: string | null;
    variant?: string | null;
  },
): Promise<{ run_id: string | null }> {
  const conversation = getConversationMeta(conversationId);
  if (!conversation) throw new Error("对话不存在");

  const attachmentPayload: Record<string, unknown> | null =
    options?.attachments?.length || options?.skillNames?.length || options?.modelRef || options?.agentName
      ? {
          ...(options?.attachments?.length
            ? {
                attachments: options.attachments.map((a) => ({
                  id: a.id,
                  name: a.name,
                  path: a.path,
                  kind: a.kind,
                  size: a.size,
                })),
              }
            : {}),
          ...(options?.skillNames?.length ? { skills: options.skillNames } : {}),
          ...(options?.modelRef ? { model_ref: options.modelRef } : {}),
          ...(options?.agentName ? { agent: options.agentName } : {}),
          ...(options?.variant ? { variant: options.variant } : {}),
        }
      : null;

  return startRunWithPump(
    conversationId,
    content,
    {
      attachmentPayload,
      modelRef: options?.modelRef,
      agentName: options?.agentName,
      variant: options?.variant,
    },
    async ({ client, sessionId, workspaceDir }) => {
      const settings = getWorkSettings();
      const selectedModel = await resolvePromptModel(options?.modelRef, conversation.model_ref);
      const effectiveAgent = options?.agentName?.trim() || conversation.agent_name || settings.model.default_agent || undefined;
      const effectiveVariant = options?.variant?.trim() || conversation.variant || settings.model.default_variant || undefined;

      let knownSubagents: Set<string> | undefined;
      if (content.includes("@")) {
        const agents = await client.listAgents(workspaceDir).catch(() => []);
        knownSubagents = new Set(agents.filter((a) => a.mode === "subagent" || a.mode === "all").map((a) => a.name));
      }

      const system = buildSystemInstructions(workspaceDir, options?.skillNames, options?.attachments);
      const parts = buildPromptParts(content, options?.attachments, knownSubagents);

      await client.promptAsync(sessionId, workspaceDir, {
        model: selectedModel,
        agent: effectiveAgent,
        variant: effectiveVariant,
        system,
        parts,
      });
    },
  );
}

export async function runSlashCommand(
  conversationId: string,
  command: string,
  args: string,
  options?: { modelRef?: string | null; agentName?: string | null; variant?: string | null },
): Promise<{ run_id: string | null }> {
  const conversation = getConversationMeta(conversationId);
  if (!conversation) throw new Error("对话不存在");
  const cleanCmd = command.replace(/^\/+/, "").trim();
  const display = args.trim() ? `/${cleanCmd} ${args.trim()}` : `/${cleanCmd}`;

  return startRunWithPump(
    conversationId,
    display,
    { modelRef: options?.modelRef, agentName: options?.agentName, variant: options?.variant },
    async ({ client, sessionId, workspaceDir }) => {
      const settings = getWorkSettings();
      const model = await resolvePromptModel(options?.modelRef, conversation.model_ref);
      const effectiveAgent = options?.agentName?.trim() || conversation.agent_name || settings.model.default_agent || undefined;
      const effectiveVariant = options?.variant?.trim() || conversation.variant || settings.model.default_variant || undefined;
      await client.runCommand(sessionId, workspaceDir, {
        command: cleanCmd,
        arguments: args,
        agent: effectiveAgent,
        model: model ? `${model.providerID}/${model.modelID}` : undefined,
        variant: effectiveVariant,
      });
    },
  );
}

export async function runShellCommand(
  conversationId: string,
  command: string,
  options?: { agentName?: string | null; modelRef?: string | null },
): Promise<{ run_id: string | null }> {
  const conversation = getConversationMeta(conversationId);
  if (!conversation) throw new Error("对话不存在");
  const clean = command.replace(/^!+/, "").trim();
  if (!clean) throw new Error("请输入要执行的终端命令");

  return startRunWithPump(
    conversationId,
    `! ${clean}`,
    { agentName: options?.agentName, modelRef: options?.modelRef },
    async ({ client, sessionId, workspaceDir }) => {
      const settings = getWorkSettings();
      const model = await resolvePromptModel(options?.modelRef, conversation.model_ref);
      const effectiveAgent = options?.agentName?.trim() || conversation.agent_name || settings.model.default_agent || "build";
      await client.runShell(sessionId, workspaceDir, {
        agent: effectiveAgent,
        command: clean,
        ...(model ? { model } : {}),
      });
    },
  );
}

function finalizeRunStreams(conversationId: string, run: ActiveRun): void {
  if (run.pendingPartDeltas.size) {
    for (const [partId, pending] of run.pendingPartDeltas.entries()) {
      if (!pending) continue;
      const kind = run.partTypes.get(partId) ?? "text";
      if (kind === "reasoning") {
        run.partReasons.set(partId, (run.partReasons.get(partId) ?? "") + pending);
        appendReasoningDelta(conversationId, run, partId, pending);
      } else {
        run.partTexts.set(partId, (run.partTexts.get(partId) ?? "") + pending);
        appendTextWithThinkFilter(conversationId, run, partId, pending);
      }
    }
    run.pendingPartDeltas.clear();
  }
  for (const partId of run.partThinkStates.keys()) {
    appendTextWithThinkFilter(conversationId, run, partId, "", true);
  }
  completeOpenThinkingItems(run);
}

function finalizeCompletedRun(conversationId: string, run: ActiveRun): void {
  if (run.finished || run.stopped) return;
  finalizeRunStreams(conversationId, run);
  run.finished = true;
  run.retry = null;
  run.pendingControls = [];
  if (!run.content.trim() && run.lastTextOutput.trim()) {
    run.content = run.lastTextOutput;
  }
  if (run.assistantId) {
    const existing = getMessageRow(run.assistantId)?.tool_payload ?? {};
    updateMessage(run.assistantId, {
      status: "completed",
      content: run.content,
      tool_payload: buildPersistedPayload(run, existing),
    });
  }
  emit(conversationId, {
    event: "run.completed",
    data: {
      output: run.assistantId ? run.content : undefined,
      message_id: run.assistantId,
      plan: run.plan,
      reasoning: run.reasoning,
      timeline: run.timeline,
      usage: run.usage,
    },
  });
  const convMeta = getConversationMeta(conversationId);
  notifyWorkEvent({
    title: "Whitz Work 任务已完成",
    body: convMeta?.title ? `「${convMeta.title}」已生成结果` : "当前本地工作区任务已完成",
    conversationId,
  });
  run.controller.abort();
}

function enqueuePermission(conversationId: string, client: OpenCodeClient, run: ActiveRun, props: Record<string, unknown>): void {
  const requestId = String(props.id ?? "");
  if (!requestId) return;
  const tool = String(props.permission ?? "tool");
  if (tool === "bash" && getWorkSettings().model.full_command_mode) {
    void client.replyPermission(requestId, run.directory, "always").catch((err) => {
      logger.warn("auto-approve bash permission failed", err instanceof Error ? err.message : String(err));
    });
    return;
  }
  if (run.pendingControls.some((c) => c.request_id === requestId)) return;
  const patterns = Array.isArray(props.patterns) ? props.patterns.map(String).filter(Boolean) : [];
  const alwaysPatterns = Array.isArray(props.always) ? props.always.map(String).filter(Boolean) : [];
  const metadata =
    props.metadata && typeof props.metadata === "object" && !Array.isArray(props.metadata)
      ? (props.metadata as Record<string, unknown>)
      : null;
  const preview = patterns.length ? { patterns, metadata } : metadata;
  const ctrl: WorkPendingControl = {
    kind: "approval",
    request_id: requestId,
    execution_generation: 1,
    tool,
    preview,
    patterns,
    always_patterns: alwaysPatterns,
    metadata,
    choices: ["once", "always", "deny"],
  };
  run.pendingControls.push(ctrl);
  if (run.assistantId) updateMessage(run.assistantId, { status: "waiting" });
  emit(conversationId, {
    event: "approval.request",
    data: {
      ...ctrl,
      pending_controls: [...run.pendingControls],
      detail: props,
    },
  });
  notifyWorkEvent({
    title: "Whitz Work 需要你的授权",
    body: `OpenCode 请求执行 ${tool}${patterns[0] ? `：${patterns[0]}` : ""}`,
    conversationId,
  });
}

function normalizeQuestionRequest(props: Record<string, unknown>): WorkClarifyQuestion[] {
  const rawList = Array.isArray(props.questions) ? (props.questions as Array<Record<string, unknown>>) : [];
  return rawList.map((item, idx) => {
    const rawOpts = Array.isArray(item.options) ? (item.options as Array<Record<string, unknown>>) : [];
    const options = rawOpts
      .map((o) => ({
        label: String(o.label ?? "").trim(),
        description: typeof o.description === "string" && o.description.trim() ? o.description.trim() : undefined,
      }))
      .filter((o) => o.label);
    return {
      id: `q_${idx}`,
      header: typeof item.header === "string" && item.header.trim() ? item.header.trim() : undefined,
      question: String(item.question ?? "OpenCode 需要你的补充说明").trim(),
      options,
      multiple: Boolean(item.multiple),
      custom: item.custom !== false,
    };
  });
}

function enqueueQuestion(conversationId: string, run: ActiveRun, props: Record<string, unknown>): void {
  const requestId = String(props.id ?? "");
  if (!requestId || run.pendingControls.some((c) => c.request_id === requestId)) return;
  const questions = normalizeQuestionRequest(props);
  const first = questions[0];
  const preview = first?.question ?? "OpenCode 需要你的补充说明";
  const choices = first?.options.length ? first.options.map((o) => o.label) : null;
  const ctrl: WorkPendingControl = {
    kind: "clarify",
    request_id: requestId,
    execution_generation: 1,
    tool: "question",
    preview,
    choices,
    questions: questions.length ? questions : null,
  };
  run.pendingControls.push(ctrl);
  if (run.assistantId) updateMessage(run.assistantId, { status: "waiting" });
  emit(conversationId, {
    event: "clarify.request",
    data: {
      ...ctrl,
      pending_controls: [...run.pendingControls],
      detail: props,
    },
  });
  notifyWorkEvent({
    title: "Whitz Work 需要你补充信息",
    body: questions.length > 1 ? `OpenCode 有 ${questions.length} 个问题需要确认` : preview,
    conversationId,
  });
}

function removePendingControl(
  conversationId: string,
  run: ActiveRun,
  requestId: string,
  resolvedEvent: "approval.resolved" | "clarify.resolved",
  extra?: Record<string, unknown>,
): void {
  const prevLen = run.pendingControls.length;
  run.pendingControls = run.pendingControls.filter((c) => c.request_id !== requestId);
  if (run.pendingControls.length === 0 && run.assistantId) {
    updateMessage(run.assistantId, { status: "streaming" });
  }
  if (prevLen !== run.pendingControls.length || extra) {
    emit(conversationId, {
      event: resolvedEvent,
      data: { ...(extra ?? {}), request_id: requestId, pending_controls: [...run.pendingControls] },
    });
  }
}

async function reconcileRunState(conversationId: string, client: OpenCodeClient, run: ActiveRun): Promise<void> {
  if (run.finished || run.stopped || !run.promptSent) return;
  try {
    const [perms, questions, children, statuses] = await Promise.all([
      client.listPermissions(run.directory).catch(() => null),
      client.listQuestions(run.directory).catch(() => null),
      client.getSessionChildren(run.sessionId, run.directory).catch(() => []),
      client.getSessionStatuses(run.directory).catch(() => null),
    ]);
    for (const cid of children) run.childSessionIds.add(cid);
    const sessionSet = new Set<string>([run.sessionId, ...run.childSessionIds]);

    const liveIds = new Set<string>();
    if (Array.isArray(perms)) {
      for (const p of perms) {
        const sid = String(p.sessionID ?? "");
        const rid = String(p.id ?? "");
        if (!rid || (sid && !sessionSet.has(sid))) continue;
        liveIds.add(rid);
        enqueuePermission(conversationId, client, run, p);
      }
    }
    if (Array.isArray(questions)) {
      for (const q of questions) {
        const sid = String(q.sessionID ?? "");
        const rid = String(q.id ?? "");
        if (!rid || (sid && !sessionSet.has(sid))) continue;
        liveIds.add(rid);
        enqueueQuestion(conversationId, run, q);
      }
    }

    if (perms && questions) {
      const removed = run.pendingControls.filter((c) => !liveIds.has(c.request_id));
      for (const stale of removed) {
        removePendingControl(
          conversationId,
          run,
          stale.request_id,
          stale.kind === "clarify" ? "clarify.resolved" : "approval.resolved",
        );
      }
    }

    const st = statuses?.[run.sessionId];
    if (
      st?.type === "idle" &&
      run.pendingControls.length === 0 &&
      Date.now() - run.lastEventAt > 3500
    ) {
      finalizeCompletedRun(conversationId, run);
    }
  } catch {
    /* ignore transient reconcile failures */
  }
}

export function flushPendingBashApprovals(): void {
  if (!getWorkSettings().model.full_command_mode) return;
  const client = new OpenCodeClient();
  for (const [conversationId, run] of active.entries()) {
    if (run.finished || run.stopped) continue;
    const bashControls = run.pendingControls.filter((c) => c.kind === "approval" && c.tool === "bash");
    for (const ctrl of bashControls) {
      void client.replyPermission(ctrl.request_id, run.directory, "always").catch(() => undefined);
      removePendingControl(conversationId, run, ctrl.request_id, "approval.resolved", { choice: "always" });
    }
  }
}

async function pump(
  conversationId: string,
  client: OpenCodeClient,
  run: ActiveRun,
  onConnected: () => void,
): Promise<void> {
  const watchdog = setInterval(() => {
    void reconcileRunState(conversationId, client, run);
  }, 2500);
  watchdog.unref?.();

  try {
    for await (const ev of client.streamEvents(run.directory, run.controller.signal, onConnected)) {
      if (run.finished || run.stopped) break;
      if (ev.type === "server.connected") {
        onConnected();
        continue;
      }
      if (ev.type === "session.created") {
        const info = ev.properties.info as Record<string, unknown> | undefined;
        const parentId = typeof info?.parentID === "string" ? info.parentID : "";
        const childId = typeof info?.id === "string" ? info.id : "";
        if (childId && (parentId === run.sessionId || run.childSessionIds.has(parentId))) {
          run.childSessionIds.add(childId);
          run.subagentToolCounts.set(childId, 0);
          emit(conversationId, {
            event: "subagent.started",
            data: {
              subagent_id: childId,
              goal: typeof info?.title === "string" && info.title.trim() ? info.title.trim() : "子代理任务",
              status: "running",
            },
          });
        }
        continue;
      }
      const evSessionId = extractSessionId(ev.properties);
      const isMain = !evSessionId || evSessionId === run.sessionId;
      const isChild = Boolean(evSessionId && run.childSessionIds.has(evSessionId));
      if (!isMain && !isChild) continue;
      if (isChild) {
        if (["permission.asked", "permission.replied", "question.asked", "question.replied", "question.rejected"].includes(ev.type)) {
          run.lastEventAt = Date.now();
          handleOpenCodeEvent(conversationId, client, run, ev.type, ev.properties);
        } else if (ev.type === "message.part.updated") {
          const part = ev.properties.part as Record<string, unknown> | undefined;
          if (part?.type === "tool") {
            const count = (run.subagentToolCounts.get(evSessionId) ?? 0) + 1;
            run.subagentToolCounts.set(evSessionId, count);
            emit(conversationId, {
              event: "subagent.progress",
              data: { subagent_id: evSessionId, tool_count: count, status: "running" },
            });
          }
        } else if (ev.type === "session.idle") {
          emit(conversationId, {
            event: "subagent.completed",
            data: { subagent_id: evSessionId, status: "completed" },
          });
        }
        continue;
      }
      run.lastEventAt = Date.now();
      handleOpenCodeEvent(conversationId, client, run, ev.type, ev.properties);
      if (run.finished) break;
    }
  } catch (err) {
    if (!run.stopped && !run.finished) {
      const message = err instanceof Error ? err.message : "OpenCode 事件流中断";
      logger.warn("opencode event stream failed", message);
      finalizeRunStreams(conversationId, run);
      run.finished = true;
      const targetId = run.assistantId ?? addMessage({ conversation_id: conversationId, role: "assistant", content: message, status: "failed", run_id: run.runId }).id;
      const existing = getMessageRow(targetId)?.tool_payload ?? {};
      updateMessage(targetId, { status: "failed", content: run.content || message, tool_payload: buildPersistedPayload(run, existing) });
      emit(conversationId, { event: "run.failed", data: { error: message, output: run.content, message_id: targetId } });
    }
  } finally {
    clearInterval(watchdog);
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
  const targetId = ensureAssistantRow(conversationId, run);
  let block = run.reasoning.find((r) => r.step === partId);
  if (!block) {
    block = { step: partId, title: "", text: "", tools: [] };
    run.reasoning.push(block);
  }
  block.text = String(block.text ?? "") + delta;

  const timelineId = `think:${partId}`;
  let item = run.timeline.find((entry) => entry.id === timelineId);
  if (!item) {
    item = { id: timelineId, kind: "thinking", title: "深度思考", text: delta, status: "running" };
    run.timeline.push(item);
  } else {
    item.text = `${item.text ?? ""}${delta}`;
    item.status = "running";
  }

  flush(run);
  emit(conversationId, { event: "reasoning.delta", data: { step: partId, delta, message_id: targetId } });
  emit(conversationId, { event: "timeline.delta", data: { id: timelineId, kind: "thinking", title: "深度思考", delta, message_id: targetId } });
}

function appendTextWithThinkFilter(
  conversationId: string,
  run: ActiveRun,
  partId: string,
  delta: string,
  flushEnd = false,
): void {
  let state = run.partThinkStates.get(partId);
  if (!state) {
    state = { inThink: false, pending: "" };
    run.partThinkStates.set(partId, state);
  }
  if (delta) state.pending += delta;

  while (state.pending.length > 0) {
    if (!state.inThink) {
      const openMatch = /<think(?:ing)?>/i.exec(state.pending);
      if (openMatch && openMatch.index !== undefined) {
        const before = state.pending.slice(0, openMatch.index);
        if (before) appendTextDelta(conversationId, run, partId, before);
        state.pending = state.pending.slice(openMatch.index + openMatch[0].length).replace(/^\r?\n/, "");
        state.inThink = true;
        continue;
      }
      if (!flushEnd) {
        const partial = /<(?:t(?:h(?:i(?:n(?:k(?:i(?:n(?:g)?)?)?)?)?)?)?)?$/i.exec(state.pending);
        const cut = partial ? partial.index : state.pending.length;
        const safe = state.pending.slice(0, cut);
        if (safe) appendTextDelta(conversationId, run, partId, safe);
        state.pending = state.pending.slice(cut);
        break;
      }
      appendTextDelta(conversationId, run, partId, state.pending);
      state.pending = "";
      break;
    }

    const closeMatch = /<\/think(?:ing)?>/i.exec(state.pending);
    if (closeMatch && closeMatch.index !== undefined) {
      const inside = state.pending.slice(0, closeMatch.index);
      if (inside) appendReasoningDelta(conversationId, run, `${partId}:inline`, inside);
      state.pending = state.pending.slice(closeMatch.index + closeMatch[0].length).replace(/^\r?\n+/, "");
      state.inThink = false;
      continue;
    }
    if (!flushEnd) {
      const partialClose = /<\/(?:t(?:h(?:i(?:n(?:k(?:i(?:n(?:g)?)?)?)?)?)?)?)?$/i.exec(state.pending);
      const cut = partialClose ? partialClose.index : state.pending.length;
      const safe = state.pending.slice(0, cut);
      if (safe) appendReasoningDelta(conversationId, run, `${partId}:inline`, safe);
      state.pending = state.pending.slice(cut);
      break;
    }
    appendReasoningDelta(conversationId, run, `${partId}:inline`, state.pending);
    state.pending = "";
    break;
  }
}

function appendTextDelta(conversationId: string, run: ActiveRun, partId: string, delta: string): void {
  if (!delta) return;
  const targetId = ensureAssistantRow(conversationId, run);
  completeOpenThinkingItems(run);
  let appended = delta;
  if (!run.segmentTextPartIds.has(partId)) {
    run.segmentTextPartIds.add(partId);
    if (run.content.length > 0 && !/\s$/.test(run.content) && !/^\s/.test(delta)) {
      appended = `\n\n${delta}`;
    }
  }
  run.content += appended;
  if (run.content.trim()) {
    run.lastTextOutput = run.content;
  }
  updateMessage(targetId, { content: run.content });
  emit(conversationId, { event: "message.delta", data: { text: appended, message_id: targetId } });
}

function handleOpenCodeEvent(
  conversationId: string,
  client: OpenCodeClient,
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
        if (!run.userMapped) {
          run.userMapped = true;
          const prev = getMessageRow(run.userId)?.tool_payload ?? {};
          updateMessage(run.userId, { tool_payload: { ...prev, opencode_message_id: msgId } });
        }
        return;
      }
      if (info.role === "assistant" && msgId) {
        run.assistantMessageIds.add(msgId);
        run.latestOcAssistantId = msgId;
        if (run.assistantId) {
          const prev = getMessageRow(run.assistantId)?.tool_payload ?? {};
          if (!prev.opencode_message_id) {
            updateMessage(run.assistantId, { tool_payload: { ...prev, opencode_message_id: msgId } });
          }
        }
        const tokens = info.tokens as Record<string, unknown> | undefined;
        if (tokens && typeof tokens === "object") {
          const input = Number(tokens.input ?? 0) || 0;
          const output = Number(tokens.output ?? 0) || 0;
          const reasoning = Number(tokens.reasoning ?? 0) || 0;
          const cache = (tokens.cache as Record<string, unknown> | undefined) ?? {};
          const cacheRead = Number(cache.read ?? 0) || 0;
          const cacheWrite = Number(cache.write ?? 0) || 0;
          const cost = Number(info.cost ?? 0) || 0;
          const total = input + output + reasoning + cacheRead + cacheWrite;
          const infoProvider = typeof info.providerID === "string" ? info.providerID : "";
          const infoModel = typeof info.modelID === "string" ? info.modelID : "";
          const detectedRef = infoProvider && infoModel ? `${infoProvider}/${infoModel}` : run.modelRef;
          const ctxLimit = lookupContextLimit(detectedRef) ?? run.usage?.context_limit ?? null;
          run.usage = {
            input,
            output,
            reasoning,
            cache_read: cacheRead,
            cache_write: cacheWrite,
            cost,
            total,
            context_limit: ctxLimit,
          };
          emit(conversationId, { event: "usage.updated", data: { usage: run.usage } });
        }
        if (info.error) {
          const errMsg = extractErrorText(info.error);
          finalizeRunStreams(conversationId, run);
          run.finished = true;
          const targetId =
            run.assistantId ??
            addMessage({ conversation_id: conversationId, role: "assistant", content: errMsg, status: "failed", run_id: run.runId }).id;
          const existing = getMessageRow(targetId)?.tool_payload ?? {};
          updateMessage(targetId, { status: "failed", content: run.content || errMsg, tool_payload: buildPersistedPayload(run, existing) });
          emit(conversationId, { event: "run.failed", data: { error: errMsg, output: run.content, timeline: run.timeline, message_id: targetId } });
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
      if (field === "reasoning") {
        run.partTypes.set(partId, "reasoning");
        const prev = run.partReasons.get(partId) ?? "";
        run.partReasons.set(partId, prev + delta);
        appendReasoningDelta(conversationId, run, partId, delta);
      } else if (field === "text") {
        const knownType = run.partTypes.get(partId);
        if (knownType === "reasoning") {
          const prev = run.partReasons.get(partId) ?? "";
          run.partReasons.set(partId, prev + delta);
          appendReasoningDelta(conversationId, run, partId, delta);
        } else if (knownType === "text") {
          const prev = run.partTexts.get(partId) ?? "";
          run.partTexts.set(partId, prev + delta);
          appendTextWithThinkFilter(conversationId, run, partId, delta);
        } else {
          const prevPending = run.pendingPartDeltas.get(partId) ?? "";
          run.pendingPartDeltas.set(partId, prevPending + delta);
        }
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
        run.partTypes.set(partId, "text");
        const buffered = run.pendingPartDeltas.get(partId) ?? "";
        if (buffered) {
          run.pendingPartDeltas.delete(partId);
          run.partTexts.set(partId, (run.partTexts.get(partId) ?? "") + buffered);
          appendTextWithThinkFilter(conversationId, run, partId, buffered);
        }
        const full = String(part.text ?? "");
        const prev = run.partTexts.get(partId) ?? "";
        if (full.length > prev.length && full.startsWith(prev)) {
          const diff = full.slice(prev.length);
          run.partTexts.set(partId, full);
          appendTextWithThinkFilter(conversationId, run, partId, diff);
        }
        return;
      }
      if (partType === "reasoning") {
        run.partTypes.set(partId, "reasoning");
        const buffered = run.pendingPartDeltas.get(partId) ?? "";
        if (buffered) {
          run.pendingPartDeltas.delete(partId);
          run.partReasons.set(partId, (run.partReasons.get(partId) ?? "") + buffered);
          appendReasoningDelta(conversationId, run, partId, buffered);
        }
        const full = String(part.text ?? "");
        const prev = run.partReasons.get(partId) ?? "";
        if (full.length > prev.length && full.startsWith(prev)) {
          const diff = full.slice(prev.length);
          run.partReasons.set(partId, full);
          appendReasoningDelta(conversationId, run, partId, diff);
        }
        return;
      }
      run.pendingPartDeltas.delete(partId);
      if (partType === "tool") {
        const toolName = String(part.tool ?? "tool");
        const callId = String(part.callID ?? partId);
        const stateObj = (part.state as Record<string, unknown> | undefined) ?? {};
        const stateMeta = (stateObj.metadata as Record<string, unknown> | undefined) ?? {};
        const childSessionId =
          typeof stateMeta.sessionId === "string"
            ? stateMeta.sessionId
            : typeof stateMeta.sessionID === "string"
              ? stateMeta.sessionID
              : null;
        if (childSessionId) run.childSessionIds.add(childSessionId);
        const status = String(stateObj.status ?? "pending");
        const prevStatus = run.toolStates.get(callId);
        const targetId = ensureAssistantRow(conversationId, run);
        if (status === "running" && prevStatus !== "running") {
          promotePreToolContent(conversationId, run);
          run.toolStates.set(callId, "running");
          const item: WorkTimelineItem = {
            id: callId,
            kind: toolName === "task" ? "subagent" : "tool",
            tool: toolName,
            call_id: callId,
            title: stateObj.title ? String(stateObj.title) : null,
            args: stateObj.input ?? null,
            child_session_id: childSessionId,
            status: "running",
          };
          upsertTimelineItem(conversationId, run, item);
          emit(conversationId, {
            event: "tool.started",
            data: { tool: toolName, preview: stateObj.input ?? null, tool_call_id: callId, message_id: targetId },
          });
          return;
        }
        if ((status === "completed" || status === "error") && prevStatus !== status) {
          if (!prevStatus) {
            promotePreToolContent(conversationId, run);
          } else {
            completeOpenThinkingItems(run);
          }
          run.toolStates.set(callId, status);
          const timeObj = stateObj.time as Record<string, number> | undefined;
          const duration =
            timeObj && typeof timeObj.end === "number" && typeof timeObj.start === "number"
              ? Math.max(0, (timeObj.end - timeObj.start) / 1000)
              : null;
          const errorText = status === "error" ? String(stateObj.error ?? "工具执行失败") : null;
          const resultPreview = stateObj.output ?? stateObj.error ?? stateObj.title ?? null;
          const prevItem = run.timeline.find((entry) => entry.id === callId);
          const item: WorkTimelineItem = {
            id: callId,
            kind: toolName === "task" ? "subagent" : "tool",
            tool: toolName,
            call_id: callId,
            title: stateObj.title ? String(stateObj.title) : (prevItem?.title ?? null),
            args: stateObj.input ?? prevItem?.args ?? null,
            result: resultPreview,
            duration,
            error: errorText,
            child_session_id: childSessionId ?? prevItem?.child_session_id ?? null,
            status: errorText ? "failed" : "completed",
          };
          upsertTimelineItem(conversationId, run, item);
          emit(conversationId, {
            event: "tool.completed",
            data: {
              tool: toolName,
              tool_call_id: callId,
              preview: resultPreview,
              duration,
              error: errorText,
              message_id: targetId,
            },
          });
        }
        return;
      }
      if (partType === "subtask") {
        promotePreToolContent(conversationId, run);
        upsertTimelineItem(conversationId, run, {
          id: `subtask:${partId}`,
          kind: "subagent",
          tool: "task",
          title: String(part.description ?? part.agent ?? "子代理任务"),
          text: String(part.prompt ?? ""),
          status: "running",
        });
        return;
      }
      if (partType === "patch") {
        const files = Array.isArray(part.files) ? part.files.map(String).filter(Boolean) : [];
        if (files.length) {
          upsertTimelineItem(conversationId, run, {
            id: `patch:${partId}`,
            kind: "patch",
            title: `快照变更 ${files.length} 个文件`,
            files,
            status: "completed",
          });
        }
        return;
      }
      if (partType === "compaction") {
        upsertTimelineItem(conversationId, run, {
          id: `compact:${partId}`,
          kind: "compaction",
          title: part.auto ? "自动压缩上下文" : "压缩上下文",
          status: "completed",
        });
        return;
      }
      if (partType === "retry") {
        const attempt = Number(part.attempt ?? 1) || 1;
        upsertTimelineItem(conversationId, run, {
          id: `retry:${partId}`,
          kind: "retry",
          title: `模型调用重试（第 ${attempt} 次）`,
          attempt,
          error: part.error ? extractErrorText(part.error) : null,
          status: "running",
        });
        return;
      }
      return;
    }

    case "session.status": {
      const st = props.status as Record<string, unknown> | undefined;
      if (!st) return;
      if (st.type === "retry") {
        const retryState: WorkSessionRetryState = {
          attempt: Number(st.attempt ?? 1) || 1,
          message: String(st.message ?? "请求限流或网络波动，正在自动重试…"),
          next: Number(st.next ?? 0) || 0,
          action: (st.action as WorkSessionRetryState["action"]) ?? null,
        };
        run.retry = retryState;
        emit(conversationId, { event: "run.retry", data: { retry: retryState } });
      } else {
        if (run.retry) {
          run.retry = null;
          emit(conversationId, { event: "run.retry", data: { retry: null } });
        }
      }
      return;
    }

    case "session.diff": {
      const diffs = Array.isArray(props.diff) ? props.diff : [];
      emit(conversationId, { event: "session.diff", data: { diffs } });
      return;
    }

    case "session.compacted": {
      emit(conversationId, { event: "session.compacted", data: {} });
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
      enqueuePermission(conversationId, client, run, props);
      return;
    }

    case "permission.replied": {
      const requestId = String(props.requestID ?? props.id ?? "");
      if (requestId) removePendingControl(conversationId, run, requestId, "approval.resolved", { choice: props.reply });
      return;
    }

    case "question.asked": {
      enqueueQuestion(conversationId, run, props);
      return;
    }

    case "question.replied":
    case "question.rejected": {
      const requestId = String(props.requestID ?? props.id ?? "");
      if (requestId) removePendingControl(conversationId, run, requestId, "clarify.resolved");
      return;
    }

    case "session.error": {
      const errMsg = extractErrorText(props.error);
      finalizeRunStreams(conversationId, run);
      run.finished = true;
      run.pendingControls = [];
      const targetId =
        run.assistantId ??
        addMessage({ conversation_id: conversationId, role: "assistant", content: errMsg, status: "failed", run_id: run.runId }).id;
      const existing = getMessageRow(targetId)?.tool_payload ?? {};
      updateMessage(targetId, { status: "failed", content: run.content || errMsg, tool_payload: buildPersistedPayload(run, existing) });
      emit(conversationId, { event: "run.failed", data: { error: errMsg, output: run.content, timeline: run.timeline, message_id: targetId } });
      run.controller.abort();
      return;
    }

    case "session.idle": {
      if (!run.promptSent || run.pendingControls.length > 0) return;
      finalizeCompletedRun(conversationId, run);
      return;
    }

    default:
      return;
  }
}

export async function steerRun(conversationId: string, content: string): Promise<void> {
  const run = active.get(conversationId);
  if (!run) throw new Error("当前没有运行中的任务");
  const conv = getConversationMeta(conversationId);
  const model = await resolvePromptModel(conv?.model_ref);
  await new OpenCodeClient().promptAsync(run.sessionId, run.directory, {
    model,
    agent: conv?.agent_name ?? undefined,
    variant: conv?.variant ?? undefined,
    parts: [{ type: "text", text: content }],
  });
}

export async function stopRun(conversationId: string): Promise<void> {
  const run = active.get(conversationId);
  if (!run) return;
  finalizeRunStreams(conversationId, run);
  for (const item of run.timeline) {
    if (item.kind === "tool" && item.status === "running") {
      item.status = "failed";
      item.error = item.error ?? "已手动停止";
    }
  }
  if (!run.content.trim() && run.lastTextOutput.trim()) {
    run.content = run.lastTextOutput;
  }
  run.stopped = true;
  run.finished = true;
  run.pendingControls = [];
  run.controller.abort();
  try {
    await new OpenCodeClient().abortSession(run.sessionId, run.directory);
  } catch (err) {
    logger.warn("abort opencode session failed", err instanceof Error ? err.message : String(err));
  }
  if (run.assistantId) {
    const existing = getMessageRow(run.assistantId)?.tool_payload ?? {};
    updateMessage(run.assistantId, {
      status: "cancelled",
      content: run.content,
      tool_payload: buildPersistedPayload(run, existing),
    });
  }
  emit(conversationId, {
    event: "run.cancelled",
    data: { output: run.assistantId ? run.content : undefined, message_id: run.assistantId, timeline: run.timeline },
  });
  active.delete(conversationId);
}

export async function approveRun(
  conversationId: string,
  requestId: string,
  _generation: number,
  choice: WorkApprovalChoice,
  message?: string,
): Promise<void> {
  const run = active.get(conversationId);
  if (!run) throw new Error("当前没有等待审批的任务");
  const reqId = requestId || run.pendingControls.find((c) => c.kind === "approval")?.request_id || "";
  if (!reqId) throw new Error("缺少权限审批编号");
  const reply = choice === "deny" ? "reject" : choice === "always" ? "always" : "once";
  const client = new OpenCodeClient();
  await client.replyPermission(reqId, run.directory, reply, choice === "deny" ? message : undefined);
  removePendingControl(conversationId, run, reqId, "approval.resolved", { choice });
  if (choice === "always") {
    void reconcileRunState(conversationId, client, run);
  }
}

export async function clarifyRun(
  conversationId: string,
  requestId: string,
  _generation: number,
  answers: string | string[][],
): Promise<void> {
  const run = active.get(conversationId);
  if (!run) throw new Error("当前没有等待确认的任务");
  const reqId = requestId || run.pendingControls.find((c) => c.kind === "clarify")?.request_id || "";
  if (!reqId) throw new Error("缺少提问请求编号");
  const normalized: string[][] = Array.isArray(answers)
    ? answers.map((row) => (Array.isArray(row) ? row.map(String).filter(Boolean) : [String(row)]))
    : [[String(answers)]];
  await new OpenCodeClient().replyQuestion(reqId, run.directory, normalized);
  removePendingControl(conversationId, run, reqId, "clarify.resolved", { answers: normalized });
}

export async function rejectClarifyRun(conversationId: string, requestId: string): Promise<void> {
  const run = active.get(conversationId);
  if (!run) throw new Error("当前没有等待确认的任务");
  const reqId = requestId || run.pendingControls.find((c) => c.kind === "clarify")?.request_id || "";
  if (!reqId) throw new Error("缺少提问请求编号");
  await new OpenCodeClient().rejectQuestion(reqId, run.directory);
  removePendingControl(conversationId, run, reqId, "clarify.resolved", { rejected: true });
}

export async function forkConversation(conversationId: string, messageId?: string | null): Promise<WorkConversation> {
  const conv = getConversationMeta(conversationId);
  if (!conv) throw new Error("对话不存在");
  await ensureReady();
  const dir = safeWorkspaceDir(conv.workspace_path || getActiveWorkspacePath());
  const client = new OpenCodeClient();
  let newSessionId: string | null = null;
  if (conv.opencode_session_id) {
    const targetMsg = messageId ? getMessageRow(messageId) : null;
    const ocMsgId = typeof targetMsg?.tool_payload?.opencode_message_id === "string"
      ? targetMsg.tool_payload.opencode_message_id
      : null;
    newSessionId = await client.forkSession(conv.opencode_session_id, dir, ocMsgId);
  }
  const forked = createConversation(`${conv.title} · 分支`, conv.workspace_path, {
    opencode_session_id: newSessionId,
    model_ref: conv.model_ref,
    agent_name: conv.agent_name,
    variant: conv.variant,
  });
  copyMessagesUpTo(conversationId, forked.id, messageId);
  return forked;
}

export async function revertToMessage(conversationId: string, messageId: string): Promise<WorkConversationDetail> {
  const conv = getConversationMeta(conversationId);
  if (!conv) throw new Error("对话不存在");
  if (active.has(conversationId)) await stopRun(conversationId);
  const targetMsg = getMessageRow(messageId);
  if (!targetMsg || targetMsg.conversation_id !== conversationId) throw new Error("消息不存在");
  const ocMsgId = typeof targetMsg.tool_payload?.opencode_message_id === "string"
    ? targetMsg.tool_payload.opencode_message_id
    : null;
  if (conv.opencode_session_id && ocMsgId) {
    await ensureReady();
    const dir = safeWorkspaceDir(conv.workspace_path || getActiveWorkspacePath());
    await new OpenCodeClient().revertSession(conv.opencode_session_id, dir, ocMsgId);
  }
  markMessagesRevertedFrom(conversationId, messageId);
  const detail = getConversation(conversationId);
  if (!detail) throw new Error("对话不存在");
  return detail;
}

export async function unrevertConversation(conversationId: string): Promise<WorkConversationDetail> {
  const conv = getConversationMeta(conversationId);
  if (!conv) throw new Error("对话不存在");
  if (conv.opencode_session_id) {
    await ensureReady();
    const dir = safeWorkspaceDir(conv.workspace_path || getActiveWorkspacePath());
    await new OpenCodeClient().unrevertSession(conv.opencode_session_id, dir);
  }
  unrevertAllMessages(conversationId);
  const detail = getConversation(conversationId);
  if (!detail) throw new Error("对话不存在");
  return detail;
}

export async function compactConversation(conversationId: string, modelRef?: string | null): Promise<void> {
  const conv = getConversationMeta(conversationId);
  if (!conv) throw new Error("对话不存在");
  if (!conv.opencode_session_id) throw new Error("当前会话尚未初始化，暂无可压缩上下文");
  await ensureReady();
  const dir = safeWorkspaceDir(conv.workspace_path || getActiveWorkspacePath());
  const model = await resolvePromptModel(modelRef, conv.model_ref);
  if (!model) throw new Error("请先在设置或输入区指定一个模型后再执行上下文压缩");
  await new OpenCodeClient().summarizeSession(conv.opencode_session_id, dir, model);
  addMessage({
    conversation_id: conversationId,
    role: "assistant",
    content: "已完成当前会话上下文压缩总结（`/compact`），后续轮次将继续沿用精简后的上下文。",
    status: "completed",
  });
}

export async function initConversationAgents(conversationId: string, modelRef?: string | null): Promise<void> {
  const conv = getConversationMeta(conversationId);
  if (!conv) throw new Error("对话不存在");
  await ensureReady();
  const dir = safeWorkspaceDir(conv.workspace_path || getActiveWorkspacePath());
  const client = new OpenCodeClient();
  let sessionId = conv.opencode_session_id;
  if (!sessionId) {
    sessionId = await client.createSession(conv.title, dir);
    setOpenCodeSession(conversationId, sessionId);
  }
  const model = await resolvePromptModel(modelRef, conv.model_ref);
  if (!model) throw new Error("请先选择或配置默认模型后再生成 AGENTS.md");
  const syntheticMsgId = `msg_${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
  await client.initSession(sessionId, dir, {
    providerID: model.providerID,
    modelID: model.modelID,
    messageID: syntheticMsgId,
  });
  addMessage({
    conversation_id: conversationId,
    role: "assistant",
    content: "已触发项目 `AGENTS.md` 分析与初始化生成（`/init`），请稍后在右侧「文件」面板查看更新。",
    status: "completed",
  });
}

export async function getConversationDiff(conversationId: string): Promise<WorkSessionDiffItem[]> {
  const conv = getConversationMeta(conversationId);
  if (!conv?.opencode_session_id || !getStatus().running) return [];
  const dir = safeWorkspaceDir(conv.workspace_path || getActiveWorkspacePath());
  try {
    return await new OpenCodeClient().getSessionDiff(conv.opencode_session_id, dir);
  } catch {
    return [];
  }
}
