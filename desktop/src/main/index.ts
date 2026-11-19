import "./early";
import { Menu, Tray, app, nativeImage, session } from "electron";
import fs from "node:fs";
import path from "node:path";
import { createMainWindow, handleAppProtocol, quitApp, registerAppProtocol, toggleWindow } from "./window";
import { registerIpc } from "./ipc/register";
import { initLogger, scoped } from "./logger";
import { APP_ORIGIN, loadConfig } from "./config";
import { refreshPolicy } from "./policy/policyService";
import { startConnectivityWatch, stopConnectivityWatch } from "./net/connectivity";
import { ensureLocalOpenAIGateway, stopLocalOpenAIGateway } from "./runtime/localOpenAIGateway";
import { ensureAutoStarted, getStatus, stopRuntime } from "./runtime/opencodeRuntime";
import { closeDb } from "./work/db";
import { initUpdater } from "./updater";

const logger = scoped("main");
let tray: Tray | null = null;

if (process.platform === "win32") {
  app.setAppUserModelId("com.whitz.desktop");
}

registerAppProtocol();

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    createMainWindow();
  });

  app.whenReady().then(async () => {
    initLogger();
    logger.info("starting", { version: app.getVersion(), apiBase: loadConfig().apiBase });
    handleAppProtocol();
    installCsp();
    registerIpc();
    createMainWindow();
    createTray();
    startConnectivityWatch();
    await ensureLocalOpenAIGateway().catch(() => undefined);
    void refreshPolicy().finally(() => {
      void ensureAutoStarted();
    });
    initUpdater();

    app.on("activate", () => createMainWindow());
  }).catch((err: unknown) => {
    logger.error("startup failed", err instanceof Error ? err.message : String(err));
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  let quitting = false;
  app.on("before-quit", (event) => {
    if (quitting) return;
    quitting = true;
    stopConnectivityWatch();
    stopLocalOpenAIGateway();
    if (getStatus().running) {
      event.preventDefault();
      void stopRuntime(true)
        .catch(() => undefined)
        .finally(() => {
          closeDb();
          app.quit();
        });
      return;
    }
    void stopRuntime(true).catch(() => undefined);
    closeDb();
  });
}

function installCsp(): void {
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    "connect-src 'self' https: http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*",
    "media-src 'self' blob: https:",
    "object-src 'none'",
    "frame-src 'none'",
    "base-uri 'self'",
  ].join("; ");
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (!details.url.startsWith(APP_ORIGIN) && !details.url.startsWith("http://localhost:5174")) {
      callback({ responseHeaders: details.responseHeaders });
      return;
    }
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [csp],
      },
    });
  });
}

function createTray(): void {
  const iconPath = [
    path.join(process.resourcesPath ?? "", "icon.ico"),
    path.join(__dirname, "../../resources/icon.ico"),
    path.join(process.cwd(), "resources/icon.ico"),
  ].find((candidate) => candidate && fs.existsSync(candidate));
  if (!iconPath) {
    logger.info("tray icon missing, tray disabled");
    return;
  }
  try {
    tray = new Tray(nativeImage.createFromPath(iconPath));
    tray.setToolTip("Whitz");
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: "显示 / 隐藏 Whitz", click: () => toggleWindow() },
        { type: "separator" },
        { label: "退出", click: () => quitApp() },
      ]),
    );
    tray.on("click", () => toggleWindow());
  } catch (err) {
    logger.warn("tray init failed", err);
    tray = null;
  }
}
