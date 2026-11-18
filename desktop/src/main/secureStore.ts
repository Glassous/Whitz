import { safeStorage } from "electron";
import fs from "node:fs";
import path from "node:path";
import { storagePaths } from "./config";
import { scoped } from "./logger";

const logger = scoped("secrets");

export interface SecretData {
  refresh_token?: string;
  refresh_expires_in?: number;
  last_user?: Record<string, unknown>;
  llm_api_key?: string;
  provider_keys?: Record<string, string>;
  device_id?: string;
}

function targetFile(): string {
  return storagePaths().secrets;
}

function decode(raw: string): SecretData {
  try {
    if (raw.startsWith("enc1:")) {
      if (!safeStorage.isEncryptionAvailable()) return {};
      const buf = Buffer.from(raw.slice(5), "base64");
      return JSON.parse(safeStorage.decryptString(buf)) as SecretData;
    }
    if (raw.startsWith("raw1:")) {
      return JSON.parse(Buffer.from(raw.slice(5), "base64").toString("utf-8")) as SecretData;
    }
    return JSON.parse(raw) as SecretData;
  } catch (err) {
    logger.warn("failed to decode secrets file", err);
    return {};
  }
}

function encode(data: SecretData): string {
  const plain = JSON.stringify(data);
  if (safeStorage.isEncryptionAvailable()) {
    return "enc1:" + safeStorage.encryptString(plain).toString("base64");
  }
  logger.warn("DPAPI unavailable, falling back to obfuscated local storage");
  return "raw1:" + Buffer.from(plain, "utf-8").toString("base64");
}

export function readSecrets(): SecretData {
  const file = targetFile();
  try {
    if (!fs.existsSync(file)) return {};
    return decode(fs.readFileSync(file, "utf-8"));
  } catch (err) {
    logger.warn("failed to read secrets file", err);
    return {};
  }
}

export function writeSecrets(patch: Partial<SecretData>): SecretData {
  const current = readSecrets();
  const next: SecretData = { ...current, ...patch };
  for (const key of Object.keys(next) as Array<keyof SecretData>) {
    if (next[key] === undefined) delete next[key];
  }
  const file = targetFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, encode(next), { encoding: "utf-8", mode: 0o600 });
  fs.renameSync(tmp, file);
  return next;
}

export function clearSecrets(keys: Array<keyof SecretData>): SecretData {
  const current = readSecrets();
  for (const key of keys) delete current[key];
  const file = targetFile();
  if (!fs.existsSync(file)) return current;
  fs.writeFileSync(file, encode(current), { encoding: "utf-8", mode: 0o600 });
  return current;
}

export function getDeviceId(): string {
  const current = readSecrets();
  if (current.device_id) return current.device_id;
  const deviceId = `whitz-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  writeSecrets({ device_id: deviceId });
  return deviceId;
}
