<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import type { WorkConversation } from "@shared/work-types";
import { useWorkStore } from "../../stores/work";
import { useDesktopStore } from "../../stores/desktop";
import DesktopSidebarShell from "../shell/DesktopSidebarShell.vue";
import BaseButton from "@web/components/ui/BaseButton.vue";
import BaseInput from "@web/components/ui/BaseInput.vue";
import BaseModal from "@web/components/ui/BaseModal.vue";

defineProps<{
  open?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  "drag-progress": [number | null];
}>();

const work = useWorkStore();
const desktop = useDesktopStore();

const query = ref("");
const searchVisible = ref(false);
const workspaceMenuOpen = ref(false);
const openMenuId = ref<string | null>(null);
const renameTarget = ref<WorkConversation | null>(null);
const renameText = ref("");
const deleteTarget = ref<WorkConversation | null>(null);

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return work.conversations;
  return work.conversations.filter((item) => item.title.toLowerCase().includes(q));
});

const pinnedItems = computed(() => filtered.value.filter((c) => c.is_pinned));
const recentItems = computed(() => filtered.value.filter((c) => !c.is_pinned));
const sections = computed(() => {
  if (!pinnedItems.value.length) {
    return recentItems.value.length ? [{ key: "all", label: "", items: recentItems.value }] : [];
  }
  const out: Array<{ key: string; label: string; items: WorkConversation[] }> = [
    { key: "pinned", label: "置顶对话", items: pinnedItems.value },
  ];
  if (recentItems.value.length) {
    out.push({ key: "recent", label: "最近对话", items: recentItems.value });
  }
  return out;
});

function closePopovers() {
  openMenuId.value = null;
  workspaceMenuOpen.value = false;
}

onMounted(() => document.addEventListener("click", closePopovers));
onBeforeUnmount(() => document.removeEventListener("click", closePopovers));

async function createConversation() {
  closePopovers();
  await work.create();
  emit("close");
}

async function selectConversation(id: string) {
  closePopovers();
  await work.select(id);
  emit("close");
}

function toggleMenu(c: WorkConversation) {
  workspaceMenuOpen.value = false;
  openMenuId.value = openMenuId.value === c.id ? null : c.id;
}

async function togglePin(c: WorkConversation) {
  openMenuId.value = null;
  await work.pin(c.id, !c.is_pinned);
}

function openRename(c: WorkConversation) {
  openMenuId.value = null;
  renameTarget.value = c;
  renameText.value = c.title;
}

async function confirmRename() {
  if (renameTarget.value && renameText.value.trim()) {
    await work.rename(renameTarget.value.id, renameText.value.trim());
  }
  renameTarget.value = null;
  renameText.value = "";
}

function askDelete(c: WorkConversation) {
  openMenuId.value = null;
  deleteTarget.value = c;
}

async function confirmDelete() {
  if (!deleteTarget.value) return;
  const id = deleteTarget.value.id;
  deleteTarget.value = null;
  await work.remove(id);
  if (!work.current && work.conversations[0]) {
    await work.select(work.conversations[0].id);
  }
}

async function pickFolder() {
  workspaceMenuOpen.value = false;
  await work.pickWorkspace();
}

async function switchWorkspace(wsPath: string) {
  workspaceMenuOpen.value = false;
  await work.selectWorkspace(wsPath);
}

async function openExplorer() {
  workspaceMenuOpen.value = false;
  await work.openInExplorer().catch(() => undefined);
}

async function removeRecentWorkspace(wsPath: string) {
  await work.removeWorkspace(wsPath);
}

function folderShortName(fullPath: string | null): string {
  if (!fullPath) return "未绑定";
  const parts = fullPath.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || fullPath;
}
</script>

