import fs from "node:fs";
import path from "node:path";
import { shell } from "electron";
import { IPC } from "../../shared/ipc-contract";
import { loadConfig } from "../config";
import { handle } from "./common";
import { scoped } from "../logger";
import {
  listConversations,
  createConversation,
  getConversation,
  renameConversation,
  pinConversation,
  deleteConversation,
  setConversationPrefs,
} from "../work/repository";
import {
  approveRun,
  clarifyRun,
  compactConversation,
  flushPendingBashApprovals,
  forkConversation,
  getActiveRunSnapshots,
  getConversationDiff,
  hasAnyActiveRun,
  initConversationAgents,
  revertToMessage,
  runShellCommand,
  runSlashCommand,
  sendMessage,
  steerRun,
  stopRun,
  unrevertConversation,
} from "../work/runner";
import { getWorkSettings, saveWorkSettings } from "../work/settings";
import {
  deleteWorkspace,
  getActiveWorkspace,
  getGitDiff,
  getGitStatus,
  listDirectoryTree,
  listSavedWorkspaces,
  openInExplorer,
  pickAttachments,
  pickWorkspaceFolder,
  readWorkspaceFile,
  searchWorkspaceFiles,
  selectWorkspace,
} from "../work/workspaceService";
import { OpenCodeClient } from "../work/opencodeClient";
import { resetRuntimeDetectCache } from "../runtime/installer";
import { ensureBuiltinKey, getLocalGatewayStatus, localGatewayBaseUrl } from "../runtime/localOpenAIGateway";
import {
  buildConfigSnapshot,
  deleteMcpFromDisk,
  deleteProviderFromDisk,
  listMcpServersFromDisk,
  opencodeFiles,
  removeWhitzProviderFromDisk,
  saveOpenCodePreferencesOnDisk,
  syncFullCommandPermissionOnDisk,
  upsertMcpOnDisk,
  upsertProviderOnDisk,
  writeWhitzProviderToDisk,
} from "../runtime/opencodeConfig";
import {
  ensureAutoStarted,
  getStatus,
  reloadIfConfigChanged,
  runtimeEvents,
  syncWorkspaceIfIdle,
} from "../runtime/opencodeRuntime";
import type {
  OpenCodeConfigSavePatch,
  OpenCodeConfigSnapshot,
  OpenCodeProviderInput,
  WorkAgentInfo,
  WorkApprovalChoice,
  WorkAttachment,
  WorkCommandInfo,
  WorkLspStatus,
  WorkMcpServerInfo,
  WorkMcpServerInput,
  WorkSessionPrefsPatch,
  WorkSettingsPatch,
  WorkSkillItem,
} from "../../shared/work-types";

const logger = scoped("ipc:work");

interface TestResult {
  ok: boolean;
  latency_ms: number | null;
  model: string | null;
  detail: string | null;
}

async function testModel(): Promise<TestResult> {
  const settings = getWorkSettings();
  const started = Date.now();
  try {
    if (settings.model.mode === "builtin") {
      const key = (await ensureBuiltinKey()).trim();
      const base = localGatewayBaseUrl() ?? `${loadConfig().apiBase.replace(/\/api$/, "")}/api/desktop/llm/v1`;
      const resp = await fetch(`${base.replace(/\/+$/, "")}/models`, {
        headers: { Authorization: `Bearer ${key}` },
        signal: AbortSignal.timeout(15_000),
      });
      const text = await resp.text();
      if (!resp.ok) return { ok: false, latency_ms: null, model: null, detail: text.slice(0, 200) };
      return {
        ok: true,
        latency_ms: Date.now() - started,
        model: `whitz/${settings.model.builtin_model || "whitz-default"}`,
        detail: `本机服务 ${base}`,
      };
    }

    const snapshot = await getOpenCodeSnapshot();
    if (!getStatus().running) {
      return {
        ok: Boolean(snapshot.default_model || snapshot.providers.length),
        latency_ms: Date.now() - started,
        model: snapshot.default_model || "OpenCode 自动选择",
        detail: "OpenCode 服务尚未就绪，仅完成本地配置文件校验",
      };
    }
    const targetRef = snapshot.default_model;
    const providerId = targetRef.includes("/") ? targetRef.split("/")[0] : "";
    const provider = providerId ? snapshot.providers.find((p) => p.id === providerId) : snapshot.providers[0];
    if (!provider) {
      return { ok: false, latency_ms: null, model: null, detail: "本机 OpenCode 尚未配置可用 Provider" };
    }
    return {
      ok: provider.connected,
      latency_ms: Date.now() - started,
      model: targetRef || `${provider.id}/${provider.models[0]?.id ?? "default"}`,
      detail: provider.connected ? "本机 OpenCode Provider 已就绪" : "该 Provider 尚未连接或缺少凭据",
    };
  } catch (err) {
    return {
      ok: false,
      latency_ms: null,
      model: null,
      detail: err instanceof Error ? err.message : "连接失败",
    };
  }
}

