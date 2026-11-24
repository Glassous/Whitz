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
  WorkMessage,
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
} from "./work-types";

export const IPC = {
  appInfo: "app:info",
  appOpenExternal: "app:open-external",
  appWindowControl: "app:window-control",
  appSetThemeOverlay: "app:set-theme-overlay",
  appQuit: "app:quit",
  updaterCheck: "app:update-check",
  updaterInstall: "app:update-install",

  authSession: "auth:session",
  authLoginPassword: "auth:login-password",
  authLoginCode: "auth:login-code",
  authRegister: "auth:register",
  authSendCode: "auth:send-code",
  authResetPassword: "auth:reset-password",
  authRefresh: "auth:refresh",
  authLogout: "auth:logout",
  authPersist: "auth:persist",

  policyGet: "policy:get",
  policyRefresh: "policy:refresh",

  runtimeStatus: "runtime:status",
  runtimeRedetect: "runtime:redetect",
  runtimeStart: "runtime:start",
  runtimeStop: "runtime:stop",
  runtimeRestart: "runtime:restart",
  runtimeUpgrade: "runtime:upgrade",
  runtimeOpenLogs: "runtime:open-logs",
  runtimePickExe: "runtime:pick-exe",

  workList: "work:list",
  workCreate: "work:create",
  workGet: "work:get",
  workRename: "work:rename",
  workPin: "work:pin",
  workDelete: "work:delete",
  workSetPrefs: "work:set-prefs",
  workActiveRuns: "work:active-runs",
  workSend: "work:send",
  workSteer: "work:steer",
  workStop: "work:stop",
  workApprove: "work:approve",
  workClarify: "work:clarify",
  workClarifyReject: "work:clarify-reject",
  workFork: "work:fork",
  workRevert: "work:revert",
  workUnrevert: "work:unrevert",
  workCompact: "work:compact",
  workInitAgents: "work:init-agents",
  workRunCommand: "work:run-command",
  workRunShell: "work:run-shell",
  workSessionDiff: "work:session-diff",
  workShare: "work:share",
  workUnshare: "work:unshare",
  workRemoteSessions: "work:remote-sessions",
  workImportSession: "work:import-session",
  workSubsessionMessages: "work:subsession-messages",
  workAgentsList: "work:agents-list",
  workCommandsList: "work:commands-list",
  workTestModel: "work:test-model",
  workSettingsGet: "work:settings-get",
  workSettingsSave: "work:settings-save",
  workExport: "work:export",
  workExportJson: "work:export-json",
  workSkillsList: "work:skills-list",
  workPickAttachments: "work:pick-attachments",
  workSaveClipboardImage: "work:save-clipboard-image",
  workAttachmentsFromPaths: "work:attachments-from-paths",

  opencodeConfigGet: "opencode:config-get",
  opencodeConfigSave: "opencode:config-save",
  opencodeProviderUpsert: "opencode:provider-upsert",
  opencodeProviderDelete: "opencode:provider-delete",
  opencodeProviderCatalog: "opencode:provider-catalog",
  opencodeProviderSetKey: "opencode:provider-set-key",
  opencodeProviderOAuthStart: "opencode:provider-oauth-start",
  opencodeProviderOAuthCallback: "opencode:provider-oauth-callback",
  opencodeWriteWhitz: "opencode:write-whitz",
  opencodeRemoveWhitz: "opencode:remove-whitz",
  opencodeOpenConfigDir: "opencode:open-config-dir",
  opencodeMcpList: "opencode:mcp-list",
  opencodeMcpUpsert: "opencode:mcp-upsert",
  opencodeMcpDelete: "opencode:mcp-delete",
  opencodeMcpToggle: "opencode:mcp-toggle",
  opencodeMcpAuth: "opencode:mcp-auth",
  opencodeMcpAuthRemove: "opencode:mcp-auth-remove",
  opencodeLspStatus: "opencode:lsp-status",
  opencodeFormatterStatus: "opencode:formatter-status",
  opencodeVcsInfo: "opencode:vcs-info",
  gatewayStatus: "gateway:status",

  ptyShells: "pty:shells",
  ptyList: "pty:list",
  ptyCreate: "pty:create",
  ptyUpdate: "pty:update",
  ptyRemove: "pty:remove",
  ptyConnectInfo: "pty:connect-info",

  worktreeList: "worktree:list",
  worktreeCreate: "worktree:create",
  worktreeRemove: "worktree:remove",
  worktreeReset: "worktree:reset",

  workspaceList: "workspace:list",
  workspaceActive: "workspace:active",
  workspacePick: "workspace:pick",
  workspaceSelect: "workspace:select",
  workspaceRemove: "workspace:remove",
  workspaceOpenExplorer: "workspace:open-explorer",
  workspaceOpenInEditor: "workspace:open-in-editor",
  workspaceFsTree: "workspace:fs-tree",
  workspaceFsSearch: "workspace:fs-search",
  workspaceFindText: "workspace:find-text",
  workspaceFindSymbols: "workspace:find-symbols",
  workspaceFsRead: "workspace:fs-read",
  workspaceGitStatus: "workspace:git-status",
  workspaceGitDiff: "workspace:git-diff",
  workspaceGitRevertFile: "workspace:git-revert-file",

  connectivityGet: "net:get",
  connectivityForceOffline: "net:force-offline",
  connectivityCheck: "net:check",
} as const;

