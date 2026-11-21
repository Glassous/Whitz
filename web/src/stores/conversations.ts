import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";
import type { Conversation, ConversationDetail } from "../types";

function timeMs(value: string | null | undefined): number {
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

export function sortConversations(list: Conversation[]): Conversation[] {
  return list.toSorted((a, b) => {
    const aMain = a.kind === "main";
    const bMain = b.kind === "main";
    if (aMain !== bMain) return aMain ? -1 : 1;
    const aPinned = Boolean(a.is_pinned);
    const bPinned = Boolean(b.is_pinned);
    if (aPinned !== bPinned) return aPinned ? -1 : 1;
    if (aPinned && bPinned) {
      const pinDiff = timeMs(b.pinned_at) - timeMs(a.pinned_at);
      if (pinDiff !== 0) return pinDiff;
    }
    const ta = timeMs(a.last_message_at ?? a.updated_at ?? a.created_at);
    const tb = timeMs(b.last_message_at ?? b.updated_at ?? b.created_at);
    return tb - ta;
  });
}

export const useConversationsStore = defineStore("conversations", () => {
  const conversations = ref<Conversation[]>([]);
  const current = ref<ConversationDetail | null>(null);
  const loading = ref(false);

  const mainConversation = computed<Conversation | null>(
    () => conversations.value.find((c) => c.kind === "main") ?? null,
  );
  const sideConversations = computed<Conversation[]>(() =>
    conversations.value.filter((c) => c.kind !== "main"),
  );

  async function fetchList() {
    loading.value = true;
    try {
      const list = await api.get<Conversation[]>("/conversations");
      conversations.value = sortConversations(list);
    } finally {
      loading.value = false;
    }
  }

  async function openMain(): Promise<ConversationDetail> {
    current.value = await api.get<ConversationDetail>("/conversations/main");
    return current.value;
  }

  async function create(title = "新旁聊"): Promise<Conversation> {
    const conv = await api.post<Conversation>("/conversations", { title });
    conversations.value = sortConversations([conv, ...conversations.value]);
    return conv;
  }

  async function open(id: string) {
    current.value = await api.get<ConversationDetail>(`/conversations/${id}`);
    return current.value;
  }

  async function rename(id: string, title: string) {
    const target = conversations.value.find((c) => c.id === id);
    if (target?.kind === "main") return;
    const updated = await api.patch<Conversation>(`/conversations/${id}`, { title });
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx >= 0) {
      const next = [...conversations.value];
      next[idx] = { ...next[idx], ...updated };
      conversations.value = sortConversations(next);
    }
    if (current.value?.id === id) current.value.title = title;
  }

  async function togglePin(id: string, isPinned: boolean): Promise<Conversation> {
    const idx = conversations.value.findIndex((c) => c.id === id);
    const prevSnapshot = idx >= 0 ? { ...conversations.value[idx] } : null;
    const prevCurrentPin =
      current.value?.id === id
        ? { is_pinned: current.value.is_pinned, pinned_at: current.value.pinned_at }
        : null;

    // Optimistic immediate UI update
    if (idx >= 0) {
      const next = [...conversations.value];
      next[idx] = {
        ...next[idx],
        is_pinned: isPinned,
        pinned_at: isPinned ? new Date().toISOString() : null,
      };
      conversations.value = sortConversations(next);
    }
    if (current.value?.id === id) {
      current.value.is_pinned = isPinned;
      current.value.pinned_at = isPinned ? new Date().toISOString() : null;
    }

    try {
      const updated = await api.patch<Conversation>(`/conversations/${id}`, { is_pinned: isPinned });
      const latestIdx = conversations.value.findIndex((c) => c.id === id);
      if (latestIdx >= 0) {
        const next = [...conversations.value];
        next[latestIdx] = { ...next[latestIdx], ...updated };
        conversations.value = sortConversations(next);
      }
      if (current.value?.id === id) {
        current.value.is_pinned = updated.is_pinned;
        current.value.pinned_at = updated.pinned_at;
      }
      return updated;
    } catch (e) {
      // Roll back optimistic state on error
      if (prevSnapshot) {
        const curIdx = conversations.value.findIndex((c) => c.id === id);
        if (curIdx >= 0) {
          const next = [...conversations.value];
          next[curIdx] = prevSnapshot;
          conversations.value = sortConversations(next);
        }
      }
      if (prevCurrentPin && current.value?.id === id) {
        current.value.is_pinned = prevCurrentPin.is_pinned;
        current.value.pinned_at = prevCurrentPin.pinned_at;
      }
      throw e;
    }
  }

  function applyTitle(id: string, title: string) {
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx >= 0) {
      if (conversations.value[idx].kind === "main") return;
      conversations.value[idx] = { ...conversations.value[idx], title };
    }
    if (current.value?.id === id && current.value.kind !== "main") current.value.title = title;
  }

  async function remove(id: string) {
    const target = conversations.value.find((c) => c.id === id);
    if (target?.kind === "main") return;
    await api.delete(`/conversations/${id}`);
    conversations.value = conversations.value.filter((c) => c.id !== id);
    if (current.value?.id === id) current.value = null;
  }

  function clearCurrent() {
    current.value = null;
  }

  function reset() {
    conversations.value = [];
    current.value = null;
    loading.value = false;
  }

  return {
    conversations,
    mainConversation,
    sideConversations,
    current,
    loading,
    fetchList,
    openMain,
    create,
    open,
    rename,
    togglePin,
    applyTitle,
    remove,
    clearCurrent,
    reset,
  };
});