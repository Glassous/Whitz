import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { loadConfig, storagePaths } from "../config";
import { scoped } from "../logger";
import type { RuntimeProgress } from "../../shared/work-types";

const logger = scoped("runtime:install");
const INSTALL_URL = process.env.WHITZ_HERMES_INSTALL_URL || "https://hermes-agent.nousresearch.com/install.ps1";

export interface RuntimeMeta {
  version: string;
  dir: string;
  exe: string;
  installed_at: string;
}

function metaFile(): string {
  return path.join(storagePaths().hermesRuntime, "current.json");
}

export function readRuntimeMeta(): RuntimeMeta | null {
  try {
    const file = metaFile();
    if (!fs.existsSync(file)) return null;
    const meta = JSON.parse(fs.readFileSync(file, "utf-8")) as RuntimeMeta;
    if (!meta.exe || !fs.existsSync(meta.exe)) return null;
    return meta;
  } catch {
    return null;
  }
}

function writeRuntimeMeta(meta: RuntimeMeta): void {
  fs.mkdirSync(path.dirname(metaFile()), { recursive: true });
  fs.writeFileSync(metaFile(), JSON.stringify(meta, null, 2), "utf-8");
}

const EXE_NAMES = ["hermes.exe", "hermes.cmd", "hermes.bat"];

export function findHermesExe(root: string, maxDepth = 4): string | null {
  if (!root || !fs.existsSync(root)) return null;
  const queue: Array<{ dir: string; depth: number }> = [{ dir: root, depth: 0 }];
  while (queue.length) {
    const current = queue.shift()!;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(current.dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(current.dir, entry.name);
      if (entry.isFile() && EXE_NAMES.includes(entry.name.toLowerCase())) return full;
    }
    if (current.depth >= maxDepth) continue;
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (entry.name === "node_modules" || entry.name === "site-packages" || entry.name === "__pycache__") continue;
      queue.push({ dir: path.join(current.dir, entry.name), depth: current.depth + 1 });
    }
  }
  return null;
}

export interface InstallResult {
  ok: boolean;
  meta: RuntimeMeta | null;
  message: string;
  log: string[];
}

function quote(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

function parseProgress(line: string): number | null {
  const match = /(\d{1,3})\s*%/.exec(line);
  if (!match) return null;
  return Math.min(100, Math.max(0, Number.parseInt(match[1], 10)));
}

export async function installRuntime(
  onProgress: (progress: RuntimeProgress) => void,
): Promise<InstallResult> {
  const config = loadConfig();
  const paths = storagePaths();
  if (process.platform !== "win32") {
    return { ok: false, meta: null, message: "当前版本仅支持 Windows", log: [] };
  }
  const tag = config.hermesInstallTag.trim();
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const installDir = path.join(paths.hermesRuntime, tag || stamp);
  fs.mkdirSync(installDir, { recursive: true });
  fs.mkdirSync(paths.hermesHome, { recursive: true });

  onProgress({ phase: "check", percent: 2, message: "正在准备安装 Hermes Agent…" });

  const args = [
    `-HermesHome ${quote(paths.hermesHome)}`,
    `-InstallDir ${quote(installDir)}`,
    "-SkipSetup",
  ];
  if (tag) args.unshift(`-Tag ${quote(tag)}`);
  const script = `& ([scriptblock]::Create((irm ${quote(INSTALL_URL)}))) ${args.join(" ")}`;

  const log: string[] = [];
  const result = await new Promise<{ code: number | null; error: string | null }>((resolve) => {
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
      { windowsHide: true, env: { ...process.env, PYTHONIOENCODING: "utf-8" } },
    );
    const timer = setTimeout(() => {
      child.kill();
      resolve({ code: null, error: "安装超时，请检查网络后重试" });
    }, 30 * 60 * 1000);

    const handle = (chunk: Buffer) => {
      const text = chunk.toString("utf-8");
      for (const line of text.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        log.push(trimmed);
        if (log.length > 400) log.shift();
        const percent = parseProgress(trimmed);
        onProgress({
          phase: percent !== null ? "download" : "extract",
          percent: percent ?? 20,
          message: trimmed.slice(0, 160),
          log_line: trimmed,
        });
      }
    };
    child.stdout.on("data", handle);
    child.stderr.on("data", handle);
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: null, error: err.message });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, error: null });
    });
  });

  if (result.error || result.code !== 0) {
    logger.error("install failed", result.error ?? `exit ${result.code}`, log.slice(-5));
    onProgress({ phase: "error", percent: 100, message: result.error ?? "安装失败，请重试" });
    return { ok: false, meta: null, message: result.error ?? "安装失败，请重试", log };
  }

  onProgress({ phase: "configure", percent: 92, message: "正在校验运行时…" });
  const exe = findHermesExe(installDir);
  if (!exe) {
    onProgress({ phase: "error", percent: 100, message: "未找到 hermes 可执行文件" });
    return { ok: false, meta: null, message: "未找到 hermes 可执行文件", log };
  }
  const version = await readVersion(exe);
  const meta: RuntimeMeta = {
    version,
    dir: installDir,
    exe,
    installed_at: new Date().toISOString(),
  };
  writeRuntimeMeta(meta);
  onProgress({ phase: "done", percent: 100, message: `Hermes ${version} 安装完成` });
  return { ok: true, meta, message: "安装完成", log };
}

export function readVersion(exe: string): Promise<string> {
  return new Promise((resolve) => {
    const child = spawn(exe, ["version"], { windowsHide: true });
    let out = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve("unknown");
    }, 20_000);
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

export function autoDetectRuntime(): RuntimeMeta | null {
  const existing = readRuntimeMeta();
  if (existing) return existing;
  const exe = findHermesExe(storagePaths().hermesRuntime);
  if (!exe) return null;
  const meta: RuntimeMeta = {
    version: "unknown",
    dir: path.dirname(exe),
    exe,
    installed_at: new Date().toISOString(),
  };
  writeRuntimeMeta(meta);
  return meta;
}
