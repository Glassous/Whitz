<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useWorkStore, type WorkProjectGroup } from "../../stores/work";
import type { WorkConversation } from "@shared/work-types";
import DesktopSidebarShell from "../shell/DesktopSidebarShell.vue";
import BaseModal from "@web/components/ui/BaseModal.vue";
import BaseInput from "@web/components/ui/BaseInput.vue";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{
  open?: boolean;
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  "drag-progress": [number | null];
  openRemoteSessions: [string | null];
  createWorktree: [string];
}>();

const work = useWorkStore();
const shellRef = ref<InstanceType<typeof DesktopSidebarShell> | null>(null);

const filterOpen = ref(false);
const filterText = ref("");
const runningOnly = ref(false);
const collapsedGroups = ref<Set<string>>(new Set());
const expandedAllGroups = ref<Set<string>>(new Set());

// Context menus (task & project)
const menuConvId = ref<string | null>(null);
const menuGroupKey = ref<string | null>(null);

// Rename & Delete modals (matching ConversationSidebar UX)
const renamingId = ref<string | null>(null);
const renameText = ref("");
const deletingId = ref<string | null>(null);
const deletingTitle = ref("");
const deleteRemoteSession = ref(false);
const noticeMessage = ref<string | null>(null);

const DEFAULT_VISIBLE_PER_PROJECT = 6;

function formatRelativeAge(iso: string): string {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60) return "刚刚";
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;
  const months = Math.max(1, Math.floor(days / 30));
  if (months < 12) return `${months}mo`;
  return `${Math.floor(months / 12)}y`;
}

const totalRunningCount = computed(() => {
  let count = 0;
  for (const rs of Object.values(work.runsByConversation)) {
    if (rs.streaming) count += 1;
  }
  return count;
});

const filteredGroups = computed<WorkProjectGroup[]>(() => {
  const q = filterText.value.trim().toLowerCase();
  const out: WorkProjectGroup[] = [];
  for (const g of work.projectGroups) {
    let convs = g.conversations;
    if (runningOnly.value) {
      convs = convs.filter((c) => work.isConversationRunning(c.id) || work.isConversationWaiting(c.id));
    }
    if (q) {
      const groupMatches = g.name.toLowerCase().includes(q) || (g.path ?? "").toLowerCase().includes(q);
      if (!groupMatches) {
        convs = convs.filter((c) => c.title.toLowerCase().includes(q));
      }
      if (!groupMatches && !convs.length) continue;
    }
    if (runningOnly.value && !convs.length) continue;
    // Skip empty default fallback group
    if (g.path === null && !convs.length) continue;
    out.push({ ...g, conversations: convs });
  }
  return out;
});

function isGroupCollapsed(key: string): boolean {
  return collapsedGroups.value.has(key);
}

