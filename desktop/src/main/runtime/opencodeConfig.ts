import fs from "node:fs";
import path from "node:path";
import { storagePaths } from "../config";
import { scoped } from "../logger";
import type {
  OpenCodeConfigSavePatch,
  OpenCodeConfigSnapshot,
  OpenCodeModelOption,
  OpenCodePermissionPreset,
  OpenCodeProviderInfo,
  OpenCodeProviderInput,
  WorkMcpServerConfig,
  WorkMcpServerInfo,
  WorkMcpServerInput,
} from "../../shared/work-types";
import { localGatewayBaseUrl } from "./localOpenAIGateway";

const logger = scoped("opencode:config");

export interface OpenCodeFiles {
  configDir: string;
  dataDir: string;
  configFile: string;
  jsoncFile: string;
  agentsFile: string;
  authFile: string;
}

export function opencodeFiles(): OpenCodeFiles {
  const { opencodeConfigDir, opencodeDataDir } = storagePaths();
  return {
    configDir: opencodeConfigDir,
    dataDir: opencodeDataDir,
    configFile: path.join(opencodeConfigDir, "opencode.json"),
    jsoncFile: path.join(opencodeConfigDir, "opencode.jsonc"),
    agentsFile: path.join(opencodeConfigDir, "AGENTS.md"),
    authFile: path.join(opencodeDataDir, "auth.json"),
  };
}

function stripJsonComments(input: string): string {
  let out = "";
  let inString = false;
  let escape = false;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    const next = input[i + 1];
    if (inString) {
      out += ch;
      if (escape) escape = false;
      else if (ch === "\\") escape = true;
      else if (ch === "\"") inString = false;
      continue;
    }
    if (ch === "\"") {
      inString = true;
      out += ch;
      continue;
    }
    if (ch === "/" && next === "/") {
      while (i < input.length && input[i] !== "\n") i += 1;
      out += "\n";
      continue;
    }
    if (ch === "/" && next === "*") {
      i += 2;
      while (i < input.length && !(input[i] === "*" && input[i + 1] === "/")) i += 1;
      i += 1;
      continue;
    }
    out += ch;
  }
  return out.replace(/,\s*([}\]])/g, "$1");
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return Boolean(v && typeof v === "object" && !Array.isArray(v));
}

export function readOpenCodeJsonDoc(): { doc: Record<string, unknown>; activeFile: string } {
  const files = opencodeFiles();
  const candidates = [files.configFile, files.jsoncFile];
  for (const file of candidates) {
    if (!fs.existsSync(file)) continue;
    try {
      const raw = fs.readFileSync(file, "utf-8");
      const parsed = JSON.parse(stripJsonComments(raw));
      if (isRecord(parsed)) {
        return { doc: parsed, activeFile: file };
      }
    } catch (err) {
      logger.warn("failed reading opencode config", { file, error: err instanceof Error ? err.message : String(err) });
    }
  }
  return {
    doc: { $schema: "https://opencode.ai/config.json" },
    activeFile: files.configFile,
  };
}

export function writeOpenCodeJsonDoc(doc: Record<string, unknown>): string {
  const files = opencodeFiles();
  fs.mkdirSync(files.configDir, { recursive: true });
  if (!doc.$schema) doc.$schema = "https://opencode.ai/config.json";
  fs.writeFileSync(files.configFile, `${JSON.stringify(doc, null, 2)}\n`, "utf-8");
  return files.configFile;
}

export function readOpenCodeAgentsMd(): string {
  const { agentsFile } = opencodeFiles();
  try {
    return fs.existsSync(agentsFile) ? fs.readFileSync(agentsFile, "utf-8") : "";
  } catch {
    return "";
  }
}

export function writeOpenCodeAgentsMd(content: string): void {
  const { configDir, agentsFile } = opencodeFiles();
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(agentsFile, content, "utf-8");
}