function exportConversation(id: string): { path: string } {
  const detail = getConversation(id);
  if (!detail) throw new Error("对话不存在");
  const lines = [`# ${detail.conversation.title}`, "", `> 导出时间：${new Date().toLocaleString()}`, ""];
  for (const message of detail.messages) {
    if (message.role === "tool") {
      lines.push(`- 工具 ${message.tool_name ?? ""} (${message.status})`, "");
      continue;
    }
    lines.push(message.role === "user" ? "## 用户" : "## Whitz Work", "", message.content, "");
  }
  const targetDir = path.join(process.env.USERPROFILE ?? process.cwd(), "Documents", "Whitz Work");
  fs.mkdirSync(targetDir, { recursive: true });
  const file = path.join(targetDir, `${detail.conversation.title.replace(/[\\/:*?"<>|]/g, "_")}.md`);
  fs.writeFileSync(file, lines.join("\n"), "utf-8");
  return { path: file };
}

async function listWorkSkills(workspacePath?: string | null): Promise<WorkSkillItem[]> {
  if (getStatus().running) {
    try {
      return await new OpenCodeClient().listSkills(workspacePath ?? getActiveWorkspace()?.path ?? null);
    } catch (err) {
      logger.warn("opencode /skill failed", err instanceof Error ? err.message : String(err));
    }
  }
  return [];
}

async function listWorkAgents(workspacePath?: string | null): Promise<WorkAgentInfo[]> {
  if (getStatus().running) {
    try {
      return await new OpenCodeClient().listAgents(workspacePath ?? getActiveWorkspace()?.path ?? null);
    } catch (err) {
      logger.warn("opencode /agent failed", err instanceof Error ? err.message : String(err));
    }
  }
  return [
    { name: "build", description: "默认执行代理，可读写文件并运行命令", mode: "primary", native: true },
    { name: "plan", description: "只读规划分析代理，避免误改代码", mode: "primary", native: true },
  ];
}

async function listWorkCommands(workspacePath?: string | null): Promise<WorkCommandInfo[]> {
  if (getStatus().running) {
    try {
      return await new OpenCodeClient().listCommands(workspacePath ?? getActiveWorkspace()?.path ?? null);
    } catch (err) {
      logger.warn("opencode /command failed", err instanceof Error ? err.message : String(err));
    }
  }
  return [];
}

async function getMcpList(workspacePath?: string | null): Promise<WorkMcpServerInfo[]> {
  const dir = workspacePath ?? getActiveWorkspace()?.path ?? null;
  if (getStatus().running) {
    try {
      const live = await new OpenCodeClient().getMcpStatus(dir);
      return listMcpServersFromDisk(live);
    } catch {
      /* fallback to disk */
    }
  }
  return listMcpServersFromDisk();
}

async function getLspList(workspacePath?: string | null): Promise<WorkLspStatus[]> {
  if (!getStatus().running) return [];
  try {
    return await new OpenCodeClient().getLspStatus(workspacePath ?? getActiveWorkspace()?.path ?? null);
  } catch {
    return [];
  }
}

async function getVcsBranch(workspacePath?: string | null): Promise<{ branch: string | null }> {
  if (!getStatus().running) return { branch: null };
  try {
    return await new OpenCodeClient().getVcsInfo(workspacePath ?? getActiveWorkspace()?.path ?? null);
  } catch {
    return { branch: null };
  }
}

async function getOpenCodeSnapshot(): Promise<OpenCodeConfigSnapshot> {
  if (getStatus().running) {
    const dir = getActiveWorkspace()?.path ?? null;
    try {
      const client = new OpenCodeClient();
      const [live, liveMcp] = await Promise.all([
        client.listProviders(dir),
        client.getMcpStatus(dir).catch(() => null),
      ]);
      return buildConfigSnapshot(live, liveMcp);
    } catch {
      /* fallback to disk only */
    }
  }
  return buildConfigSnapshot();
}

