import { app } from "electron";
import { EventEmitter } from "node:events";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { apiRequest } from "../api";
import { loadConfig, storagePaths } from "../config";
import { scoped } from "../logger";
import type { DesktopPolicyEnvelope, DesktopPolicyPayload, PolicyView } from "../../shared/ipc-contract";

const logger = scoped("policy");
export const policyEvents = new EventEmitter();

interface CachedPolicy {
  envelope: DesktopPolicyEnvelope;
  fetched_at: string;
}

function cacheFile(): string {
  return path.join(storagePaths().root, "policy.json");
}

function publicKey(): string | null {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, "policy_pubkey.pem")]
    : [path.join(__dirname, "../../resources/policy_pubkey.pem"), path.join(process.cwd(), "resources/policy_pubkey.pem")];
  for (const file of candidates) {
    try {
      if (fs.existsSync(file)) return fs.readFileSync(file, "utf-8");
    } catch {
      /* ignore */
    }
  }
  return null;
}

interface VerifiedPolicy {
  payload: DesktopPolicyPayload;
  verified: boolean;
}

function verifyEnvelope(envelope: DesktopPolicyEnvelope): VerifiedPolicy | null {
  let payload: DesktopPolicyPayload;
  try {
    payload = JSON.parse(envelope.payload) as DesktopPolicyPayload;
  } catch {
    return null;
  }
  if (typeof payload.version !== "number" || !payload.work_mode) return null;
  const key = publicKey();
  if (!key) {
    // Development builds ship without a public key: trust the payload but mark it unverified.
    logger.warn("policy public key missing, accepting unsigned policy");
    return { payload, verified: false };
  }
  if (!envelope.signature) return null;
  try {
    const ok = crypto.verify(
      null,
      Buffer.from(envelope.payload, "utf-8"),
      key,
      Buffer.from(envelope.signature, "base64"),
    );
    if (!ok) return null;
    return { payload, verified: true };
  } catch (err) {
    logger.warn("policy signature verification failed", err);
    return null;
  }
}

function readCache(): CachedPolicy | null {
  try {
    const file = cacheFile();
    if (!fs.existsSync(file)) return null;
    return JSON.parse(fs.readFileSync(file, "utf-8")) as CachedPolicy;
  } catch {
    return null;
  }
}

function writeCache(envelope: DesktopPolicyEnvelope): void {
  const file = cacheFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ envelope, fetched_at: new Date().toISOString() }), "utf-8");
}

function defaultPolicy(reason: string | null, enabled?: boolean): PolicyView {
  const config = loadConfig();
  return {
    enabled: enabled ?? config.workModeDefault,
    source: "default",
    verified: false,
    version: 0,
    not_after: null,
    disabled_reason: reason,
    min_app_version: null,
    latest_version: null,
    fetched_at: null,
  };
}

function isExpired(payload: DesktopPolicyPayload): boolean {
  const notAfter = Date.parse(payload.not_after);
  if (Number.isNaN(notAfter)) return true;
  return Date.now() > notAfter;
}

function meetsMinVersion(min: string | null): boolean {
  if (!min) return true;
  const current = app.getVersion();
  const a = current.split(".").map((n) => Number.parseInt(n, 10) || 0);
  const b = min.split(".").map((n) => Number.parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const left = a[i] ?? 0;
    const right = b[i] ?? 0;
    if (left !== right) return left > right;
  }
  return true;
}

function toView(payload: DesktopPolicyPayload, verified: boolean, source: PolicyView["source"], fetchedAt: string | null): PolicyView {
  const expired = isExpired(payload);
  const versionOk = meetsMinVersion(payload.work_mode.min_app_version || payload.desktop?.min_app_version || null);
  const enabled = Boolean(payload.work_mode.enabled) && !expired && versionOk;
  return {
    enabled,
    source,
    verified,
    version: payload.version,
    not_after: payload.not_after,
    disabled_reason: expired
      ? "策略已过期，请连接网络后重试"
      : !versionOk
        ? `需要升级到 ${payload.work_mode.min_app_version} 或更高版本`
        : payload.work_mode.disabled_reason ?? null,
    min_app_version: payload.work_mode.min_app_version ?? payload.desktop?.min_app_version ?? null,
    latest_version: payload.desktop?.latest_version ?? null,
    fetched_at: fetchedAt,
  };
}

let current: PolicyView | null = null;

export function getPolicy(): PolicyView {
  if (/^(1|true)$/i.test(process.env.WHITZ_DISABLE_WORK ?? "")) {
    return {
      ...(current ?? defaultPolicy(null)),
      enabled: false,
      disabled_reason: "本地兜底已禁用 Work 模式",
    };
  }
  if (current) return current;
  const cached = readCache();
  if (cached) {
    const result = verifyEnvelope(cached.envelope);
    if (result && !isExpired(result.payload)) {
      current = toView(result.payload, result.verified, "cache", cached.fetched_at);
      return current;
    }
    // An expired or tampered cache must fail closed: Work stays off until a fresh
    // signed policy is fetched from the server.
    current = defaultPolicy(
      result ? "策略已过期，请连接网络后重试" : "策略验签失败，已按关闭处理",
      false,
    );
    return current;
  }
  current = defaultPolicy(null);
  return current;
}

export function isWorkModeEnabled(): boolean {
  return getPolicy().enabled;
}

export async function refreshPolicy(): Promise<PolicyView> {
  try {
    const envelope = await apiRequest<DesktopPolicyEnvelope>("/desktop/policy", { timeoutMs: 8000 });
    if (!envelope?.payload) return getPolicy();
    const result = verifyEnvelope(envelope);
    if (!result) {
      current = defaultPolicy("策略验签失败，已按关闭处理", false);
      policyEvents.emit("changed", current);
      return current;
    }
    const cached = readCache();
    const cachedResult = cached ? verifyEnvelope(cached.envelope) : null;
    if (cachedResult && result.payload.version < cachedResult.payload.version) {
      return getPolicy();
    }
    writeCache(envelope);
    current = toView(result.payload, result.verified, "remote", new Date().toISOString());
    policyEvents.emit("changed", current);
    return current;
  } catch (err) {
    logger.warn("policy refresh failed", err);
    return getPolicy();
  }
}

export function resetPolicyCacheForTests(): void {
  current = null;
}
