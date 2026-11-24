import { IPC_EVENTS } from "../../shared/ipc-contract";
import type { WorkConversationSummary, WorkGlobalEvent } from "../../shared/work-types";
import { broadcast } from "../ipc/common";
import { scoped } from "../logger";
import { getStatus, runtimeEvents } from "../runtime/opencodeRuntime";
import { OpenCodeClient } from "./opencodeClient";
import { getConversationByOpenCodeSession, updateConversationMeta } from "./repository";

const logger = scoped("work:eventbus");

let controller: AbortController | null = null;
let reconnectTimer: NodeJS.Timeout | null = null;
let running = false;
let initialized = false;
let backoffMs = 1000;

const FORWARDED_TYPES = new Set([
  "session.created",
  "session.updated",
  "session.deleted",
  "session.diff",
  "session.status",
  "session.compacted",
  "file.watcher.updated",
  "file.edited",
  "vcs.branch.updated",
  "lsp.updated",
  "mcp.tools.changed",
  "pty.created",
  "pty.updated",
  "pty.exited",
  "pty.deleted",
  "worktree.ready",
  "worktree.failed",
]);

function handleGlobalEvent(ev: WorkGlobalEvent): void {
  if (ev.type === "session.updated") {
    const info = ev.properties.info as Record<string, unknown> | undefined;
    const sessionId = typeof info?.id === "string" ? info.id : String(ev.properties.sessionID ?? "");
    if (sessionId) {
      const conv = getConversationByOpenCodeSession(sessionId);
      if (conv && info) {
        const title = typeof info.title === "string" ? info.title.trim() : "";
        const shareObj = info.share as Record<string, unknown> | undefined;
        const shareUrl = typeof shareObj?.url === "string" ? shareObj.url : undefined;
        const summaryObj = info.summary as Record<string, unknown> | undefined;
        let summary: WorkConversationSummary | undefined;
        if (summaryObj && typeof summaryObj === "object") {
          summary = {
            additions: Number(summaryObj.additions ?? 0) || 0,
            deletions: Number(summaryObj.deletions ?? 0) || 0,
            files: Number(summaryObj.files ?? 0) || 0,
          };
        }
        const cost = typeof info.cost === "number" ? info.cost : undefined;
        const shouldAdoptTitle =
          Boolean(title) &&
          title !== "新的工作区对话" &&
          title !== "New session" &&
          (conv.title === "新的工作区对话" || conv.title === "新的本地对话" || conv.title.endsWith("…"));

        updateConversationMeta(conv.id, {
          ...(shouldAdoptTitle ? { title } : {}),
          ...(shareUrl !== undefined ? { share_url: shareUrl } : {}),
          ...(summary !== undefined ? { summary } : {}),
          ...(cost !== undefined ? { total_cost: cost } : {}),
        });
      }
    }
  }

  if (FORWARDED_TYPES.has(ev.type)) {
    broadcast(IPC_EVENTS.workGlobalEvent, ev);
  }
}

function clearReconnect(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function scheduleReconnect(): void {
  clearReconnect();
  if (!getStatus().running) return;
  const delay = Math.min(15_000, backoffMs);
  backoffMs = Math.min(15_000, Math.round(backoffMs * 1.6));
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    startGlobalEventBus();
  }, delay);
  reconnectTimer.unref?.();
}

export function startGlobalEventBus(): void {
  if (running) return;
  if (!getStatus().running) return;
  clearReconnect();
  running = true;
  const ac = new AbortController();
  controller = ac;

  void (async () => {
    try {
      const client = new OpenCodeClient();
      for await (const ev of client.streamGlobalEvents(ac.signal, () => {
        backoffMs = 1000;
        logger.info("connected to opencode /global/event");
      })) {
        if (ac.signal.aborted) break;
        handleGlobalEvent(ev);
      }
    } catch (err) {
      if (!ac.signal.aborted) {
        logger.warn("global event stream closed", err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (controller === ac) {
        controller = null;
        running = false;
      }
      if (!ac.signal.aborted && getStatus().running) {
        scheduleReconnect();
      }
    }
  })();
}

export function stopGlobalEventBus(): void {
  clearReconnect();
  if (controller) {
    controller.abort();
    controller = null;
  }
  running = false;
}

export function initGlobalEventBus(): void {
  if (initialized) return;
  initialized = true;
  runtimeEvents.on("status", (status) => {
    if (status?.state === "ready" && status?.running) {
      startGlobalEventBus();
    } else if (status?.state === "stopped" || status?.state === "error" || status?.state === "disabled") {
      stopGlobalEventBus();
    }
  });
  if (getStatus().running) {
    startGlobalEventBus();
  }
}
