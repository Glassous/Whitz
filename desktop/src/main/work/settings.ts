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

interface RawWorkSettings {
  mode: WorkAccessMode;
  builtin_model: string;
  custom_opencode_exe: string;
  enabled_models: string[] | null;
  default_composer_model: string;
  default_agent: string;
  default_variant: string;
  full_command_mode: boolean;
  updated_at: string;
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

function normalizeEnabledModels(raw: unknown): string[] | null {
  if (raw === null || raw === undefined) return null;
  if (!Array.isArray(raw)) return null;
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string") continue;
    const clean = item.trim();
    if (!clean || seen.has(clean)) continue;
    seen.add(clean);
    out.push(clean);
  }
  return out;
}

function readRaw(): RawWorkSettings {
  const fallbackMode = inferDefaultMode();
  try {
    const file = settingsFile();
    if (!fs.existsSync(file)) {
      return {
        mode: fallbackMode,
        builtin_model: "whitz-default",
        custom_opencode_exe: "",
        enabled_models: null,
        default_composer_model: "",
        default_agent: "build",
        default_variant: "",
        full_command_mode: false,
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
      enabled_models: normalizeEnabledModels(parsed.model?.enabled_models),
      default_composer_model: parsed.model?.default_composer_model?.trim() || "",
      default_agent: parsed.model?.default_agent?.trim() || "build",
      default_variant: parsed.model?.default_variant?.trim() || "",
      full_command_mode: Boolean(parsed.model?.full_command_mode),
      updated_at: parsed.updated_at ?? new Date().toISOString(),
    };
  } catch {
    return {
      mode: fallbackMode,
      builtin_model: "whitz-default",
      custom_opencode_exe: "",
      enabled_models: null,
      default_composer_model: "",
      default_agent: "build",
      default_variant: "",
      full_command_mode: false,
      updated_at: new Date().toISOString(),
    };
  }
}

function activeModelLabel(raw: RawWorkSettings): string {
  if (raw.default_composer_model) return raw.default_composer_model;
  if (raw.mode === "builtin") return `whitz/${raw.builtin_model || "whitz-default"}`;
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
      active_model_label: activeModelLabel(raw),
      enabled_models: raw.enabled_models,
      default_composer_model: raw.default_composer_model,
      default_agent: raw.default_agent,
      default_variant: raw.default_variant,
      full_command_mode: raw.full_command_mode,
    },
    updated_at: raw.updated_at,
  };
}

export function saveWorkSettings(patch: WorkSettingsPatch): WorkSettings {
  const raw = readRaw();
  const next: RawWorkSettings = {
    mode: patch.mode ?? raw.mode,
    builtin_model: patch.builtin_model !== undefined ? patch.builtin_model.trim() || "whitz-default" : raw.builtin_model,
    custom_opencode_exe:
      patch.custom_opencode_exe !== undefined ? patch.custom_opencode_exe.trim() : raw.custom_opencode_exe,
    enabled_models:
      patch.enabled_models !== undefined ? normalizeEnabledModels(patch.enabled_models) : raw.enabled_models,
    default_composer_model:
      patch.default_composer_model !== undefined ? patch.default_composer_model.trim() : raw.default_composer_model,
    default_agent: patch.default_agent !== undefined ? patch.default_agent.trim() || "build" : raw.default_agent,
    default_variant: patch.default_variant !== undefined ? patch.default_variant.trim() : raw.default_variant,
    full_command_mode: patch.full_command_mode !== undefined ? Boolean(patch.full_command_mode) : raw.full_command_mode,
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
          enabled_models: next.enabled_models,
          default_composer_model: next.default_composer_model,
          default_agent: next.default_agent,
          default_variant: next.default_variant,
          full_command_mode: next.full_command_mode,
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
