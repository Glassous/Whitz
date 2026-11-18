import log from "electron-log/main";
import fs from "node:fs";
import path from "node:path";
import { storagePaths } from "./config";

const SECRET_PATTERNS: Array<[RegExp, string]> = [
  [/sk-[A-Za-z0-9_-]{12,}/g, "sk-***"],
  [/Bearer\s+[A-Za-z0-9._-]{12,}/gi, "Bearer ***"],
  [/("?(?:refresh_token|access_token|api_key|apiKey|password)"?\s*[:=]\s*")[^"]+"/gi, "$1***"],
];

export function redact(input: string): string {
  let output = input;
  for (const [pattern, replacement] of SECRET_PATTERNS) {
    output = output.replace(pattern, replacement);
  }
  return output;
}

let initialized = false;

export function initLogger(): typeof log {
  if (initialized) return log;
  initialized = true;
  const logs = storagePaths().logs;
  fs.mkdirSync(logs, { recursive: true });
  log.initialize({ preload: false });
  log.transports.file.level = "info";
  log.transports.file.maxSize = 5 * 1024 * 1024;
  log.transports.file.resolvePathFn = (variables) =>
    path.join(logs, `${(variables as { processType?: string }).processType ?? "main"}.log`);
  log.transports.console.level = process.env.NODE_ENV === "development" ? "debug" : "info";
  const originalInfo = log.info.bind(log);
  const originalWarn = log.warn.bind(log);
  const originalError = log.error.bind(log);
  log.info = (...args: unknown[]) => originalInfo(...args.map(redactArg));
  log.warn = (...args: unknown[]) => originalWarn(...args.map(redactArg));
  log.error = (...args: unknown[]) => originalError(...args.map(redactArg));
  return log;
}

function redactArg(value: unknown): unknown {
  if (typeof value === "string") return redact(value);
  if (value instanceof Error) return redact(value.stack ?? value.message);
  return value;
}

export function scoped(scope: string) {
  const logger = initLogger();
  return {
    info: (...args: unknown[]) => logger.info(`[${scope}]`, ...args),
    warn: (...args: unknown[]) => logger.warn(`[${scope}]`, ...args),
    error: (...args: unknown[]) => logger.error(`[${scope}]`, ...args),
    debug: (...args: unknown[]) => logger.debug(`[${scope}]`, ...args),
  };
}