export const IPC_EVENTS = {
  workEvent: "work:event",
  workGlobalEvent: "work:global-event",
  workFocusConversation: "work:focus-conversation",
  runtimeProgress: "runtime:progress",
  runtimeStatus: "runtime:status-changed",
  authChanged: "auth:changed",
  connectivityChanged: "net:changed",
  policyChanged: "policy:changed",
  updateAvailable: "update:available",
  updateDownloaded: "update:downloaded",
  menuAction: "app:menu-action",
} as const;

export interface AuthPayload {
  email?: string;
  password?: string;
  code?: string;
  display_name?: string;
  refresh_token?: string;
  refresh_expires_in?: number;
}

export interface AuthRefreshResult {
  session: DesktopSession | null;
  reason: "ok" | "unauthorized" | "error";
}

export interface PolicyView {
  enabled: boolean;
  source: "remote" | "cache" | "default";
  verified: boolean;
  version: number;
  not_after: string | null;
  disabled_reason: string | null;
  min_app_version: string | null;
  latest_version: string | null;
  fetched_at: string | null;
}

export interface DesktopPolicyPayload {
  version: number;
  issued_at: string;
  not_after: string;
  work_mode: {
    enabled: boolean;
    min_app_version: string;
    disabled_reason: string | null;
  };
  desktop: {
    min_app_version: string;
    latest_version: string;
  };
  llm: {
    enabled: boolean;
    model_alias: string;
  };
}

export interface DesktopPolicyEnvelope {
  payload: string;
  signature: string;
  key_id: string;
}

export interface RuntimeStatusResult {
  status: RuntimeStatus;
  policy: PolicyView;
}

export interface WorkApi {
  info(): Promise<DesktopInfo>;
  openExternal(url: string): Promise<void>;
  windowControl(action: "minimize" | "maximize" | "close"): Promise<void>;
  setThemeOverlay(dark: boolean): Promise<void>;
  quit(): Promise<void>;
  updater: {
    check(): Promise<void>;
    install(): Promise<void>;
  };

  auth: {
    session(): Promise<DesktopSession | null>;
    loginPassword(email: string, password: string): Promise<DesktopSession>;
    loginCode(email: string, code: string): Promise<DesktopSession>;
    register(email: string, password: string, displayName: string, code: string): Promise<DesktopSession>;
    sendCode(email: string, purpose: "login" | "register" | "reset"): Promise<{ message: string; cooldown: number }>;
    resetPassword(email: string, code: string, password: string): Promise<void>;
    refresh(): Promise<AuthRefreshResult>;
    logout(): Promise<void>;
    persist(refreshToken: string, refreshExpiresIn?: number): Promise<void>;
  };

  policy: {
    get(): Promise<PolicyView>;
    refresh(): Promise<PolicyView>;
  };

  runtime: {
    status(): Promise<RuntimeStatusResult>;
    redetect(): Promise<RuntimeStatusResult>;
    start(): Promise<RuntimeStatusResult>;
    stop(): Promise<RuntimeStatusResult>;
    restart(): Promise<RuntimeStatusResult>;
    upgrade(target?: string): Promise<{ ok: boolean; detail: string }>;
    openLogs(): Promise<void>;
    pickExe(): Promise<string | null>;
  };

