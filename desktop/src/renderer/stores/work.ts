import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { useCreditsStore } from "@web/stores/credits";
import { useRuntimeStore } from "./runtime";
import type {
  WorkActiveRunSnapshot,
  WorkAgentInfo,
  WorkApprovalChoice,
  WorkAttachment,
  WorkCommandInfo,
  WorkConversation,
  WorkConversationDetail,
  WorkEvent,
  WorkMessage,
  WorkSessionDiffItem,
  WorkSessionPrefsPatch,
  WorkSkillItem,
  WorkTokenUsage,
  WorkWorkspace,
  WorkspaceEntry,
  WorkspaceFileContent,
  WorkspaceGitStatus,
} from "@shared/work-types";

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

export interface PendingControl {
  kind: "approval" | "clarify";
  requestId: string;
  generation: number;
  tool: string | null;
  preview: unknown;
  choices: string[] | null;
}

export interface SubagentActivity {
  id: string;
  goal: string;
  status: string;
  summary?: string;
  toolCount?: number;
}

export interface WorkRunState {
  streaming: boolean;
  sending: boolean;
  error: string | null;
  pendingControls: PendingControl[];
  activeAssistantId: string | null;
  plan: Record<string, unknown> | null;
  subagents: SubagentActivity[];
  usage: WorkTokenUsage | null;
}

export interface WorkProjectGroup {
  key: string;
  name: string;
  path: string | null;
  conversations: WorkConversation[];
  runningCount: number;
  waitingCount: number;
}

export type WorkInspectorTab = "files" | "git" | "plan" | "runtime";

function emptyRunState(): WorkRunState {
  return {
    streaming: false,
    sending: false,
    error: null,
    pendingControls: [],
    activeAssistantId: null,
    plan: null,
    subagents: [],
    usage: null,
  };
}

function normalizePathKey(p: string | null | undefined): string {
  if (!p) return "__default__";
  return p.replace(/[\\/]+$/, "").toLowerCase();
}

