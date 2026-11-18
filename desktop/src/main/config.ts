import { app } from "electron";
import fs from "node:fs";
import path from "node:path";

export interface AppConfig {
  apiBase: string;
  devApiBase: string;
  appOrigin: string;
  updateFeed: string;
  hermesInstallTag: string;
  workModeDefault: boolean;
  requestTimeoutMs: number;
}

const DEFAULTS: AppConfig = {
  apiBase: "https://whitzapi.kamisato.top/api",
  devApiBase: "http://localhost:8001/api",
  appOrigin: "app://whitz",
  updateFeed: "",
  hermesInstallTag: "",
  workModeDefault: true,
  requestTimeoutMs: 30000,
};

let cached: AppConfig | null = null;

function readConfigFile(): Partial<AppConfig> {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, "app-config.json")]
    : [path.join(__dirname, "../../resources/app-config.json"), path.join(process.cwd(), "resources/app-config.json")];
  for (const file of candidates) {
    try {
      if (!fs.existsSync(file)) continue;
      return JSON.parse(fs.readFileSync(file, "utf-8")) as Partial<AppConfig>;
    } catch {
      /* try next candidate */
    }
  }
  return {};
}

export function loadConfig(): AppConfig {
  if (cached) return cached;
  const fromFile = readConfigFile();
  const envBase = process.env.WHITZ_API_BASE?.trim();
  const fileBase = app.isPackaged
    ? fromFile.apiBase || DEFAULTS.apiBase
    : fromFile.devApiBase || DEFAULTS.devApiBase;
  const base = (envBase || fileBase).replace(/\/+$/, "");
  cached = {
    ...DEFAULTS,
    ...fromFile,
    apiBase: base.endsWith("/api") ? base : `${base}/api`,
    updateFeed: (process.env.WHITZ_UPDATE_FEED || fromFile.updateFeed || DEFAULTS.updateFeed).replace(/\/+$/, ""),
  };
  return cached;
}

export const APP_ORIGIN = "app://whitz";
export const APP_INDEX = "app://whitz/index.html";

export interface StoragePaths {
  root: string;
  db: string;
  logs: string;
  hermesRoot: string;
  hermesHome: string;
  hermesRuntime: string;
  hermesProfiles: string;
  secrets: string;
}

export function storagePaths(): StoragePaths {
  const root = app.getPath("userData");
  const hermesRoot = path.join(root, "hermes");
  return {
    root,
    db: path.join(root, "work.db"),
    logs: path.join(root, "logs"),
    hermesRoot,
    hermesHome: path.join(hermesRoot, "home"),
    hermesRuntime: path.join(hermesRoot, "runtime"),
    hermesProfiles: path.join(hermesRoot, "profiles"),
    secrets: path.join(root, "secrets.json"),
  };
}

export function isDev(): boolean {
  return !app.isPackaged;
}
