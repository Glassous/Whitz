import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { storagePaths } from "../config";
import { scoped } from "../logger";
import { isWorkModeEnabled } from "../policy/policyService";
import { getWorkSettings } from "../work/settings";
import { autoDetectRuntime, findHermesExe, readRuntimeMeta, type RuntimeMeta } from "./installer";
import { profilePaths, readProfileApiKey, writeHermesConfig, WORK_PROFILE } from "./config";
import type { RuntimeProgress, RuntimeStatus } from "../../shared/work-types";

const logger = scoped("hermes");
export const runtimeEvents = new EventEmitter();

let child: ChildProcess | null = null;
let port: number | null = null;
let state: RuntimeStatus["state"] = "idle";
let detail: string | null = null;
let intentionalStop = false;
let restarts = 0;
let readyPromise: Promise<void> | null = null;

function logFile(): string {
  const dir = storagePaths().logs;
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, "hermes.log");
}

function appendLog(line: string): void {
  try {
    const file = logFile();
    if (fs.existsSync(file) && fs.statSync(file).size > 5 * 1024 * 1024) {
      fs.renameSync(file, `${file}.1`);
    }
    fs.appendFileSync(file, `${new Date().toISOString()} ${line}\n`, "utf-8");
  } catch {
    /* ignore */
  }
}

function setState(next: RuntimeStatus["state"], message: string | null = null): void {
  state = next;
  detail = message;
  runtimeEvents.emit("status", getStatus());
}

function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const chosen = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(chosen));
    });
  });
}

export function getStatus(): RuntimeStatus {
  const meta = autoDetectRuntime();
  const settings = getWorkSettings();
  return {
    installed: Boolean(meta),
    running: Boolean(child && !child.killed && state === "ready"),
    state: isWorkModeEnabled() ? state : "disabled",
    version: meta?.version ?? null,
    latest_version: meta?.version ?? null,
    port,
    home_dir: storagePaths().hermesHome,
    detail: isWorkModeEnabled() ? detail : "Whitz Work 已被禁用",
    model: settings.model.model || (settings.model.protocol === "builtin" ? "Whitz 内置" : ""),
    installed_at: meta?.installed_at ?? null,
    log_path: logFile(),
  };
}

export function gatewayBaseUrl(): string {
  if (!port) return "";
  return `http://127.0.0.1:${port}/p/${WORK_PROFILE}`;
}

export function gatewayApiKey(): string {
  try {
    return readProfileApiKey();
  } catch {
    return "";
  }
}

async function healthy(timeoutMs = 1500): Promise<boolean> {
  if (!port) return false;
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/health`, {
      headers: { Authorization: `Bearer ${gatewayApiKey()}` },
      signal: AbortSignal.timeout(timeoutMs),
    });
    return resp.ok || resp.status === 401 || resp.status === 403;
  } catch {
    return false;
  }
}

async function waitForReady(timeoutMs = 90_000): Promise<void> {
  const started = Date.now();
  let delay = 400;
  while (Date.now() - started < timeoutMs) {
    if (!child) throw new Error("本地运行时已退出");
    if (await healthy()) return;
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(2000, Math.round(delay * 1.4));
  }
  throw new Error("本地运行时启动超时，请查看日志");
}

export async function startRuntime(): Promise<RuntimeStatus> {
  if (!isWorkModeEnabled()) throw new Error("Whitz Work 已被远程策略禁用");
  if (state === "ready" && child) return getStatus();
  if (readyPromise) {
    await readyPromise;
    return getStatus();
  }
  const meta = autoDetectRuntime();
  if (!meta) throw new Error("尚未安装本地 Hermes 运行时");

  readyPromise = (async () => {
    setState("starting", "正在启动本地智能体…");
    intentionalStop = false;
    const { model } = await writeHermesConfig();
    const chosen = await findFreePort();
    port = chosen;
    const exe = meta.exe || findHermesExe(meta.dir);
    if (!exe) throw new Error("找不到 hermes 可执行文件");
    const paths = profilePaths();
    const batch = /\.(cmd|bat)$/i.test(exe);
    const env = {
      ...process.env,
      HERMES_HOME: paths.homeDir,
      API_SERVER_ENABLED: "true",
      API_SERVER_HOST: "127.0.0.1",
      API_SERVER_PORT: String(chosen),
      API_SERVER_KEY: gatewayApiKey() || readProfileApiKey(),
      GATEWAY_MULTIPLEX_PROFILES: "true",
      PYTHONIOENCODING: "utf-8",
    };
    appendLog(`starting ${exe} gateway run --port ${chosen} model=${model}`);
    const proc = batch
      ? spawn(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", `""${exe}" gateway run"`], {
          cwd: paths.homeDir,
          env,
          windowsHide: true,
          windowsVerbatimArguments: true,
          stdio: ["ignore", "pipe", "pipe"],
        })
      : spawn(exe, ["gateway", "run"], {
          cwd: paths.homeDir,
          env,
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
        });
    child = proc;
    proc.stdout?.on("data", (chunk: Buffer) => appendLog(chunk.toString("utf-8").trim()));
    proc.stderr?.on("data", (chunk: Buffer) => appendLog(`[stderr] ${chunk.toString("utf-8").trim()}`));
    proc.on("exit", (code, signal) => {
      appendLog(`gateway exited code=${code} signal=${signal}`);
      const wasReady = state === "ready";
      child = null;
      port = null;
      if (intentionalStop) {
        setState("stopped", "本地智能体已停止");
        return;
      }
      if (wasReady && restarts < 3) {
        restarts += 1;
        setState("starting", `本地智能体异常退出，正在重启（${restarts}/3）…`);
        setTimeout(() => {
          void startRuntime().catch((err: Error) => setState("error", err.message));
        }, 1500 * restarts);
        return;
      }
      setState("error", `本地智能体已退出${code !== null ? `（code ${code}）` : ""}`);
    });
    proc.on("error", (err) => {
      appendLog(`spawn error: ${err.message}`);
      setState("error", err.message);
    });

    await waitForReady();
    restarts = 0;
    setState("ready", null);
  })();

  try {
    await readyPromise;
  } catch (err) {
    const message = err instanceof Error ? err.message : "启动失败";
    setState("error", message);
    await stopRuntime();
    throw new Error(message);
  } finally {
    readyPromise = null;
  }
  return getStatus();
}

export async function stopRuntime(): Promise<RuntimeStatus> {
  intentionalStop = true;
  const proc = child;
  if (proc?.pid) {
    if (process.platform === "win32") {
      await new Promise<void>((resolve) => {
        const killer = spawn("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { windowsHide: true });
        killer.on("close", () => resolve());
        killer.on("error", () => resolve());
      });
    } else {
      proc.kill("SIGTERM");
      setTimeout(() => proc.kill("SIGKILL"), 3000).unref?.();
    }
  }
  child = null;
  port = null;
  setState("stopped", "本地智能体已停止");
  return getStatus();
}

export async function restartRuntime(): Promise<RuntimeStatus> {
  await stopRuntime();
  return startRuntime();
}

export function isRuntimeBusy(): boolean {
  return state === "starting" || state === "installing";
}

export function emitProgress(progress: RuntimeProgress): void {
  runtimeEvents.emit("progress", progress);
}

export function runtimeMeta(): RuntimeMeta | null {
  return readRuntimeMeta();
}
