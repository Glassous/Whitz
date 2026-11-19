import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import { IPC, IPC_EVENTS, type AuthRefreshResult, type PolicyView, type RuntimeStatusResult, type WorkApi } from "../shared/ipc-contract";
import type {
  ConnectivityState,
  DesktopInfo,
  DesktopSession,
  LocalGatewayStatus,
  OpenCodeConfigSavePatch,
  OpenCodeConfigSnapshot,
  OpenCodeProviderInput,
  RuntimeProgress,
  RuntimeStatus,
  WorkApprovalChoice,
  WorkAttachment,
  WorkConversation,
  WorkConversationDetail,
  WorkEvent,
  WorkSettings,
  WorkSettingsPatch,
  WorkSkillItem,
  WorkWorkspace,
  WorkspaceEntry,
  WorkspaceFileContent,
  WorkspaceGitStatus,
} from "../shared/work-types";

function cleanError(err: unknown): Error {
  const raw = err instanceof Error ? err.message : String(err);
  const match = /Error:\s*(.*)$/.exec(raw);
  return new Error((match ? match[1] : raw).trim() || "操作失败");
}

async function invoke<T>(channel: string, ...args: unknown[]): Promise<T> {
  try {
    return (await ipcRenderer.invoke(channel, ...args)) as T;
  } catch (err) {
    throw cleanError(err);
  }
}

