<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { api } from "../../api/client";
import type { SkillItem } from "../../types";
import AppIcon from "../ui/AppIcon.vue";

const MAX_SELECTED_SKILLS = 10;

const props = defineProps<{
  selectedSkills: string[];
}>();

const emit = defineEmits<{
  "update:selectedSkills": [skills: string[]];
}>();

const popoverRef = ref<HTMLElement | null>(null);
const searchInputRef = ref<HTMLInputElement | null>(null);
const skills = ref<SkillItem[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const searchQuery = ref("");

const enabledSkills = computed(() => skills.value.filter((s) => s.enabled));

const filteredSkills = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return enabledSkills.value;
  return enabledSkills.value.filter((s) => {
    const haystack = [s.name, s.title ?? "", s.description ?? "", s.category ?? "", ...(s.tags ?? [])]
      .join(" ")
      .toLowerCase();
    return haystack.includes(q);
  });
});

const selectedSet = computed(() => new Set(props.selectedSkills));
const atLimit = computed(() => props.selectedSkills.length >= MAX_SELECTED_SKILLS);

async function fetchSkills() {
  loading.value = true;
  error.value = null;
  try {
    const res = await api.get<unknown>("/skills");
    if (Array.isArray(res)) {
      skills.value = res as SkillItem[];
    } else if (res && typeof res === "object" && Array.isArray((res as any).items)) {
      skills.value = (res as any).items as SkillItem[];
    } else {
      skills.value = [];
    }
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "加载技能列表失败";
  } finally {
    loading.value = false;
  }
}

function onTogglePopover(e: Event) {
  const state = (e as ToggleEvent).newState;
  if (state === "open") {
    void fetchSkills();
    void nextTick(() => searchInputRef.value?.focus());
  }
}

function toggleSkill(name: string) {
  if (selectedSet.value.has(name)) {
    emit(
      "update:selectedSkills",
      props.selectedSkills.filter((item) => item !== name),
    );
    return;
  }
  if (atLimit.value) return;
  emit("update:selectedSkills", [...props.selectedSkills, name]);
}

function clearSelection() {
  emit("update:selectedSkills", []);
}

function closePopover() {
  const el = popoverRef.value as (HTMLElement & { hidePopover?: () => void }) | null;
  el?.hidePopover?.();
}

function sourceLabel(source?: string): string {
  switch (source) {
    case "builtin":
      return "内置";
    case "github":
      return "GitHub";
    case "assistant":
      return "AI";
    case "user":
    case "custom":
      return "自定义";
    default:
      return "";
  }
}
</script>

<template>
  <div
    id="chat-skill-picker"
    ref="popoverRef"
    popover="auto"
    class="skill-picker-popover w-[min(22rem,calc(100dvw-2rem))]"
    @toggle="onTogglePopover"
  >
    <div class="flex flex-col">
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <div class="flex items-center gap-2">
          <span class="text-[13.5px] font-semibold text-fg">附加技能</span>
          <span class="rounded-full bg-surface px-1.5 py-0.5 text-[11px] tabular-nums text-fg-muted">
            {{ selectedSkills.length }} / {{ MAX_SELECTED_SKILLS }}
          </span>
        </div>
        <button
          v-if="selectedSkills.length"
          type="button"
          class="focus-ring rounded-lg px-2 py-0.5 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          @click="clearSelection"
        >
          清空
        </button>
      </div>

      <!-- Search -->
      <div class="border-b border-line px-3 py-2">
        <div class="icon-search-group flex items-center gap-2 rounded-xl bg-surface px-2.5 py-1.5">
          <AppIcon name="search" motion="search-focus" class="h-3.5 w-3.5 shrink-0 text-fg-faint" :stroke-width="2" />
          <input
            ref="searchInputRef"
            v-model="searchQuery"
            type="text"
            placeholder="搜索已启用的技能…"
            class="min-w-0 flex-1 bg-transparent text-[13px] text-fg outline-none placeholder:text-fg-faint"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="focus-ring flex h-4 w-4 items-center justify-center rounded-full text-fg-faint hover:bg-hover hover:text-fg"
            aria-label="清空搜索"
            @click="searchQuery = ''"
          >
            <AppIcon name="close" class="h-3 w-3" :stroke-width="2.2" />
          </button>
        </div>
      </div>

      <!-- Skill List -->
      <div v-scrollbar class="custom-scrollbar max-h-60 overflow-y-auto p-2">
        <div v-if="loading && !skills.length" class="space-y-1.5 py-1">
          <div v-for="i in 3" :key="i" class="h-12 animate-pulse rounded-xl bg-surface" />
        </div>

        <p v-else-if="error" class="px-2 py-6 text-center text-[12.5px] text-danger">
          {{ error }}
        </p>

        <div v-else-if="filteredSkills.length" class="space-y-1">
          <button
            v-for="skill in filteredSkills"
            :key="skill.name"
            type="button"
            :aria-pressed="selectedSet.has(skill.name)"
            :disabled="!selectedSet.has(skill.name) && atLimit"
            class="focus-ring flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            :class="selectedSet.has(skill.name) ? 'bg-accent-weak/80 text-fg' : 'hover:bg-hover/80 text-fg'"
            @click="toggleSkill(skill.name)"
          >
            <span
              class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors"
              :class="
                selectedSet.has(skill.name)
                  ? 'border-primary bg-primary text-primary-fg'
                  : 'border-line-strong bg-canvas'
              "
            >
              <AppIcon v-if="selectedSet.has(skill.name)" name="check" motion="check-draw" class="h-3 w-3" :stroke-width="2.6" />
            </span>

            <span class="min-w-0 flex-1">
              <span class="flex items-center gap-1.5">
                <span class="truncate text-[13px] font-medium text-fg">{{ skill.title || skill.name }}</span>
                <span
                  v-if="sourceLabel(skill.source)"
                  class="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10px] font-medium text-fg-muted"
                >
                  {{ sourceLabel(skill.source) }}
                </span>
              </span>
              <span v-if="skill.description" class="mt-0.5 line-clamp-2 block text-[11.5px] leading-snug text-fg-faint">
                {{ skill.description }}
              </span>
            </span>
          </button>
        </div>

        <p v-else class="px-3 py-6 text-center text-[12.5px] text-fg-faint">
          {{ searchQuery.trim() ? "没有匹配的已启用技能" : "暂无已启用的技能" }}
        </p>
      </div>

      <!-- Footer -->
      <div class="flex items-center justify-between border-t border-line bg-sidebar/60 px-3.5 py-2">
        <span class="text-[11.5px] text-fg-faint">
          {{ atLimit ? `最多选择 ${MAX_SELECTED_SKILLS} 个技能` : "发送后仅作用于本轮" }}
        </span>
        <router-link
          to="/settings?tab=skills"
          class="focus-ring inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-accent transition-colors hover:bg-hover"
          @click="closePopover"
        >
          <span>管理 / GitHub 安装</span>
          <AppIcon name="chevron-right" class="h-3.5 w-3.5" :stroke-width="2" />
        </router-link>
      </div>
    </div>
  </div>
</template>
