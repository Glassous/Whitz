import fs from "node:fs";
import path from "node:path";
import { storagePaths } from "../config";
import { readOpenCodeJsonDoc } from "../runtime/opencodeConfig";
import { readSecrets } from "../secureStore";
import type { WorkAccessMode, WorkModelSettings, WorkSettings, WorkSettingsPatch } from "../../shared/work-types";

interface StoredWorkSettings {
  version?: number;
  model?: Partial<WorkModelSettings> & { protocol?: string };
  updated_at?: string;
}

function settingsFile(): string {
  return path.join(storagePaths().root, "work-settings.json");
}

function inferDefaultMode(): WorkAccessMode {
  const { doc } = readOpenCodeJsonDoc();
  const hasLocalConfig =
    (typeof doc.model === "string" && Boolean(doc.model.trim())) ||
    Boolean(doc.provider && typeof doc.provider === "object" && Object.keys(doc.provider as object).length > 0);
  if (hasLocalConfig) return "opencode_local";
  if (readSecrets().refresh_token) return "builtin";
  return "opencode_local";
}

function readRaw(): { mode: WorkAccessMode; builtin_model: string; custom_opencode_exe: string; updated_at: string } {
  const fallbackMode = inferDefaultMode();
  try {
    const file = settingsFile();
    if (!fs.existsSync(file)) {
      return {
        mode: fallbackMode,
        builtin_model: "whitz-default",
        custom_opencode_exe: "",
        updated_at: new Date().toISOString(),
      };
    }
    const parsed = JSON.parse(fs.readFileSync(file, "utf-8")) as StoredWorkSettings;
    const rawMode = parsed.model?.mode ?? (parsed.model?.protocol === "builtin" ? "builtin" : undefined);
    const mode: WorkAccessMode = rawMode === "builtin" || rawMode === "opencode_local" ? rawMode : fallbackMode;
    return {
      mode,
      builtin_model: parsed.model?.builtin_model?.trim() || "whitz-default",
      custom_opencode_exe: parsed.model?.custom_opencode_exe?.trim() || "",
      updated_at: parsed.updated_at ?? new Date().toISOString(),
    };
  } catch {
    return {
      mode: fallbackMode,
      builtin_model: "whitz-default",
      custom_opencode_exe: "",
      updated_at: new Date().toISOString(),
    };
  }
}

function activeModelLabel(mode: WorkAccessMode, builtinModel: string): string {
  if (mode === "builtin") return `whitz/${builtinModel || "whitz-default"}`;
  const { doc } = readOpenCodeJsonDoc();
  return typeof doc.model === "string" && doc.model.trim() ? doc.model.trim() : "OpenCode 自动选择";
}

export function getWorkSettings(): WorkSettings {
  const raw = readRaw();
  return {
    version: 2,
    model: {
      mode: raw.mode,
      builtin_model: raw.builtin_model,
      custom_opencode_exe: raw.custom_opencode_exe,
      active_model_label: activeModelLabel(raw.mode, raw.builtin_model),
    },
    updated_at: raw.updated_at,
  };
}

export function saveWorkSettings(patch: WorkSettingsPatch): WorkSettings {
  const raw = readRaw();
  const next = {
    mode: patch.mode ?? raw.mode,
    builtin_model: patch.builtin_model !== undefined ? patch.builtin_model.trim() || "whitz-default" : raw.builtin_model,
    custom_opencode_exe:
      patch.custom_opencode_exe !== undefined ? patch.custom_opencode_exe.trim() : raw.custom_opencode_exe,
    updated_at: new Date().toISOString(),
  };

  const file = settingsFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(
    file,
    JSON.stringify(
      {
        version: 2,
        model: {
          mode: next.mode,
          builtin_model: next.builtin_model,
          custom_opencode_exe: next.custom_opencode_exe,
        },
        updated_at: next.updated_at,
      },
      null,
      2,
    ),
    "utf-8",
  );

  return getWorkSettings();
}