export function registerWorkHandlers(): void {
  handle(IPC.workList, (workspacePath?: string | null) => listConversations(workspacePath));
  handle(IPC.workCreate, (title?: string, workspacePath?: string | null) =>
    createConversation(title, workspacePath),
  );
  handle(IPC.workGet, (id: string) => {
    const detail = getConversation(id);
    if (!detail) throw new Error("对话不存在");
    return detail;
  });
  handle(IPC.workRename, (id: string, title: string) => renameConversation(id, title));
  handle(IPC.workPin, (id: string, isPinned: boolean) => pinConversation(id, isPinned));
  handle(IPC.workDelete, (id: string) => deleteConversation(id));
  handle(IPC.workSetPrefs, (id: string, prefs: WorkSessionPrefsPatch) => setConversationPrefs(id, prefs));
  handle(IPC.workActiveRuns, () => getActiveRunSnapshots());
  handle(
    IPC.workSend,
    (
      conversationId: string,
      content: string,
      options?: {
        skillNames?: string[];
        attachments?: WorkAttachment[];
        modelRef?: string | null;
        agentName?: string | null;
        variant?: string | null;
      },
    ) => sendMessage(conversationId, content, options),
  );
  handle(IPC.workSteer, (conversationId: string, content: string) => steerRun(conversationId, content));
  handle(IPC.workStop, (conversationId: string) => stopRun(conversationId));
  handle(
    IPC.workApprove,
    (conversationId: string, requestId: string, generation: number, choice: WorkApprovalChoice) =>
      approveRun(conversationId, requestId, generation, choice),
  );
  handle(IPC.workClarify, (conversationId: string, requestId: string, generation: number, answer: string) =>
    clarifyRun(conversationId, requestId, generation, answer),
  );
  handle(IPC.workFork, (conversationId: string, messageId?: string | null) =>
    forkConversation(conversationId, messageId),
  );
  handle(IPC.workRevert, (conversationId: string, messageId: string) => revertToMessage(conversationId, messageId));
  handle(IPC.workUnrevert, (conversationId: string) => unrevertConversation(conversationId));
  handle(IPC.workCompact, (conversationId: string, modelRef?: string | null) =>
    compactConversation(conversationId, modelRef),
  );
  handle(IPC.workInitAgents, (conversationId: string, modelRef?: string | null) =>
    initConversationAgents(conversationId, modelRef),
  );
  handle(
    IPC.workRunCommand,
    (
      conversationId: string,
      command: string,
      args: string,
      options?: { modelRef?: string | null; agentName?: string | null; variant?: string | null },
    ) => runSlashCommand(conversationId, command, args, options),
  );
  handle(
    IPC.workRunShell,
    (conversationId: string, command: string, options?: { agentName?: string | null; modelRef?: string | null }) =>
      runShellCommand(conversationId, command, options),
  );
  handle(IPC.workSessionDiff, (conversationId: string) => getConversationDiff(conversationId));
  handle(IPC.workAgentsList, (workspacePath?: string | null) => listWorkAgents(workspacePath));
  handle(IPC.workCommandsList, (workspacePath?: string | null) => listWorkCommands(workspacePath));

  handle(IPC.workSettingsGet, () => getWorkSettings());
  handle(IPC.workSettingsSave, (patch: WorkSettingsPatch) => {
    const next = saveWorkSettings(patch);
    if (patch.full_command_mode !== undefined) {
      syncFullCommandPermissionOnDisk(patch.full_command_mode);
      if (patch.full_command_mode) flushPendingBashApprovals();
    }
    resetRuntimeDetectCache();
    runtimeEvents.emit("status", getStatus());
    void reloadIfConfigChanged().catch(() => void ensureAutoStarted());
    return next;
  });
  handle(IPC.workTestModel, () => testModel());
  handle(IPC.workExport, (id: string) => exportConversation(id));
  handle(IPC.workSkillsList, (workspacePath?: string | null) => listWorkSkills(workspacePath));
  handle(IPC.workPickAttachments, () => pickAttachments());

  handle(IPC.opencodeConfigGet, () => getOpenCodeSnapshot());
  handle(IPC.opencodeConfigSave, async (patch: OpenCodeConfigSavePatch) => {
    saveOpenCodePreferencesOnDisk(patch);
    await reloadIfConfigChanged();
    runtimeEvents.emit("status", getStatus());
    return getOpenCodeSnapshot();
  });
  handle(IPC.opencodeProviderUpsert, async (input: OpenCodeProviderInput) => {
    upsertProviderOnDisk(input);
    if (getStatus().running) {
      const client = new OpenCodeClient();
      if (input.clearApiKey) await client.removeAuth(input.id).catch(() => undefined);
      else if (input.apiKey?.trim()) await client.setAuth(input.id, input.apiKey.trim()).catch(() => undefined);
    }
    await reloadIfConfigChanged();
    runtimeEvents.emit("status", getStatus());
    return getOpenCodeSnapshot();
  });
  handle(IPC.opencodeProviderDelete, async (id: string) => {
    deleteProviderFromDisk(id);
    if (getStatus().running) {
      await new OpenCodeClient().removeAuth(id).catch(() => undefined);
    }
    await reloadIfConfigChanged();
    runtimeEvents.emit("status", getStatus());
    return getOpenCodeSnapshot();
  });
  handle(IPC.opencodeWriteWhitz, async () => {
    writeWhitzProviderToDisk();
    await reloadIfConfigChanged();
    runtimeEvents.emit("status", getStatus());
    return getOpenCodeSnapshot();
  });
  handle(IPC.opencodeRemoveWhitz, async () => {
    removeWhitzProviderFromDisk();
    await reloadIfConfigChanged();
    runtimeEvents.emit("status", getStatus());
    return getOpenCodeSnapshot();
  });
  handle(IPC.opencodeOpenConfigDir, async () => {
    const dir = opencodeFiles().configDir;
    fs.mkdirSync(dir, { recursive: true });
    await shell.openPath(dir);
  });
  handle(IPC.opencodeMcpList, (workspacePath?: string | null) => getMcpList(workspacePath));
  handle(IPC.opencodeMcpUpsert, async (input: WorkMcpServerInput) => {
    upsertMcpOnDisk(input);
    await reloadIfConfigChanged();
    runtimeEvents.emit("status", getStatus());
    return getMcpList();
  });
  handle(IPC.opencodeMcpDelete, async (name: string) => {
    deleteMcpFromDisk(name);
    await reloadIfConfigChanged();
    runtimeEvents.emit("status", getStatus());
    return getMcpList();
  });
  handle(IPC.opencodeMcpToggle, async (name: string, connect: boolean, workspacePath?: string | null) => {
    const dir = workspacePath ?? getActiveWorkspace()?.path ?? null;
    if (getStatus().running) {
      const client = new OpenCodeClient();
      if (connect) await client.connectMcp(name, dir);
      else await client.disconnectMcp(name, dir);
    }
    return getMcpList(dir);
  });
  handle(IPC.opencodeLspStatus, (workspacePath?: string | null) => getLspList(workspacePath));
  handle(IPC.opencodeVcsInfo, (workspacePath?: string | null) => getVcsBranch(workspacePath));
  handle(IPC.gatewayStatus, () => getLocalGatewayStatus());

  handle(IPC.workspaceList, () => listSavedWorkspaces());
  handle(IPC.workspaceActive, () => getActiveWorkspace());
  handle(IPC.workspacePick, async () => {
    const picked = await pickWorkspaceFolder();
    if (picked) void syncWorkspaceIfIdle(hasAnyActiveRun()).catch(() => undefined);
    return picked;
  });
  handle(IPC.workspaceSelect, (workspacePath: string) => {
    const selected = selectWorkspace(workspacePath);
    void syncWorkspaceIfIdle(hasAnyActiveRun()).catch(() => undefined);
    return selected;
  });
  handle(IPC.workspaceRemove, (workspacePath: string) => {
    deleteWorkspace(workspacePath);
    runtimeEvents.emit("status", getStatus());
  });
  handle(IPC.workspaceOpenExplorer, (targetPath?: string) => openInExplorer(targetPath));
  handle(IPC.workspaceFsTree, (relDir?: string, includeHidden?: boolean) =>
    listDirectoryTree(relDir ?? "", Boolean(includeHidden)),
  );
  handle(IPC.workspaceFsSearch, (query: string) => searchWorkspaceFiles(query));
  handle(IPC.workspaceFsRead, (relPath: string) => readWorkspaceFile(relPath));
  handle(IPC.workspaceGitStatus, () => getGitStatus());
  handle(IPC.workspaceGitDiff, (relPath?: string) => getGitDiff(relPath));

  logger.info("work ipc registered");
}
