import fs from "node:fs";
import path from "node:path";
import { loadConfig, storagePaths } from "../config";
import { apiRequest } from "../api";
import { ensureAccessToken } from "../auth/authService";
import { getProviderKey, getWorkSettings, setProviderKey } from "../work/settings";
import { scoped } from "../logger";
import type { ProviderProtocol } from "../../shared/work-types";

const logger = scoped("runtime:config");
export const WORK_PROFILE = "work";

export interface ProfilePaths {
  profileDir: string;
  homeDir: string;
  configFile: string;
  envFile: string;
  soulFile: string;
}

export function profilePaths(): ProfilePaths {
  const homeDir = storagePaths().hermesHome;
  const profileDir = path.join(homeDir, "profiles", WORK_PROFILE);
  return {
    homeDir,
    profileDir,
    configFile: path.join(profileDir, "config.yaml"),
    envFile: path.join(profileDir, ".env"),
    soulFile: path.join(profileDir, "SOUL.md"),
  };
}

export function randomKey(): string {
  return `whitz-local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

export function readProfileApiKey(): string {
  const { envFile } = profilePaths();
  try {
    if (!fs.existsSync(envFile)) return "";
    const line = fs
      .readFileSync(envFile, "utf-8")
      .split(/\r?\n/)
      .find((row) => row.startsWith("API_SERVER_KEY="));
    return line ? line.slice("API_SERVER_KEY=".length).trim() : "";
  } catch {
    return "";
  }
}

export function ensureProfileFiles(): { apiKey: string } {
  const paths = profilePaths();
  fs.mkdirSync(paths.profileDir, { recursive: true });
  let apiKey = readProfileApiKey();
  if (!apiKey) {
    apiKey = randomKey();
    fs.writeFileSync(paths.envFile, `API_SERVER_KEY=${apiKey}\n`, "utf-8");
  }
  if (!fs.existsSync(paths.soulFile)) {
    fs.writeFileSync(paths.soulFile, SOUL, "utf-8");
  }
  return { apiKey };
}

const SOUL = `# 身份

你是 Whitz Work 的本地智能体，运行在用户自己的电脑上。你友好、专业、简洁，默认使用中文回复。

# 工作方式

- 复杂任务先调用 todo_list 制定计划，并持续更新步骤状态。
- 文件、终端、浏览器等工具在本机执行；操作前遵守用户的审批设置。
- 所有对话与记忆只保存在本机，不会上传到 Whitz 云端。
- 不确定用户意图时使用 clarify 提问，不要凭空猜测。
- 回答保持简洁清晰，善用 Markdown；代码块标注语言。
`;

function providerFor(protocol: ProviderProtocol): string {
  if (protocol === "openai" || protocol === "anthropic" || protocol === "google") return protocol;
  return "custom";
}

export function builtinProxyBase(): string {
  return `${loadConfig().apiBase.replace(/\/api$/, "")}/api/desktop/llm/v1`;
}

export async function ensureBuiltinKey(): Promise<string> {
  const existing = getProviderKey("builtin");
  if (existing) return existing;
  const token = await ensureAccessToken();
  if (!token) throw new Error("内置模型需要登录 Whitz 账号");
  const resp = await apiRequest<{ key: string }>("/desktop/llm-key", { method: "POST", token });
  if (!resp?.key) throw new Error("未能获取内置模型凭证");
  setProviderKey("builtin", resp.key);
  return resp.key;
}

export async function writeHermesConfig(): Promise<{ apiKey: string; model: string }> {
  const { apiKey } = ensureProfileFiles();
  const settings = getWorkSettings();
  const model = settings.model;
  let baseUrl = model.base_url.trim();
  let apiKeyValue = "";
  let modelName = model.model.trim();

  if (model.protocol === "builtin") {
    apiKeyValue = await ensureBuiltinKey();
    baseUrl = builtinProxyBase();
    modelName = modelName || "whitz-default";
  } else {
    apiKeyValue = getProviderKey(model.protocol);
    if (!apiKeyValue) throw new Error("请先填写该协议的 API Key");
    if (!baseUrl) throw new Error("请填写接口地址");
    if (!modelName) throw new Error("请填写模型名称");
  }

  const lines = [
    "model:",
    `  default: ${JSON.stringify(modelName)}`,
    `  provider: ${JSON.stringify(providerFor(model.protocol))}`,
    `  base_url: ${JSON.stringify(baseUrl)}`,
    `  api_key: ${JSON.stringify(apiKeyValue)}`,
    `  supports_vision: ${model.supports_vision ? "true" : "false"}`,
    "platform_toolsets:",
    "  api_server:",
    "    - web",
    "    - todo",
    "    - skills",
    "    - memory",
    "    - session_search",
    "    - clarify",
    "    - terminal",
    "    - file",
    "    - browser",
    "    - code_execution",
    "    - computer_use",
    "approvals:",
    `  mode: ${JSON.stringify(model.approvals)}`,
    "memory:",
    "  memory_enabled: true",
    "  user_profile_enabled: true",
    "  write_approval: false",
    "  memory_char_limit: 2200",
    "  user_char_limit: 1375",
    "skills:",
    "  disabled: []",
    "agent:",
    `  max_turns: ${Math.max(5, Math.min(200, model.max_turns || 60))}`,
    `  image_input_mode: ${model.supports_vision ? JSON.stringify("native") : JSON.stringify("auto")}`,
    "",
  ];
  const paths = profilePaths();
  fs.mkdirSync(paths.profileDir, { recursive: true });
  fs.writeFileSync(paths.configFile, lines.join("\n"), "utf-8");
  fs.writeFileSync(paths.envFile, `API_SERVER_KEY=${apiKey}\n`, "utf-8");
  logger.info("hermes profile config written", { protocol: model.protocol, model: modelName });
  return { apiKey, model: modelName };
}
