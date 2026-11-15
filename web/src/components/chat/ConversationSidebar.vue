<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { streamSSE } from "../../api/sse";
import type { Conversation } from "../../types";
import { useAuthStore } from "../../stores/auth";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import BaseInput from "../ui/BaseInput.vue";
import ThemeToggle from "../ui/ThemeToggle.vue";

const props = defineProps<{
  conversations: Conversation[];
  currentId: string | null;
  loading?: boolean;
  open?: boolean;
}>();
const emit = defineEmits<{
  select: [string];
  create: [];
  rename: [string, string];
  delete: [string];
  close: [];
}>();

const auth = useAuthStore();
const router = useRouter();

const renameTarget = ref<Conversation | null>(null);
const renameText = ref("");
const renameError = ref<string | null>(null);
const renameGenerating = ref(false);
let titleController: AbortController | null = null;
const deleteTarget = ref<Conversation | null>(null);
const openMenuId = ref<string | null>(null);

function timestamp(c: Conversation): number {
  return new Date(c.last_message_at ?? c.updated_at ?? c.created_at).getTime();
}

const groups = computed(() => {
  const sorted = [...props.conversations].sort((a, b) => timestamp(b) - timestamp(a));
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets: { label: string; items: Conversation[] }[] = [
    { label: "今天", items: [] },
    { label: "昨天", items: [] },
    { label: "过去 7 天", items: [] },
    { label: "更早", items: [] },
  ];
  for (const c of sorted) {
    const t = new Date(timestamp(c));
    const startDay = new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();
    const days = Math.round((startToday - startDay) / 86_400_000);
    const idx = days <= 0 ? 0 : days === 1 ? 1 : days <= 7 ? 2 : 3;
    buckets[idx].items.push(c);
  }
  return buckets.filter((b) => b.items.length > 0);
});

const initials = computed(() => {
  const name = auth.user?.display_name?.trim();
  if (name) return name.slice(0, 1).toUpperCase();
  return auth.user?.email?.slice(0, 1).toUpperCase() ?? "U";
});

function select(id: string) {
  openMenuId.value = null;
  emit("select", id);
  emit("close");
}

function create() {
  openMenuId.value = null;
  emit("create");
  emit("close");
}

function toggleMenu(c: Conversation) {
  openMenuId.value = openMenuId.value === c.id ? null : c.id;
}

function closeMenu() {
  openMenuId.value = null;
}

onMounted(() => document.addEventListener("click", closeMenu));
onBeforeUnmount(() => {
  document.removeEventListener("click", closeMenu);
  stopTitleGeneration();
});

function stopTitleGeneration() {
  titleController?.abort();
  titleController = null;
  renameGenerating.value = false;
}

function openRename(c: Conversation) {
  openMenuId.value = null;
  stopTitleGeneration();
  renameError.value = null;
  renameTarget.value = c;
  renameText.value = c.title;
}

function closeRename() {
  stopTitleGeneration();
  renameTarget.value = null;
  renameText.value = "";
  renameError.value = null;
}

async function generateRenameTitle() {
  if (!renameTarget.value || renameGenerating.value) return;
  const id = renameTarget.value.id;
  renameError.value = null;
  renameText.value = "";
  renameGenerating.value = true;
  const controller = new AbortController();
  titleController = controller;
  try {
    for await (const ev of streamSSE(`/conversations/${id}/title/generate`, {}, controller.signal)) {
      if (controller.signal.aborted) break;
      if (ev.event === "title.delta") {
        const text = typeof ev.data.text === "string" ? ev.data.text : "";
        if (text) renameText.value += text;
      } else if (ev.event === "title.done") {
        const title = typeof ev.data.title === "string" ? ev.data.title.trim() : "";
        if (title) renameText.value = title;
        break;
      } else if (ev.event === "error") {
        renameError.value = typeof ev.data.detail === "string" ? ev.data.detail : "标题生成失败";
        break;
      }
    }
  } catch (e: any) {
    if (!controller.signal.aborted) {
      renameError.value = e?.detail?.detail ?? e?.message ?? "标题生成失败";
    }
  } finally {
    if (titleController === controller) {
      titleController = null;
      renameGenerating.value = false;
    }
  }
}

function confirmRename() {
  if (renameGenerating.value) return;
  if (renameTarget.value && renameText.value.trim()) {
    emit("rename", renameTarget.value.id, renameText.value.trim());
  }
  closeRename();
}
function askDelete(c: Conversation) {
  openMenuId.value = null;
  deleteTarget.value = c;
}
function confirmDelete() {
  if (deleteTarget.value) emit("delete", deleteTarget.value.id);
  deleteTarget.value = null;
}
async function logout() {
  await auth.logout();
  await router.push("/login");
}
</script>

