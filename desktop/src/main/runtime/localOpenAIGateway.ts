import http from "node:http";
import https from "node:https";
import zlib from "node:zlib";
import { apiRequest } from "../api";
import { ensureAccessToken } from "../auth/authService";
import { loadConfig } from "../config";
import { scoped } from "../logger";
import { readSecrets, writeSecrets } from "../secureStore";
import type { LocalGatewayStatus } from "../../shared/work-types";

const logger = scoped("openai-gateway");

const PREFERRED_PORTS = [18432, 18433, 18434, 18435, 18436, 18437, 18438, 0];

let server: http.Server | null = null;
let port: number | null = null;
let startPromise: Promise<LocalGatewayStatus> | null = null;
let lastError: string | null = null;

function targetBaseUrl(): URL {
  const root = loadConfig().apiBase.replace(/\/api$/, "");
  return new URL(`${root}/api/desktop/llm/v1`);
}

export function isBuiltinLoggedIn(): boolean {
  const s = readSecrets();
  return Boolean(s.refresh_token || s.llm_api_key);
}

export async function ensureBuiltinKey(): Promise<string> {
  const existing = readSecrets().llm_api_key?.trim();
  if (existing) return existing;
  const token = await ensureAccessToken();
  if (!token) throw new Error("请先在 Whitz 客户端登录账号以使用内置模型");
  const resp = await apiRequest<{ key: string }>("/desktop/llm-key", { method: "POST", token });
  if (!resp?.key) throw new Error("未能获取 Whitz 内置模型凭证");
  writeSecrets({ llm_api_key: resp.key });
  return resp.key;
}

export function localGatewayBaseUrl(): string | null {
  return server && port ? `http://127.0.0.1:${port}/v1` : null;
}

export function getLocalGatewayStatus(): LocalGatewayStatus {
  return {
    running: Boolean(server && port),
    port,
    base_url: localGatewayBaseUrl(),
    logged_in: isBuiltinLoggedIn(),
    error: lastError,
  };
}

function setCorsHeaders(res: http.ServerResponse): void {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept, OpenAI-Organization");
}

function sendOpenAIError(res: http.ServerResponse, statusCode: number, message: string, code: string): void {
  if (res.headersSent) return;
  setCorsHeaders(res);
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  res.end(
    JSON.stringify({
      error: {
        message,
        type: statusCode === 401 ? "authentication_error" : "api_error",
        code,
      },
    }),
  );
}

function normalizeRoutePath(rawUrl: string | undefined): string {
  const urlPath = (rawUrl || "/").split("?")[0] || "/";
  if (urlPath === "/v1/models" || urlPath === "/models") return "/models";
  if (urlPath === "/v1/chat/completions" || urlPath === "/chat/completions") return "/chat/completions";
  if (urlPath === "/health" || urlPath === "/v1/health") return "/health";
  return urlPath.startsWith("/v1/") ? urlPath.slice(3) : urlPath;
}

async function handleModels(res: http.ServerResponse): Promise<void> {
  setCorsHeaders(res);
  const fallback = {
    object: "list",
    data: [{ id: "whitz-default", object: "model", owned_by: "whitz" }],
  };
  try {
    const key = readSecrets().llm_api_key?.trim();
    if (key) {
      const base = targetBaseUrl();
      const resp = await fetch(`${base.toString().replace(/\/+$/, "")}/models`, {
        headers: { Authorization: `Bearer ${key}`, "Accept-Encoding": "identity" },
        signal: AbortSignal.timeout(8000),
      });
      if (resp.ok) {
        const parsed = (await resp.json()) as { data?: Array<{ id: string }> };
        const items = Array.isArray(parsed?.data) ? parsed.data : [];
        if (!items.some((m) => m.id === "whitz-default")) {
          items.unshift({ id: "whitz-default" });
        }
        res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ object: "list", data: items }));
        return;
      }
    }
  } catch {
    /* fall back gracefully */
  }
  res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(fallback));
}

