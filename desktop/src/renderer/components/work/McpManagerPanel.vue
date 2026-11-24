<script setup lang="ts">
import { onMounted, ref } from "vue";
import type { WorkMcpServerInfo } from "@shared/work-types";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore } from "../../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";

const runtime = useRuntimeStore();
const work = useWorkStore();

const editorOpen = ref(false);
const name = ref("");
const mcpType = ref<"local" | "remote">("local");
const commandLine = ref("");
const envLines = ref("");
const remoteUrl = ref("");
const headerLines = ref("");
const enabled = ref(true);

const saving = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);

function parseKeyValueLines(raw: string, sep: "=" | ":"): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  for (const line of raw.split(/\r?\n/)) {
    const idx = line.indexOf(sep);
    if (idx <= 0) continue;
    const k = line.slice(0, idx).trim();
    const v = line.slice(idx + 1).trim();
    if (k) out[k] = v;
  }
  return Object.keys(out).length ? out : undefined;
}

function openCreate() {
  message.value = null;
  error.value = null;
  editorOpen.value = true;
  name.value = "";
  mcpType.value = "local";
  commandLine.value = "npx -y @modelcontextprotocol/server-filesystem";
  envLines.value = "";
  remoteUrl.value = "";
  headerLines.value = "";
  enabled.value = true;
}

function editServer(item: WorkMcpServerInfo) {
  message.value = null;
  error.value = null;
  editorOpen.value = true;
  name.value = item.name;
  mcpType.value = item.config?.type ?? "local";
  commandLine.value = item.config?.command?.join(" ") ?? "";
  envLines.value = item.config?.environment
    ? Object.entries(item.config.environment)
        .map(([k, v]) => `${k}=${v}`)
        .join("\n")
    : "";
  remoteUrl.value = item.config?.url ?? "";
  headerLines.value = item.config?.headers
    ? Object.entries(item.config.headers)
        .map(([k, v]) => `${k}: ${v}`)
        .join("\n")
    : "";
  enabled.value = item.config?.enabled ?? true;
}

async function saveServer() {
  saving.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.upsertMcpServer({
      name: name.value.trim(),
      type: mcpType.value,
      ...(mcpType.value === "local"
        ? {
            command: commandLine.value
              .trim()
              .split(/\s+/)
              .filter(Boolean),
            environment: parseKeyValueLines(envLines.value, "="),
          }
        : {
            url: remoteUrl.value.trim(),
            headers: parseKeyValueLines(headerLines.value, ":"),
          }),
      enabled: enabled.value,
    });
    editorOpen.value = false;
    message.value = `MCP「${name.value.trim()}」已写入 opencode.json`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存 MCP 配置失败";
  } finally {
    saving.value = false;
  }
}

async function deleteServer(serverName: string) {
  saving.value = true;
  try {
    await runtime.deleteMcpServer(serverName);
    message.value = `已移除 MCP「${serverName}」`;
  } finally {
    saving.value = false;
  }
}

async function toggleConnect(item: WorkMcpServerInfo) {
  try {
    await runtime.toggleMcpServer(item.name, item.status !== "connected", work.activeWorkspace?.path);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "切换 MCP 状态失败";
  }
}

async function authenticateServer(item: WorkMcpServerInfo) {
  error.value = null;
  message.value = null;
  try {
    await runtime.authMcpServer(item.name, work.activeWorkspace?.path);
    message.value = `MCP「${item.name}」OAuth 授权已完成`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "MCP OAuth 授权失败";
  }
}

async function clearServerAuth(item: WorkMcpServerInfo) {
  try {
    await runtime.removeMcpAuth(item.name, work.activeWorkspace?.path);
    message.value = `已清除 MCP「${item.name}」授权凭据`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "清除 MCP 授权失败";
  }
}

function statusMeta(status: WorkMcpServerInfo["status"]) {
  if (status === "connected") return { text: "已连接", color: "var(--success)" };
  if (status === "failed") return { text: "连接失败", color: "var(--danger)" };
  if (status === "needs_auth") return { text: "需鉴权", color: "var(--warning)" };
  if (status === "disabled") return { text: "已停用", color: "var(--fg-faint)" };
  return { text: "已配置", color: "var(--fg-muted)" };
}

onMounted(() => {
  void runtime.loadMcpServers(work.activeWorkspace?.path);
});
</script>