export const useWorkStore = defineStore("work", () => {
  const conversations = ref<WorkConversation[]>([]);
  const current = ref<WorkConversationDetail | null>(null);
  const detailCache = ref<Record<string, WorkConversationDetail>>({});
  const runsByConversation = ref<Record<string, WorkRunState>>({});
  const unreadCompletedIds = ref<Set<string>>(new Set());

  // Workspace & Explorer state
  const workspaces = ref<WorkWorkspace[]>([]);
  const activeWorkspace = ref<WorkWorkspace | null>(null);
  const childrenByDir = ref<Record<string, WorkspaceEntry[]>>({});
  const expandedDirs = ref<Set<string>>(new Set());
  const treeLoading = ref(false);
  const previewFile = ref<WorkspaceFileContent | null>(null);
  const previewLoading = ref(false);
  const previewDiff = ref<{ path: string; diff: string } | null>(null);
  const gitStatus = ref<WorkspaceGitStatus>({ is_repo: false, branch: null, changes: [] });
  const gitLoading = ref(false);
  const sessionDiffs = ref<WorkSessionDiffItem[]>([]);
  const vcsBranch = ref<string | null>(null);

  // OpenCode instance metadata for active project
  const skills = ref<WorkSkillItem[]>([]);
  const agents = ref<WorkAgentInfo[]>([]);
  const commands = ref<WorkCommandInfo[]>([]);

  const inspectorOpen = ref(
    typeof window !== "undefined" ? window.localStorage.getItem("whitz_work_inspector_open") !== "0" : true,
  );
  const inspectorTab = ref<WorkInspectorTab>("files");

  let started = false;

  const activeConversationId = computed(() => current.value?.conversation.id ?? null);
  const messages = computed<WorkMessage[]>(() => current.value?.messages ?? []);

  const currentRun = computed<WorkRunState>(() => {
    const id = activeConversationId.value;
    if (!id) return emptyRunState();
    return runsByConversation.value[id] ?? emptyRunState();
  });

  const streaming = computed(() => currentRun.value.streaming);
  const sending = computed(() => currentRun.value.sending);
  const error = computed<string | null>({
    get: () => currentRun.value.error,
    set: (val) => {
      const id = activeConversationId.value;
      if (!id) return;
      ensureRun(id).error = val;
    },
  });
  const pendingControl = computed(() => currentRun.value.pendingControls[0] ?? null);
  const pendingCount = computed(() => currentRun.value.pendingControls.length);
  const activeAssistantId = computed(() => currentRun.value.activeAssistantId);
  const plan = computed(() => currentRun.value.plan);
  const subagents = computed(() => currentRun.value.subagents);
  const usage = computed(() => currentRun.value.usage);

  const primaryAgents = computed(() => agents.value.filter((a) => a.mode === "primary" || a.mode === "all"));
  const subagentDefs = computed(() => agents.value.filter((a) => a.mode === "subagent" || a.mode === "all"));

  const projectGroups = computed<WorkProjectGroup[]>(() => {
    const groupMap = new Map<string, WorkProjectGroup>();

    for (const ws of workspaces.value) {
      const key = normalizePathKey(ws.path);
      if (!groupMap.has(key)) {
        groupMap.set(key, {
          key,
          name: ws.name,
          path: ws.path,
          conversations: [],
          runningCount: 0,
          waitingCount: 0,
        });
      }
    }

    for (const conv of conversations.value) {
      const key = normalizePathKey(conv.workspace_path);
      let group = groupMap.get(key);
      if (!group) {
        const rawPath = conv.workspace_path;
        const name = rawPath ? rawPath.split(/[\\/]/).filter(Boolean).pop() || rawPath : "默认工作区";
        group = {
          key,
          name,
          path: rawPath,
          conversations: [],
          runningCount: 0,
          waitingCount: 0,
        };
        groupMap.set(key, group);
      }
      group.conversations.push(conv);
      const rs = runsByConversation.value[conv.id];
      if (rs?.pendingControls.length) group.waitingCount += 1;
      else if (rs?.streaming) group.runningCount += 1;
    }

    const groups = Array.from(groupMap.values());
    for (const g of groups) {
      g.conversations.sort((a, b) => {
        if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1;
        return b.updated_at.localeCompare(a.updated_at);
      });
    }

    groups.sort((a, b) => {
      if (a.path === null && b.path !== null) return 1;
      if (b.path === null && a.path !== null) return -1;
      const aLatest = a.conversations[0]?.updated_at ?? "";
      const bLatest = b.conversations[0]?.updated_at ?? "";
      if (aLatest && bLatest && aLatest !== bLatest) return bLatest.localeCompare(aLatest);
      if (aLatest && !bLatest) return -1;
      if (!aLatest && bLatest) return 1;
      return a.name.localeCompare(b.name);
    });
    return groups;
  });

  function ensureRun(conversationId: string): WorkRunState {
    if (!runsByConversation.value[conversationId]) {
      runsByConversation.value[conversationId] = emptyRunState();
    }
    return runsByConversation.value[conversationId];
  }

  function isConversationRunning(conversationId: string): boolean {
    return Boolean(runsByConversation.value[conversationId]?.streaming);
  }

  function isConversationWaiting(conversationId: string): boolean {
    return Boolean(runsByConversation.value[conversationId]?.pendingControls.length);
  }

  function hasUnreadDone(conversationId: string): boolean {
    return unreadCompletedIds.value.has(conversationId);
  }

  function setInspectorOpen(open: boolean) {
    inspectorOpen.value = open;
    try {
      window.localStorage.setItem("whitz_work_inspector_open", open ? "1" : "0");
    } catch {
      /* ignore */
    }
  }

  function bindEvents() {
    if (started) return;
    started = true;
    bridge().onWorkEvent(({ conversationId, event }) => {
      handleEvent(conversationId, event);
    });
  }

  function toPendingControl(raw: {
    kind: "approval" | "clarify";
    request_id: string;
    execution_generation?: number;
    tool: string | null;
    preview: unknown;
    choices?: string[] | null;
  }): PendingControl {
    return {
      kind: raw.kind,
      requestId: raw.request_id,
      generation: Number(raw.execution_generation ?? 1),
      tool: raw.tool ? String(raw.tool) : null,
      preview: raw.preview ?? null,
      choices: Array.isArray(raw.choices) ? raw.choices : null,
    };
  }

  function applyActiveSnapshot(snap: WorkActiveRunSnapshot) {
    const run = ensureRun(snap.conversation_id);
    run.streaming = true;
    run.activeAssistantId = snap.assistant_id || null;
    run.plan = snap.plan ?? run.plan;
    run.usage = snap.usage ?? run.usage;
    if (Array.isArray(snap.pending_controls)) {
      run.pendingControls = snap.pending_controls.map(toPendingControl);
    } else if (snap.pending_control) {
      run.pendingControls = [toPendingControl(snap.pending_control)];
    } else {
      run.pendingControls = [];
    }
  }

  async function syncActiveRuns() {
    try {
      const snapshots = await bridge().work.activeRuns();
      const liveIds = new Set(snapshots.map((s) => s.conversation_id));
      for (const snap of snapshots) applyActiveSnapshot(snap);
      for (const [cid, rs] of Object.entries(runsByConversation.value)) {
        if (rs.streaming && !rs.sending && !liveIds.has(cid)) {
          rs.streaming = false;
          rs.pendingControls = [];
        }
      }
    } catch {
      /* ignore */
    }
  }

  async function loadProjectMetadata(workspacePath?: string | null) {
    const dir = workspacePath ?? activeWorkspace.value?.path ?? null;
    const [skillList, agentList, cmdList, vcs] = await Promise.all([
      bridge().work.skills(dir).catch(() => []),
      bridge().work.agents(dir).catch(() => []),
      bridge().work.commands(dir).catch(() => []),
      bridge().opencode.vcsInfo(dir).catch(() => ({ branch: null })),
    ]);
    skills.value = skillList;
    if (agentList.length) agents.value = agentList;
    commands.value = cmdList;
    vcsBranch.value = vcs.branch;
  }

  async function loadWorkspaceState() {
    const api = bridge();
    const [list, active] = await Promise.all([api.workspace.list(), api.workspace.active()]);
    workspaces.value = list;
    activeWorkspace.value = active;
    if (active) {
      await Promise.all([loadTree(""), refreshGitStatus(), loadProjectMetadata(active.path)]);
    } else {
      childrenByDir.value = {};
      expandedDirs.value = new Set();
      gitStatus.value = { is_repo: false, branch: null, changes: [] };
      previewFile.value = null;
      previewDiff.value = null;
      await loadProjectMetadata(null);
    }
  }

  async function loadList() {
    conversations.value = await bridge().work.list();
  }

  async function pickWorkspace() {
    const picked = await bridge().workspace.pick();
    if (!picked) return null;
    await afterWorkspaceSwitch(picked);
    return picked;
  }

  async function selectWorkspace(workspacePath: string) {
    const selected = await bridge().workspace.select(workspacePath);
    if (!selected) return null;
    await afterWorkspaceSwitch(selected);
    return selected;
  }

  async function afterWorkspaceSwitch(ws: WorkWorkspace) {
    activeWorkspace.value = ws;
    workspaces.value = await bridge().workspace.list();
    previewFile.value = null;
    previewDiff.value = null;
    expandedDirs.value = new Set();
    await Promise.all([loadTree(""), refreshGitStatus(), loadProjectMetadata(ws.path), loadList()]);
  }

  async function removeWorkspace(workspacePath: string) {
    await bridge().workspace.remove(workspacePath);
    await loadWorkspaceState();
    await loadList();
  }

  async function openInExplorer(targetPath?: string) {
    await bridge().workspace.openExplorer(targetPath);
  }

  async function loadTree(relDir = "") {
    if (!activeWorkspace.value) {
      childrenByDir.value = {};
      return;
    }
    if (relDir === "") treeLoading.value = true;
    try {
      const entries = await bridge().workspace.tree(relDir);
      childrenByDir.value = { ...childrenByDir.value, [relDir]: entries };
    } finally {
      if (relDir === "") treeLoading.value = false;
    }
  }

  async function toggleDir(relDir: string) {
    const next = new Set(expandedDirs.value);
    if (next.has(relDir)) {
      next.delete(relDir);
      expandedDirs.value = next;
      return;
    }
    next.add(relDir);
    expandedDirs.value = next;
    await loadTree(relDir);
  }

  async function openFilePreview(relPath: string) {
    previewLoading.value = true;
    previewDiff.value = null;
    setInspectorOpen(true);
    inspectorTab.value = "files";
    try {
      previewFile.value = await bridge().workspace.read(relPath);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "无法读取文件";
    } finally {
      previewLoading.value = false;
    }
  }

  async function openDiffPreview(relPath?: string) {
    setInspectorOpen(true);
    inspectorTab.value = "git";
    previewFile.value = null;
    const diff = await bridge().workspace.gitDiff(relPath);
    previewDiff.value = { path: relPath ?? "全部变更", diff };
  }

  async function refreshGitStatus() {
    if (!activeWorkspace.value) {
      gitStatus.value = { is_repo: false, branch: null, changes: [] };
      return;
    }
    gitLoading.value = true;
    try {
      gitStatus.value = await bridge().workspace.gitStatus();
    } catch {
      gitStatus.value = { is_repo: false, branch: null, changes: [] };
    } finally {
      gitLoading.value = false;
    }
  }

  async function refreshSessionDiff(conversationId?: string) {
    const id = conversationId ?? activeConversationId.value;
    if (!id) {
      sessionDiffs.value = [];
      return;
    }
    try {
      sessionDiffs.value = await bridge().work.sessionDiff(id);
    } catch {
      sessionDiffs.value = [];
    }
  }

  async function refreshWorkspace() {
    if (!activeWorkspace.value) return;
    const dirs = ["", ...Array.from(expandedDirs.value)];
    await Promise.all([
      ...dirs.map((d) => loadTree(d).catch(() => undefined)),
      refreshGitStatus(),
      refreshSessionDiff(),
    ]);
    if (previewFile.value) {
      try {
        previewFile.value = await bridge().workspace.read(previewFile.value.rel_path);
      } catch {
        previewFile.value = null;
      }
    }
  }

  async function loadSkills() {
    skills.value = await bridge().work.skills(activeWorkspace.value?.path ?? null).catch(() => []);
  }

  async function create(title?: string, workspacePath?: string | null) {
    const targetPath = workspacePath !== undefined ? workspacePath : (activeWorkspace.value?.path ?? null);
    const conversation = await bridge().work.create(title, targetPath);
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
    const nextUnread = new Set(unreadCompletedIds.value);
    if (nextUnread.delete(id)) unreadCompletedIds.value = nextUnread;

    const cached = detailCache.value[id];
    if (cached) {
      current.value = cached;
    }

    const [detail, snapshots] = await Promise.all([
      bridge().work.get(id),
      bridge().work.activeRuns().catch(() => [] as WorkActiveRunSnapshot[]),
    ]);
    detailCache.value[id] = detail;
    current.value = detail;

    const targetWs = detail.conversation.workspace_path;
    if (targetWs && normalizePathKey(targetWs) !== normalizePathKey(activeWorkspace.value?.path)) {
      const selected = await bridge().workspace.select(targetWs).catch(() => null);
      if (selected) {
        activeWorkspace.value = selected;
        previewFile.value = null;
        previewDiff.value = null;
        expandedDirs.value = new Set();
        void Promise.all([loadTree(""), refreshGitStatus(), loadProjectMetadata(selected.path)]);
      }
    }

    const run = ensureRun(id);
    run.error = null;
    const liveSnap = snapshots.find((s) => s.conversation_id === id);
    if (liveSnap) {
      applyActiveSnapshot(liveSnap);
    } else {
      const waiting = [...detail.messages].reverse().find((m) => m.status === "waiting" || m.status === "streaming");
      run.activeAssistantId = waiting?.id ?? null;
      run.streaming = Boolean(waiting);
      run.pendingControls = [];
    }

    const lastPlan = [...detail.messages].reverse().find((m) => m.tool_payload?.plan)?.tool_payload?.plan;
    run.plan = (lastPlan as Record<string, unknown>) ?? run.plan ?? null;
    const lastUsage = [...detail.messages].reverse().find((m) => m.tool_payload?.usage)?.tool_payload?.usage;
    if (lastUsage) run.usage = lastUsage as WorkTokenUsage;

    void refreshSessionDiff(id);
    return detail;
  }

  async function setSessionPrefs(prefs: WorkSessionPrefsPatch) {
    if (!current.value) return;
    const updated = await bridge().work.setPrefs(current.value.conversation.id, prefs);
    current.value.conversation = updated;
    const idx = conversations.value.findIndex((c) => c.id === updated.id);
    if (idx >= 0) conversations.value[idx] = updated;
  }

  async function rename(id: string, title: string) {
    await bridge().work.rename(id, title);
    await loadList();
    if (current.value?.conversation.id === id) current.value.conversation.title = title;
  }

  async function pin(id: string, isPinned: boolean) {
    await bridge().work.pin(id, isPinned);
    await loadList();
    if (current.value?.conversation.id === id) current.value.conversation.is_pinned = isPinned;
  }

  async function remove(id: string) {
    await bridge().work.delete(id);
    delete detailCache.value[id];
    delete runsByConversation.value[id];
    if (current.value?.conversation.id === id) current.value = null;
    await loadList();
  }

  function getDetailTarget(conversationId: string): WorkConversationDetail | null {
    if (current.value?.conversation.id === conversationId) return current.value;
    return detailCache.value[conversationId] ?? null;
  }

  function patchActive(conversationId: string, patch: Partial<WorkMessage>) {
    const detail = getDetailTarget(conversationId);
    const run = runsByConversation.value[conversationId];
    if (!detail) return;
    const message =
      (run?.activeAssistantId ? detail.messages.find((m) => m.id === run.activeAssistantId) : undefined) ??
      [...detail.messages].reverse().find((m) => m.role === "assistant");
    if (!message) return;
    Object.assign(message, patch);
  }

  function reasoningBlocks(conversationId: string): Array<Record<string, unknown>> {
    const detail = getDetailTarget(conversationId);
    const run = runsByConversation.value[conversationId];
    if (!detail || !run) return [];
    const message = detail.messages.find((m) => m.id === run.activeAssistantId);
    const blocks = message?.tool_payload?.reasoning;
    return Array.isArray(blocks) ? (blocks as Array<Record<string, unknown>>) : [];
  }

  function saveReasoning(conversationId: string, blocks: Array<Record<string, unknown>>) {
    const detail = getDetailTarget(conversationId);
    const run = runsByConversation.value[conversationId];
    if (!detail || !run) return;
    const message = detail.messages.find((m) => m.id === run.activeAssistantId);
    if (!message) return;
    message.tool_payload = { ...(message.tool_payload ?? {}), reasoning: blocks, plan: run.plan };
  }

  function prepareOptimisticMessages(
    conversationId: string,
    userText: string,
    payload: Record<string, unknown> | null,
  ) {
    const run = ensureRun(conversationId);
    run.error = null;
    run.pendingControls = [];
    run.plan = null;
    run.subagents = [];

    const userMessage: WorkMessage = {
      id: uid(),
      conversation_id: conversationId,
      role: "user",
      content: userText,
      status: "completed",
      tool_name: null,
      tool_payload: payload,
      run_id: null,
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
      run_id: null,
      created_at: new Date().toISOString(),
    };
    const detail = getDetailTarget(conversationId);
    if (detail) {
      detail.messages.push(userMessage, assistantMessage);
    }
    run.activeAssistantId = assistantMessage.id;
    run.streaming = true;
    run.sending = true;
    return { run, assistantMessage };
  }

  async function send(
    content: string,
    options?: {
      skillNames?: string[];
      attachments?: WorkAttachment[];
      modelRef?: string | null;
      agentName?: string | null;
      variant?: string | null;
    },
  ) {
    const text = content.trim();
    if (!text) return;
    await ensureConversation();
    if (!current.value) return;
    const conversationId = current.value.conversation.id;
    const existingRun = ensureRun(conversationId);
    if (existingRun.sending) return;

    const payload: Record<string, unknown> | null =
      options?.attachments?.length || options?.skillNames?.length || options?.modelRef || options?.agentName
        ? {
            ...(options?.attachments?.length ? { attachments: options.attachments } : {}),
            ...(options?.skillNames?.length ? { skills: options.skillNames } : {}),
            ...(options?.modelRef ? { model_ref: options.modelRef } : {}),
            ...(options?.agentName ? { agent: options.agentName } : {}),
            ...(options?.variant ? { variant: options.variant } : {}),
          }
        : null;

    const { run, assistantMessage } = prepareOptimisticMessages(conversationId, text, payload);
    try {
      await bridge().work.send(conversationId, text, options);
      await loadList();
    } catch (err) {
      run.error = err instanceof Error ? err.message : "发送失败";
      assistantMessage.status = "failed";
      run.streaming = false;
    } finally {
      run.sending = false;
    }
  }

  async function runSlashCommand(
    command: string,
    args: string,
    options?: { modelRef?: string | null; agentName?: string | null; variant?: string | null },
  ) {
    await ensureConversation();
    if (!current.value) return;
    const conversationId = current.value.conversation.id;
    const cleanCmd = command.replace(/^\/+/, "").trim();
    const display = args.trim() ? `/${cleanCmd} ${args.trim()}` : `/${cleanCmd}`;
    const { run, assistantMessage } = prepareOptimisticMessages(conversationId, display, null);
    try {
      await bridge().work.runCommand(conversationId, cleanCmd, args, options);
      await loadList();
    } catch (err) {
      run.error = err instanceof Error ? err.message : "命令执行失败";
      assistantMessage.status = "failed";
      run.streaming = false;
    } finally {
      run.sending = false;
    }
  }

  async function runShellCommand(
    command: string,
    options?: { agentName?: string | null; modelRef?: string | null },
  ) {
    await ensureConversation();
    if (!current.value) return;
    const conversationId = current.value.conversation.id;
    const clean = command.replace(/^!+/, "").trim();
    const { run, assistantMessage } = prepareOptimisticMessages(conversationId, `! ${clean}`, null);
    try {
      await bridge().work.runShell(conversationId, clean, options);
      await loadList();
    } catch (err) {
      run.error = err instanceof Error ? err.message : "终端命令执行失败";
      assistantMessage.status = "failed";
      run.streaming = false;
    } finally {
      run.sending = false;
    }
  }

  async function fork(messageId?: string | null) {
    if (!current.value) return null;
    const forked = await bridge().work.fork(current.value.conversation.id, messageId);
    await loadList();
    await select(forked.id);
    return forked;
  }

  async function revert(messageId: string) {
    if (!current.value) return null;
    const id = current.value.conversation.id;
    const detail = await bridge().work.revert(id, messageId);
    detailCache.value[id] = detail;
    current.value = detail;
    const run = ensureRun(id);
    run.streaming = false;
    run.pendingControls = [];
    void refreshWorkspace();
    return detail;
  }

  async function unrevert() {
    if (!current.value) return null;
    const id = current.value.conversation.id;
    const detail = await bridge().work.unrevert(id);
    detailCache.value[id] = detail;
    current.value = detail;
    void refreshWorkspace();
    return detail;
  }

  async function compact(modelRef?: string | null) {
    if (!current.value) return;
    const id = current.value.conversation.id;
    await bridge().work.compact(id, modelRef);
    await refreshConversation(id);
  }

  async function initAgentsMd(modelRef?: string | null) {
    await ensureConversation();
    if (!current.value) return;
    const id = current.value.conversation.id;
    await bridge().work.initAgents(id, modelRef);
    await refreshConversation(id);
    await refreshWorkspace();
  }

  async function steer(content: string) {
    if (!current.value || !streaming.value) return;
    const trimmed = content.trim();
    if (!trimmed) return;
    await bridge().work.steer(current.value.conversation.id, trimmed);
    current.value.messages.push({
      id: uid(),
      conversation_id: current.value.conversation.id,
      role: "user",
      content: `[引导] ${trimmed}`,
      status: "completed",
      tool_name: null,
      tool_payload: null,
      run_id: null,
      created_at: new Date().toISOString(),
    });
  }

  function handleEvent(conversationId: string, event: WorkEvent) {
    const run = ensureRun(conversationId);
    const detail = getDetailTarget(conversationId);
    const data = event.data;

    switch (event.event) {
      case "message.created": {
        if (data.is_continuation && typeof data.assistant_message_id === "string") {
          const nextId = data.assistant_message_id;
          run.activeAssistantId = nextId;
          if (detail && !detail.messages.some((m) => m.id === nextId)) {
            detail.messages.push({
              id: nextId,
              conversation_id: conversationId,
              role: "assistant",
              content: "",
              status: "streaming",
              tool_name: null,
              tool_payload: { reasoning: [] },
              run_id: null,
              created_at: new Date().toISOString(),
            });
          }
          return;
        }
        if (detail) {
          const tempUser = [...detail.messages].reverse().find((m) => m.role === "user" && m.id.startsWith("temp-"));
          if (tempUser && typeof data.user_message_id === "string") tempUser.id = data.user_message_id;
          const assistant = detail.messages.find((m) => m.id === run.activeAssistantId);
          if (assistant && typeof data.assistant_message_id === "string") {
            assistant.id = data.assistant_message_id;
            run.activeAssistantId = data.assistant_message_id;
          }
        } else if (typeof data.assistant_message_id === "string") {
          run.activeAssistantId = data.assistant_message_id;
        }
        return;
      }
      case "message.removed": {
        const targetId = typeof data.message_id === "string" ? data.message_id : "";
        if (detail && targetId) {
          detail.messages = detail.messages.filter((m) => m.id !== targetId);
        }
        if (run.activeAssistantId === targetId) run.activeAssistantId = null;
        return;
      }
      case "segment.completed": {
        const targetId = typeof data.message_id === "string" ? data.message_id : "";
        const msg = targetId ? detail?.messages.find((m) => m.id === targetId) : undefined;
        if (msg) msg.status = "completed";
        return;
      }
      case "run.started": {
        run.streaming = true;
        const assistant = detail?.messages.find((m) => m.id === run.activeAssistantId);
        if (assistant && typeof data.run_id === "string") assistant.run_id = data.run_id;
        return;
      }
      case "message.delta": {
        const text = String(data.text ?? "");
        const targetId = typeof data.message_id === "string" ? data.message_id : run.activeAssistantId;
        const assistant = targetId ? detail?.messages.find((m) => m.id === targetId) : undefined;
        if (assistant) assistant.content += text;
        return;
      }
      case "reasoning.delta":
      case "reasoning.block": {
        const text = String(data.text ?? data.delta ?? "");
        const targetId = typeof data.message_id === "string" ? data.message_id : run.activeAssistantId;
        if (targetId) run.activeAssistantId = targetId;
        const blocks = reasoningBlocks(conversationId);
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
        saveReasoning(conversationId, blocks);
        return;
      }
      case "commentary": {
        const text = String(data.text ?? "").trim();
        if (!text) return;
        const blocks = reasoningBlocks(conversationId);
        const last = blocks[blocks.length - 1];
        if (last) last.content = `${String(last.content ?? "")}\n\n${text}`.trim();
        else blocks.push({ step: data.step ?? null, title: data.title ?? "", text: "", content: text, tools: [] });
        saveReasoning(conversationId, blocks);
        return;
      }
      case "tool.started": {
        if (!detail) return;
        detail.messages.push({
          id: String(data.message_id ?? uid()),
          conversation_id: conversationId,
          role: "tool",
          content: "",
          status: "running",
          tool_name: String(data.tool ?? "tool"),
          tool_payload: {
            args: data.preview,
            tool_call_id: data.tool_call_id ?? null,
            status: "running",
          },
          run_id: null,
          created_at: new Date().toISOString(),
        });
        return;
      }
      case "tool.completed": {
        const message = detail?.messages.find((m) => m.id === data.message_id);
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
        if (
          conversationId === activeConversationId.value &&
          ["write", "edit", "multiedit", "apply_patch", "bash", "write_file", "patch", "terminal", "execute_code"].includes(
            String(data.tool ?? ""),
          )
        ) {
          void refreshWorkspace();
        }
        return;
      }
      case "subagent.started": {
        const sid = String(data.subagent_id ?? data.delegation_id ?? uid());
        run.subagents = [...run.subagents, { id: sid, goal: String(data.goal ?? "子任务"), status: "running", toolCount: 0 }];
        return;
      }
      case "subagent.progress": {
        const sid = String(data.subagent_id ?? data.delegation_id ?? "");
        const item = run.subagents.find((s) => s.id === sid);
        if (item) {
          if (typeof data.tool_count === "number") item.toolCount = data.tool_count;
          if (typeof data.status === "string") item.status = data.status;
        }
        return;
      }
      case "subagent.completed": {
        const sid = String(data.subagent_id ?? data.delegation_id ?? "");
        const item = run.subagents.find((s) => s.id === sid);
        if (item) {
          item.status = String(data.status ?? "completed");
          if (typeof data.summary === "string") item.summary = data.summary;
        }
        return;
      }
      case "plan.updated": {
        run.plan = data as Record<string, unknown>;
        const assistant = detail?.messages.find((m) => m.id === run.activeAssistantId);
        if (assistant) assistant.tool_payload = { ...(assistant.tool_payload ?? {}), plan: run.plan };
        return;
      }
      case "usage.updated": {
        if (data.usage && typeof data.usage === "object") {
          run.usage = data.usage as WorkTokenUsage;
        }
        return;
      }
      case "approval.request":
      case "clarify.request": {
        if (Array.isArray(data.pending_controls)) {
          run.pendingControls = (data.pending_controls as any[]).map(toPendingControl);
        } else {
          const item = toPendingControl({
            kind: event.event === "approval.request" ? "approval" : "clarify",
            request_id: String(data.request_id ?? ""),
            execution_generation: Number(data.execution_generation ?? 1),
            tool: data.tool ? String(data.tool) : null,
            preview: data.preview ?? null,
            choices: Array.isArray(data.choices) ? (data.choices as string[]) : null,
          });
          if (item.requestId && !run.pendingControls.some((c) => c.requestId === item.requestId)) {
            run.pendingControls = [...run.pendingControls, item];
          }
        }
        patchActive(conversationId, { status: "waiting" });
        return;
      }
      case "approval.resolved":
      case "clarify.resolved": {
        if (Array.isArray(data.pending_controls)) {
          run.pendingControls = (data.pending_controls as any[]).map(toPendingControl);
        } else if (typeof data.request_id === "string") {
          run.pendingControls = run.pendingControls.filter((c) => c.requestId !== data.request_id);
        } else {
          run.pendingControls = run.pendingControls.slice(1);
        }
        if (run.pendingControls.length === 0) {
          patchActive(conversationId, { status: "streaming" });
        }
        return;
      }
      case "run.completed":
      case "run.failed":
      case "run.cancelled":
      case "run.interrupted": {
        const status =
          event.event === "run.completed" ? "completed" : event.event === "run.failed" ? "failed" : "cancelled";
        const targetId = typeof data.message_id === "string" ? data.message_id : null;
        if (targetId || typeof data.output === "string") {
          const targetMsg = targetId ? detail?.messages.find((m) => m.id === targetId) : undefined;
          if (targetMsg) {
            targetMsg.status = status;
            if (typeof data.output === "string") targetMsg.content = data.output;
          } else {
            patchActive(conversationId, { status, content: typeof data.output === "string" ? data.output : undefined });
          }
        }
        if (event.event === "run.failed" && data.error) {
          run.error = typeof data.error === "string" ? data.error : "任务执行失败";
        }
        run.streaming = false;
        run.pendingControls = [];

        if (conversationId !== activeConversationId.value && event.event === "run.completed") {
          const next = new Set(unreadCompletedIds.value);
          next.add(conversationId);
          unreadCompletedIds.value = next;
        }

        void refreshConversation(conversationId);
        if (conversationId === activeConversationId.value) {
          void refreshWorkspace();
        }
        const rt = useRuntimeStore();
        const usesWhitz =
          rt.settings?.model.mode === "builtin" ||
          Boolean(rt.opencodeConfig?.default_model?.startsWith("whitz/")) ||
          Boolean(detail?.conversation.model_ref?.startsWith("whitz/"));
        if (usesWhitz) {
          void useCreditsStore().fetch().catch(() => undefined);
        }
        return;
      }
      case "error": {
        run.error = String(data.detail ?? "发生错误");
        run.streaming = false;
        patchActive(conversationId, { status: "failed" });
        return;
      }
      default:
        return;
    }
  }

  async function refreshConversation(conversationId: string) {
    try {
      const detail = await bridge().work.get(conversationId);
      detailCache.value[conversationId] = detail;
      if (current.value?.conversation.id === conversationId) {
        current.value = detail;
        const lastAssistant = [...detail.messages].reverse().find((m) => m.role === "assistant");
        ensureRun(conversationId).activeAssistantId = lastAssistant?.id ?? null;
      }
      await loadList();
    } catch {
      /* ignore */
    }
  }

  async function refreshCurrent() {
    if (!current.value) return;
    await refreshConversation(current.value.conversation.id);
  }

  async function stop() {
    if (!current.value) return;
    await bridge().work.stop(current.value.conversation.id);
  }

  async function approve(choice: WorkApprovalChoice) {
    if (!current.value || !pendingControl.value) return;
    const cid = current.value.conversation.id;
    const control = pendingControl.value;
    await bridge().work.approve(cid, control.requestId, control.generation, choice);
    const run = ensureRun(cid);
    run.pendingControls = run.pendingControls.filter((c) => c.requestId !== control.requestId);
    if (run.pendingControls.length === 0) {
      patchActive(cid, { status: "streaming" });
    }
  }

  async function clarify(answer: string) {
    if (!current.value || !pendingControl.value) return;
    const cid = current.value.conversation.id;
    const control = pendingControl.value;
    await bridge().work.clarify(cid, control.requestId, control.generation, answer);
    const run = ensureRun(cid);
    run.pendingControls = run.pendingControls.filter((c) => c.requestId !== control.requestId);
    if (run.pendingControls.length === 0) {
      patchActive(cid, { status: "streaming" });
    }
  }

  function reset() {
    current.value = null;
    conversations.value = [];
    detailCache.value = {};
    runsByConversation.value = {};
    unreadCompletedIds.value = new Set();
  }

  return {
    conversations,
    current,
    messages,
    streaming,
    sending,
    error,
    pendingControl,
    pendingCount,
    plan,
    subagents,
    usage,
    activeAssistantId,
    activeConversationId,
    runsByConversation,
    projectGroups,
    workspaces,
    activeWorkspace,
    childrenByDir,
    expandedDirs,
    treeLoading,
    previewFile,
    previewLoading,
    previewDiff,
    gitStatus,
    gitLoading,
    sessionDiffs,
    vcsBranch,
    skills,
    agents,
    primaryAgents,
    subagentDefs,
    commands,
    inspectorOpen,
    inspectorTab,
    isConversationRunning,
    isConversationWaiting,
    hasUnreadDone,
    setInspectorOpen,
    bindEvents,
    syncActiveRuns,
    loadWorkspaceState,
    loadProjectMetadata,
    loadList,
    pickWorkspace,
    selectWorkspace,
    removeWorkspace,
    openInExplorer,
    loadTree,
    toggleDir,
    openFilePreview,
    openDiffPreview,
    refreshGitStatus,
    refreshSessionDiff,
    refreshWorkspace,
    loadSkills,
    create,
    select,
    setSessionPrefs,
    rename,
    pin,
    remove,
    send,
    runSlashCommand,
    runShellCommand,
    fork,
    revert,
    unrevert,
    compact,
    initAgentsMd,
    steer,
    stop,
    approve,
    clarify,
    reset,
  };
});
