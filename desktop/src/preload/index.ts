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
  WorkActiveRunSnapshot,
  WorkAgentInfo,
  WorkApprovalChoice,
  WorkAttachment,
  WorkCommandInfo,
  WorkConversation,
  WorkConversationDetail,
  WorkEvent,
  WorkFindMatch,
  WorkFormatterStatus,
  WorkGlobalEvent,
  WorkLspStatus,
  WorkMcpServerInfo,
  WorkMcpServerInput,
  WorkProviderCatalogItem,
  WorkProviderOAuthStart,
  WorkPtyConnectInfo,
  WorkPtyInfo,
  WorkRemoteSessionSummary,
  WorkSessionDiffItem,
  WorkSessionPrefsPatch,
  WorkSettings,
  WorkSettingsPatch,
  WorkShellOption,
  WorkSkillItem,
  WorkSymbolMatch,
  WorkTimelineItem,
  WorkWorktreeInfo,
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
  setThemeOverlay: (dark) => invoke<void>(IPC.appSetThemeOverlay, dark),
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
    upgrade: (target) => invoke<{ ok: boolean; detail: string }>(IPC.runtimeUpgrade, target),
    openLogs: () => invoke<void>(IPC.runtimeOpenLogs),
    pickExe: () => invoke<string | null>(IPC.runtimePickExe),
  },

  work: {
    list: (workspacePath) => invoke<WorkConversation[]>(IPC.workList, workspacePath),
    create: (title, workspacePath, options) => invoke<WorkConversation>(IPC.workCreate, title, workspacePath, options),
    get: (id) => invoke<WorkConversationDetail>(IPC.workGet, id),
    rename: (id, title) => invoke<void>(IPC.workRename, id, title),
    pin: (id, isPinned) => invoke<void>(IPC.workPin, id, isPinned),
    delete: (id, options) => invoke<void>(IPC.workDelete, id, options),
    setPrefs: (id, prefs: WorkSessionPrefsPatch) => invoke<WorkConversation>(IPC.workSetPrefs, id, prefs),
    activeRuns: () => invoke<WorkActiveRunSnapshot[]>(IPC.workActiveRuns),
    send: (conversationId, content, options) =>
      invoke<{ run_id: string | null }>(IPC.workSend, conversationId, content, options),
    steer: (conversationId, content) => invoke<void>(IPC.workSteer, conversationId, content),
    stop: (conversationId) => invoke<void>(IPC.workStop, conversationId),
    approve: (conversationId, requestId, generation, choice: WorkApprovalChoice, message?: string) =>
      invoke<void>(IPC.workApprove, conversationId, requestId, generation, choice, message),
    clarify: (conversationId, requestId, generation, answers) =>
      invoke<void>(IPC.workClarify, conversationId, requestId, generation, answers),
    rejectClarify: (conversationId, requestId) =>
      invoke<void>(IPC.workClarifyReject, conversationId, requestId),
    fork: (conversationId, messageId) => invoke<WorkConversation>(IPC.workFork, conversationId, messageId),
    revert: (conversationId, messageId) => invoke<WorkConversationDetail>(IPC.workRevert, conversationId, messageId),
    unrevert: (conversationId) => invoke<WorkConversationDetail>(IPC.workUnrevert, conversationId),
    compact: (conversationId, modelRef) => invoke<void>(IPC.workCompact, conversationId, modelRef),
    initAgents: (conversationId, modelRef) => invoke<void>(IPC.workInitAgents, conversationId, modelRef),
    runCommand: (conversationId, command, args, options) =>
      invoke<{ run_id: string | null }>(IPC.workRunCommand, conversationId, command, args, options),
    runShell: (conversationId, command, options) =>
      invoke<{ run_id: string | null }>(IPC.workRunShell, conversationId, command, options),
    sessionDiff: (conversationId) => invoke<WorkSessionDiffItem[]>(IPC.workSessionDiff, conversationId),
    share: (conversationId) => invoke<{ url: string }>(IPC.workShare, conversationId),
    unshare: (conversationId) => invoke<void>(IPC.workUnshare, conversationId),
    remoteSessions: (workspacePath) => invoke<WorkRemoteSessionSummary[]>(IPC.workRemoteSessions, workspacePath),
    importSession: (sessionId, workspacePath) =>
      invoke<WorkConversation>(IPC.workImportSession, sessionId, workspacePath),
    subsessionMessages: (childSessionId, workspacePath) =>
      invoke<WorkTimelineItem[]>(IPC.workSubsessionMessages, childSessionId, workspacePath),
    agents: (workspacePath) => invoke<WorkAgentInfo[]>(IPC.workAgentsList, workspacePath),
    commands: (workspacePath) => invoke<WorkCommandInfo[]>(IPC.workCommandsList, workspacePath),
    settings: () => invoke<WorkSettings>(IPC.workSettingsGet),
    saveSettings: (patch: WorkSettingsPatch) => invoke<WorkSettings>(IPC.workSettingsSave, patch),
    testModel: () =>
      invoke<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null }>(IPC.workTestModel),
    export: (id) => invoke<{ path: string }>(IPC.workExport, id),
    exportJson: (id) => invoke<{ path: string }>(IPC.workExportJson, id),
    skills: (workspacePath) => invoke<WorkSkillItem[]>(IPC.workSkillsList, workspacePath),
    pickAttachments: () => invoke<WorkAttachment[]>(IPC.workPickAttachments),
    saveClipboardImage: (dataUrl, name) => invoke<WorkAttachment>(IPC.workSaveClipboardImage, dataUrl, name),
    attachmentsFromPaths: (filePaths) => invoke<WorkAttachment[]>(IPC.workAttachmentsFromPaths, filePaths),
  },

  opencode: {
    config: () => invoke<OpenCodeConfigSnapshot>(IPC.opencodeConfigGet),
    saveConfig: (patch: OpenCodeConfigSavePatch) => invoke<OpenCodeConfigSnapshot>(IPC.opencodeConfigSave, patch),
    upsertProvider: (input: OpenCodeProviderInput) =>
      invoke<OpenCodeConfigSnapshot>(IPC.opencodeProviderUpsert, input),
    deleteProvider: (id: string) => invoke<OpenCodeConfigSnapshot>(IPC.opencodeProviderDelete, id),
    providerCatalog: (workspacePath) =>
      invoke<WorkProviderCatalogItem[]>(IPC.opencodeProviderCatalog, workspacePath),
    setProviderApiKey: (providerId, apiKey) =>
      invoke<OpenCodeConfigSnapshot>(IPC.opencodeProviderSetKey, providerId, apiKey),
    startProviderOAuth: (providerId, methodIndex, inputs, workspacePath) =>
      invoke<WorkProviderOAuthStart>(IPC.opencodeProviderOAuthStart, providerId, methodIndex, inputs, workspacePath),
    completeProviderOAuth: (providerId, methodIndex, code, workspacePath) =>
      invoke<OpenCodeConfigSnapshot>(IPC.opencodeProviderOAuthCallback, providerId, methodIndex, code, workspacePath),
    writeWhitzProvider: () => invoke<OpenCodeConfigSnapshot>(IPC.opencodeWriteWhitz),
    removeWhitzProvider: () => invoke<OpenCodeConfigSnapshot>(IPC.opencodeRemoveWhitz),
    openConfigDir: () => invoke<void>(IPC.opencodeOpenConfigDir),
    mcpList: (workspacePath) => invoke<WorkMcpServerInfo[]>(IPC.opencodeMcpList, workspacePath),
    upsertMcp: (input: WorkMcpServerInput) => invoke<WorkMcpServerInfo[]>(IPC.opencodeMcpUpsert, input),
    deleteMcp: (name: string) => invoke<WorkMcpServerInfo[]>(IPC.opencodeMcpDelete, name),
    toggleMcp: (name: string, connect: boolean, workspacePath?: string | null) =>
      invoke<WorkMcpServerInfo[]>(IPC.opencodeMcpToggle, name, connect, workspacePath),
    authMcp: (name, workspacePath) => invoke<WorkMcpServerInfo[]>(IPC.opencodeMcpAuth, name, workspacePath),
    removeMcpAuth: (name, workspacePath) => invoke<WorkMcpServerInfo[]>(IPC.opencodeMcpAuthRemove, name, workspacePath),
    lspStatus: (workspacePath) => invoke<WorkLspStatus[]>(IPC.opencodeLspStatus, workspacePath),
    formatterStatus: (workspacePath) => invoke<WorkFormatterStatus[]>(IPC.opencodeFormatterStatus, workspacePath),
    vcsInfo: (workspacePath) => invoke<{ branch: string | null }>(IPC.opencodeVcsInfo, workspacePath),
    gatewayStatus: () => invoke<LocalGatewayStatus>(IPC.gatewayStatus),
  },

  pty: {
    shells: (workspacePath) => invoke<WorkShellOption[]>(IPC.ptyShells, workspacePath),
    list: (workspacePath) => invoke<WorkPtyInfo[]>(IPC.ptyList, workspacePath),
    create: (options) => invoke<WorkPtyInfo>(IPC.ptyCreate, options),
    update: (ptyId, patch, workspacePath) => invoke<WorkPtyInfo>(IPC.ptyUpdate, ptyId, patch, workspacePath),
    remove: (ptyId, workspacePath) => invoke<void>(IPC.ptyRemove, ptyId, workspacePath),
    connectInfo: (ptyId, workspacePath) => invoke<WorkPtyConnectInfo>(IPC.ptyConnectInfo, ptyId, workspacePath),
  },

  worktree: {
    list: (workspacePath) => invoke<string[]>(IPC.worktreeList, workspacePath),
    create: (name, workspacePath) => invoke<WorkWorktreeInfo>(IPC.worktreeCreate, name, workspacePath),
    remove: (directory, workspacePath) => invoke<void>(IPC.worktreeRemove, directory, workspacePath),
    reset: (directory, workspacePath) => invoke<void>(IPC.worktreeReset, directory, workspacePath),
  },

  workspace: {
    list: () => invoke<WorkWorkspace[]>(IPC.workspaceList),
    active: () => invoke<WorkWorkspace | null>(IPC.workspaceActive),
    pick: () => invoke<WorkWorkspace | null>(IPC.workspacePick),
    select: (workspacePath: string) => invoke<WorkWorkspace | null>(IPC.workspaceSelect, workspacePath),
    remove: (workspacePath: string) => invoke<void>(IPC.workspaceRemove, workspacePath),
    openExplorer: (targetPath?: string) => invoke<void>(IPC.workspaceOpenExplorer, targetPath),
    openInEditor: (relPath: string) => invoke<void>(IPC.workspaceOpenInEditor, relPath),
    tree: (relDir, includeHidden) => invoke<WorkspaceEntry[]>(IPC.workspaceFsTree, relDir, includeHidden),
    searchFiles: (query) => invoke<string[]>(IPC.workspaceFsSearch, query),
    findText: (pattern, workspacePath) => invoke<WorkFindMatch[]>(IPC.workspaceFindText, pattern, workspacePath),
    findSymbols: (query, workspacePath) => invoke<WorkSymbolMatch[]>(IPC.workspaceFindSymbols, query, workspacePath),
    read: (relPath) => invoke<WorkspaceFileContent>(IPC.workspaceFsRead, relPath),
    gitStatus: () => invoke<WorkspaceGitStatus>(IPC.workspaceGitStatus),
    gitDiff: (relPath) => invoke<string>(IPC.workspaceGitDiff, relPath),
    gitRevertFile: (relPath) => invoke<void>(IPC.workspaceGitRevertFile, relPath),
  },

  net: {
    get: () => invoke<ConnectivityState>(IPC.connectivityGet),
    forceOffline: (value) => invoke<ConnectivityState>(IPC.connectivityForceOffline, value),
    check: () => invoke<ConnectivityState>(IPC.connectivityCheck),
  },

  onWorkEvent: (cb) => subscribe(IPC_EVENTS.workEvent, cb),
  onWorkGlobalEvent: (cb) => subscribe<WorkGlobalEvent>(IPC_EVENTS.workGlobalEvent, cb),
  onWorkFocusConversation: (cb) => subscribe<string>(IPC_EVENTS.workFocusConversation, cb),
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
