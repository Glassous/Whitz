import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { dialog } from "electron";
import { getWorkSettings } from "../work/settings";
import { getMainWindow } from "../window";
import type { RuntimeSource } from "../../shared/work-types";

export interface RuntimeMeta {
  version: string;
  dir: string;
  exe: string;
  installed_at: string;
  source: RuntimeSource;
}

function resolveWrapperToExe(candidate: string): string {
  const lower = candidate.toLowerCase();
  if (lower.endsWith(".exe")) return candidate;
  const dir = path.dirname(candidate);
  const directExe = path.join(dir, "opencode.exe");
  if (fs.existsSync(directExe)) return directExe;
  const npmNative = path.join(dir, "node_modules", "opencode-ai", "bin", "opencode.exe");
  if (fs.existsSync(npmNative)) return npmNative;
  const npmCmdDir = path.join(dir, "..", "node_modules", "opencode-ai", "bin", "opencode.exe");
  if (fs.existsSync(npmCmdDir)) return path.resolve(npmCmdDir);
  return candidate;
}

export function findOpenCodeInPath(): { exe: string; source: RuntimeSource } | null {
  try {
    const cmd = process.platform === "win32" ? "where.exe" : "which";
    const out = execFileSync(cmd, ["opencode"], { encoding: "utf-8", windowsHide: true, timeout: 4000 });
    for (const line of out.split(/\r?\n/)) {
      const candidate = line.trim();
      if (!candidate || !fs.existsSync(candidate)) continue;
      const resolved = resolveWrapperToExe(candidate);
      if (fs.existsSync(resolved)) {
        const lower = resolved.toLowerCase();
        const source: RuntimeSource = lower.includes("scoop")
          ? "scoop"
          : lower.includes("winget")
            ? "winget"
            : lower.includes("node_modules")
              ? "npm"
              : "system";
        return { exe: resolved, source };
      }
    }
  } catch {
    /* not on PATH */
  }
  return null;
}

export function findOpenCodeCandidates(): Array<{ exe: string; source: RuntimeSource }> {
  const home = os.homedir();
  const appData = process.env.APPDATA || path.join(home, "AppData", "Roaming");
  const localAppData = process.env.LOCALAPPDATA || path.join(home, "AppData", "Local");
  if (process.platform !== "win32") {
    return [
      { exe: path.join(home, ".opencode", "bin", "opencode"), source: "system" },
      { exe: "/usr/local/bin/opencode", source: "system" },
      { exe: "/opt/homebrew/bin/opencode", source: "system" },
    ];
  }
  return [
    { exe: path.join(appData, "npm", "node_modules", "opencode-ai", "bin", "opencode.exe"), source: "npm" },
    { exe: path.join(home, ".opencode", "bin", "opencode.exe"), source: "system" },
    { exe: path.join(home, "scoop", "apps", "opencode", "current", "opencode.exe"), source: "scoop" },
    { exe: path.join(home, "scoop", "shims", "opencode.exe"), source: "scoop" },
    { exe: path.join(localAppData, "Microsoft", "WinGet", "Links", "opencode.exe"), source: "winget" },
    { exe: path.join(appData, "npm", "opencode.cmd"), source: "npm" },
  ];
}

export function readVersion(exe: string): Promise<string> {
  return new Promise((resolve) => {
    const batch = /\.(cmd|bat)$/i.test(exe);
    const child = batch
      ? spawn(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", `""${exe}" --version"`], {
          windowsHide: true,
          windowsVerbatimArguments: true,
        })
      : spawn(exe, ["--version"], { windowsHide: true });
    let out = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve("unknown");
    }, 15_000);
    child.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString("utf-8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      out += chunk.toString("utf-8");
    });
    child.on("error", () => {
      clearTimeout(timer);
      resolve("unknown");
    });
    child.on("close", () => {
      clearTimeout(timer);
      const match = /v?(\d+\.\d+\.\d+(?:[-+][\w.]+)?)/.exec(out);
      resolve(match ? match[1] : "unknown");
    });
  });
}

let cachedMeta: RuntimeMeta | null | undefined;
const versionProbeInFlight = new Set<string>();

function probeExeVersionAsync(exe: string, onUpdated?: () => void): void {
  if (versionProbeInFlight.has(exe)) return;
  versionProbeInFlight.add(exe);
  void readVersion(exe)
    .then((version) => {
      if (cachedMeta && cachedMeta.exe === exe && version && version !== "unknown") {
        cachedMeta.version = version;
        onUpdated?.();
      }
    })
    .finally(() => versionProbeInFlight.delete(exe));
}

function buildMeta(exe: string, source: RuntimeSource, onUpdated?: () => void): RuntimeMeta {
  let installedAt = new Date().toISOString();
  try {
    installedAt = fs.statSync(exe).mtime.toISOString();
  } catch {
    /* ignore */
  }
  const meta: RuntimeMeta = {
    version: "local",
    dir: path.dirname(exe),
    exe,
    installed_at: installedAt,
    source,
  };
  cachedMeta = meta;
  probeExeVersionAsync(exe, onUpdated);
  return meta;
}

export function resetRuntimeDetectCache(): void {
  cachedMeta = undefined;
}

export function autoDetectRuntime(onVersionUpdated?: () => void): RuntimeMeta | null {
  const custom = getWorkSettings().model.custom_opencode_exe?.trim();
  if (custom) {
    const resolvedCustom = resolveWrapperToExe(custom);
    if (fs.existsSync(resolvedCustom)) {
      if (cachedMeta && cachedMeta.exe === resolvedCustom && cachedMeta.source === "custom") {
        return cachedMeta;
      }
      return buildMeta(resolvedCustom, "custom", onVersionUpdated);
    }
  }

  if (cachedMeta !== undefined) {
    if (cachedMeta && !fs.existsSync(cachedMeta.exe)) {
      cachedMeta = undefined;
    } else {
      return cachedMeta;
    }
  }

  const fromPath = findOpenCodeInPath();
  if (fromPath) {
    return buildMeta(fromPath.exe, fromPath.source, onVersionUpdated);
  }

  for (const candidate of findOpenCodeCandidates()) {
    if (fs.existsSync(candidate.exe)) {
      const resolved = resolveWrapperToExe(candidate.exe);
      return buildMeta(resolved, candidate.source, onVersionUpdated);
    }
  }

  cachedMeta = null;
  return null;
}

export function redetectRuntime(onVersionUpdated?: () => void): RuntimeMeta | null {
  resetRuntimeDetectCache();
  return autoDetectRuntime(onVersionUpdated);
}

export async function pickOpenCodeExe(): Promise<string | null> {
  const win = getMainWindow();
  const options = {
    title: "选择本机 opencode 可执行文件",
    properties: ["openFile"] as Array<"openFile">,
    filters: process.platform === "win32" ? [{ name: "OpenCode CLI", extensions: ["exe", "cmd"] }] : undefined,
  };
  const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
}
