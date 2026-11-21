import { defineStore } from "pinia";
import { ref } from "vue";
import { streamSSEGet } from "../api/sse";
import { useChatStore } from "./chat";
import { sortConversations, useConversationsStore } from "./conversations";
import { useFilesStore } from "./files";

/**
 * Per-user multi-device real-time sync stream (`GET /api/events/stream`).
 * Keeps sidebar running indicators, conversation titles/pins/deletes, HITL control resolution,
 * library indexing updates, and idle-tab auto-attach to newly started runs converged in real time.
 */
export const useRealtimeStore = defineStore("realtime", () => {
  const connected = ref(false);
  const libraryVersion = ref(0);
  let controller: AbortController | null = null;
  let running = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let backoffMs = 1000;

  function scheduleReconnect() {
    if (!running) return;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    const delay = Math.min(backoffMs, 15_000);
    backoffMs = Math.min(backoffMs * 2, 15_000);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (running) void pump();
    }, delay);
  }

  function handleSyncEvent(event: string, d: Record<string, any>) {
    const convs = useConversationsStore();
    const chat = useChatStore();
    const filesStore = useFilesStore();

    if (event === "sync.connected") {
      connected.value = true;
      backoffMs = 1000;
      return;
    }

    if (event === "conversation.run_updated") {
      const cid = typeof d.conversation_id === "string" ? d.conversation_id : null;
      if (!cid) return;
      const runId = typeof d.active_run_id === "string" ? d.active_run_id : null;
      const runStatus = typeof d.active_run_status === "string" ? d.active_run_status : null;
      const pendingCtrl = d.pending_control ?? null;

      // Update sidebar conversation status immediately across all tabs/devices
      const item = convs.conversations.find((c) => c.id === cid);
      if (item) {
        item.active_run_id = runId;
        item.active_run_status = runStatus;
        item.pending_control = pendingCtrl;
      }
      if (convs.current?.id === cid) {
        convs.current.active_run_id = runId;
        convs.current.active_run_status = runStatus;
        convs.current.pending_control = pendingCtrl;
      }

      // If this device is currently viewing this conversation:
      if (chat.convId === cid) {
        if (runId && runId !== "pending" && !chat.streaming) {
          // Another device started a run on the conversation we're viewing -> refresh messages & attach live!
          void convs.open(cid).then((detail) => {
            if (chat.convId === cid && !chat.streaming) {
              chat.loadFromConversation(detail);
            }
          });
        } else if (!runId && chat.streaming && chat.activeRunId) {
          // Run finished on server while our stream lagged; refresh snapshot if not already terminal
          void convs.open(cid).then((detail) => {
            if (chat.convId === cid && !detail.active_run_id) {
              chat.loadFromConversation(detail);
            }
          });
        }
      }
      return;
    }

    if (event === "control.resolved") {
      const cid = typeof d.conversation_id === "string" ? d.conversation_id : null;
      if (cid && chat.convId === cid) {
        chat.clearPendingControlFromSync();
      }
      return;
    }

    if (event === "conversation.updated") {
      const cid = typeof d.conversation_id === "string" ? d.conversation_id : null;
      const action = typeof d.action === "string" ? d.action : "";
      if (action === "deleted" && cid) {
        convs.conversations = convs.conversations.filter((c) => c.id !== cid);
      } else if (typeof d.title === "string" && cid) {
        convs.applyTitle(cid, d.title);
        if (typeof d.is_pinned === "boolean") {
          const idx = convs.conversations.findIndex((c) => c.id === cid);
          if (idx >= 0) {
            const next = [...convs.conversations];
            next[idx] = {
              ...next[idx],
              is_pinned: d.is_pinned,
              pinned_at: typeof d.pinned_at === "string" ? d.pinned_at : null,
            };
            convs.conversations = sortConversations(next);
          }
        }
      } else {
        void convs.fetchList();
      }
      return;
    }

    if (event === "library.updated") {
      libraryVersion.value += 1;
      const fileId = typeof d.file_id === "string" ? d.file_id : null;
      const action = typeof d.action === "string" ? d.action : "";
      if (action === "deleted" && fileId) {
        filesStore.removeLocalFile(fileId);
      } else if (action === "indexed" && fileId) {
        filesStore.patchLocalIndexStatus(
          fileId,
          typeof d.index_status === "string" ? d.index_status : "ready",
          typeof d.indexed_chunks === "number" ? d.indexed_chunks : undefined,
        );
      }
    }
  }

  async function pump() {
    if (!running) return;
    controller?.abort();
    const ac = new AbortController();
    controller = ac;
    try {
      // User sync stream pings every 15s -> 55s idle timeout catches dead sockets cleanly
      for await (const ev of streamSSEGet("/events/stream", ac.signal, {}, 55_000)) {
        if (!running || ac.signal.aborted) break;
        handleSyncEvent(ev.event, ev.data as Record<string, any>);
      }
    } catch (e: any) {
      if (e?.name === "AbortError" || !running) return;
      // Stop reconnecting on 401/403 (auth store handles logout)
      if (e?.status === 401 || e?.status === 403) {
        stop();
        return;
      }
    } finally {
      connected.value = false;
      if (controller === ac) controller = null;
      if (running) scheduleReconnect();
    }
  }

  function start() {
    if (running) return;
    running = true;
    backoffMs = 1000;
    void pump();
  }

  function stop() {
    running = false;
    connected.value = false;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    controller?.abort();
    controller = null;
  }

  return { connected, libraryVersion, start, stop };
});
