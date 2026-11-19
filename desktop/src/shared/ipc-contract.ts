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
  WorkMessage,
  WorkSettings,
  WorkSettingsPatch,
  WorkSkillItem,
  WorkWorkspace,
  WorkspaceEntry,
  WorkspaceFileContent,
  WorkspaceGitStatus,
} from "./work-types";

export const IPC = {
  appInfo: "app:info",
  appOpenExternal: "app:open-external",
  appWindowControl: "app:window-control",
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
  runtimeOpenLogs: "runtime:open-logs",
  runtimePickExe: "runtime:pick-exe",

  workList: "work:list",
  workCreate: "work:create",
  workGet: "work:get",
  workRename: "work:rename",
  workPin: "work:pin",
  workDelete: "work:delete",
  workSend: "work:send",
  workSteer: "work:steer",
  workStop: "work:stop",
  workApprove: "work:approve",
  workClarify: "work:clarify",
  workTestModel: "work:test-model",
  workSettingsGet: "work:settings-get",
  workSettingsSave: "work:settings-save",
  workExport: "work:export",
  workSkillsList: "work:skills-list",
  workPickAttachments: "work:pick-attachments",

  opencodeConfigGet: "opencode:config-get",
  opencodeConfigSave: "opencode:config-save",
  opencodeProviderUpsert: "opencode:provider-upsert",
  opencodeProviderDelete: "opencode:provider-delete",
  opencodeWriteWhitz: "opencode:write-whitz",
  opencodeRemoveWhitz: "opencode:remove-whitz",
  opencodeOpenConfigDir: "opencode:open-config-dir",
  gatewayStatus: "gateway:status",

  workspaceList: "workspace:list",
  workspaceActive: "workspace:active",
  workspacePick: "workspace:pick",
  workspaceSelect: "workspace:select",
  workspaceRemove: "workspace:remove",
  workspaceOpenExplorer: "workspace:open-explorer",
  workspaceFsTree: "workspace:fs-tree",
  workspaceFsSearch: "workspace:fs-search",
  workspaceFsRead: "workspace:fs-read",
  workspaceGitStatus: "workspace:git-status",
  workspaceGitDiff: "workspace:git-diff",

  connectivityGet: "net:get",
  connectivityForceOffline: "net:force-offline",
  connectivityCheck: "net:check",
} as const;

export const IPC_EVENTS = {
  workEvent: "work:event",
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
    openLogs(): Promise<void>;
    pickExe(): Promise<string | null>;
  };

  work: {
    list(workspacePath?: string | null): Promise<WorkConversation[]>;
    create(title?: string, workspacePath?: string | null): Promise<WorkConversation>;
    get(id: string): Promise<WorkConversationDetail>;
    rename(id: string, title: string): Promise<void>;
    pin(id: string, isPinned: boolean): Promise<void>;
    delete(id: string): Promise<void>;
    send(
      conversationId: string,
      content: string,
      options?: { skillNames?: string[]; attachments?: WorkAttachment[] },
    ): Promise<{ run_id: string | null }>;
    steer(conversationId: string, content: string): Promise<void>;
    stop(conversationId: string): Promise<void>;
    approve(conversationId: string, requestId: string, generation: number, choice: WorkApprovalChoice): Promise<void>;
    clarify(conversationId: string, requestId: string, generation: number, answer: string): Promise<void>;
    settings(): Promise<WorkSettings>;
    saveSettings(patch: WorkSettingsPatch): Promise<WorkSettings>;
    testModel(): Promise<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null }>;
    export(id: string): Promise<{ path: string }>;
    skills(): Promise<WorkSkillItem[]>;
    pickAttachments(): Promise<WorkAttachment[]>;
  };

  opencode: {
    config(): Promise<OpenCodeConfigSnapshot>;
    saveConfig(patch: OpenCodeConfigSavePatch): Promise<OpenCodeConfigSnapshot>;
    upsertProvider(input: OpenCodeProviderInput): Promise<OpenCodeConfigSnapshot>;
    deleteProvider(id: string): Promise<OpenCodeConfigSnapshot>;
    writeWhitzProvider(): Promise<OpenCodeConfigSnapshot>;
    removeWhitzProvider(): Promise<OpenCodeConfigSnapshot>;
    openConfigDir(): Promise<void>;
    gatewayStatus(): Promise<LocalGatewayStatus>;
  };

  workspace: {
    list(): Promise<WorkWorkspace[]>;
    active(): Promise<WorkWorkspace | null>;
    pick(): Promise<WorkWorkspace | null>;
    select(workspacePath: string): Promise<WorkWorkspace | null>;
    remove(workspacePath: string): Promise<void>;
    openExplorer(targetPath?: string): Promise<void>;
    tree(relDir?: string, includeHidden?: boolean): Promise<WorkspaceEntry[]>;
    searchFiles(query: string): Promise<string[]>;
    read(relPath: string): Promise<WorkspaceFileContent>;
    gitStatus(): Promise<WorkspaceGitStatus>;
    gitDiff(relPath?: string): Promise<string>;
  };

  net: {
    get(): Promise<ConnectivityState>;
    forceOffline(value: boolean): Promise<ConnectivityState>;
    check(): Promise<ConnectivityState>;
  };

  onWorkEvent(cb: (payload: { conversationId: string; event: WorkEvent }) => void): () => void;
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
