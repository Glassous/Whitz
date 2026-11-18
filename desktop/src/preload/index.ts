import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import { IPC, IPC_EVENTS, type AuthRefreshResult, type PolicyView, type RuntimeStatusResult, type WorkApi } from "../shared/ipc-contract";
import type {
  ConnectivityState,
  DesktopInfo,
  DesktopSession,
  RuntimeProgress,
  RuntimeStatus,
  WorkConversation,
  WorkConversationDetail,
  WorkEvent,
  WorkSettings,
  WorkSettingsPatch,
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
    install: () => invoke<RuntimeStatusResult>(IPC.runtimeInstall),
    start: () => invoke<RuntimeStatusResult>(IPC.runtimeStart),
    stop: () => invoke<RuntimeStatusResult>(IPC.runtimeStop),
    restart: () => invoke<RuntimeStatusResult>(IPC.runtimeRestart),
    openLogs: () => invoke<void>(IPC.runtimeOpenLogs),
  },

  work: {
    list: () => invoke<WorkConversation[]>(IPC.workList),
    create: (title) => invoke<WorkConversation>(IPC.workCreate, title),
    get: (id) => invoke<WorkConversationDetail>(IPC.workGet, id),
    rename: (id, title) => invoke<void>(IPC.workRename, id, title),
    delete: (id) => invoke<void>(IPC.workDelete, id),
    send: (conversationId, content, skillNames) =>
      invoke<{ run_id: string | null }>(IPC.workSend, conversationId, content, skillNames),
    stop: (conversationId) => invoke<void>(IPC.workStop, conversationId),
    approve: (conversationId, requestId, generation, choice) =>
      invoke<void>(IPC.workApprove, conversationId, requestId, generation, choice),
    clarify: (conversationId, requestId, generation, answer) =>
      invoke<void>(IPC.workClarify, conversationId, requestId, generation, answer),
    settings: () => invoke<WorkSettings>(IPC.workSettingsGet),
    saveSettings: (patch: WorkSettingsPatch) => invoke<WorkSettings>(IPC.workSettingsSave, patch),
    clearKey: () => invoke<WorkSettings>(IPC.workSettingsClearKey),
    testModel: () =>
      invoke<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null }>(IPC.workTestModel),
    export: (id) => invoke<{ path: string }>(IPC.workExport, id),
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
