import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "../api/client";
import type { Conversation, ConversationDetail } from "../types";

export const useConversationsStore = defineStore("conversations", () => {
  const conversations = ref<Conversation[]>([]);
  const current = ref<ConversationDetail | null>(null);
  const loading = ref(false);

  async function fetchList() {
    loading.value = true;
    try {
      conversations.value = await api.get<Conversation[]>("/conversations");
    } finally {
      loading.value = false;
    }
  }

  async function create(title = "新对话"): Promise<Conversation> {
    const conv = await api.post<Conversation>("/conversations", { title });
    conversations.value.unshift(conv);
    return conv;
  }

  async function open(id: string) {
    current.value = await api.get<ConversationDetail>(`/conversations/${id}`);
    return current.value;
  }

  async function rename(id: string, title: string) {
    const updated = await api.patch<Conversation>(`/conversations/${id}`, { title });
    const idx = conversations.value.findIndex((c) => c.id === id);
    if (idx >= 0) conversations.value[idx] = { ...conversations.value[idx], ...updated };
    if (current.value?.id === id) current.value.title = title;
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

  return { conversations, current, loading, fetchList, create, open, rename, applyTitle, remove, clearCurrent, reset };
});