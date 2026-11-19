import crypto from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { storagePaths } from "../config";
import { scoped } from "../logger";
import { isWorkModeEnabled } from "../policy/policyService";
import { readSecrets } from "../secureStore";
import { getActiveWorkspacePath } from "../work/repository";
import { getWorkSettings } from "../work/settings";
import { autoDetectRuntime, findOpenCodeInPath } from "./installer";
import { ensureLocalOpenAIGateway, getLocalGatewayStatus } from "./localOpenAIGateway";
import { buildBridgeConfigContent, findConfiguredWhitzInfo, readOpenCodeJsonDoc } from "./opencodeConfig";
import type { RuntimeStatus } from "../../shared/work-types";

const logger = scoped("opencode");
export const runtimeEvents = new EventEmitter();

let child: ChildProcess | null = null;
let port: number | null = null;
let serverPassword = "";
let state: RuntimeStatus["state"] = "idle";
let detail: string | null = null;
let intentionalStop = false;
let restarts = 0;
let readyPromise: Promise<void> | null = null;
let retryTimer: NodeJS.Timeout | null = null;
let watchdogTimer: NodeJS.Timeout | null = null;
let lastBridgeSignature = "";

function logFile(): string {
  const dir = storagePaths().logs;
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, "opencode.log");
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

function currentModelDisplay(): string {
  const settings = getWorkSettings();
  if (settings.model.mode === "builtin") {
    const whitzInfo = findConfiguredWhitzInfo();
    return `${settings.model.builtin_model || "whitz/whitz-default"} (${whitzInfo.configured ? "原生直连" : "桥接模式"})`;
  }
  const { doc } = readOpenCodeJsonDoc();
  return typeof doc.model === "string" && doc.model ? doc.model : "OpenCode 自动选择";
}

export function opencodeBaseUrl(): string {
  if (!port) return "";
  return `http://127.0.0.1:${port}`;
}

export function opencodeAuthHeader(): Record<string, string> {
  if (!serverPassword) return {};
  const token = Buffer.from(`opencode:${serverPassword}`, "utf-8").toString("base64");
  return { Authorization: `Basic ${token}` };
}

export function getStatus(): RuntimeStatus {
  const meta = autoDetectRuntime(() => {
    runtimeEvents.emit("status", getStatus());
  });
  return {
    installed: Boolean(meta),
    running: Boolean(child && !child.killed && state === "ready"),
    state: isWorkModeEnabled() ? state : "disabled",
    version: meta?.version ?? null,
    latest_version: meta?.version ?? null,
    port,
    home_dir: storagePaths().opencodeConfigDir,
    exe_path: meta?.exe ?? null,
    source: meta?.source ?? null,
    workspace_path: getActiveWorkspacePath(),
    detail: isWorkModeEnabled() ? detail : "Whitz Work 已被禁用",
    model: currentModelDisplay(),
    installed_at: meta?.installed_at ?? null,
    log_path: logFile(),
    gateway: getLocalGatewayStatus(),
  };
}

