import type {
  ConnectivityState,
  DesktopInfo,
  DesktopSession,
  RuntimeProgress,
  RuntimeStatus,
  WorkConversation,
  WorkConversationDetail,
  WorkEvent,
  WorkMessage,
  WorkSettings,
  WorkSettingsPatch,
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
  runtimeInstall: "runtime:install",
  runtimeStart: "runtime:start",
  runtimeStop: "runtime:stop",
  runtimeRestart: "runtime:restart",
  runtimeOpenLogs: "runtime:open-logs",

  workList: "work:list",
  workCreate: "work:create",
  workGet: "work:get",
  workRename: "work:rename",
  workDelete: "work:delete",
  workSend: "work:send",
  workStop: "work:stop",
  workApprove: "work:approve",
  workClarify: "work:clarify",
  workTestModel: "work:test-model",
  workSettingsGet: "work:settings-get",
  workSettingsSave: "work:settings-save",
  workSettingsClearKey: "work:settings-clear-key",
  workExport: "work:export",

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
    install(): Promise<RuntimeStatusResult>;
    start(): Promise<RuntimeStatusResult>;
    stop(): Promise<RuntimeStatusResult>;
    restart(): Promise<RuntimeStatusResult>;
    openLogs(): Promise<void>;
  };

  work: {
    list(): Promise<WorkConversation[]>;
    create(title?: string): Promise<WorkConversation>;
    get(id: string): Promise<WorkConversationDetail>;
    rename(id: string, title: string): Promise<void>;
    delete(id: string): Promise<void>;
    send(conversationId: string, content: string, skillNames?: string[]): Promise<{ run_id: string | null }>;
    stop(conversationId: string): Promise<void>;
    approve(conversationId: string, requestId: string, generation: number, choice: "once" | "always" | "deny"): Promise<void>;
    clarify(conversationId: string, requestId: string, generation: number, answer: string): Promise<void>;
    settings(): Promise<WorkSettings>;
    saveSettings(patch: WorkSettingsPatch): Promise<WorkSettings>;
    clearKey(): Promise<WorkSettings>;
    testModel(): Promise<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null }>;
    export(id: string): Promise<{ path: string }>;
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