<template>
  <DesktopSidebarShell
    mode="work"
    :open="open"
    :collapsed="desktop.sidebarCollapsed"
    @close="emit('close')"
    @drag-progress="emit('drag-progress', $event)"
  >
    <template #top-context="{ isRail, showTooltip, hideTooltip }">
      <div class="relative">
        <button
          type="button"
          class="focus-ring group/ws flex w-full items-center overflow-hidden rounded-xl border transition-colors"
          :class="[
            isRail ? 'h-10.5 border-transparent hover:bg-hover/80' : 'border-line bg-canvas/75 px-2.5 py-2 hover:border-line-strong hover:bg-canvas',
          ]"
          :aria-label="work.activeWorkspace ? `工作区：${work.activeWorkspace.name}` : '选择本地工作区'"
          @mouseenter="
            showTooltip(
              $event,
              work.activeWorkspace ? `工作区：${work.activeWorkspace.name}` : '选择本地工作区',
              work.activeWorkspace?.path || '点击选择一个本地项目文件夹',
            )
          "
          @mouseleave="hideTooltip"
          @click.stop="isRail ? pickFolder() : (workspaceMenuOpen = !workspaceMenuOpen)"
        >
          <span
            class="relative flex shrink-0 items-center justify-center"
            :class="isRail ? 'h-10.5 w-10' : 'h-8 w-8 rounded-lg bg-surface/80'"
          >
            <svg class="h-[18px] w-[18px] text-fg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M3 7a2 2 0 012-2h4.2a2 2 0 011.4.58l1.3 1.34A2 2 0 0013.3 7.5H19a2 2 0 012 2V17a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
              />
            </svg>
            <span
              class="absolute bottom-1 right-1 h-2 w-2 rounded-full border border-sidebar"
              :style="{ background: work.activeWorkspace ? 'var(--work-accent)' : 'var(--fg-faint)' }"
            />
          </span>

          <div v-if="!isRail" class="ml-2.5 min-w-0 flex-1 text-left">
            <div class="flex items-center justify-between gap-1.5">
              <span class="truncate text-[13px] font-semibold text-fg">
                {{ work.activeWorkspace ? work.activeWorkspace.name : "选择本地工作区" }}
              </span>
              <span class="shrink-0 text-[10.5px] font-medium" style="color: var(--work-accent)">
                {{ work.activeWorkspace ? "切换" : "打开" }}
              </span>
            </div>
            <p class="truncate text-[11px] text-fg-faint" :title="work.activeWorkspace?.path">
              {{ work.activeWorkspace ? work.activeWorkspace.path : "点击选择本地文件夹作为 Work 工作区" }}
            </p>
          </div>
        </button>

        <!-- Workspace dropdown -->
        <Transition
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="opacity-0 -translate-y-1 scale-95"
          enter-to-class="opacity-100 translate-y-0 scale-100"
          leave-active-class="transition duration-100 ease-in"
          leave-from-class="opacity-100 translate-y-0 scale-100"
          leave-to-class="opacity-0 -translate-y-1 scale-95"
        >
          <div
            v-if="workspaceMenuOpen && !isRail"
            class="absolute inset-x-0 top-full z-40 mt-1.5 rounded-2xl border border-line bg-canvas p-2 shadow-lg dark:bg-[#161615]"
            style="box-shadow: var(--shadow)"
            @click.stop
          >
            <button
              type="button"
              class="focus-ring flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[12.5px] font-medium text-fg transition-colors hover:bg-hover"
              @click="pickFolder"
            >
              <svg class="h-4 w-4 shrink-0" style="color: var(--work-accent)" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 11v6m-3-3h6M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
              </svg>
              <span>选择本地文件夹…</span>
            </button>

            <button
              v-if="work.activeWorkspace"
              type="button"
              class="focus-ring flex w-full items-center gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              @click="openExplorer"
            >
              <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
                <path stroke-linecap="round" stroke-linejoin="round" d="M14 3h7v7m0-7L10 14M5 5h4M5 5v14h14v-4" />
              </svg>
              <span>在资源管理器中打开</span>
            </button>

            <div v-if="work.workspaces.length" class="mt-2 border-t border-line/70 pt-2">
              <p class="px-2 pb-1 text-[10.5px] font-medium uppercase tracking-wider text-fg-faint">最近工作区</p>
              <div class="max-h-44 space-y-0.5 overflow-y-auto custom-scrollbar">
                <div
                  v-for="ws in work.workspaces"
                  :key="ws.id"
                  class="group/witem flex items-center gap-1 rounded-lg px-2 py-1.5 transition-colors"
                  :class="work.activeWorkspace?.path === ws.path ? 'bg-active/80 text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
                >
                  <button
                    type="button"
                    class="min-w-0 flex-1 text-left"
                    :title="ws.path"
                    @click="switchWorkspace(ws.path)"
                  >
                    <p class="truncate text-[12px] font-medium">{{ ws.name }}</p>
                    <p class="truncate text-[10.5px] text-fg-faint">{{ ws.path }}</p>
                  </button>
                  <button
                    type="button"
                    class="hidden rounded p-1 text-[11px] text-fg-faint hover:text-danger group-hover/witem:block"
                    title="从列表移除"
                    @click.stop="removeRecentWorkspace(ws.path)"
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>
          </div>
        </Transition>
      </div>
    </template>

    <template #actions="{ isRail, showTooltip, hideTooltip }">
      <!-- New Work Session -->
      <button
        type="button"
        class="focus-ring group/new flex h-10.5 w-full items-center overflow-hidden rounded-xl text-[14.5px] font-semibold text-fg/90 transition-colors duration-150 hover:bg-hover/80 hover:text-fg"
        aria-label="新建工作台对话"
        @mouseenter="showTooltip($event, '新建本地任务', '在当前工作区开启新对话')"
        @mouseleave="hideTooltip"
        @click="createConversation"
      >
        <span class="flex h-10.5 w-10 shrink-0 items-center justify-center">
          <svg
            class="h-[21px] w-[21px] text-fg transition-transform duration-150 group-hover/new:scale-105"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
          >
            <path stroke-linecap="round" d="M12 5v14M5 12h14" />
          </svg>
        </span>
        <span
          class="whitespace-nowrap pr-2.5 text-left transition-opacity duration-200"
          :class="isRail ? 'pointer-events-none opacity-0' : 'opacity-100'"
        >
          新建任务
        </span>
      </button>

      <!-- Search Local Sessions -->
      <button
        type="button"
        class="focus-ring group/search flex h-10.5 w-full items-center overflow-hidden rounded-xl text-[14.5px] font-semibold text-fg/85 transition-colors duration-150 hover:bg-hover/80 hover:text-fg"
        aria-label="搜索本地对话"
        @mouseenter="showTooltip($event, '搜索本地对话', '仅搜索 Work 本地记录')"
        @mouseleave="hideTooltip"
        @click="searchVisible = !searchVisible"
      >
        <span class="flex h-10.5 w-10 shrink-0 items-center justify-center">
          <svg
            class="h-5 w-5 text-fg-muted transition-colors group-hover/search:text-fg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
          >
            <circle cx="11" cy="11" r="7" />
            <path stroke-linecap="round" d="M20 20l-3.5-3.5" />
          </svg>
        </span>
        <span
          class="whitespace-nowrap pr-2.5 text-left transition-opacity duration-200"
          :class="isRail ? 'pointer-events-none opacity-0' : 'opacity-100'"
        >
          搜索本地记录
        </span>
      </button>

      <div v-if="searchVisible && !isRail" class="px-1 pt-0.5">
        <input
          v-model="query"
          type="search"
          autofocus
          placeholder="筛选本机对话标题…"
          class="focus-ring w-full rounded-xl border border-line bg-canvas px-3 py-1.5 text-[12.5px] text-fg placeholder:text-fg-faint"
        />
      </div>
    </template>

    <template #list>
      <div class="mb-1.5 flex items-center justify-between px-2.5 pt-1">
        <span class="text-[11px] font-medium text-fg-faint">
          {{ work.showAllWorkspaces ? "全部本地会话" : work.activeWorkspace ? `${work.activeWorkspace.name} 的会话` : "本地会话" }}
        </span>
        <button
          v-if="work.activeWorkspace"
          type="button"
          class="rounded-md px-1.5 py-0.5 text-[10.5px] text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          @click="work.setShowAllWorkspaces(!work.showAllWorkspaces)"
        >
          {{ work.showAllWorkspaces ? "仅当前" : "看全部" }}
        </button>
      </div>

      <div v-if="sections.length" class="pt-0.5">
        <div v-for="(section, sIdx) in sections" :key="section.key" :class="sIdx > 0 ? 'mt-3' : ''">
          <p v-if="section.label" class="px-3 pb-1 text-[11.5px] font-medium text-fg-faint">
            {{ section.label }}
          </p>
          <div class="space-y-0.5">
            <div
              v-for="c in section.items"
              :key="c.id"
              class="group/item relative flex items-center rounded-xl pr-1 transition-colors duration-150"
              :class="work.current?.conversation.id === c.id ? 'bg-hover/90 dark:bg-active' : 'hover:bg-hover/65'"
            >
              <button
                type="button"
                class="focus-ring flex h-10 min-w-0 flex-1 items-center gap-2 rounded-xl pl-3 pr-1 text-left text-[13.5px] transition-colors"
                :class="work.current?.conversation.id === c.id ? 'font-medium text-fg' : 'text-fg-muted hover:text-fg'"
                @click="selectConversation(c.id)"
              >
                <span
                  v-if="work.current?.conversation.id === c.id && work.streaming"
                  class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full"
                  style="background: var(--work-accent)"
                />
                <svg
                  v-if="c.is_pinned"
                  class="h-3.5 w-3.5 shrink-0 text-fg-faint"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-label="已置顶"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M12 17v5M9 10.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V16a1 1 0 001 1h12a1 1 0 001-1v-.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V7a1 1 0 011-1 2 2 0 000-4H8a2 2 0 000 4 1 1 0 011 1v3.76z"
                  />
                </svg>
                <span class="min-w-0 flex-1 truncate">{{ c.title }}</span>
                <span
                  v-if="work.showAllWorkspaces && c.workspace_path"
                  class="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10px] text-fg-faint"
                  :title="c.workspace_path"
                >
                  {{ folderShortName(c.workspace_path) }}
                </span>
              </button>

              <button
                type="button"
                class="focus-ring flex h-7.5 w-7.5 shrink-0 items-center justify-center rounded-lg text-fg-faint transition-opacity hover:bg-surface hover:text-fg md:opacity-0 md:group-hover/item:opacity-100"
                :class="openMenuId === c.id ? 'md:opacity-100 bg-surface text-fg' : ''"
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
                class="animate-rise absolute right-1 top-10.5 z-30 w-36 origin-top-right rounded-xl bg-canvas p-1 shadow-lg dark:bg-[#161615]"
                style="box-shadow: var(--shadow)"
                @click.stop
              >
                <button
                  type="button"
                  class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                  @click="togglePin(c)"
                >
                  {{ c.is_pinned ? "取消置顶" : "置顶" }}
                </button>
                <button
                  type="button"
                  class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                  @click="openRename(c)"
                >
                  重命名
                </button>
                <button
                  type="button"
                  class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-danger transition-colors hover:bg-danger-weak"
                  @click="askDelete(c)"
                >
                  删除
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <p v-else class="px-3 py-10 text-center text-[12.5px] leading-relaxed text-fg-faint">
        暂无本地工作区对话<br />
        <span class="text-[11.5px]">仅存本机 SQLite · 与 Chat 历史不互通</span>
      </p>

      <!-- Rename Modal -->
      <BaseModal :open="!!renameTarget" title="重命名本地对话" @close="renameTarget = null">
        <BaseInput
          v-model="renameText"
          label="标题"
          rounded="full"
          soft
          @keydown.enter="confirmRename"
        />
        <template #footer>
          <BaseButton variant="soft" rounded="full" @click="renameTarget = null">取消</BaseButton>
          <BaseButton rounded="full" @click="confirmRename">保存</BaseButton>
        </template>
      </BaseModal>

      <!-- Delete Modal -->
      <BaseModal :open="!!deleteTarget" title="删除本地对话" @close="deleteTarget = null">
        <p class="text-[15px] leading-relaxed text-fg-muted">
          确定删除本机对话「<span class="font-medium text-fg">{{ deleteTarget?.title }}</span>」吗？此操作仅影响本地记录且不可撤销。
        </p>
        <template #footer>
          <BaseButton variant="soft" rounded="full" @click="deleteTarget = null">取消</BaseButton>
          <BaseButton variant="danger" rounded="full" @click="confirmDelete">删除</BaseButton>
        </template>
      </BaseModal>
    </template>
  </DesktopSidebarShell>
</template>