<template>
  <div class="space-y-5">
    <div class="rounded-2xl bg-surface/65 p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-[15px] font-semibold text-fg">MCP 服务器管理 (opencode.json["mcp"])</h2>
          <p class="mt-0.5 text-[12.5px] text-fg-muted">
            接入本地 <code class="rounded bg-canvas px-1 py-0.5 font-mono text-[11px]">stdio</code> 进程或远程 HTTP/SSE 服务，自动为 OpenCode 扩展外部工具与上下文。
          </p>
        </div>
        <BaseButton size="sm" @click="openCreate">+ 添加 MCP 服务</BaseButton>
      </div>
    </div>

    <!-- Add / Edit Form -->
    <div v-if="editorOpen" class="rounded-2xl bg-surface/85 p-5 space-y-4">
      <div class="flex items-center justify-between">
        <h3 class="text-[14px] font-semibold text-fg">配置 MCP 服务</h3>
        <button type="button" class="text-[12px] text-fg-faint hover:text-fg" @click="editorOpen = false">取消</button>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <label class="block">
          <span class="text-[12px] text-fg-muted">服务标识 (Name)</span>
          <input
            v-model="name"
            type="text"
            placeholder="github / sentry / context7"
            class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12.5px] text-fg outline-none"
          />
        </label>

        <div class="block">
          <span class="text-[12px] text-fg-muted">传输类型</span>
          <div class="mt-1 grid grid-cols-2 gap-1.5 rounded-xl bg-canvas p-1">
            <button
              type="button"
              class="rounded-lg py-1.5 text-[12px] font-medium transition-colors"
              :class="mcpType === 'local' ? 'bg-active text-fg' : 'text-fg-muted hover:text-fg'"
              @click="mcpType = 'local'"
            >
              本地进程 (stdio)
            </button>
            <button
              type="button"
              class="rounded-lg py-1.5 text-[12px] font-medium transition-colors"
              :class="mcpType === 'remote' ? 'bg-active text-fg' : 'text-fg-muted hover:text-fg'"
              @click="mcpType = 'remote'"
            >
              远程端点 (HTTP/SSE)
            </button>
          </div>
        </div>

        <template v-if="mcpType === 'local'">
          <label class="block sm:col-span-2">
            <span class="text-[12px] text-fg-muted">启动命令（空格分隔，如 npx -y ...）</span>
            <input
              v-model="commandLine"
              type="text"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12.5px] text-fg outline-none"
            />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-[12px] text-fg-muted">环境变量（每行 KEY=VALUE，可选）</span>
            <textarea
              v-model="envLines"
              rows="2"
              placeholder="GITHUB_TOKEN=ghp_xxx"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12px] text-fg outline-none"
            />
          </label>
        </template>

        <template v-else>
          <label class="block sm:col-span-2">
            <span class="text-[12px] text-fg-muted">远程 URL</span>
            <input
              v-model="remoteUrl"
              type="url"
              placeholder="https://mcp.example.com/sse"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12.5px] text-fg outline-none"
            />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-[12px] text-fg-muted">请求头（每行 Header: Value，可选）</span>
            <textarea
              v-model="headerLines"
              rows="2"
              placeholder="Authorization: Bearer token"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12px] text-fg outline-none"
            />
          </label>
        </template>
      </div>

      <div class="flex items-center justify-between">
        <label class="flex cursor-pointer items-center gap-2 text-[12px] text-fg-muted">
          <input v-model="enabled" type="checkbox" class="accent-primary" />
          <span>启动 OpenCode 时自动启用</span>
        </label>
        <div class="flex gap-2">
          <BaseButton size="sm" variant="ghost" @click="editorOpen = false">取消</BaseButton>
          <BaseButton size="sm" :loading="saving" @click="saveServer">保存 MCP</BaseButton>
        </div>
      </div>
    </div>

    <!-- Server List -->
    <div v-if="runtime.mcpServers.length" class="space-y-2.5">
      <div
        v-for="item in runtime.mcpServers"
        :key="item.name"
        class="rounded-2xl bg-surface/65 p-4"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full" :style="{ background: statusMeta(item.status).color }" />
              <span class="text-[14px] font-semibold text-fg">{{ item.name }}</span>
              <span class="rounded-md bg-canvas px-1.5 py-0.5 text-[10.5px] text-fg-faint">
                {{ item.config?.type === "remote" ? "remote" : "local" }}
              </span>
              <span class="text-[11.5px]" :style="{ color: statusMeta(item.status).color }">
                {{ statusMeta(item.status).text }}
              </span>
            </div>
            <p class="mt-1 truncate font-mono text-[11.5px] text-fg-faint">
              {{ item.config?.type === "remote" ? item.config?.url : item.config?.command?.join(" ") }}
            </p>
            <p v-if="item.error" class="mt-1 text-[11.5px] text-danger">{{ item.error }}</p>
          </div>

          <div class="flex shrink-0 items-center gap-1.5">
            <BaseButton
              v-if="runtime.ready && (item.status === 'needs_auth' || item.status === 'needs_client_registration')"
              size="sm"
              @click="authenticateServer(item)"
            >
              OAuth 授权
            </BaseButton>
            <BaseButton
              v-if="runtime.ready && item.config?.type === 'remote' && item.status === 'connected'"
              size="sm"
              variant="ghost"
              @click="clearServerAuth(item)"
            >
              清除授权
            </BaseButton>
            <BaseButton
              v-if="runtime.ready"
              size="sm"
              variant="secondary"
              @click="toggleConnect(item)"
            >
              {{ item.status === "connected" ? "断开" : "连接" }}
            </BaseButton>
            <BaseButton v-if="item.config" size="sm" variant="ghost" @click="editServer(item)">编辑</BaseButton>
            <BaseButton v-if="item.config" size="sm" variant="ghost" @click="deleteServer(item.name)">删除</BaseButton>
          </div>
        </div>
      </div>
    </div>
    <p v-else class="rounded-2xl bg-surface/40 p-8 text-center text-[13px] text-fg-faint">
      尚未配置任何 MCP 服务器，可点击右上角添加。
    </p>

    <p v-if="message" class="text-[12.5px]" style="color: var(--success)">{{ message }}</p>
    <p v-if="error" class="text-[12.5px] text-danger">{{ error }}</p>
  </div>
</template>
