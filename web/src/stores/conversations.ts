import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "../api/client";
import type { Conversation, ConversationDetail } from "../types";

function timeMs(value: string | null | undefined): number {
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

export function sortConversations(list: Conversation[]): Conversation[] {
  return list.toSorted((a, b) => {
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

  async function fetchList() {
    loading.value = true;
    try {
      const list = await api.get<Conversation[]>("/conversations");
      conversations.value = sortConversations(list);
    } finally {
      loading.value = false;
    }
  }

  async function create(title = "新对话"): Promise<Conversation> {
    const conv = await api.post<Conversation>("/conversations", { title });
    conversations.value = sortConversations([conv, ...conversations.value]);
    return conv;
  }

  async function open(id: string) {
    current.value = await api.get<ConversationDetail>(`/conversations/${id}`);
    return current.value;
  }

  async function rename(id: string, title: string) {
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
    const updated = await api.patch<Conversation>(`/conversations/${id}`, { is_pinned: isPinned });
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx >= 0) {
      const next = [...conversations.value];
      next[idx] = { ...next[idx], ...updated };
      conversations.value = sortConversations(next);
    }
    if (current.value?.id === id) {
      current.value.is_pinned = updated.is_pinned;
      current.value.pinned_at = updated.pinned_at;
    }
    return updated;
  }

  function applyTitle(id: string, title: string) {
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx >= 0) conversations.value[idx] = { ...conversations.value[idx], title };
    if (current.value?.id === id) current.value.title = title;
  }

  async function remove(id: string) {
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
    current,
    loading,
    fetchList,
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