function subscribe<T>(channel: string, callback: (payload: T) => void): () => void {
  const listener = (_event: IpcRendererEvent, payload: T) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

const api: WorkApi = {
  info: () => invoke<DesktopInfo>(IPC.appInfo),
  openExternal: (url) => invoke<void>(IPC.appOpenExternal, url),
  windowControl: (action) => invoke<void>(IPC.appWindowControl, action),
  quit: () => invoke<void>(IPC.appQuit),
  updater: {
    check: () => invoke<void>(IPC.updaterCheck),
    install: () => invoke<void>(IPC.updaterInstall),
  },

  auth: {
    session: () => invoke<DesktopSession | null>(IPC.authSession),
    loginPassword: (email, password) => invoke<DesktopSession>(IPC.authLoginPassword, email, password),
    loginCode: (email, code) => invoke<DesktopSession>(IPC.authLoginCode, email, code),
    register: (email, password, displayName, code) =>
      invoke<DesktopSession>(IPC.authRegister, email, password, displayName, code),
    sendCode: (email, purpose) =>
      invoke<{ message: string; cooldown: number }>(IPC.authSendCode, email, purpose),
    resetPassword: (email, code, password) => invoke<void>(IPC.authResetPassword, email, code, password),
    refresh: () => invoke<AuthRefreshResult>(IPC.authRefresh),
    logout: () => invoke<void>(IPC.authLogout),
    persist: (refreshToken, refreshExpiresIn) => invoke<void>(IPC.authPersist, refreshToken, refreshExpiresIn),
  },

  policy: {
    get: () => invoke<PolicyView>(IPC.policyGet),
    refresh: () => invoke<PolicyView>(IPC.policyRefresh),
  },

  runtime: {
    status: () => invoke<RuntimeStatusResult>(IPC.runtimeStatus),
    redetect: () => invoke<RuntimeStatusResult>(IPC.runtimeRedetect),
    start: () => invoke<RuntimeStatusResult>(IPC.runtimeStart),
    stop: () => invoke<RuntimeStatusResult>(IPC.runtimeStop),
    restart: () => invoke<RuntimeStatusResult>(IPC.runtimeRestart),
    openLogs: () => invoke<void>(IPC.runtimeOpenLogs),
    pickExe: () => invoke<string | null>(IPC.runtimePickExe),
  },

  work: {
    list: (workspacePath) => invoke<WorkConversation[]>(IPC.workList, workspacePath),
    create: (title, workspacePath) => invoke<WorkConversation>(IPC.workCreate, title, workspacePath),
    get: (id) => invoke<WorkConversationDetail>(IPC.workGet, id),
    rename: (id, title) => invoke<void>(IPC.workRename, id, title),
    pin: (id, isPinned) => invoke<void>(IPC.workPin, id, isPinned),
    delete: (id) => invoke<void>(IPC.workDelete, id),
    send: (conversationId, content, options) =>
      invoke<{ run_id: string | null }>(IPC.workSend, conversationId, content, options),
    steer: (conversationId, content) => invoke<void>(IPC.workSteer, conversationId, content),
    stop: (conversationId) => invoke<void>(IPC.workStop, conversationId),
    approve: (conversationId, requestId, generation, choice: WorkApprovalChoice) =>
      invoke<void>(IPC.workApprove, conversationId, requestId, generation, choice),
    clarify: (conversationId, requestId, generation, answer) =>
      invoke<void>(IPC.workClarify, conversationId, requestId, generation, answer),
    settings: () => invoke<WorkSettings>(IPC.workSettingsGet),
    saveSettings: (patch: WorkSettingsPatch) => invoke<WorkSettings>(IPC.workSettingsSave, patch),
    testModel: () =>
      invoke<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null }>(IPC.workTestModel),
    export: (id) => invoke<{ path: string }>(IPC.workExport, id),
    skills: () => invoke<WorkSkillItem[]>(IPC.workSkillsList),
    pickAttachments: () => invoke<WorkAttachment[]>(IPC.workPickAttachments),
  },

  opencode: {
    config: () => invoke<OpenCodeConfigSnapshot>(IPC.opencodeConfigGet),
    saveConfig: (patch: OpenCodeConfigSavePatch) => invoke<OpenCodeConfigSnapshot>(IPC.opencodeConfigSave, patch),
    upsertProvider: (input: OpenCodeProviderInput) =>
      invoke<OpenCodeConfigSnapshot>(IPC.opencodeProviderUpsert, input),
    deleteProvider: (id: string) => invoke<OpenCodeConfigSnapshot>(IPC.opencodeProviderDelete, id),
    writeWhitzProvider: () => invoke<OpenCodeConfigSnapshot>(IPC.opencodeWriteWhitz),
    removeWhitzProvider: () => invoke<OpenCodeConfigSnapshot>(IPC.opencodeRemoveWhitz),
    openConfigDir: () => invoke<void>(IPC.opencodeOpenConfigDir),
    gatewayStatus: () => invoke<LocalGatewayStatus>(IPC.gatewayStatus),
  },

  workspace: {
    list: () => invoke<WorkWorkspace[]>(IPC.workspaceList),
    active: () => invoke<WorkWorkspace | null>(IPC.workspaceActive),
    pick: () => invoke<WorkWorkspace | null>(IPC.workspacePick),
    select: (workspacePath) => invoke<WorkWorkspace | null>(IPC.workspaceSelect, workspacePath),
    remove: (workspacePath) => invoke<void>(IPC.workspaceRemove, workspacePath),
    openExplorer: (targetPath) => invoke<void>(IPC.workspaceOpenExplorer, targetPath),
    tree: (relDir, includeHidden) => invoke<WorkspaceEntry[]>(IPC.workspaceFsTree, relDir, includeHidden),
    searchFiles: (query) => invoke<string[]>(IPC.workspaceFsSearch, query),
    read: (relPath) => invoke<WorkspaceFileContent>(IPC.workspaceFsRead, relPath),
    gitStatus: () => invoke<WorkspaceGitStatus>(IPC.workspaceGitStatus),
    gitDiff: (relPath) => invoke<string>(IPC.workspaceGitDiff, relPath),
  },

  net: {
    get: () => invoke<ConnectivityState>(IPC.connectivityGet),
    forceOffline: (value) => invoke<ConnectivityState>(IPC.connectivityForceOffline, value),
    check: () => invoke<ConnectivityState>(IPC.connectivityCheck),
  },

  onWorkEvent: (cb) => subscribe(IPC_EVENTS.workEvent, cb),
  onRuntimeProgress: (cb) => subscribe<RuntimeProgress>(IPC_EVENTS.runtimeProgress, cb),
  onRuntimeStatus: (cb) => subscribe<RuntimeStatusResult>(IPC_EVENTS.runtimeStatus, cb),
  onAuthChanged: (cb) => subscribe<DesktopSession | null>(IPC_EVENTS.authChanged, cb),
  onConnectivity: (cb) => subscribe<ConnectivityState>(IPC_EVENTS.connectivityChanged, cb),
  onPolicyChanged: (cb) => subscribe<PolicyView>(IPC_EVENTS.policyChanged, cb),
  onMenuAction: (cb) => subscribe<string>(IPC_EVENTS.menuAction, cb),
  onUpdateDownloaded: (cb) => subscribe<{ version: string }>(IPC_EVENTS.updateDownloaded, cb),
};

contextBridge.exposeInMainWorld("whitzDesktop", api);

export type { WorkEvent, RuntimeStatus };