async function healthy(timeoutMs = 1500): Promise<boolean> {
  if (!port) return false;
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/global/health`, {
      headers: opencodeAuthHeader(),
      signal: AbortSignal.timeout(timeoutMs),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

async function waitForReady(timeoutMs = 45_000): Promise<void> {
  const started = Date.now();
  let delay = 250;
  while (Date.now() - started < timeoutMs) {
    if (!child) throw new Error("OpenCode 服务已退出");
    if (await healthy()) return;
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(1200, Math.round(delay * 1.3));
  }
  throw new Error("OpenCode 服务启动超时，请查看日志");
}

function clearRetryTimer(): void {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function startWatchdog(): void {
  if (watchdogTimer) return;
  watchdogTimer = setInterval(async () => {
    if (intentionalStop || !isWorkModeEnabled()) return;
    if (state !== "ready") return;
    if (!child || child.killed || !(await healthy(2500))) {
      logger.warn("opencode health watchdog triggered restart");
      void restartRuntime().catch((err: Error) => {
        logger.warn("watchdog restart failed", err.message);
      });
    }
  }, 15_000);
  watchdogTimer.unref?.();
}

function stopWatchdog(): void {
  if (watchdogTimer) {
    clearInterval(watchdogTimer);
    watchdogTimer = null;
  }
}

function scheduleReconnect(reason?: string): void {
  if (intentionalStop || !isWorkModeEnabled() || !autoDetectRuntime()) return;
  clearRetryTimer();
  restarts += 1;
  const delayMs = Math.min(15_000, 1500 * Math.min(restarts, 6));
  setState("starting", reason ?? `OpenCode 正在重连（第 ${restarts} 次）…`);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    void ensureAutoStarted();
  }, delayMs);
  retryTimer.unref?.();
}

function canAutoStartNow(): { ok: boolean; reason?: string } {
  if (!isWorkModeEnabled()) return { ok: false, reason: "Whitz Work 已被远程策略禁用" };
  if (!autoDetectRuntime()) return { ok: false, reason: "未检测到本机 OpenCode，请先安装或指定路径" };
  return { ok: true };
}

export async function ensureAutoStarted(): Promise<void> {
  await ensureLocalOpenAIGateway().catch(() => undefined);
  if (intentionalStop) return;
  if (state === "ready" && child && !child.killed) return;
  if (readyPromise) {
    await readyPromise.catch(() => undefined);
    return;
  }
  const check = canAutoStartNow();
  if (!check.ok) {
    if (check.reason && state !== "disabled") {
      setState("idle", check.reason);
    }
    return;
  }
  try {
    await startRuntime();
  } catch (err) {
    const message = err instanceof Error ? err.message : "启动失败";
    logger.warn("opencode auto-start failed, scheduling retry", message);
    scheduleReconnect(`OpenCode 启动失败，正在重试：${message}`);
  }
}

export async function startRuntime(): Promise<RuntimeStatus> {
  if (!isWorkModeEnabled()) throw new Error("Whitz Work 已被远程策略禁用");
  clearRetryTimer();
  await ensureLocalOpenAIGateway();
  if (state === "ready" && child && !child.killed) return getStatus();
  if (readyPromise) {
    await readyPromise;
    return getStatus();
  }
  const meta = autoDetectRuntime() ?? (() => {
    const found = findOpenCodeInPath();
    return found ? { exe: found.exe, dir: path.dirname(found.exe), version: "local", installed_at: "", source: found.source } : null;
  })();
  if (!meta) throw new Error("未检测到本机 OpenCode CLI，请先安装或指定 opencode.exe 路径");

  readyPromise = (async () => {
    setState("starting", "正在启动本机 OpenCode 服务…");
    intentionalStop = false;
    const chosen = await findFreePort();
    port = chosen;
    serverPassword = crypto.randomBytes(18).toString("base64url");

    const bridgeContent = buildBridgeConfigContent();
    lastBridgeSignature = bridgeContent ?? "__native__";

    const workDir = getActiveWorkspacePath();
    const cwd = workDir && fs.existsSync(workDir) ? workDir : process.cwd();
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      OPENCODE_SERVER_PASSWORD: serverPassword,
      NO_PROXY: process.env.NO_PROXY ? `${process.env.NO_PROXY},127.0.0.1,localhost` : "127.0.0.1,localhost",
      no_proxy: process.env.no_proxy ? `${process.env.no_proxy},127.0.0.1,localhost` : "127.0.0.1,localhost",
    };
    if (bridgeContent) {
      env.OPENCODE_CONFIG_CONTENT = bridgeContent;
    } else {
      delete env.OPENCODE_CONFIG_CONTENT;
    }

    const args = ["serve", "--port", String(chosen), "--hostname", "127.0.0.1", "--print-logs", "--log-level", "INFO"];
    appendLog(
      `starting ${meta.exe} ${args.join(" ")} cwd=${cwd} mode=${bridgeContent ? "bridge" : "native"} gateway=${getLocalGatewayStatus().base_url}`,
    );

    const batch = /\.(cmd|bat)$/i.test(meta.exe);
    const proc = batch
      ? spawn(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", `""${meta.exe}" ${args.join(" ")}"`], {
          cwd,
          env,
          windowsHide: true,
          windowsVerbatimArguments: true,
          stdio: ["ignore", "pipe", "pipe"],
        })
      : spawn(meta.exe, args, {
          cwd,
          env,
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
        });

    child = proc;
    proc.stdout?.on("data", (chunk: Buffer) => appendLog(chunk.toString("utf-8").trim()));
    proc.stderr?.on("data", (chunk: Buffer) => appendLog(`[stderr] ${chunk.toString("utf-8").trim()}`));
    proc.on("exit", (code, signal) => {
      appendLog(`opencode exited code=${code} signal=${signal}`);
      const wasActiveProc = child === proc;
      if (wasActiveProc) {
        child = null;
        port = null;
      }
      if (intentionalStop) {
        setState("stopped", "OpenCode 服务已停止");
        return;
      }
      if (wasActiveProc && state === "ready") {
        scheduleReconnect(`OpenCode 意外退出${code !== null ? `（code ${code}）` : ""}，正在自动重启…`);
      }
    });
    proc.on("error", (err) => {
      appendLog(`spawn error: ${err.message}`);
      setState("error", err.message);
    });

    await waitForReady();
    restarts = 0;
    const settings = getWorkSettings();
    const note =
      settings.model.mode === "builtin" && !readSecrets().refresh_token && !readSecrets().llm_api_key
        ? "OpenCode 已就绪；内置模型需先登录 Whitz 账号"
        : null;
    setState("ready", note);
    startWatchdog();
  })();

  try {
    await readyPromise;
  } catch (err) {
    const message = err instanceof Error ? err.message : "启动失败";
    await killCurrentProcess();
    setState("error", message);
    throw new Error(message);
  } finally {
    readyPromise = null;
  }
  return getStatus();
}

async function killCurrentProcess(): Promise<void> {
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
}

export async function stopRuntime(shutdown = false): Promise<RuntimeStatus> {
  clearRetryTimer();
  if (shutdown) stopWatchdog();
  intentionalStop = true;
  await killCurrentProcess();
  setState("stopped", "OpenCode 服务已停止");
  return getStatus();
}

export async function restartRuntime(): Promise<RuntimeStatus> {
  await stopRuntime(false);
  intentionalStop = false;
  return startRuntime();
}

export async function reloadIfConfigChanged(): Promise<void> {
  const nextSig = buildBridgeConfigContent() ?? "__native__";
  if (nextSig !== lastBridgeSignature || !child || state !== "ready") {
    await restartRuntime().catch(() => void ensureAutoStarted());
    return;
  }
  try {
    await fetch(`${opencodeBaseUrl()}/global/dispose`, {
      method: "POST",
      headers: opencodeAuthHeader(),
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    await restartRuntime().catch(() => undefined);
  }
}

export async function syncWorkspaceIfIdle(_hasActiveRun: boolean): Promise<void> {
  runtimeEvents.emit("status", getStatus());
  if (!child || state !== "ready") {
    void ensureAutoStarted();
  }
}