function proxyRequestToUpstream(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  upstreamSubPath: string,
  body: Buffer,
  llmKey: string,
): void {
  const base = targetBaseUrl();
  const targetUrl = new URL(`${base.pathname.replace(/\/+$/, "")}${upstreamSubPath}`, base.origin);
  const headers: Record<string, string> = {};
  for (const [key, val] of Object.entries(req.headers)) {
    const lower = key.toLowerCase();
    if (
      lower === "host" ||
      lower === "content-length" ||
      lower === "accept-encoding" ||
      lower === "connection" ||
      lower === "authorization"
    ) {
      continue;
    }
    if (typeof val === "string") headers[key] = val;
    else if (Array.isArray(val)) headers[key] = val.join(", ");
  }
  headers["Authorization"] = `Bearer ${llmKey}`;
  headers["Accept-Encoding"] = "identity";
  if (body.length) headers["Content-Length"] = String(body.length);

  const transport = targetUrl.protocol === "https:" ? https : http;
  const upstream = transport.request(targetUrl, { method: req.method, headers }, (upRes) => {
    setCorsHeaders(res);
    const outHeaders: Record<string, string | string[]> = {};
    for (const [k, v] of Object.entries(upRes.headers)) {
      const lower = k.toLowerCase();
      if (!v || lower === "content-encoding" || lower === "content-length" || lower === "transfer-encoding") {
        continue;
      }
      outHeaders[k] = v;
    }

    const encoding = String(upRes.headers["content-encoding"] || "").toLowerCase();
    if (encoding.includes("gzip")) {
      res.writeHead(upRes.statusCode ?? 502, outHeaders);
      upRes.pipe(zlib.createGunzip()).pipe(res);
      return;
    }

    // Some proxies omit Content-Encoding while still emitting gzip bytes (0x1f 0x8b).
    let decided = false;
    let headBuf = Buffer.alloc(0);
    let gunzip: zlib.Gunzip | null = null;

    upRes.on("data", (chunk: Buffer) => {
      if (!decided) {
        headBuf = Buffer.concat([headBuf, chunk]);
        if (headBuf.length < 2) return;
        decided = true;
        res.writeHead(upRes.statusCode ?? 502, outHeaders);
        if (headBuf[0] === 0x1f && headBuf[1] === 0x8b) {
          gunzip = zlib.createGunzip();
          gunzip.on("error", (err) => {
            logger.warn("gunzip stream error", err.message);
            if (!res.writableEnded) res.end();
          });
          gunzip.pipe(res);
          gunzip.write(headBuf);
        } else {
          res.write(headBuf);
        }
        return;
      }
      if (gunzip) gunzip.write(chunk);
      else res.write(chunk);
    });

    upRes.on("end", () => {
      if (!decided) {
        res.writeHead(upRes.statusCode ?? 502, outHeaders);
        if (headBuf.length) res.write(headBuf);
        res.end();
        return;
      }
      if (gunzip) gunzip.end();
      else if (!res.writableEnded) res.end();
    });

    upRes.on("error", (err) => {
      logger.warn("upstream stream error", err.message);
      sendOpenAIError(res, 502, err.message, "upstream_stream_error");
    });
  });

  upstream.on("error", (err) => {
    logger.warn("gateway request failed", err.message);
    sendOpenAIError(res, 502, `无法连接 Whitz 远端服务：${err.message}`, "upstream_unreachable");
  });

  if (body.length) upstream.write(body);
  upstream.end();
}

function createGatewayServer(): http.Server {
  return http.createServer((req, res) => {
    if (req.method === "OPTIONS") {
      setCorsHeaders(res);
      res.writeHead(204);
      res.end();
      return;
    }

    const route = normalizeRoutePath(req.url);
    if (req.method === "GET" && route === "/health") {
      setCorsHeaders(res);
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(getLocalGatewayStatus()));
      return;
    }

    if (req.method === "GET" && route === "/models") {
      void handleModels(res);
      return;
    }

    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      const body = Buffer.concat(chunks);
      void (async () => {
        let llmKey: string;
        try {
          llmKey = await ensureBuiltinKey();
        } catch (err) {
          const message = err instanceof Error ? err.message : "请先登录 Whitz 账号";
          sendOpenAIError(res, 401, message, "whitz_auth_required");
          return;
        }
        proxyRequestToUpstream(req, res, route, body, llmKey);
      })();
    });
  });
}

function tryListen(srv: http.Server, candidatePort: number): Promise<number> {
  return new Promise((resolve, reject) => {
    const onError = (err: Error) => {
      srv.removeListener("listening", onListening);
      reject(err);
    };
    const onListening = () => {
      srv.removeListener("error", onError);
      const addr = srv.address();
      resolve(typeof addr === "object" && addr ? addr.port : candidatePort);
    };
    srv.once("error", onError);
    srv.once("listening", onListening);
    srv.listen(candidatePort, "127.0.0.1");
  });
}

export async function ensureLocalOpenAIGateway(): Promise<LocalGatewayStatus> {
  if (server && port) return getLocalGatewayStatus();
  if (startPromise) return startPromise;

  startPromise = (async () => {
    lastError = null;
    for (const candidate of PREFERRED_PORTS) {
      const created = createGatewayServer();
      try {
        const bound = await tryListen(created, candidate);
        server = created;
        port = bound;
        logger.info("localhost OpenAI gateway listening", { baseUrl: localGatewayBaseUrl() });
        return getLocalGatewayStatus();
      } catch {
        try {
          created.close();
        } catch {
          /* ignore */
        }
      }
    }
    lastError = "无法绑定本地 OpenAI 监听端口";
    return getLocalGatewayStatus();
  })().finally(() => {
    startPromise = null;
  });

  return startPromise;
}

export function stopLocalOpenAIGateway(): void {
  if (!server) return;
  try {
    server.close();
  } catch {
    /* ignore */
  }
  server = null;
  port = null;
}