function toggleGroupCollapsed(key: string) {
  const next = new Set(collapsedGroups.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  collapsedGroups.value = next;
}

function isGroupExpandedAll(key: string): boolean {
  return Boolean(filterText.value.trim()) || expandedAllGroups.value.has(key);
}

function toggleGroupExpandedAll(key: string) {
  const next = new Set(expandedAllGroups.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  expandedAllGroups.value = next;
}

function visibleConversations(group: WorkProjectGroup): WorkConversation[] {
  if (isGroupExpandedAll(group.key)) return group.conversations;
  const head = group.conversations.slice(0, DEFAULT_VISIBLE_PER_PROJECT);
  // Ensure active conversation inside this project stays visible even when collapsed to 6
  const activeId = work.activeConversationId;
  if (activeId && !head.some((c) => c.id === activeId)) {
    const activeConv = group.conversations.find((c) => c.id === activeId);
    if (activeConv) return [...head.slice(0, DEFAULT_VISIBLE_PER_PROJECT - 1), activeConv];
  }
  return head;
}

async function selectConversation(id: string) {
  menuConvId.value = null;
  menuGroupKey.value = null;
  await work.select(id);
  emit("close");
}

async function createInGroup(group: WorkProjectGroup) {
  menuConvId.value = null;
  menuGroupKey.value = null;
  if (collapsedGroups.value.has(group.key)) {
    toggleGroupCollapsed(group.key);
  }
  await work.create(undefined, group.path);
  emit("close");
}

function toggleTaskMenu(id: string) {
  menuGroupKey.value = null;
  menuConvId.value = menuConvId.value === id ? null : id;
}

function toggleGroupMenu(key: string) {
  menuConvId.value = null;
  menuGroupKey.value = menuGroupKey.value === key ? null : key;
}

function startRename(conv: WorkConversation) {
  menuConvId.value = null;
  renamingId.value = conv.id;
  renameText.value = conv.title;
}

async function submitRename() {
  if (!renamingId.value || !renameText.value.trim()) return;
  await work.rename(renamingId.value, renameText.value.trim());
  renamingId.value = null;
}

function askDelete(conv: WorkConversation) {
  menuConvId.value = null;
  deletingId.value = conv.id;
  deletingTitle.value = conv.title;
  deleteRemoteSession.value = false;
}

async function confirmDelete() {
  if (!deletingId.value) return;
  await work.remove(deletingId.value, deleteRemoteSession.value);
  deletingId.value = null;
}

async function handleExportJson(id: string) {
  menuConvId.value = null;
  try {
    const res = await work.exportJson(id);
    if (res?.path) {
      noticeMessage.value = `已导出 JSON 至 ${res.path}`;
      setTimeout(() => {
        noticeMessage.value = null;
      }, 3000);
    }
  } catch {
    /* ignore */
  }
}

async function handleExport(id: string) {
  menuConvId.value = null;
  try {
    const res = await window.whitzDesktop?.work.export(id);
    if (res?.path) {
      noticeMessage.value = `已导出至 ${res.path}`;
      setTimeout(() => {
        noticeMessage.value = null;
      }, 3000);
    }
  } catch {
    /* ignore */
  }
}

async function handleFork(id: string) {
  menuConvId.value = null;
  if (work.activeConversationId !== id) {
    await work.select(id);
  }
  await work.fork();
  emit("close");
}

function closeMenus() {
  menuConvId.value = null;
  menuGroupKey.value = null;
}

onMounted(() => document.addEventListener("click", closeMenus));
onBeforeUnmount(() => document.removeEventListener("click", closeMenus));
</script>

<template>
  <DesktopSidebarShell
    ref="shellRef"
    mode="work"
    :open="open"
    :collapsed="collapsed"
    @close="emit('close')"
    @drag-progress="emit('drag-progress', $event)"
  >
    <!-- Actions Header (Projects + Filter + Add Project) -->
    <template #actions="{ isRail, showTooltip, hideTooltip }">
      <!-- Rail Collapsed Mode Icons -->
      <div v-if="isRail" class="flex flex-col items-center gap-2 pt-1">
        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/75 hover:text-fg"
          aria-label="新建工作区任务"
          @mouseenter="showTooltip($event, '新建任务', work.activeWorkspace?.name ?? '当前项目')"
          @mouseleave="hideTooltip"
          @click="work.create()"
        >
          <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 5v14M5 12h14" />
          </svg>
        </button>

        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/75 hover:text-fg"
          aria-label="打开项目文件夹"
          @mouseenter="showTooltip($event, '打开项目', '添加本地文件夹')"
          @mouseleave="hideTooltip"
          @click="work.pickWorkspace()"
        >
          <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
            <path stroke-linecap="round" d="M12 10v6M9 13h6" />
          </svg>
        </button>
      </div>

      <!-- Expanded Mode: Projects Header (Matches Target Screenshot) -->
      <div v-else class="space-y-2 pt-0.5">
        <div class="flex items-center justify-between px-1">
          <div class="flex items-center gap-2">
            <span class="text-[13.5px] font-medium tracking-tight text-fg-muted">Projects</span>
            <span
              v-if="totalRunningCount > 0"
              class="inline-flex items-center gap-1 rounded-full bg-surface px-2 py-0.5 text-[10.5px] font-medium text-fg-muted"
              :title="`${totalRunningCount} 个任务并行运行中`"
            >
              <span class="h-1.5 w-1.5 rounded-full animate-pulse" style="background: var(--work-accent)" />
              {{ totalRunningCount }} 运行中
            </span>
          </div>

          <div class="flex items-center gap-0.5">
            <button
              type="button"
              class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg transition-colors"
              :class="filterOpen || runningOnly ? 'bg-active text-fg' : 'text-fg-faint hover:bg-hover/75 hover:text-fg'"
              title="筛选项目与任务"
              aria-label="筛选项目与任务"
              @click="filterOpen = !filterOpen"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
                <path stroke-linecap="round" d="M4 6h16M7 12h10M10 18h4" />
              </svg>
            </button>

            <button
              type="button"
              class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover/75 hover:text-fg"
              title="添加本地项目文件夹"
              aria-label="添加本地项目文件夹"
              @click="work.pickWorkspace()"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
                <path stroke-linecap="round" d="M12 10.5v5M9.5 13h5" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Inline Filter Input -->
        <div v-if="filterOpen || filterText || runningOnly" class="space-y-1.5 px-0.5">
          <div class="flex items-center gap-1.5 rounded-xl bg-surface/80 px-2.5 py-1.5">
            <svg class="h-3.5 w-3.5 shrink-0 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="7" />
              <path stroke-linecap="round" d="M20 20l-3.5-3.5" />
            </svg>
            <input
              v-model="filterText"
              type="text"
              placeholder="搜索项目或任务…"
              class="min-w-0 flex-1 bg-transparent text-[12.5px] text-fg outline-none placeholder:text-fg-faint"
            />
            <button
              v-if="filterText"
              type="button"
              class="text-[11px] text-fg-faint hover:text-fg"
              @click="filterText = ''"
            >
              清空
            </button>
          </div>
          <div class="flex items-center gap-1 text-[11px]">
            <button
              type="button"
              class="rounded-lg px-2 py-0.5 transition-colors"
              :class="!runningOnly ? 'bg-active text-fg font-medium' : 'text-fg-faint hover:text-fg'"
              @click="runningOnly = false"
            >
              全部
            </button>
            <button
              type="button"
              class="rounded-lg px-2 py-0.5 transition-colors"
              :class="runningOnly ? 'bg-active text-fg font-medium' : 'text-fg-faint hover:text-fg'"
              @click="runningOnly = true"
            >
              运行中 / 待审批
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- Projects & Tasks Tree -->
    <template #list>
      <p
        v-if="noticeMessage"
        class="mx-1 mb-2 truncate rounded-lg bg-surface px-2.5 py-1 text-[11px] text-fg-muted"
        :title="noticeMessage"
      >
        {{ noticeMessage }}
      </p>

      <div v-if="!filteredGroups.length" class="px-3 py-10 text-center">
        <p class="text-[12.5px] text-fg-faint">
          {{ filterText || runningOnly ? "没有匹配的项目或任务" : "尚未添加本地项目文件夹" }}
        </p>
        <button
          v-if="!filterText && !runningOnly"
          type="button"
          class="mt-3 rounded-xl bg-surface px-3 py-1.5 text-[12px] font-medium text-fg transition-colors hover:bg-hover"
          @click="work.pickWorkspace()"
        >
          打开项目文件夹
        </button>
      </div>

      <div v-else class="space-y-3 pt-1">
        <section v-for="group in filteredGroups" :key="group.key" class="space-y-0.5">
          <!-- Project Folder Header -->
          <div
            class="group/proj relative flex items-center gap-1.5 rounded-xl px-2 py-1.5 transition-colors hover:bg-hover/55"
          >
            <button
              type="button"
              class="flex min-w-0 flex-1 items-center gap-2 text-left"
              :title="group.path ?? '未绑定目录的历史对话'"
              @click="toggleGroupCollapsed(group.key)"
            >
              <svg
                v-if="isGroupCollapsed(group.key)"
                class="h-4 w-4 shrink-0 text-fg-faint"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
              </svg>
              <svg
                v-else
                class="h-4 w-4 shrink-0 text-fg-muted"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v1H3V7z" />
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 10h18l-1.3 8.1A2 2 0 0117.7 20H6.3a2 2 0 01-2-1.9L3 10z" />
              </svg>

              <span class="min-w-0 flex-1 truncate text-[13.5px] font-medium text-fg-muted group-hover/proj:text-fg">
                {{ group.name }}
              </span>

              <span
                v-if="group.waitingCount > 0"
                class="h-1.5 w-1.5 shrink-0 rounded-full bg-warning"
                title="该项目中存在等待审批的任务"
              />
              <span
                v-else-if="group.runningCount > 0"
                class="h-1.5 w-1.5 shrink-0 rounded-full animate-pulse"
                style="background: var(--work-accent)"
                title="运行中"
              />
            </button>

            <!-- Hover Actions: + New Task in Project & Folder Menu -->
            <div class="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover/proj:opacity-100 focus-within:opacity-100">
              <button
                type="button"
                class="flex h-6 w-6 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-surface hover:text-fg"
                :title="`在 ${group.name} 中新建任务`"
                @click.stop="createInGroup(group)"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
                  <path stroke-linecap="round" d="M12 5v14M5 12h14" />
                </svg>
              </button>

              <button
                v-if="group.path"
                type="button"
                class="flex h-6 w-6 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-surface hover:text-fg"
                title="项目操作"
                @click.stop="toggleGroupMenu(group.key)"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="5" cy="12" r="1.7" />
                  <circle cx="12" cy="12" r="1.7" />
                  <circle cx="19" cy="12" r="1.7" />
                </svg>
              </button>
            </div>

            <!-- Project Dropdown Menu -->
            <div
              v-if="menuGroupKey === group.key && group.path"
              class="absolute right-1 top-8 z-30 w-44 rounded-xl bg-canvas p-1 text-[12.5px] dark:bg-[#1a1a19]"
              style="box-shadow: var(--shadow)"
              @click.stop
            >
              <button
                type="button"
                class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                @click="menuGroupKey = null; work.selectWorkspace(group.path!)"
              >
                设为当前工作区
              </button>
              <button
                type="button"
                class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                @click="menuGroupKey = null; emit('createWorktree', group.path!)"
              >
                隔离 Worktree 新建任务
              </button>
              <button
                type="button"
                class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                @click="menuGroupKey = null; emit('openRemoteSessions', group.path!)"
              >
                同步 OpenCode CLI 会话
              </button>
              <button
                type="button"
                class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                @click="menuGroupKey = null; work.openInExplorer(group.path!)"
              >
                打开所在目录
              </button>
              <button
                type="button"
                class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-danger hover:bg-hover"
                @click="menuGroupKey = null; work.removeWorkspace(group.path!)"
              >
                从项目列表移除
              </button>
            </div>
          </div>

          <!-- Project Conversations List -->
          <div v-if="!isGroupCollapsed(group.key)" class="space-y-0.5 pl-2">
            <div
              v-for="conv in visibleConversations(group)"
              :key="conv.id"
              class="group/item relative flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[13.5px] transition-colors"
              :class="
                conv.id === work.activeConversationId
                  ? 'bg-hover/90 font-medium text-fg dark:bg-active'
                  : 'text-fg-muted hover:bg-hover/60 hover:text-fg'
              "
            >
              <button
                type="button"
                class="flex min-w-0 flex-1 items-center gap-2 text-left"
                @click="selectConversation(conv.id)"
              >
                <!-- Live Parallel Status Dot -->
                <span
                  v-if="work.isConversationWaiting(conv.id)"
                  class="h-2 w-2 shrink-0 rounded-full bg-warning animate-pulse"
                  title="等待你的审批或补充信息"
                />
                <span
                  v-else-if="work.isConversationRunning(conv.id)"
                  class="h-2 w-2 shrink-0 rounded-full animate-pulse"
                  style="background: var(--work-accent)"
                  title="并行运行中"
                />
                <span
                  v-else-if="work.hasUnreadDone(conv.id)"
                  class="h-1.5 w-1.5 shrink-0 rounded-full"
                  style="background: var(--success)"
                  title="已完成（未读）"
                />
                <span
                  v-else-if="conv.is_pinned"
                  class="h-1 w-1 shrink-0 rounded-full bg-fg-faint"
                  title="已置顶"
                />

                <span class="min-w-0 flex-1 truncate">{{ conv.title }}</span>
                <span
                  v-if="conv.summary && (conv.summary.additions || conv.summary.deletions)"
                  class="hidden shrink-0 font-mono text-[10px] text-fg-faint group-hover/item:hidden xl:inline"
                >
                  +{{ conv.summary.additions }}
                </span>
              </button>

              <!-- Right timestamp (fades out on hover to show ···) -->
              <span
                class="shrink-0 text-[11.5px] tabular-nums text-fg-faint transition-opacity group-hover/item:hidden"
                :class="menuConvId === conv.id ? 'hidden' : ''"
              >
                {{ formatRelativeAge(conv.updated_at) }}
              </span>

              <button
                type="button"
                class="hidden h-5 w-5 shrink-0 items-center justify-center rounded-md text-fg-faint transition-colors hover:bg-surface hover:text-fg group-hover/item:flex"
                :class="menuConvId === conv.id ? '!flex' : ''"
                title="更多操作"
                @click.stop="toggleTaskMenu(conv.id)"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="5" cy="12" r="1.7" />
                  <circle cx="12" cy="12" r="1.7" />
                  <circle cx="19" cy="12" r="1.7" />
                </svg>
              </button>

              <!-- Task Context Popover -->
              <div
                v-if="menuConvId === conv.id"
                class="absolute right-1 top-8 z-30 w-36 rounded-xl bg-canvas p-1 text-[12.5px] dark:bg-[#1a1a19]"
                style="box-shadow: var(--shadow)"
                @click.stop
              >
                <button
                  type="button"
                  class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                  @click="menuConvId = null; work.pin(conv.id, !conv.is_pinned)"
                >
                  {{ conv.is_pinned ? "取消置顶" : "置顶任务" }}
                </button>
                <button
                  type="button"
                  class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                  @click="startRename(conv)"
                >
                  重命名
                </button>
                <button
                  type="button"
                  class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                  @click="handleFork(conv.id)"
                >
                  分支新对话 (Fork)
                </button>
                <button
                  type="button"
                  class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                  @click="handleExport(conv.id)"
                >
                  导出 Markdown
                </button>
                <button
                  type="button"
                  class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
                  @click="handleExportJson(conv.id)"
                >
                  导出 OpenCode JSON
                </button>
                <button
                  type="button"
                  class="flex w-full rounded-lg px-2.5 py-1.5 text-left text-danger hover:bg-hover"
                  @click="askDelete(conv)"
                >
                  删除任务
                </button>
              </div>
            </div>

            <button
              v-if="!group.conversations.length"
              type="button"
              class="flex w-full items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-left text-[12px] text-fg-faint transition-colors hover:bg-hover/50 hover:text-fg"
              @click="createInGroup(group)"
            >
              <span>+ 新建首个任务</span>
            </button>

            <button
              v-if="group.conversations.length > DEFAULT_VISIBLE_PER_PROJECT && !filterText.trim()"
              type="button"
              class="px-2.5 py-1 text-left text-[12px] text-fg-faint transition-colors hover:text-fg"
              @click="toggleGroupExpandedAll(group.key)"
            >
              {{ isGroupExpandedAll(group.key) ? "收起部分任务" : `See all (${group.conversations.length})` }}
            </button>
          </div>
        </section>
      </div>
    </template>
  </DesktopSidebarShell>

  <!-- Rename Modal -->
  <BaseModal :open="Boolean(renamingId)" title="重命名任务" max-width="400px" @close="renamingId = null">
    <form class="space-y-4" @submit.prevent="submitRename">
      <BaseInput v-model="renameText" placeholder="输入新的任务名称" autofocus />
      <div class="flex justify-end gap-2">
        <BaseButton size="sm" variant="ghost" @click="renamingId = null">取消</BaseButton>
        <BaseButton type="submit" size="sm" :disabled="!renameText.trim()">保存</BaseButton>
      </div>
    </form>
  </BaseModal>

  <!-- Delete Confirm Modal -->
  <BaseModal :open="Boolean(deletingId)" title="删除任务" max-width="420px" @close="deletingId = null">
    <p class="text-[13.5px] leading-relaxed text-fg-muted">
      确认删除本地任务「<span class="font-medium text-fg">{{ deletingTitle }}</span>」？删除后无法恢复。
    </p>
    <label class="mt-3 flex cursor-pointer items-center gap-2 rounded-xl bg-surface/70 px-3 py-2 text-[12px] text-fg-muted">
      <input v-model="deleteRemoteSession" type="checkbox" class="accent-primary" />
      <span>同时删除本机 OpenCode 底层历史会话</span>
    </label>
    <div class="mt-5 flex justify-end gap-2">
      <BaseButton size="sm" variant="ghost" @click="deletingId = null">取消</BaseButton>
      <BaseButton size="sm" variant="danger" @click="confirmDelete">删除</BaseButton>
    </div>
  </BaseModal>
</template>