function readAuthJson(): Record<string, unknown> {
  const { authFile } = opencodeFiles();
  try {
    if (!fs.existsSync(authFile)) return {};
    const parsed = JSON.parse(fs.readFileSync(authFile, "utf-8"));
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeAuthKeyToDisk(providerId: string, apiKey: string | null): void {
  const { dataDir, authFile } = opencodeFiles();
  const auth = readAuthJson();
  if (apiKey) {
    auth[providerId] = { type: "api", key: apiKey };
  } else {
    delete auth[providerId];
  }
  fs.mkdirSync(dataDir, { recursive: true });
  fs.writeFileSync(authFile, `${JSON.stringify(auth, null, 2)}\n`, "utf-8");
}

export function findConfiguredWhitzInfo(doc?: Record<string, unknown>): {
  configured: boolean;
  providerId: string | null;
  baseURL: string | null;
} {
  const target = doc ?? readOpenCodeJsonDoc().doc;
  const providers = isRecord(target.provider) ? target.provider : null;
  if (!providers) return { configured: false, providerId: null, baseURL: null };

  if (isRecord(providers.whitz)) {
    const opts = isRecord(providers.whitz.options) ? providers.whitz.options : null;
    const baseURL = typeof opts?.baseURL === "string" ? opts.baseURL : null;
    return { configured: true, providerId: "whitz", baseURL };
  }

  for (const [id, entry] of Object.entries(providers)) {
    if (!isRecord(entry)) continue;
    const opts = isRecord(entry.options) ? entry.options : null;
    const base = typeof opts?.baseURL === "string" ? opts.baseURL : "";
    if (/^http:\/\/(127\.0\.0\.1|localhost):184\d\d(\/v1)?$/i.test(base)) {
      return { configured: true, providerId: id, baseURL: base };
    }
  }
  return { configured: false, providerId: null, baseURL: null };
}

function normalizeUrlBase(url: string | null | undefined): string {
  return (url ?? "").trim().replace(/\/+$/, "");
}

/**
 * Case 1 vs Case 2:
 * - Case 1: User's opencode.json does NOT have `whitz` -> return OPENCODE_CONFIG_CONTENT overlay
 *   so Whitz Work bridges `whitz/whitz-default` into OpenCode without touching disk config.
 * - Case 2: User's opencode.json ALREADY has `whitz` -> return null so native OpenCode reads
 *   the disk config directly and calls our localhost OpenAI gateway natively.
 */
export function buildBridgeConfigContent(): string | null {
  const gatewayUrl = localGatewayBaseUrl();
  if (!gatewayUrl) return null;
  const info = findConfiguredWhitzInfo();
  if (info.configured) {
    return null;
  }
  return JSON.stringify({
    provider: {
      whitz: {
        npm: "@ai-sdk/openai-compatible",
        name: "Whitz 内置",
        options: {
          baseURL: gatewayUrl,
          apiKey: "whitz-local",
          setCacheKey: true,
        },
        models: {
          "whitz-default": {
            name: "Whitz 内置模型",
          },
        },
      },
    },
  });
}

function permissionPresetFrom(raw: unknown): OpenCodePermissionPreset {
  if (raw === "allow") return "allow_all";
  if (raw === "ask") return "ask_all";
  if (isRecord(raw)) {
    if (raw.edit === "ask" && isRecord(raw.bash)) return "smart";
  }
  if (raw === undefined || raw === null) return "smart";
  return "custom";
}

function permissionConfigForPreset(preset: Exclude<OpenCodePermissionPreset, "custom">): unknown {
  if (preset === "allow_all") return "allow";
  if (preset === "ask_all") return "ask";
  return {
    edit: "ask",
    bash: {
      "*": "ask",
      "git status*": "allow",
      "git diff*": "allow",
      "git log*": "allow",
      "ls *": "allow",
      "dir *": "allow",
    },
    webfetch: "allow",
    external_directory: "ask",
  };
}

export function syncFullCommandPermissionOnDisk(enabled: boolean): void {
  const { doc } = readOpenCodeJsonDoc();
  if (enabled) {
    if (doc.permission === "allow") return;
    const base: Record<string, unknown> = isRecord(doc.permission)
      ? { ...doc.permission }
      : {
          edit: doc.permission === "ask" ? "ask" : "ask",
          webfetch: "allow",
          external_directory: "ask",
        };
    base.bash = "allow";
    doc.permission = base;
    writeOpenCodeJsonDoc(doc);
    return;
  }
  if (isRecord(doc.permission) && doc.permission.bash === "allow") {
    doc.permission = {
      ...doc.permission,
      bash: {
        "*": "ask",
        "git status*": "allow",
        "git diff*": "allow",
        "git log*": "allow",
        "ls *": "allow",
        "dir *": "allow",
      },
    };
    writeOpenCodeJsonDoc(doc);
  }
}

export interface LiveProviderPayload {
  all?: Array<{
    id: string;
    name?: string;
    source?: "env" | "config" | "custom" | "api";
    key?: string;
    options?: Record<string, unknown>;
    models?: Record<
      string,
      {
        id?: string;
        name?: string;
        api?: { npm?: string; url?: string };
        variants?: Record<string, unknown>;
        limit?: { context?: number; output?: number };
        capabilities?: {
          reasoning?: boolean;
          attachment?: boolean;
          input?: { text?: boolean; image?: boolean; pdf?: boolean };
        };
      }
    >;
  }>;
  connected?: string[];
}

function parseMcpEntry(raw: unknown): WorkMcpServerConfig | null {
  if (!isRecord(raw)) return null;
  const type = raw.type === "remote" ? "remote" : "local";
  const enabled = typeof raw.enabled === "boolean" ? raw.enabled : true;
  if (type === "remote") {
    return {
      type: "remote",
      url: typeof raw.url === "string" ? raw.url : "",
      headers: isRecord(raw.headers)
        ? Object.fromEntries(Object.entries(raw.headers).map(([k, v]) => [k, String(v ?? "")]))
        : undefined,
      enabled,
    };
  }
  const command = Array.isArray(raw.command) ? raw.command.map(String).filter(Boolean) : [];
  const environment = isRecord(raw.environment)
    ? Object.fromEntries(Object.entries(raw.environment).map(([k, v]) => [k, String(v ?? "")]))
    : undefined;
  return { type: "local", command, environment, enabled };
}

export function listMcpServersFromDisk(liveStatus?: Record<string, { status: string; error?: string }> | null): WorkMcpServerInfo[] {
  const { doc } = readOpenCodeJsonDoc();
  const diskMcp = isRecord(doc.mcp) ? doc.mcp : {};
  const names = new Set<string>([...Object.keys(diskMcp), ...Object.keys(liveStatus ?? {})]);
  const out: WorkMcpServerInfo[] = [];
  for (const name of names) {
    const cfg = parseMcpEntry(diskMcp[name]);
    const live = liveStatus?.[name];
    const rawStatus = live?.status;
    const status: WorkMcpServerInfo["status"] =
      rawStatus === "connected" ||
      rawStatus === "disabled" ||
      rawStatus === "failed" ||
      rawStatus === "needs_auth" ||
      rawStatus === "needs_client_registration"
        ? rawStatus
        : cfg?.enabled === false
          ? "disabled"
          : "configured";
    out.push({
      name,
      status,
      error: live?.error ?? null,
      config: cfg,
    });
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

export function upsertMcpOnDisk(input: WorkMcpServerInput): WorkMcpServerInfo[] {
  const name = input.name.trim();
  if (!name || !/^[a-zA-Z0-9._-]+$/.test(name)) {
    throw new Error("MCP 名称仅支持字母、数字、点、下划线或短横线");
  }
  const { doc } = readOpenCodeJsonDoc();
  const mcp = isRecord(doc.mcp) ? { ...doc.mcp } : {};
  if (input.type === "remote") {
    const url = (input.url ?? "").trim();
    if (!url) throw new Error("请填写远程 MCP Server URL");
    mcp[name] = {
      type: "remote",
      url,
      ...(input.headers && Object.keys(input.headers).length ? { headers: input.headers } : {}),
      enabled: input.enabled ?? true,
    };
  } else {
    const command = (input.command ?? []).map((s) => s.trim()).filter(Boolean);
    if (!command.length) throw new Error("请填写本地 MCP 启动命令（如 npx -y ...）");
    mcp[name] = {
      type: "local",
      command,
      ...(input.environment && Object.keys(input.environment).length ? { environment: input.environment } : {}),
      enabled: input.enabled ?? true,
    };
  }
  doc.mcp = mcp;
  writeOpenCodeJsonDoc(doc);
  return listMcpServersFromDisk();
}

export function deleteMcpFromDisk(name: string): WorkMcpServerInfo[] {
  const clean = name.trim();
  if (!clean) throw new Error("缺少 MCP 名称");
  const { doc } = readOpenCodeJsonDoc();
  if (isRecord(doc.mcp)) {
    const mcp = { ...doc.mcp };
    delete mcp[clean];
    doc.mcp = mcp;
    writeOpenCodeJsonDoc(doc);
  }
  return listMcpServersFromDisk();
}

export function buildConfigSnapshot(
  live?: LiveProviderPayload | null,
  liveMcp?: Record<string, { status: string; error?: string }> | null,
): OpenCodeConfigSnapshot {
  const { doc } = readOpenCodeJsonDoc();
  const files = opencodeFiles();
  const auth = readAuthJson();
  const gatewayUrl = localGatewayBaseUrl();
  const whitzInfo = findConfiguredWhitzInfo(doc);
  const whitzPortMatches = whitzInfo.configured && normalizeUrlBase(whitzInfo.baseURL) === normalizeUrlBase(gatewayUrl);

  const providerMap = new Map<string, OpenCodeProviderInfo>();
  const modelMeta = new Map<
    string,
    { variants?: string[]; context_limit?: number | null; supports_image?: boolean; supports_pdf?: boolean; reasoning?: boolean }
  >();

  const diskProviders = isRecord(doc.provider) ? doc.provider : {};
  for (const [id, rawEntry] of Object.entries(diskProviders)) {
    if (!isRecord(rawEntry)) continue;
    const opts = isRecord(rawEntry.options) ? rawEntry.options : {};
    const rawModels = isRecord(rawEntry.models) ? rawEntry.models : {};
    const models = Object.entries(rawModels).map(([mid, mval]) => {
      if (isRecord(mval)) {
        const variants = isRecord(mval.variants) ? Object.keys(mval.variants) : undefined;
        const limit = isRecord(mval.limit) && typeof mval.limit.context === "number" ? mval.limit.context : null;
        modelMeta.set(`${id}/${mid}`, { variants, context_limit: limit });
      }
      return {
        id: mid,
        name: isRecord(mval) && typeof mval.name === "string" && mval.name ? mval.name : mid,
      };
    });
    providerMap.set(id, {
      id,
      name: typeof rawEntry.name === "string" && rawEntry.name ? rawEntry.name : id,
      npm: typeof rawEntry.npm === "string" ? rawEntry.npm : "@ai-sdk/openai-compatible",
      baseURL: typeof opts.baseURL === "string" ? opts.baseURL : "",
      source: "config",
      connected: true,
      has_key: Boolean(typeof opts.apiKey === "string" && opts.apiKey.trim()) || Boolean(auth[id]),
      models,
    });
  }

  const connectedSet = new Set(live?.connected ?? []);
  for (const item of live?.all ?? []) {
    const isConnected = connectedSet.has(item.id) || providerMap.has(item.id);
    if (!isConnected && item.id !== "whitz") continue;
    const liveModels = Object.entries(item.models ?? {}).map(([mid, m]) => {
      const ref = `${item.id}/${mid}`;
      const prevMeta = modelMeta.get(ref);
      const variants = m?.variants && typeof m.variants === "object" ? Object.keys(m.variants) : prevMeta?.variants;
      const contextLimit = typeof m?.limit?.context === "number" ? m.limit.context : (prevMeta?.context_limit ?? null);
      modelMeta.set(ref, {
        variants: variants?.length ? variants : prevMeta?.variants,
        context_limit: contextLimit,
        supports_image: Boolean(m?.capabilities?.input?.image),
        supports_pdf: Boolean(m?.capabilities?.input?.pdf),
        reasoning: Boolean(m?.capabilities?.reasoning),
      });
      return {
        id: mid,
        name: m?.name || mid,
      };
    });
    const existing = providerMap.get(item.id);
    const mergedModels = existing ? [...existing.models] : [];
    const seen = new Set(mergedModels.map((m) => m.id));
    for (const lm of liveModels) {
      if (!seen.has(lm.id)) mergedModels.push(lm);
    }
    const sampleModel = Object.values(item.models ?? {})[0];
    providerMap.set(item.id, {
      id: item.id,
      name: existing?.name || item.name || item.id,
      npm: existing?.npm || sampleModel?.api?.npm || "@ai-sdk/openai-compatible",
      baseURL: existing?.baseURL || (typeof item.options?.baseURL === "string" ? item.options.baseURL : sampleModel?.api?.url || ""),
      source: existing ? "config" : item.id === "whitz" && !whitzInfo.configured ? "bridge" : item.source === "api" ? "auth" : "env",
      connected: true,
      has_key: existing?.has_key || Boolean(item.key) || Boolean(auth[item.id]) || item.id === "whitz",
      models: mergedModels,
    });
  }

  // Ensure bridged Whitz model appears in selectable list even before runtime responds
  if (!whitzInfo.configured && !providerMap.has("whitz") && gatewayUrl) {
    providerMap.set("whitz", {
      id: "whitz",
      name: "Whitz 内置（桥接）",
      npm: "@ai-sdk/openai-compatible",
      baseURL: gatewayUrl,
      source: "bridge",
      connected: true,
      has_key: true,
      models: [{ id: "whitz-default", name: "Whitz 内置模型" }],
    });
  }

  const providers = Array.from(providerMap.values());
  const availableModels: OpenCodeModelOption[] = [];
  for (const p of providers) {
    for (const m of p.models) {
      const ref = `${p.id}/${m.id}`;
      const meta = modelMeta.get(ref);
      availableModels.push({
        ref,
        label: `${p.name || p.id} / ${m.name || m.id}`,
        providerID: p.id,
        modelID: m.id,
        connected: p.connected,
        is_whitz: p.id === "whitz" || p.id === whitzInfo.providerId,
        variants: meta?.variants,
        context_limit: meta?.context_limit ?? null,
        supports_image: meta?.supports_image,
        supports_pdf: meta?.supports_pdf,
        reasoning: meta?.reasoning,
      });
    }
  }

  return {
    config_file: files.configFile,
    agents_file: files.agentsFile,
    default_model: typeof doc.model === "string" ? doc.model : "",
    small_model: typeof doc.small_model === "string" ? doc.small_model : "",
    whitz_configured: whitzInfo.configured,
    whitz_bridge_active: !whitzInfo.configured,
    whitz_base_url: gatewayUrl,
    whitz_port_matches: whitzPortMatches,
    permission_preset: permissionPresetFrom(doc.permission),
    providers,
    available_models: availableModels,
    mcp_servers: listMcpServersFromDisk(liveMcp),
    agents_md: readOpenCodeAgentsMd(),
    raw_json: `${JSON.stringify(doc, null, 2)}\n`,
  };
}

export function writeWhitzProviderToDisk(): OpenCodeConfigSnapshot {
  const gatewayUrl = localGatewayBaseUrl();
  if (!gatewayUrl) throw new Error("Whitz 本地 OpenAI 服务尚未就绪");
  const { doc } = readOpenCodeJsonDoc();
  const provider = isRecord(doc.provider) ? { ...doc.provider } : {};
  const existingWhitz = isRecord(provider.whitz) ? provider.whitz : {};
  const existingModels = isRecord(existingWhitz.models) ? existingWhitz.models : {};

  provider.whitz = {
    ...existingWhitz,
    npm: "@ai-sdk/openai-compatible",
    name: "Whitz 内置",
    options: {
      ...(isRecord(existingWhitz.options) ? existingWhitz.options : {}),
      baseURL: gatewayUrl,
      apiKey: "whitz-local",
      setCacheKey: true,
    },
    models: {
      ...existingModels,
      "whitz-default": { name: "Whitz 内置模型" },
    },
  };
  doc.provider = provider;
  writeOpenCodeJsonDoc(doc);
  return buildConfigSnapshot();
}

export function removeWhitzProviderFromDisk(): OpenCodeConfigSnapshot {
  const { doc } = readOpenCodeJsonDoc();
  if (isRecord(doc.provider)) {
    const provider = { ...doc.provider };
    delete provider.whitz;
    doc.provider = provider;
  }
  if (typeof doc.model === "string" && doc.model.startsWith("whitz/")) {
    delete doc.model;
  }
  writeOpenCodeJsonDoc(doc);
  return buildConfigSnapshot();
}

export function upsertProviderOnDisk(input: OpenCodeProviderInput): OpenCodeConfigSnapshot {
  const id = input.id.trim();
  if (!id || !/^[a-zA-Z0-9._-]+$/.test(id)) {
    throw new Error("Provider ID 仅支持字母、数字、点、下划线或短横线");
  }
  const { doc } = readOpenCodeJsonDoc();
  const provider = isRecord(doc.provider) ? { ...doc.provider } : {};
  const existing = isRecord(provider[id]) ? { ...provider[id] } : {};
  const existingOpts = isRecord(existing.options) ? { ...existing.options } : {};

  const nextOpts: Record<string, unknown> = { ...existingOpts };
  if (input.baseURL?.trim()) nextOpts.baseURL = input.baseURL.trim();
  else delete nextOpts.baseURL;

  if (input.clearApiKey) {
    delete nextOpts.apiKey;
    writeAuthKeyToDisk(id, null);
  } else if (input.apiKey?.trim()) {
    const trimmed = input.apiKey.trim();
    nextOpts.apiKey = trimmed;
    writeAuthKeyToDisk(id, trimmed);
  }

  if (input.setCacheKey !== undefined) {
    nextOpts.setCacheKey = input.setCacheKey;
  }

  const nextModels: Record<string, { name: string; variants?: Record<string, Record<string, unknown>> }> = {};
  for (const m of input.models) {
    const mid = m.id.trim();
    if (!mid) continue;
    nextModels[mid] = {
      name: (m.name || mid).trim(),
      ...(m.variants && Object.keys(m.variants).length ? { variants: m.variants } : {}),
    };
  }

  const existingModels = isRecord(existing.models) ? existing.models : {};
  provider[id] = {
    ...existing,
    npm: input.npm.trim() || "@ai-sdk/openai-compatible",
    ...(input.name?.trim() ? { name: input.name.trim() } : {}),
    options: nextOpts,
    models: Object.keys(nextModels).length ? nextModels : existingModels,
  };
  doc.provider = provider;
  writeOpenCodeJsonDoc(doc);
  return buildConfigSnapshot();
}

export function deleteProviderFromDisk(id: string): OpenCodeConfigSnapshot {
  const cleanId = id.trim();
  if (!cleanId) throw new Error("缺少 Provider ID");
  const { doc } = readOpenCodeJsonDoc();
  if (isRecord(doc.provider)) {
    const provider = { ...doc.provider };
    delete provider[cleanId];
    doc.provider = provider;
  }
  if (typeof doc.model === "string" && doc.model.startsWith(`${cleanId}/`)) {
    delete doc.model;
  }
  writeOpenCodeJsonDoc(doc);
  writeAuthKeyToDisk(cleanId, null);
  return buildConfigSnapshot();
}

export function saveOpenCodePreferencesOnDisk(patch: OpenCodeConfigSavePatch): OpenCodeConfigSnapshot {
  if (patch.raw_json !== undefined) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(stripJsonComments(patch.raw_json));
    } catch (err) {
      throw new Error(`JSON 格式有误：${err instanceof Error ? err.message : String(err)}`);
    }
    if (!isRecord(parsed)) throw new Error("opencode.json 根节点必须为 JSON 对象");
    writeOpenCodeJsonDoc(parsed);
  } else {
    const { doc } = readOpenCodeJsonDoc();
    if (patch.default_model !== undefined) {
      const m = patch.default_model.trim();
      if (m) doc.model = m;
      else delete doc.model;
    }
    if (patch.small_model !== undefined) {
      const sm = patch.small_model.trim();
      if (sm) doc.small_model = sm;
      else delete doc.small_model;
    }
    if (patch.permission_preset !== undefined) {
      doc.permission = permissionConfigForPreset(patch.permission_preset);
    }
    writeOpenCodeJsonDoc(doc);
  }

  if (patch.agents_md !== undefined) {
    writeOpenCodeAgentsMd(patch.agents_md);
  }

  return buildConfigSnapshot();
}
