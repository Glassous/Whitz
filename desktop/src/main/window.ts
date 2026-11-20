import { BrowserWindow, Menu, app, nativeTheme, protocol, shell } from "electron";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { APP_ORIGIN, isDev } from "./config";
import { readPrefs, writePrefs } from "./prefs";
import { scoped } from "./logger";

const logger = scoped("window");
let mainWindow: BrowserWindow | null = null;

export function registerAppProtocol(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: "app",
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        corsEnabled: true,
        stream: true,
      },
    },
  ]);
}

function rendererRoot(): string {
  return path.join(__dirname, "../renderer");
}

function appIconPath(): string | undefined {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, "icon.ico")]
    : [path.join(__dirname, "../../resources/icon.ico")];
  return candidates.find((file) => fs.existsSync(file));
}

function resolveAsset(pathname: string): string | null {
  const root = path.resolve(rendererRoot());
  const relative = decodeURIComponent(pathname).replace(/^\/+/, "");
  const candidate = path.resolve(root, relative || "index.html");
  if (!candidate.startsWith(root)) return null;
  if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  const index = path.join(root, "index.html");
  return fs.existsSync(index) ? index : null;
}

export function handleAppProtocol(): void {
  protocol.handle("app", async (request) => {
    const url = new URL(request.url);
    if (url.hostname !== "whitz") {
      return new Response("Not found", { status: 404 });
    }
    const file = resolveAsset(url.pathname);
    if (!file) return new Response("Not found", { status: 404 });
    return netFetch(file);
  });
}

async function netFetch(file: string): Promise<Response> {
  const { net } = await import("electron");
  return net.fetch(pathToFileURL(file).toString());
}

export function getMainWindow(): BrowserWindow | null {
  return mainWindow;
}

export function createMainWindow(): BrowserWindow {
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
    return mainWindow;
  }
  Menu.setApplicationMenu(null);
  const prefs = readPrefs();
  const win = new BrowserWindow({
    width: prefs.windowWidth ?? 1280,
    height: prefs.windowHeight ?? 820,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#000000" : "#FFFFFF",
    title: "Whitz",
    icon: appIconPath(),
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#00000000",
      symbolColor: nativeTheme.shouldUseDarkColors ? "#A1A1AA" : "#52525B",
      height: 40,
    },
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });

  win.once("ready-to-show", () => {
    if (prefs.windowMaximized) win.maximize();
    win.show();
  });

  win.on("close", () => {
    const bounds = win.getNormalBounds();
    writePrefs({
      windowWidth: bounds.width,
      windowHeight: bounds.height,
      windowMaximized: win.isMaximized(),
    });
  });

  win.on("closed", () => {
    mainWindow = null;
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });

  win.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(APP_ORIGIN) && !url.startsWith("http://localhost:5174")) {
      event.preventDefault();
      if (/^https?:/i.test(url)) void shell.openExternal(url);
    }
  });

  win.webContents.on("render-process-gone", (_event, details) => {
    logger.error("renderer gone", details.reason);
  });

  win.webContents.on("did-finish-load", () => {
    logger.info("renderer loaded", win.webContents.getURL());
  });

  win.webContents.on("did-fail-load", (_event, code, description, url) => {
    logger.error("renderer failed to load", { code, description, url });
  });

  win.webContents.on("console-message", (_event, level, message) => {
    if (level >= 2) logger.warn("renderer console", message);
  });

  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (isDev() && devUrl) {
    void win.loadURL(devUrl);
  } else {
    void win.loadURL(`${APP_ORIGIN}/index.html`);
  }

  mainWindow = win;
  return win;
}

export function toggleWindow(): void {
  if (!mainWindow) {
    createMainWindow();
    return;
  }
  if (mainWindow.isVisible() && mainWindow.isFocused()) mainWindow.hide();
  else {
    mainWindow.show();
    mainWindow.focus();
  }
}

export function quitApp(): void {
  app.quit();
}