  work: {
    list(workspacePath?: string | null): Promise<WorkConversation[]>;
    create(
      title?: string,
      workspacePath?: string | null,
      options?: { worktreeName?: string | null; worktreeBranch?: string | null },
    ): Promise<WorkConversation>;
    get(id: string): Promise<WorkConversationDetail>;
    rename(id: string, title: string): Promise<void>;
    pin(id: string, isPinned: boolean): Promise<void>;
    delete(id: string, options?: { deleteRemote?: boolean }): Promise<void>;
    setPrefs(id: string, prefs: WorkSessionPrefsPatch): Promise<WorkConversation>;
    activeRuns(): Promise<WorkActiveRunSnapshot[]>;
    send(
      conversationId: string,
      content: string,
      options?: {
        skillNames?: string[];
        attachments?: WorkAttachment[];
        modelRef?: string | null;
        agentName?: string | null;
        variant?: string | null;
      },
    ): Promise<{ run_id: string | null }>;
    steer(conversationId: string, content: string): Promise<void>;
    stop(conversationId: string): Promise<void>;
    approve(
      conversationId: string,
      requestId: string,
      generation: number,
      choice: WorkApprovalChoice,
      message?: string,
    ): Promise<void>;
    clarify(
      conversationId: string,
      requestId: string,
      generation: number,
      answers: string | string[][],
    ): Promise<void>;
    rejectClarify(conversationId: string, requestId: string): Promise<void>;
    fork(conversationId: string, messageId?: string | null): Promise<WorkConversation>;
    revert(conversationId: string, messageId: string): Promise<WorkConversationDetail>;
    unrevert(conversationId: string): Promise<WorkConversationDetail>;
    compact(conversationId: string, modelRef?: string | null): Promise<void>;
    initAgents(conversationId: string, modelRef?: string | null): Promise<void>;
    runCommand(
      conversationId: string,
      command: string,
      args: string,
      options?: { modelRef?: string | null; agentName?: string | null; variant?: string | null },
    ): Promise<{ run_id: string | null }>;
    runShell(
      conversationId: string,
      command: string,
      options?: { agentName?: string | null; modelRef?: string | null },
    ): Promise<{ run_id: string | null }>;
    sessionDiff(conversationId: string): Promise<WorkSessionDiffItem[]>;
    share(conversationId: string): Promise<{ url: string }>;
    unshare(conversationId: string): Promise<void>;
    remoteSessions(workspacePath?: string | null): Promise<WorkRemoteSessionSummary[]>;
    importSession(sessionId: string, workspacePath?: string | null): Promise<WorkConversation>;
    subsessionMessages(childSessionId: string, workspacePath?: string | null): Promise<WorkTimelineItem[]>;
    agents(workspacePath?: string | null): Promise<WorkAgentInfo[]>;
    commands(workspacePath?: string | null): Promise<WorkCommandInfo[]>;
    settings(): Promise<WorkSettings>;
    saveSettings(patch: WorkSettingsPatch): Promise<WorkSettings>;
    testModel(): Promise<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null }>;
    export(id: string): Promise<{ path: string }>;
    exportJson(id: string): Promise<{ path: string }>;
    skills(workspacePath?: string | null): Promise<WorkSkillItem[]>;
    pickAttachments(): Promise<WorkAttachment[]>;
    saveClipboardImage(dataUrl: string, name?: string): Promise<WorkAttachment>;
    attachmentsFromPaths(filePaths: string[]): Promise<WorkAttachment[]>;
  };

  opencode: {
    config(): Promise<OpenCodeConfigSnapshot>;
    saveConfig(patch: OpenCodeConfigSavePatch): Promise<OpenCodeConfigSnapshot>;
    upsertProvider(input: OpenCodeProviderInput): Promise<OpenCodeConfigSnapshot>;
    deleteProvider(id: string): Promise<OpenCodeConfigSnapshot>;
    providerCatalog(workspacePath?: string | null): Promise<WorkProviderCatalogItem[]>;
    setProviderApiKey(providerId: string, apiKey: string): Promise<OpenCodeConfigSnapshot>;
    startProviderOAuth(
      providerId: string,
      methodIndex: number,
      inputs?: Record<string, string>,
      workspacePath?: string | null,
    ): Promise<WorkProviderOAuthStart>;
    completeProviderOAuth(
      providerId: string,
      methodIndex: number,
      code?: string,
      workspacePath?: string | null,
    ): Promise<OpenCodeConfigSnapshot>;
    writeWhitzProvider(): Promise<OpenCodeConfigSnapshot>;
    removeWhitzProvider(): Promise<OpenCodeConfigSnapshot>;
    openConfigDir(): Promise<void>;
    mcpList(workspacePath?: string | null): Promise<WorkMcpServerInfo[]>;
    upsertMcp(input: WorkMcpServerInput): Promise<WorkMcpServerInfo[]>;
    deleteMcp(name: string): Promise<WorkMcpServerInfo[]>;
    toggleMcp(name: string, connect: boolean, workspacePath?: string | null): Promise<WorkMcpServerInfo[]>;
    authMcp(name: string, workspacePath?: string | null): Promise<WorkMcpServerInfo[]>;
    removeMcpAuth(name: string, workspacePath?: string | null): Promise<WorkMcpServerInfo[]>;
    lspStatus(workspacePath?: string | null): Promise<WorkLspStatus[]>;
    formatterStatus(workspacePath?: string | null): Promise<WorkFormatterStatus[]>;
    vcsInfo(workspacePath?: string | null): Promise<{ branch: string | null }>;
    gatewayStatus(): Promise<LocalGatewayStatus>;
  };

  pty: {
    shells(workspacePath?: string | null): Promise<WorkShellOption[]>;
    list(workspacePath?: string | null): Promise<WorkPtyInfo[]>;
    create(options?: {
      command?: string;
      args?: string[];
      cwd?: string;
      title?: string;
      workspacePath?: string | null;
    }): Promise<WorkPtyInfo>;
    update(
      ptyId: string,
      patch: { title?: string; size?: { rows: number; cols: number } },
      workspacePath?: string | null,
    ): Promise<WorkPtyInfo>;
    remove(ptyId: string, workspacePath?: string | null): Promise<void>;
    connectInfo(ptyId: string, workspacePath?: string | null): Promise<WorkPtyConnectInfo>;
  };

  worktree: {
    list(workspacePath?: string | null): Promise<string[]>;
    create(name?: string, workspacePath?: string | null): Promise<WorkWorktreeInfo>;
    remove(directory: string, workspacePath?: string | null): Promise<void>;
    reset(directory: string, workspacePath?: string | null): Promise<void>;
  };

  workspace: {
    list(): Promise<WorkWorkspace[]>;
    active(): Promise<WorkWorkspace | null>;
    pick(): Promise<WorkWorkspace | null>;
    select(workspacePath: string): Promise<WorkWorkspace | null>;
    remove(workspacePath: string): Promise<void>;
    openExplorer(targetPath?: string): Promise<void>;
    openInEditor(relPath: string): Promise<void>;
    tree(relDir?: string, includeHidden?: boolean): Promise<WorkspaceEntry[]>;
    searchFiles(query: string): Promise<string[]>;
    findText(pattern: string, workspacePath?: string | null): Promise<WorkFindMatch[]>;
    findSymbols(query: string, workspacePath?: string | null): Promise<WorkSymbolMatch[]>;
    read(relPath: string): Promise<WorkspaceFileContent>;
    gitStatus(): Promise<WorkspaceGitStatus>;
    gitDiff(relPath?: string): Promise<string>;
    gitRevertFile(relPath: string): Promise<void>;
  };

  net: {
    get(): Promise<ConnectivityState>;
    forceOffline(value: boolean): Promise<ConnectivityState>;
    check(): Promise<ConnectivityState>;
  };

  onWorkEvent(cb: (payload: { conversationId: string; event: WorkEvent }) => void): () => void;
  onWorkGlobalEvent(cb: (event: WorkGlobalEvent) => void): () => void;
  onWorkFocusConversation(cb: (conversationId: string) => void): () => void;
  onRuntimeProgress(cb: (progress: RuntimeProgress) => void): () => void;
  onRuntimeStatus(cb: (status: RuntimeStatusResult) => void): () => void;
  onAuthChanged(cb: (session: DesktopSession | null) => void): () => void;
  onConnectivity(cb: (state: ConnectivityState) => void): () => void;
  onPolicyChanged(cb: (policy: PolicyView) => void): () => void;
  onMenuAction(cb: (action: string) => void): () => void;
  onUpdateDownloaded(cb: (payload: { version: string }) => void): () => void;
}

export type WorkSendResult = { run_id: string | null };
export type { WorkMessage };
