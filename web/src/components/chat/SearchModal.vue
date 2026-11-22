<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import type { Conversation, ConversationSearchHit } from "../../types";

const props = defineProps<{
  open: boolean;
  conversations: Conversation[];
}>();

const auth = useAuthStore();
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");

const emit = defineEmits<{
  close: [];
  select: [conversationId: string, messageId: string | null];
}>();

const query = ref("");
const dialogRef = ref<HTMLDialogElement | null>(null);
const inputRef = ref<HTMLInputElement | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const hits = ref<ConversationSearchHit[]>([]);
const activeIndex = ref(0);

let debounceTimer: number | null = null;
let requestSeq = 0;
let pressedOutside = false;

const recentConversations = computed(() => {
  return props.conversations
    .toSorted((a, b) => {
      const ta = new Date(a.last_message_at ?? a.updated_at ?? a.created_at).getTime();
      const tb = new Date(b.last_message_at ?? b.updated_at ?? b.created_at).getTime();
      return tb - ta;
    })
    .slice(0, 8);
});

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

function formatTime(iso: string): string {
  const d = new Date(iso);
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

function roleLabel(hit: ConversationSearchHit): string {
  if (hit.match_in === "title") return "标题";
  if (hit.role === "user") return "我";
  if (hit.role === "assistant") return assistantName.value;
  return "正文";
}

async function runSearch(raw: string) {
  const q = raw.trim();
  const seq = ++requestSeq;
  if (!q) {
    hits.value = [];
    error.value = null;
    loading.value = false;
    activeIndex.value = 0;
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    const res = await api.get<ConversationSearchHit[]>(
      `/conversations/search?q=${encodeURIComponent(q)}&limit=30`,
    );
    if (seq !== requestSeq) return;
    hits.value = res;
    activeIndex.value = 0;
  } catch (e: any) {
    if (seq !== requestSeq) return;
    error.value = e?.detail?.detail ?? e?.message ?? "搜索失败，请稍后重试";
    hits.value = [];
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
      hits.value = [];
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
    hits.value = [];
    error.value = null;
    loading.value = false;
    activeIndex.value = 0;
    return;
  }
  loading.value = true;
  debounceTimer = window.setTimeout(() => {
    void runSearch(val);
  }, 160);
});

const selectableCount = computed(() => (query.value.trim() ? hits.value.length : recentConversations.value.length));

function chooseAt(index: number) {
  if (query.value.trim()) {
    const hit = hits.value[index];
    if (!hit) return;
    emit("select", hit.conversation_id, hit.message_id);
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
    :style="{ '--whitz-modal-width': '42rem' }"
    closedby="any"
    aria-label="搜索对话"
    @cancel="onCancel"
    @close="onNativeClose"
    @pointerdown="onPointerdown"
    @pointerup="onPointerup"
  >
    <div
      class="flex max-h-[calc(100dvh-2rem)] w-full flex-col overflow-hidden rounded-[28px] bg-canvas shadow-2xl dark:bg-[#161615]"
      style="box-shadow: var(--shadow)"
    >
          <!-- Top search input (borderless, large radius) -->
          <div class="flex items-center gap-3 px-5 pb-3 pt-4">
            <svg
              class="h-5 w-5 shrink-0 text-fg-muted"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
            >
              <circle cx="11" cy="11" r="7" />
              <path stroke-linecap="round" d="M20 20l-3.5-3.5" />
            </svg>

            <input
              ref="inputRef"
              v-model="query"
              type="text"
              placeholder="搜索对话标题或正文内容…"
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
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>

            <button
              type="button"
              class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              aria-label="关闭搜索"
              @click="emit('close')"
            >
              <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          <!-- Results area -->
          <div v-scrollbar class="custom-scrollbar max-h-[min(460px,62vh)] overflow-y-auto px-3 pb-4 pt-1">
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
                      <svg class="h-2.5 w-2.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
                        <circle cx="12" cy="12" r="9" />
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 7v5l3 2" />
                      </svg>
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

            <!-- Active search -->
            <template v-else>
              <div v-if="loading && !hits.length" class="space-y-2 px-1 py-2">
                <div v-for="i in 3" :key="i" class="h-16 w-full animate-pulse rounded-2xl bg-surface" />
              </div>

              <p v-else-if="error" class="px-4 py-10 text-center text-[13.5px] text-danger">
                {{ error }}
              </p>

              <div v-else-if="hits.length" class="space-y-1">
                <button
                  v-for="(hit, idx) in hits"
                  :key="`${hit.conversation_id}:${hit.message_id ?? 'title'}`"
                  type="button"
                  class="focus-ring flex w-full flex-col gap-1.5 rounded-2xl px-3.5 py-3 text-left transition-colors"
                  :class="activeIndex === idx ? 'bg-hover/90 dark:bg-active' : 'hover:bg-hover/65'"
                  @mouseenter="activeIndex = idx"
                  @click="chooseAt(idx)"
                >
                  <div class="flex items-center justify-between gap-3">
                    <span class="min-w-0 truncate text-[14.5px] font-medium text-fg">
                      <template v-for="(part, pi) in splitHighlight(hit.conversation_title, query)" :key="pi">
                        <mark
                          v-if="part.match"
                          class="rounded-md bg-fg/15 px-1 py-0.5 font-semibold text-fg dark:bg-fg/20"
                        >{{ part.text }}</mark>
                        <template v-else>{{ part.text }}</template>
                      </template>
                    </span>

                    <div class="flex shrink-0 items-center gap-2">
                      <span class="rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-fg-muted">
                        {{ roleLabel(hit) }}
                      </span>
                      <span class="text-[12px] tabular-nums text-fg-faint">
                        {{ formatTime(hit.created_at) }}
                      </span>
                    </div>
                  </div>

                  <p
                    v-if="hit.snippet"
                    class="line-clamp-2 text-[13.5px] leading-relaxed text-fg-muted"
                  >
                    <template v-for="(part, pi) in splitHighlight(hit.snippet, query)" :key="pi">
                      <mark
                        v-if="part.match"
                        class="rounded-md bg-fg/15 px-1 py-0.5 font-semibold text-fg dark:bg-fg/20"
                      >{{ part.text }}</mark>
                      <template v-else>{{ part.text }}</template>
                    </template>
                  </p>
                </button>
              </div>

              <p v-else class="px-4 py-12 text-center text-[14px] text-fg-faint">
                未找到与「{{ query.trim() }}」相关的对话或内容
              </p>
            </template>
          </div>
        </div>
  </dialog>
</template>
