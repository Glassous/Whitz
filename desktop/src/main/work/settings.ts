import fs from "node:fs";
import path from "node:path";
import { storagePaths } from "../config";
import { readSecrets, writeSecrets, clearSecrets } from "../secureStore";
import type { ProviderProtocol, WorkModelSettings, WorkSettings, WorkSettingsPatch } from "../../shared/work-types";

const DEFAULT_MODEL: WorkModelSettings = {
  protocol: "builtin",
  base_url: "",
  model: "",
  api_key_set: false,
  supports_vision: true,
  approvals: "smart",
  max_turns: 60,
};

function settingsFile(): string {
  return path.join(storagePaths().root, "work-settings.json");
}

function readRaw(): WorkSettings {
  try {
    const file = settingsFile();
    if (!fs.existsSync(file)) {
      return { version: 1, model: { ...DEFAULT_MODEL }, updated_at: new Date().toISOString() };
    }
    const parsed = JSON.parse(fs.readFileSync(file, "utf-8")) as WorkSettings;
    return {
      version: 1,
      model: { ...DEFAULT_MODEL, ...(parsed.model ?? {}) },
      updated_at: parsed.updated_at ?? new Date().toISOString(),
    };
  } catch {
    return { version: 1, model: { ...DEFAULT_MODEL }, updated_at: new Date().toISOString() };
  }
}

function hasKey(protocol: ProviderProtocol): boolean {
  const secrets = readSecrets();
  if (protocol === "builtin") return Boolean(secrets.llm_api_key);
  return Boolean(secrets.provider_keys?.[protocol]);
}

export function getProviderKey(protocol: ProviderProtocol): string {
  const secrets = readSecrets();
  if (protocol === "builtin") return secrets.llm_api_key ?? "";
  return secrets.provider_keys?.[protocol] ?? "";
}

export function setProviderKey(protocol: ProviderProtocol, value: string): void {
  if (protocol === "builtin") {
    writeSecrets({ llm_api_key: value });
    return;
  }
  const secrets = readSecrets();
  const keys = { ...(secrets.provider_keys ?? {}) };
  if (value) keys[protocol] = value;
  else delete keys[protocol];
  writeSecrets({ provider_keys: keys });
}

export function getWorkSettings(): WorkSettings {
  const data = readRaw();
  return {
    ...data,
    model: { ...data.model, api_key_set: hasKey(data.model.protocol) },
  };
}

export function saveWorkSettings(patch: WorkSettingsPatch): WorkSettings {
  const current = readRaw();
  const nextModel: WorkModelSettings = {
    ...current.model,
    ...stripKey(patch),
  };
  if (patch.api_key !== undefined) {
    setProviderKey(nextModel.protocol, patch.api_key.trim());
  }
  const next: WorkSettings = {
    version: 1,
    model: nextModel,
    updated_at: new Date().toISOString(),
  };
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(next, null, 2), "utf-8");
  return getWorkSettings();
}

function stripKey(patch: WorkSettingsPatch): Partial<WorkModelSettings> {
  const { api_key: _ignored, ...rest } = patch;
  return rest;
}

export function clearProviderKey(): WorkSettings {
  const data = readRaw();
  if (data.model.protocol === "builtin") {
    clearSecrets(["llm_api_key"]);
  } else {
    const secrets = readSecrets();
    const keys = { ...(secrets.provider_keys ?? {}) };
    delete keys[data.model.protocol];
    writeSecrets({ provider_keys: keys });
  }
  return getWorkSettings();
}

export function resolvedBaseUrl(apiBase: string): string {
  return `${apiBase.replace(/\/api$/, "")}/api/desktop/llm/v1`;
}
