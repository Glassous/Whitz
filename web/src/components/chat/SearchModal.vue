<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import AppIcon from "../ui/AppIcon.vue";
import type {
  Conversation,
  UnifiedChatSearchHit,
  UnifiedFileSearchHit,
  UnifiedMemorySearchHit,
  UnifiedSearchResponse,
} from "../../types";

type SourceTab = "all" | "chat" | "file" | "memory";

type OmniboxItem =
  | { kind: "chat"; key: string; hit: UnifiedChatSearchHit }
  | { kind: "file"; key: string; hit: UnifiedFileSearchHit }
  | { kind: "memory"; key: string; hit: UnifiedMemorySearchHit };

const props = defineProps<{
  open: boolean;
  conversations: Conversation[];
}>();

const auth = useAuthStore();
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");

const emit = defineEmits<{
  close: [];
  select: [conversationId: string, messageId: string | null];
  "select-file": [fileId: string, filename: string, conversationId: string | null];
  "select-memory": [entryId: string, collection: string];
}>();

const query = ref("");
const activeTab = ref<SourceTab>("all");
const dialogRef = ref<HTMLDialogElement | null>(null);
const inputRef = ref<HTMLInputElement | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const results = ref<UnifiedSearchResponse | null>(null);
const activeIndex = ref(0);

let debounceTimer: number | null = null;
let requestSeq = 0;
let pressedOutside = false;

const SOURCE_TABS: { key: SourceTab; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "chat", label: "对话" },
  { key: "file", label: "资料库正文" },
  { key: "memory", label: "长期记忆" },
];

const recentConversations = computed(() => {
  return props.conversations
    .toSorted((a, b) => {
      const ta = new Date(a.last_message_at ?? a.updated_at ?? a.created_at).getTime();
      const tb = new Date(b.last_message_at ?? b.updated_at ?? b.created_at).getTime();
      return tb - ta;
    })
    .slice(0, 8);
});

const flatItems = computed<OmniboxItem[]>(() => {
  const res = results.value;
  if (!res) return [];
  const items: OmniboxItem[] = [];
  if (activeTab.value === "all" || activeTab.value === "file") {
    for (const f of res.files ?? []) {
      items.push({ kind: "file", key: `file:${f.file_id}:${f.locator}`, hit: f });
    }
  }
  if (activeTab.value === "all" || activeTab.value === "chat") {
    for (const c of res.chats ?? []) {
      items.push({ kind: "chat", key: `chat:${c.conversation_id}:${c.message_id ?? c.match_in}`, hit: c });
    }
  }
  if (activeTab.value === "all" || activeTab.value === "memory") {
    for (const m of res.memories ?? []) {
      items.push({ kind: "memory", key: `mem:${m.entry_id}`, hit: m });
    }
  }
  return items;
});

function tabCount(tab: SourceTab): number | null {
  const res = results.value;
  if (!res || !query.value.trim()) return null;
  if (tab === "all") return (res.files?.length ?? 0) + (res.chats?.length ?? 0) + (res.memories?.length ?? 0);
  if (tab === "file") return res.files?.length ?? 0;
  if (tab === "chat") return res.chats?.length ?? 0;
  return res.memories?.length ?? 0;
}

interface HighlightPart {
  text: string;
  match: boolean;
}

function splitHighlight(text: string, needle: string): HighlightPart[] {
  const q = needle.trim();
  if (!q || !text) return [{ text, match: false }];
  const lowerText = text.toLowerCase();
  const lowerQ = q.toLowerCase();
  const parts: HighlightPart[] = [];
  let pos = 0;
  while (pos < text.length) {
    const idx = lowerText.indexOf(lowerQ, pos);
    if (idx < 0) {
      parts.push({ text: text.slice(pos), match: false });
      break;
    }
    if (idx > pos) {
      parts.push({ text: text.slice(pos, idx), match: false });
    }
    parts.push({ text: text.slice(idx, idx + q.length), match: true });
    pos = idx + q.length;
  }
  return parts;
}

function formatTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  if (sameDay) {
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  if (d.getFullYear() === now.getFullYear()) {
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

function chatBadgeLabel(hit: UnifiedChatSearchHit): string {
  if (hit.match_in === "digest") return "对话摘要";
  if (hit.match_in === "semantic_turn") return "语义命中";
  if (hit.role === "user") return "我";
  if (hit.role === "assistant") return assistantName.value;
  return "对话";
}

async function runSearch(raw: string, source: SourceTab = activeTab.value) {
  const q = raw.trim();
  const seq = ++requestSeq;
  if (!q) {
    results.value = null;
    error.value = null;
    loading.value = false;
    activeIndex.value = 0;
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    const res = await api.get<UnifiedSearchResponse>(
      `/search/unified?q=${encodeURIComponent(q)}&sources=${encodeURIComponent(source)}&limit=12`,
    );
    if (seq !== requestSeq) return;
    results.value = res;
    activeIndex.value = 0;
  } catch (e: any) {
    if (seq !== requestSeq) return;
    error.value = e?.detail?.detail ?? e?.message ?? "搜索失败，请稍后重试";
    results.value = null;
  } finally {
    if (seq === requestSeq) {
      loading.value = false;
    }
  }
}

watch(
  () => props.open,
  async (val) => {
    const dialog = dialogRef.value;
    if (val) {
      query.value = "";
      activeTab.value = "all";
      results.value = null;
      error.value = null;
      loading.value = false;
      activeIndex.value = 0;
      if (dialog && !dialog.open) dialog.showModal();
      await nextTick();
      inputRef.value?.focus();
    } else {
      if (dialog?.open) dialog.close();
      if (debounceTimer) {
        window.clearTimeout(debounceTimer);
        debounceTimer = null;
      }
    }
  },
);

watch(query, (val) => {
  if (debounceTimer) window.clearTimeout(debounceTimer);
  const trimmed = val.trim();
  if (!trimmed) {
    requestSeq++;
    results.value = null;
    error.value = null;
    loading.value = false;
    activeIndex.value = 0;
    return;
  }
  loading.value = true;
  debounceTimer = window.setTimeout(() => {
    void runSearch(val, activeTab.value);
  }, 180);
});

function switchTab(tab: SourceTab) {
  if (activeTab.value === tab) return;
  activeTab.value = tab;
  activeIndex.value = 0;
  if (query.value.trim()) {
    void runSearch(query.value, tab);
  }
}

const selectableCount = computed(() => (query.value.trim() ? flatItems.value.length : recentConversations.value.length));

function chooseAt(index: number) {
  if (query.value.trim()) {
    const item = flatItems.value[index];
    if (!item) return;
    if (item.kind === "chat") {
      emit("select", item.hit.conversation_id, item.hit.message_id ?? null);
    } else if (item.kind === "file") {
      emit("select-file", item.hit.file_id, item.hit.filename, item.hit.conversation_id ?? null);
    } else {
      emit("select-memory", item.hit.entry_id, item.hit.collection);
    }
  } else {
    const conv = recentConversations.value[index];
    if (!conv) return;
    emit("select", conv.id, null);
  }
  emit("close");
}

function onInputKeydown(e: KeyboardEvent) {
  if (e.key === "ArrowDown") {
    if (!selectableCount.value) return;
    e.preventDefault();
    activeIndex.value = (activeIndex.value + 1) % selectableCount.value;
  } else if (e.key === "ArrowUp") {
    if (!selectableCount.value) return;
    e.preventDefault();
    activeIndex.value = (activeIndex.value - 1 + selectableCount.value) % selectableCount.value;
  } else if (e.key === "Enter" && !e.isComposing) {
    if (!selectableCount.value) return;
    e.preventDefault();
    chooseAt(activeIndex.value);
  }
}

function onCancel(e: Event) {
  e.preventDefault();
  emit("close");
}

function onNativeClose() {
  if (props.open) emit("close");
}

function isOutside(e: PointerEvent, dialog: HTMLDialogElement): boolean {
  const r = dialog.getBoundingClientRect();
  return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
}

function onPointerdown(e: PointerEvent) {
  const dialog = dialogRef.value;
  if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
  pressedOutside = isOutside(e, dialog);
}

function onPointerup(e: PointerEvent) {
  const dialog = dialogRef.value;
  if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
  if (pressedOutside && isOutside(e, dialog)) emit("close");
  pressedOutside = false;
}

onMounted(() => {
  if (props.open && dialogRef.value && !dialogRef.value.open) {
    dialogRef.value.showModal();
  }
});
onBeforeUnmount(() => {
  if (debounceTimer) window.clearTimeout(debounceTimer);
});
</script>

<template>
  <dialog
    ref="dialogRef"
    class="whitz-dialog"
    :style="{ '--whitz-modal-width': '44rem' }"
    closedby="any"
    aria-label="全局知识与对话检索"
    @cancel="onCancel"
    @close="onNativeClose"
    @pointerdown="onPointerdown"
    @pointerup="onPointerup"
  >
    <div
      class="flex max-h-[calc(100dvh-2rem)] w-full flex-col overflow-hidden rounded-[28px] bg-canvas shadow-2xl dark:bg-[#161615]"
      style="box-shadow: var(--shadow)"
    >
      <!-- Top search input -->
      <div class="icon-search-group flex items-center gap-3 px-5 pb-2 pt-4">
        <AppIcon name="search" motion="search-focus" class="h-5 w-5 shrink-0 text-fg-muted" :stroke-width="2" />

        <input
          ref="inputRef"
          v-model="query"
          type="text"
          placeholder="跨对话、资料库正文、长期记忆语义检索…"
          class="h-11 min-w-0 flex-1 bg-transparent text-[16px] text-fg outline-none placeholder:text-fg-faint"
          @keydown="onInputKeydown"
        />

        <button
          v-if="query"
          type="button"
          class="focus-ring flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          aria-label="清空搜索"
          @click="query = ''; inputRef?.focus()"
        >
          <AppIcon name="close" class="h-4 w-4" :stroke-width="2.1" />
        </button>

        <button
          type="button"
          class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          aria-label="关闭搜索"
          @click="emit('close')"
        >
          <AppIcon name="close" class="h-4.5 w-4.5" :stroke-width="2" />
        </button>
      </div>

      <!-- Source filter tabs -->
      <div class="flex items-center gap-1.5 border-b border-line/60 px-5 pb-3 pt-1" role="tablist" aria-label="检索范围">
        <button
          v-for="tab in SOURCE_TABS"
          :key="tab.key"
          type="button"
          role="tab"
          :aria-selected="activeTab === tab.key"
          class="focus-ring inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
          :class="
            activeTab === tab.key
              ? 'bg-primary text-primary-fg'
              : 'bg-surface text-fg-muted hover:bg-hover hover:text-fg'
          "
          @click="switchTab(tab.key)"
        >
          <span>{{ tab.label }}</span>
          <span
            v-if="tabCount(tab.key) !== null"
            class="tabular-nums text-[11px] opacity-80"
          >
            {{ tabCount(tab.key) }}
          </span>
        </button>
      </div>

      <!-- Results area -->
      <div v-scrollbar class="custom-scrollbar max-h-[min(480px,62vh)] overflow-y-auto px-3 pb-4 pt-2">
        <!-- Empty query: recent conversations -->
        <template v-if="!query.trim()">
          <div v-if="recentConversations.length" class="space-y-1">
            <p class="px-3 pb-1.5 text-[12px] font-medium text-fg-faint">最近聊天</p>
            <button
              v-for="(c, idx) in recentConversations"
              :key="c.id"
              type="button"
              class="focus-ring flex w-full items-center justify-between gap-3 rounded-2xl px-3.5 py-3 text-left transition-colors"
              :class="activeIndex === idx ? 'bg-hover/90 dark:bg-active' : 'hover:bg-hover/65'"
              @mouseenter="activeIndex = idx"
              @click="chooseAt(idx)"
            >
              <span class="flex min-w-0 items-center gap-2">
                <span class="truncate text-[14.5px] font-medium text-fg">
                  {{
                    c.kind === "main"
                      ? assistantName
                      : c.is_scheduled || c.title.startsWith("[定时]")
                        ? c.title.replace(/^\[定时\]\s*/, "").trim() || c.title
                        : c.title
                  }}
                </span>
                <span
                  v-if="c.kind === 'main'"
                  class="shrink-0 rounded-full bg-surface px-1.5 py-0.5 text-[10.5px] font-medium text-fg-muted"
                >
                  主聊
                </span>
                <span
                  v-else-if="c.is_scheduled || c.title.startsWith('[定时]')"
                  class="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-surface px-1.5 py-0.5 text-[10.5px] font-medium text-fg-muted"
                >
                  <span>定时</span>
                </span>
              </span>
              <span class="shrink-0 text-[12px] tabular-nums text-fg-faint">
                {{ formatTime(c.last_message_at ?? c.updated_at ?? c.created_at) }}
              </span>
            </button>
          </div>
          <p v-else class="px-4 py-12 text-center text-[14px] text-fg-faint">暂无历史对话</p>
        </template>

        <!-- Active semantic & keyword Omnibox results -->
        <template v-else>
          <div v-if="loading && !flatItems.length" class="space-y-2 px-1 py-2">
            <div v-for="i in 3" :key="i" class="h-16 w-full animate-pulse rounded-2xl bg-surface" />
          </div>

          <p v-else-if="error" class="px-4 py-10 text-center text-[13.5px] text-danger">
            {{ error }}
          </p>

          <div v-else-if="flatItems.length" class="space-y-1">
            <button
              v-for="(item, idx) in flatItems"
              :key="item.key"
              type="button"
              class="focus-ring flex w-full flex-col gap-1.5 rounded-2xl px-3.5 py-3 text-left transition-colors"
              :class="activeIndex === idx ? 'bg-hover/90 dark:bg-active' : 'hover:bg-hover/65'"
              @mouseenter="activeIndex = idx"
              @click="chooseAt(idx)"
            >
              <!-- File hit -->
              <template v-if="item.kind === 'file'">
                <div class="flex items-center justify-between gap-3">
                  <span class="flex min-w-0 items-center gap-2">
                    <span class="shrink-0 rounded-full bg-accent-weak px-2 py-0.5 text-[10.5px] font-semibold text-accent">
                      资料库
                    </span>
                    <span class="truncate text-[14px] font-medium text-fg">
                      <template v-for="(part, pi) in splitHighlight(item.hit.filename, query)" :key="pi">
                        <mark v-if="part.match" class="rounded bg-fg/15 px-0.5 font-semibold text-fg">{{ part.text }}</mark>
                        <template v-else>{{ part.text }}</template>
                      </template>
                    </span>
                  </span>
                  <span class="shrink-0 truncate max-w-[180px] text-[11.5px] text-fg-faint">
                    {{ item.hit.section_path || item.hit.locator }}
                  </span>
                </div>
                <p v-if="item.hit.snippet" class="line-clamp-2 text-[13px] leading-relaxed text-fg-muted">
                  <template v-for="(part, pi) in splitHighlight(item.hit.snippet, query)" :key="pi">
                    <mark v-if="part.match" class="rounded bg-fg/15 px-0.5 font-semibold text-fg">{{ part.text }}</mark>
                    <template v-else>{{ part.text }}</template>
                  </template>
                </p>
              </template>

              <!-- Memory hit -->
              <template v-else-if="item.kind === 'memory'">
                <div class="flex items-center justify-between gap-3">
                  <span class="flex min-w-0 items-center gap-2">
                    <span class="shrink-0 rounded-full bg-success-weak px-2 py-0.5 text-[10.5px] font-semibold text-success">
                      记忆
                    </span>
                    <span class="truncate text-[14px] font-medium text-fg">
                      {{ item.hit.title || item.hit.collection_name }}
                    </span>
                  </span>
                  <span class="shrink-0 rounded-full bg-surface px-2 py-0.5 text-[11px] text-fg-muted">
                    {{ item.hit.collection_name }}
                  </span>
                </div>
                <p v-if="item.hit.snippet" class="line-clamp-2 text-[13px] leading-relaxed text-fg-muted">
                  <template v-for="(part, pi) in splitHighlight(item.hit.snippet, query)" :key="pi">
                    <mark v-if="part.match" class="rounded bg-fg/15 px-0.5 font-semibold text-fg">{{ part.text }}</mark>
                    <template v-else>{{ part.text }}</template>
                  </template>
                </p>
              </template>

              <!-- Chat hit -->
              <template v-else>
                <div class="flex items-center justify-between gap-3">
                  <span class="flex min-w-0 items-center gap-2">
                    <span class="shrink-0 rounded-full bg-surface px-2 py-0.5 text-[10.5px] font-medium text-fg-muted">
                      {{ chatBadgeLabel(item.hit) }}
                    </span>
                    <span class="truncate text-[14px] font-medium text-fg">
                      <template v-for="(part, pi) in splitHighlight(item.hit.conversation_title, query)" :key="pi">
                        <mark v-if="part.match" class="rounded bg-fg/15 px-0.5 font-semibold text-fg">{{ part.text }}</mark>
                        <template v-else>{{ part.text }}</template>
                      </template>
                    </span>
                  </span>
                  <span v-if="item.hit.created_at" class="shrink-0 text-[12px] tabular-nums text-fg-faint">
                    {{ formatTime(item.hit.created_at) }}
                  </span>
                </div>
                <p v-if="item.hit.snippet" class="line-clamp-2 text-[13px] leading-relaxed text-fg-muted">
                  <template v-for="(part, pi) in splitHighlight(item.hit.snippet, query)" :key="pi">
                    <mark v-if="part.match" class="rounded bg-fg/15 px-0.5 font-semibold text-fg">{{ part.text }}</mark>
                    <template v-else>{{ part.text }}</template>
                  </template>
                </p>
              </template>
            </button>
          </div>

          <p v-else class="px-4 py-12 text-center text-[14px] text-fg-faint">
            未找到与「{{ query.trim() }}」相关的知识、文档或对话
          </p>
        </template>
      </div>
    </div>
  </dialog>
</template>
