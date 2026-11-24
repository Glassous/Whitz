import { app, shell } from "electron";
import fs from "node:fs";
import { IPC, IPC_EVENTS } from "../../shared/ipc-contract";
import { loadConfig, storagePaths } from "../config";
import { broadcast, handle } from "./common";
import { readSecrets } from "../secureStore";
import { checkConnectivity, connectivityEvents, getConnectivity, setForcedOffline } from "../net/connectivity";
import { getPolicy, isWorkModeEnabled, policyEvents, refreshPolicy } from "../policy/policyService";
import {
  authEvents,
  currentSession,
  loginCode,
  loginPassword,
  logout,
  persistRefreshToken,
  refreshSession,
  register,
  resetPassword,
  sendCode,
} from "../auth/authService";
import { ensureAutoStarted, getStatus, restartRuntime, runtimeEvents, startRuntime, stopRuntime } from "../runtime/opencodeRuntime";
import { autoDetectRuntime, pickOpenCodeExe, redetectRuntime } from "../runtime/installer";
import { hasAnyActiveRun, setWorkEventSink } from "../work/runner";
import { OpenCodeClient } from "../work/opencodeClient";
import { getMainWindow, setWindowThemeOverlay } from "../window";
import { checkForUpdates, quitAndInstall } from "../updater";
import { scoped } from "../logger";
import { registerWorkHandlers } from "./workHandlers";

const logger = scoped("ipc");

export function registerIpc(): void {
  handle(IPC.appInfo, () => {
    logger.info("desktop bridge ready");
    return {
      version: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
      apiBase: loadConfig().apiBase,
      online: getConnectivity().online,
      loggedIn: Boolean(readSecrets().refresh_token),
      workModeEnabled: isWorkModeEnabled(),
    };
  });

  handle(IPC.appOpenExternal, (url: string) => {
    if (!/^https?:\/\//i.test(url)) throw new Error("仅支持 http/https 链接");
    return shell.openExternal(url);
  });

  handle(IPC.appWindowControl, (action: "minimize" | "maximize" | "close") => {
    const win = getMainWindow();
    if (!win) return;
    if (action === "minimize") win.minimize();
    else if (action === "close") win.close();
    else if (win.isMaximized()) win.unmaximize();
    else win.maximize();
  });

  handle(IPC.appSetThemeOverlay, (dark: boolean) => {
    setWindowThemeOverlay(Boolean(dark));
  });

  handle(IPC.appQuit, () => app.quit());
  handle(IPC.updaterCheck, () => checkForUpdates());
  handle(IPC.updaterInstall, async () => {
    if (hasAnyActiveRun()) throw new Error("当前仍有运行中的 Work 任务，请等待完成或手动停止后再更新");
    if (getStatus().running) {
      await stopRuntime(true).catch(() => undefined);
    }
    quitAndInstall();
  });

  handle(IPC.authSession, () => currentSession());
  handle(IPC.authLoginPassword, (email: string, password: string) => loginPassword(email, password));
  handle(IPC.authLoginCode, (email: string, code: string) => loginCode(email, code));
  handle(IPC.authRegister, (email: string, password: string, displayName: string, code: string) =>
    register(email, password, displayName, code),
  );
  handle(IPC.authSendCode, (email: string, purpose: "login" | "register" | "reset") => sendCode(email, purpose));
  handle(IPC.authResetPassword, (email: string, code: string, password: string) => resetPassword(email, code, password));
  handle(IPC.authRefresh, () => refreshSession());
  handle(IPC.authLogout, () => logout());
  handle(IPC.authPersist, (token: string, expiresIn?: number) => persistRefreshToken(token, expiresIn));

  handle(IPC.policyGet, () => getPolicy());
  handle(IPC.policyRefresh, () => refreshPolicy());

  handle(IPC.runtimeStatus, () => {
    autoDetectRuntime();
    void ensureAutoStarted();
    return { status: getStatus(), policy: getPolicy() };
  });
  handle(IPC.runtimeRedetect, () => {
    redetectRuntime();
    const status = getStatus();
    runtimeEvents.emit("status", status);
    void ensureAutoStarted();
    return { status, policy: getPolicy() };
  });
  handle(IPC.runtimeStart, async () => {
    await startRuntime();
    return { status: getStatus(), policy: getPolicy() };
  });
  handle(IPC.runtimeStop, async () => {
    await stopRuntime();
    return { status: getStatus(), policy: getPolicy() };
  });
  handle(IPC.runtimeRestart, async () => {
    await restartRuntime();
    return { status: getStatus(), policy: getPolicy() };
  });
  handle(IPC.runtimeUpgrade, async (target?: string) => {
    if (!getStatus().running) {
      await startRuntime();
    }
    await new OpenCodeClient().upgradeGlobal(target);
    redetectRuntime();
    await restartRuntime().catch(() => undefined);
    const next = getStatus();
    runtimeEvents.emit("status", next);
    return { ok: true, detail: `已升级至 OpenCode ${next.version ?? ""}`.trim() };
  });
  handle(IPC.runtimeOpenLogs, async () => {
    const dir = storagePaths().logs;
    fs.mkdirSync(dir, { recursive: true });
    await shell.openPath(dir);
  });
  handle(IPC.runtimePickExe, () => pickOpenCodeExe());

  handle(IPC.connectivityGet, () => getConnectivity());
  handle(IPC.connectivityCheck, () => checkConnectivity());
  handle(IPC.connectivityForceOffline, (value: boolean) => setForcedOffline(value));

  setWorkEventSink(({ conversationId, event }) => {
    broadcast(IPC_EVENTS.workEvent, { conversationId, event });
  });

  authEvents.on("changed", (session) => {
    broadcast(IPC_EVENTS.authChanged, session);
    runtimeEvents.emit("status", getStatus());
    if (session) void ensureAutoStarted();
  });
  policyEvents.on("changed", (policy) => {
    broadcast(IPC_EVENTS.policyChanged, policy);
    if (policy.enabled) void ensureAutoStarted();
    else void stopRuntime(true);
  });
  runtimeEvents.on("status", (status) => broadcast(IPC_EVENTS.runtimeStatus, { status, policy: getPolicy() }));
  runtimeEvents.on("progress", (progress) => broadcast(IPC_EVENTS.runtimeProgress, progress));
  connectivityEvents.on("changed", (state) => broadcast(IPC_EVENTS.connectivityChanged, state));

  registerWorkHandlers();
}