<template>
  <aside
    class="fixed inset-y-0 left-0 z-40 flex w-[268px] shrink-0 flex-col border-r border-line bg-sidebar text-fg transition-transform duration-200 ease-out md:static md:z-auto md:translate-x-0"
    :class="open ? 'translate-x-0' : '-translate-x-full'"
  >
    <div class="flex items-center gap-2 px-3 pb-1 pt-3 lg:pt-4">
      <div class="flex h-8 w-8 items-center justify-center rounded-[10px] bg-primary text-primary-fg">
        <span class="text-[13px] font-semibold tracking-tight">W</span>
      </div>
      <span class="text-[15px] font-semibold tracking-tight">Whitz</span>
      <button
        class="focus-ring ml-auto rounded-lg p-1.5 text-fg-faint hover:bg-hover hover:text-fg md:hidden"
        aria-label="关闭侧栏"
        @click="emit('close')"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>

    <div class="px-2 pt-2">
      <button
        class="focus-ring flex h-9 w-full items-center gap-2 rounded-xl px-2.5 text-[13px] font-medium text-fg transition-colors hover:bg-hover"
        @click="create"
      >
        <svg class="h-4 w-4 text-fg-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
          <path stroke-linecap="round" d="M12 5v14M5 12h14" />
        </svg>
        新建对话
      </button>
    </div>

    <nav class="mt-1 flex-1 overflow-y-auto px-2 pb-3 no-scrollbar">
      <div v-if="loading && !conversations.length" class="space-y-2 px-2 py-4">
        <div v-for="i in 3" :key="i" class="h-7 animate-pulse rounded-lg bg-surface" />
      </div>

      <div v-for="group in groups" :key="group.label" class="pt-2">
        <p class="px-2 pb-1 text-[11px] font-medium text-fg-faint">{{ group.label }}</p>
        <div class="space-y-0.5">
          <div
            v-for="c in group.items"
            :key="c.id"
            class="group/item relative flex items-center rounded-lg pr-0.5 transition-colors"
            :class="c.id === currentId ? 'bg-active' : 'hover:bg-hover'"
          >
            <button
              class="focus-ring flex h-9 min-w-0 flex-1 items-center rounded-lg px-2 text-left text-[13px] transition-colors"
              :class="c.id === currentId ? 'font-medium text-fg' : 'text-fg-muted hover:text-fg'"
              @click="select(c.id)"
            >
              <span class="truncate">{{ c.title }}</span>
            </button>
            <button
              class="focus-ring flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-fg-faint transition-opacity hover:bg-active hover:text-fg md:opacity-0 md:group-hover/item:opacity-100"
              :class="openMenuId === c.id ? 'md:opacity-100' : ''"
              aria-label="更多操作"
              @click.stop="toggleMenu(c)"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="5" cy="12" r="1.6" />
                <circle cx="12" cy="12" r="1.6" />
                <circle cx="19" cy="12" r="1.6" />
              </svg>
            </button>

            <div
              v-if="openMenuId === c.id"
              class="absolute right-0 top-9 z-30 w-32 origin-top-right rounded-xl border border-line bg-canvas p-1 shadow-lg"
              style="box-shadow: var(--shadow)"
              @click.stop
            >
              <button
                class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                @click="openRename(c)"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M11 4H4v16h16v-7M18.5 2.5a2.1 2.1 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
                重命名
              </button>
              <button
                class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-danger transition-colors hover:bg-danger-weak"
                @click="askDelete(c)"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" />
                </svg>
                删除
              </button>
            </div>
          </div>
        </div>
      </div>

      <p v-if="!loading && !conversations.length" class="px-2 py-10 text-center text-xs leading-relaxed text-fg-faint">
        还没有对话<br />点击「新建对话」开始
      </p>
    </nav>

    <div class="border-t border-line p-2">
      <div class="flex items-center gap-2 rounded-xl px-2 py-2">
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-[12px] font-semibold text-fg">
          {{ initials }}
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-[13px] font-medium text-fg">{{ auth.user?.display_name }}</p>
          <p class="truncate text-[11px] text-fg-faint">{{ auth.user?.email }}</p>
        </div>
        <ThemeToggle />
      </div>
      <div class="mt-0.5 flex items-center gap-0.5">
        <router-link
          to="/settings"
          class="focus-ring flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg text-[12px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
            <circle cx="12" cy="12" r="3" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
          </svg>
          设置
        </router-link>
        <router-link
          v-if="auth.isAdmin"
          to="/admin"
          class="focus-ring flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg text-[12px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z" />
          </svg>
          管理
        </router-link>
        <button
          class="focus-ring flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg text-[12px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          @click="logout"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
          退出
        </button>
      </div>
    </div>

    <BaseModal :open="!!renameTarget" title="重命名对话" @close="closeRename">
      <BaseInput
        v-model="renameText"
        label="标题"
        :disabled="renameGenerating"
        :error="renameError"
        :placeholder="renameGenerating ? '正在生成标题…' : ''"
        @keydown.enter="confirmRename"
      >
        <template #label-action>
          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-accent transition-opacity hover:opacity-70 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="renameGenerating"
            @click="generateRenameTitle"
          >
            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M12 3l1.7 4.6L18 9.3l-4.3 1.7L12 15.6l-1.7-4.6L6 9.3l4.3-1.7L12 3zM18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z"
              />
            </svg>
            {{ renameGenerating ? "生成中…" : "AI 生成" }}
          </button>
        </template>
      </BaseInput>
      <template #footer>
        <BaseButton variant="secondary" @click="closeRename">取消</BaseButton>
        <BaseButton :disabled="renameGenerating" @click="confirmRename">保存</BaseButton>
      </template>
    </BaseModal>

    <BaseModal :open="!!deleteTarget" title="删除对话" @close="deleteTarget = null">
      <p class="text-sm leading-relaxed text-fg-muted">
        确定删除「<span class="font-medium text-fg">{{ deleteTarget?.title }}</span>」吗？此操作不可撤销。
      </p>
      <template #footer>
        <BaseButton variant="secondary" @click="deleteTarget = null">取消</BaseButton>
        <BaseButton variant="danger" @click="confirmDelete">删除</BaseButton>
      </template>
    </BaseModal>
  </aside>
</template>
