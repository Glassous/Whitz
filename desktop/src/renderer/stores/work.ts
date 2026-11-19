import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { useCreditsStore } from "@web/stores/credits";
import { useRuntimeStore } from "./runtime";
import type {
  WorkApprovalChoice,
  WorkAttachment,
  WorkConversation,
  WorkConversationDetail,
  WorkEvent,
  WorkMessage,
  WorkSkillItem,
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

interface PendingControl {
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

export type WorkInspectorTab = "files" | "git" | "plan" | "runtime";

export const useWorkStore = defineStore("work", () => {
  const conversations = ref<WorkConversation[]>([]);
  const current = ref<WorkConversationDetail | null>(null);
  const streaming = ref(false);
  const sending = ref(false);
  const error = ref<string | null>(null);
  const pendingControl = ref<PendingControl | null>(null);
  const activeAssistantId = ref<string | null>(null);
  const plan = ref<Record<string, unknown> | null>(null);
  const subagents = ref<SubagentActivity[]>([]);

  // Workspace & Explorer state
  const workspaces = ref<WorkWorkspace[]>([]);
  const activeWorkspace = ref<WorkWorkspace | null>(null);
  const showAllWorkspaces = ref(false);
  const childrenByDir = ref<Record<string, WorkspaceEntry[]>>({});
  const expandedDirs = ref<Set<string>>(new Set());
  const treeLoading = ref(false);
  const previewFile = ref<WorkspaceFileContent | null>(null);
  const previewLoading = ref(false);
  const previewDiff = ref<{ path: string; diff: string } | null>(null);
  const gitStatus = ref<WorkspaceGitStatus>({ is_repo: false, branch: null, changes: [] });
  const gitLoading = ref(false);
  const skills = ref<WorkSkillItem[]>([]);
  const inspectorOpen = ref(
    typeof window !== "undefined" ? window.localStorage.getItem("whitz_work_inspector_open") !== "0" : true,
  );
  const inspectorTab = ref<WorkInspectorTab>("files");

  let started = false;

  const messages = computed<WorkMessage[]>(() => current.value?.messages ?? []);
  const activeConversationId = computed(() => current.value?.conversation.id ?? null);

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
      if (conversationId !== activeConversationId.value) return;
      handleEvent(event);
    });
  }

  async function loadWorkspaceState() {
    const api = bridge();
    const [list, active] = await Promise.all([api.workspace.list(), api.workspace.active()]);
    workspaces.value = list;
    activeWorkspace.value = active;
    if (active) {
      await Promise.all([loadTree(""), refreshGitStatus()]);
    } else {
      childrenByDir.value = {};
      expandedDirs.value = new Set();
      gitStatus.value = { is_repo: false, branch: null, changes: [] };
      previewFile.value = null;
      previewDiff.value = null;
    }
  }

  async function loadList() {
    const filterPath = showAllWorkspaces.value ? undefined : (activeWorkspace.value?.path ?? undefined);
    conversations.value = await bridge().work.list(filterPath);
  }

  async function setShowAllWorkspaces(value: boolean) {
    showAllWorkspaces.value = value;
    await loadList();
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
    await Promise.all([loadTree(""), refreshGitStatus(), loadList()]);
    if (!showAllWorkspaces.value) {
      if (current.value && current.value.conversation.workspace_path !== ws.path) {
        current.value = null;
        if (conversations.value[0]) {
          await select(conversations.value[0].id);
        }
      }
    }
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

  async function refreshWorkspace() {
    if (!activeWorkspace.value) return;
    const dirs = ["", ...Array.from(expandedDirs.value)];
    await Promise.all([
      ...dirs.map((d) => loadTree(d).catch(() => undefined)),
      refreshGitStatus(),
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
    try {
      skills.value = await bridge().work.skills();
    } catch {
      skills.value = [];
    }
  }

  async function create(title?: string) {
    const conversation = await bridge().work.create(title, activeWorkspace.value?.path ?? null);
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
    subagents.value = [];
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

  async function pin(id: string, isPinned: boolean) {
    await bridge().work.pin(id, isPinned);
    await loadList();
    if (current.value?.conversation.id === id) current.value.conversation.is_pinned = isPinned;
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

  async function send(
    content: string,
    options?: { skillNames?: string[]; attachments?: WorkAttachment[] },
  ) {
    const text = content.trim();
    if (!text || sending.value) return;
    await ensureConversation();
    if (!current.value) return;
    const conversationId = current.value.conversation.id;
    error.value = null;
    pendingControl.value = null;
    plan.value = null;
    subagents.value = [];

    const userMessage: WorkMessage = {
      id: uid(),
      conversation_id: conversationId,
      role: "user",
      content: text,
      status: "completed",
      tool_name: null,
      tool_payload: options?.attachments?.length || options?.skillNames?.length
        ? { attachments: options?.attachments ?? [], skills: options?.skillNames ?? [] }
        : null,
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
    current.value.messages.push(userMessage, assistantMessage);
    activeAssistantId.value = assistantMessage.id;
    streaming.value = true;
    sending.value = true;
    try {
      await bridge().work.send(conversationId, text, options);
      await loadList();
    } catch (err) {
      error.value = err instanceof Error ? err.message : "发送失败";
      assistantMessage.status = "failed";
      streaming.value = false;
    } finally {
      sending.value = false;
    }
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
        if (assistant && typeof data.run_id === "string") assistant.run_id = data.run_id;
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
        if (["write", "edit", "multiedit", "apply_patch", "bash", "write_file", "patch", "terminal", "execute_code"].includes(String(data.tool ?? ""))) {
          void refreshWorkspace();
        }
        return;
      }
      case "subagent.started": {
        const sid = String(data.subagent_id ?? data.delegation_id ?? uid());
        subagents.value = [
          ...subagents.value,
          { id: sid, goal: String(data.goal ?? "子任务"), status: "running", toolCount: 0 },
        ];
        return;
      }
      case "subagent.progress": {
        const sid = String(data.subagent_id ?? data.delegation_id ?? "");
        const item = subagents.value.find((s) => s.id === sid);
        if (item) {
          if (typeof data.tool_count === "number") item.toolCount = data.tool_count;
          if (typeof data.status === "string") item.status = data.status;
        }
        return;
      }
      case "subagent.completed": {
        const sid = String(data.subagent_id ?? data.delegation_id ?? "");
        const item = subagents.value.find((s) => s.id === sid);
        if (item) {
          item.status = String(data.status ?? "completed");
          if (typeof data.summary === "string") item.summary = data.summary;
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
          choices: Array.isArray(data.choices) ? (data.choices as string[]) : null,
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
        void refreshWorkspace();
        // Refresh shared account credits when routing through Whitz built-in gateway.
        const rt = useRuntimeStore();
        const usesWhitz =
          rt.settings?.model.mode === "builtin" ||
          Boolean(rt.opencodeConfig?.default_model?.startsWith("whitz/"));
        if (usesWhitz) {
          void useCreditsStore().fetch().catch(() => undefined);
        }
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

  async function approve(choice: WorkApprovalChoice) {
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
    subagents.value = [];
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
    subagents,
    activeAssistantId,
    activeConversationId,
    workspaces,
    activeWorkspace,
    showAllWorkspaces,
    childrenByDir,
    expandedDirs,
    treeLoading,
    previewFile,
    previewLoading,
    previewDiff,
    gitStatus,
    gitLoading,
    skills,
    inspectorOpen,
    inspectorTab,
    setInspectorOpen,
    bindEvents,
    loadWorkspaceState,
    loadList,
    setShowAllWorkspaces,
    pickWorkspace,
    selectWorkspace,
    removeWorkspace,
    openInExplorer,
    loadTree,
    toggleDir,
    openFilePreview,
    openDiffPreview,
    refreshGitStatus,
    refreshWorkspace,
    loadSkills,
    create,
    select,
    rename,
    pin,
    remove,
    send,
    steer,
    stop,
    approve,
    clarify,
    reset,
  };
});
