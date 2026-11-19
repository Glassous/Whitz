<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import type { OpenCodeModelOption, WorkAttachment } from "@shared/work-types";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore } from "../../stores/work";
import FullCommandConfirmModal from "./FullCommandConfirmModal.vue";

const props = defineProps<{
  streaming: boolean;
  disabled?: boolean;
  modelRef?: string | null;
  agentName?: string | null;
  variant?: string | null;
}>();

const emit = defineEmits<{
  send: [
    payload: {
      text: string;
      skills: string[];
      attachments: WorkAttachment[];
      modelRef: string | null;
      agentName: string | null;
      variant: string | null;
    },
  ];
  steer: [string];
  stop: [];
  command: [payload: { name: string; args: string }];
  shell: [string];
  "update:prefs": [prefs: { model_ref?: string | null; agent_name?: string | null; variant?: string | null }];
}>();

const NORMAL_MAX_HEIGHT = 160;

const router = useRouter();
const runtime = useRuntimeStore();
const work = useWorkStore();

const text = ref("");
const area = ref<HTMLTextAreaElement | null>(null);
const canExpand = ref(false);
const expanded = ref(false);
const attachments = ref<WorkAttachment[]>([]);
const selectedSkills = ref<string[]>([]);

// Popovers
const modelMenuOpen = ref(false);
const modelSearch = ref("");
const agentMenuOpen = ref(false);
const slashPopoverOpen = ref(false);
const fullCommandConfirmOpen = ref(false);
const activeIndex = ref(0);

const fullCommandMode = computed(() => Boolean(runtime.settings?.model.full_command_mode));

function toggleFullCommandMode() {
  if (fullCommandMode.value) {
    void runtime.saveSettings({ full_command_mode: false });
    return;
  }
  fullCommandConfirmOpen.value = true;
}

async function confirmFullCommandMode() {
  fullCommandConfirmOpen.value = false;
  await runtime.saveSettings({ full_command_mode: true });
}

// Autocomplete (@ files/subagents, / commands/skills)
const mentionTrigger = ref<"@" | "/" | null>(null);
const mentionQuery = ref("");
const mentionStart = ref(-1);
const fileCandidates = ref<string[]>([]);

let searchTimer: number | null = null;

// Effective selections (conversation prefs -> global WorkSettings -> OpenCode default)
const enabledModels = computed<OpenCodeModelOption[]>(() => runtime.enabledModels);

const effectiveModelRef = computed<string | null>(() => {
  const fromProp = props.modelRef?.trim();
  if (fromProp) return fromProp;
  const fromSettings = runtime.settings?.model.default_composer_model?.trim();
  if (fromSettings) return fromSettings;
  if (runtime.settings?.model.mode === "builtin") {
    return `whitz/${runtime.settings.model.builtin_model || "whitz-default"}`;
  }
  return runtime.opencodeConfig?.default_model?.trim() || enabledModels.value[0]?.ref || null;
});

const effectiveModelOption = computed<OpenCodeModelOption | null>(() => {
  const refStr = effectiveModelRef.value;
  if (!refStr) return null;
  return (
    enabledModels.value.find((m) => m.ref === refStr) ??
    runtime.allModels.find((m) => m.ref === refStr) ??
    null
  );
});

const modelDisplayName = computed(() => {
  const opt = effectiveModelOption.value;
  if (opt) return opt.modelID;
  if (effectiveModelRef.value) {
    const parts = effectiveModelRef.value.split("/");
    return parts[parts.length - 1] || effectiveModelRef.value;
  }
  return "自动模型";
});

const availableVariants = computed<string[]>(() => effectiveModelOption.value?.variants ?? []);
const effectiveVariant = computed<string | null>(() => {
  const cur = props.variant?.trim() || runtime.settings?.model.default_variant?.trim() || null;
  if (!cur) return null;
  if (availableVariants.value.length && !availableVariants.value.includes(cur)) return null;
  return cur;
});

const primaryAgents = computed(() => {
  const list = work.primaryAgents;
  if (list.length) return list;
  return [
    { name: "build", description: "默认执行代理，读写文件与命令", mode: "primary" as const },
    { name: "plan", description: "只读规划分析代理", mode: "primary" as const },
  ];
});

const effectiveAgentName = computed(() => {
  return props.agentName?.trim() || runtime.settings?.model.default_agent?.trim() || primaryAgents.value[0]?.name || "build";
});

const isShellInput = computed(() => text.value.startsWith("!"));

const filteredModels = computed(() => {
  const q = modelSearch.value.trim().toLowerCase();
  const list = enabledModels.value;
  if (!q) return list;
  return list.filter(
    (m) => m.ref.toLowerCase().includes(q) || m.label.toLowerCase().includes(q) || m.providerID.toLowerCase().includes(q),
  );
});

const groupedFilteredModels = computed(() => {
  const map = new Map<string, { providerID: string; items: OpenCodeModelOption[] }>();
  for (const m of filteredModels.value) {
    let bucket = map.get(m.providerID);
    if (!bucket) {
      bucket = { providerID: m.providerID, items: [] };
      map.set(m.providerID, bucket);
    }
    bucket.items.push(m);
  }
  return Array.from(map.values());
});

interface SlashEntry {
  kind: "builtin" | "command" | "skill";
  name: string;
  label: string;
  desc: string;
}

const BUILTIN_COMMANDS: SlashEntry[] = [
  { kind: "builtin", name: "compact", label: "/compact", desc: "压缩当前会话历史上下文（保留关键结论）" },
  { kind: "builtin", name: "undo", label: "/undo", desc: "撤回上一轮消息并回滚快照文件改动" },
  { kind: "builtin", name: "redo", label: "/redo", desc: "恢复刚刚撤回的消息与文件状态" },
  { kind: "builtin", name: "fork", label: "/fork", desc: "从当前记录分支创建一条独立新对话" },
  { kind: "builtin", name: "init", label: "/init", desc: "分析当前项目结构并生成 AGENTS.md" },
];

const slashEntries = computed<SlashEntry[]>(() => {
  const q = (mentionTrigger.value === "/" ? mentionQuery.value : "").toLowerCase();
  const all: SlashEntry[] = [...BUILTIN_COMMANDS];
  const seen = new Set(all.map((a) => a.name));
  for (const c of work.commands) {
    if (seen.has(c.name)) continue;
    seen.add(c.name);
    all.push({ kind: "command", name: c.name, label: `/${c.name}`, desc: c.description || "OpenCode 自定义指令" });
  }
  for (const s of work.skills) {
    if (seen.has(s.name)) continue;
    all.push({ kind: "skill", name: s.name, label: `/${s.name}`, desc: s.description || "OpenCode 技能（附带激活）" });
  }
  if (!q) return all;
  return all.filter((e) => e.name.toLowerCase().includes(q) || e.desc.toLowerCase().includes(q));
});

interface MentionEntry {
  kind: "subagent" | "file";
  value: string;
  desc: string;
}

const atEntries = computed<MentionEntry[]>(() => {
  const q = (mentionTrigger.value === "@" ? mentionQuery.value : "").toLowerCase();
  const subagents: MentionEntry[] = work.subagentDefs
    .filter((a) => !q || a.name.toLowerCase().includes(q))
    .slice(0, 4)
    .map((a) => ({ kind: "subagent", value: a.name, desc: a.description || "子代理" }));
  const files: MentionEntry[] = fileCandidates.value.slice(0, 8).map((f) => ({ kind: "file", value: f, desc: "文件" }));
  return [...subagents, ...files];
});

const dropdownVisible = computed(() => {
  if (mentionTrigger.value === "/" && slashEntries.value.length > 0) return true;
  if (mentionTrigger.value === "@" && atEntries.value.length > 0) return true;
  return false;
});

const canSubmit = computed(() => Boolean(text.value.trim()) && !props.disabled);

function updateExpandState() {
  const el = area.value;
  if (!el) return;
  canExpand.value = el.scrollHeight > NORMAL_MAX_HEIGHT;
  if (!canExpand.value && expanded.value) expanded.value = false;
}

function toggleExpand() {
  if (!canExpand.value && !expanded.value) return;
  expanded.value = !expanded.value;
  area.value?.focus();
}

function updateTrigger() {
  const el = area.value;
  const pos = el?.selectionStart ?? text.value.length;
  const before = text.value.slice(0, pos);
  const match = /(^|\s)([@/])([^\s@/]*)$/.exec(before);
  if (!match) {
    mentionTrigger.value = null;
    mentionQuery.value = "";
    mentionStart.value = -1;
    fileCandidates.value = [];
    return;
  }
  const trigger = match[2] as "@" | "/";
  const query = match[3] ?? "";
  mentionTrigger.value = trigger;
  mentionQuery.value = query;
  mentionStart.value = pos - query.length - 1;
  activeIndex.value = 0;

  if (trigger === "@") {
    if (searchTimer) window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(async () => {
      try {
        fileCandidates.value = (await window.whitzDesktop?.workspace.searchFiles(query)) ?? [];
      } catch {
        fileCandidates.value = [];
      }
    }, 80);
  }
}

function applyAtEntry(entry: MentionEntry) {
  if (mentionStart.value < 0) return;
  const el = area.value;
  const end = el?.selectionStart ?? text.value.length;
  const prefix = text.value.slice(0, mentionStart.value);
  const suffix = text.value.slice(end);
  const insertion = `@${entry.value} `;
  text.value = `${prefix}${insertion}${suffix}`;
  mentionTrigger.value = null;
  void nextTick(() => {
    const cursor = prefix.length + insertion.length;
    el?.focus();
    el?.setSelectionRange(cursor, cursor);
    updateExpandState();
  });
}

function applySlashEntry(entry: SlashEntry) {
  mentionTrigger.value = null;
  slashPopoverOpen.value = false;
  if (entry.kind === "skill") {
    if (!selectedSkills.value.includes(entry.name)) {
      selectedSkills.value = [...selectedSkills.value, entry.name];
    }
    if (mentionStart.value >= 0) {
      const el = area.value;
      const end = el?.selectionStart ?? text.value.length;
      text.value = `${text.value.slice(0, mentionStart.value)}${text.value.slice(end)}`.trimStart();
    }
    area.value?.focus();
    return;
  }
  if (entry.kind === "builtin") {
    text.value = "";
    emit("command", { name: entry.name, args: "" });
    return;
  }
  text.value = `/${entry.name} `;
  void nextTick(() => area.value?.focus());
}

function cycleAgent() {
  const list = primaryAgents.value;
  if (list.length < 2) return;
  const idx = list.findIndex((a) => a.name === effectiveAgentName.value);
  const next = list[(idx + 1) % list.length];
  emit("update:prefs", { agent_name: next.name });
}

function selectAgent(name: string) {
  agentMenuOpen.value = false;
  emit("update:prefs", { agent_name: name });
}

function selectModel(opt: OpenCodeModelOption) {
  modelMenuOpen.value = false;
  const nextVariant = opt.variants?.length && effectiveVariant.value && opt.variants.includes(effectiveVariant.value)
    ? effectiveVariant.value
    : null;
  emit("update:prefs", { model_ref: opt.ref, variant: nextVariant });
}

function selectVariant(v: string | null) {
  emit("update:prefs", { variant: v });
}

function submit() {
  const val = text.value.trim();
  if (!val || props.disabled) return;
  if (props.streaming) {
    emit("steer", val);
    text.value = "";
    expanded.value = false;
    void nextTick(updateExpandState);
    return;
  }

  // !command -> native shell
  if (val.startsWith("!") && val.length > 1) {
    text.value = "";
    expanded.value = false;
    emit("shell", val.slice(1).trim());
    void nextTick(updateExpandState);
    return;
  }

  // /command -> builtin or OpenCode command
  if (val.startsWith("/")) {
    const space = val.indexOf(" ");
    const cmdName = (space > 0 ? val.slice(1, space) : val.slice(1)).trim();
    const cmdArgs = space > 0 ? val.slice(space + 1).trim() : "";
    const isBuiltin = BUILTIN_COMMANDS.some((b) => b.name === cmdName);
    const isOcCommand = work.commands.some((c) => c.name === cmdName);
    if (isBuiltin || isOcCommand) {
      text.value = "";
      expanded.value = false;
      emit("command", { name: cmdName, args: cmdArgs });
      void nextTick(updateExpandState);
      return;
    }
  }

  emit("send", {
    text: val,
    skills: [...selectedSkills.value],
    attachments: [...attachments.value],
    modelRef: effectiveModelRef.value,
    agentName: effectiveAgentName.value,
    variant: effectiveVariant.value,
  });
  text.value = "";
  attachments.value = [];
  selectedSkills.value = [];
  expanded.value = false;
  canExpand.value = false;
  void nextTick(updateExpandState);
}

function onKeydown(e: KeyboardEvent) {
  if (dropdownVisible.value) {
    const listLen = mentionTrigger.value === "@" ? atEntries.value.length : slashEntries.value.length;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex.value = (activeIndex.value + 1) % listLen;
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex.value = (activeIndex.value - 1 + listLen) % listLen;
      return;
    }
    if ((e.key === "Enter" || e.key === "Tab") && !e.isComposing) {
      e.preventDefault();
      if (mentionTrigger.value === "@" && atEntries.value[activeIndex.value]) {
        applyAtEntry(atEntries.value[activeIndex.value]);
      } else if (mentionTrigger.value === "/" && slashEntries.value[activeIndex.value]) {
        applySlashEntry(slashEntries.value[activeIndex.value]);
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      mentionTrigger.value = null;
      return;
    }
  }

  if (e.key === "Tab" && !e.shiftKey && !e.isComposing && !props.streaming) {
    e.preventDefault();
    cycleAgent();
    return;
  }

  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submit();
  }
}

async function pickFiles() {
  if (props.disabled) return;
  const picked = (await window.whitzDesktop?.work.pickAttachments()) ?? [];
  if (!picked.length) return;
  const existing = new Set(attachments.value.map((a) => a.path));
  for (const item of picked) {
    if (!existing.has(item.path)) attachments.value.push(item);
  }
}

function removeAttachment(id: string) {
  attachments.value = attachments.value.filter((a) => a.id !== id);
}

function insertPath(relPath: string) {
  const addition = `@${relPath} `;
  text.value = text.value && !text.value.endsWith(" ") ? `${text.value} ${addition}` : `${text.value}${addition}`;
  void nextTick(() => {
    area.value?.focus();
    updateExpandState();
  });
}

function closePopovers() {
  modelMenuOpen.value = false;
  agentMenuOpen.value = false;
  slashPopoverOpen.value = false;
}

watch(text, () => void nextTick(updateExpandState));
onMounted(() => document.addEventListener("click", closePopovers));
onBeforeUnmount(() => {
  document.removeEventListener("click", closePopovers);
  if (searchTimer) window.clearTimeout(searchTimer);
});

defineExpose({ insertPath });
</script>

<template>
  <div class="relative">
    <!-- @ File/Subagent or / Command/Skill Autocomplete Popover -->
    <div
      v-if="dropdownVisible"
      class="absolute bottom-full left-0 z-30 mb-2 max-h-64 w-full max-w-[440px] overflow-y-auto custom-scrollbar rounded-2xl bg-canvas p-1.5 dark:bg-[#1a1a19]"
      style="box-shadow: var(--shadow)"
    >
      <template v-if="mentionTrigger === '@'">
        <button
          v-for="(item, idx) in atEntries"
          :key="`${item.kind}-${item.value}`"
          type="button"
          class="flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-[12.5px] transition-colors"
          :class="idx === activeIndex ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @click="applyAtEntry(item)"
        >
          <span class="min-w-0 flex-1 truncate font-mono text-[12px]">@{{ item.value }}</span>
          <span
            class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium"
            :class="item.kind === 'subagent' ? 'bg-accent-weak text-accent' : 'bg-surface text-fg-faint'"
          >
            {{ item.kind === "subagent" ? "子代理" : "文件" }}
          </span>
        </button>
      </template>

      <template v-else>
        <button
          v-for="(item, idx) in slashEntries"
          :key="`${item.kind}-${item.name}`"
          type="button"
          class="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[12.5px] transition-colors"
          :class="idx === activeIndex ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @click="applySlashEntry(item)"
        >
          <span class="shrink-0 font-mono font-medium text-fg">{{ item.label }}</span>
          <span class="min-w-0 flex-1 truncate text-[11.5px] text-fg-faint">{{ item.desc }}</span>
        </button>
      </template>
    </div>

    <!-- Model Selector Popover (Aligned with Chat Card Style) -->
    <div
      v-if="modelMenuOpen"
      class="absolute bottom-full left-0 z-30 mb-2 w-full max-w-[380px] rounded-2xl bg-canvas p-2.5 dark:bg-[#1a1a19]"
      style="box-shadow: var(--shadow)"
      @click.stop
    >
      <div class="flex items-center justify-between gap-2 px-1 pb-2">
        <span class="text-[12px] font-semibold text-fg">选择 Work 模型</span>
        <button
          type="button"
          class="text-[11.5px] text-fg-faint transition-colors hover:text-fg"
          @click="modelMenuOpen = false; router.push({ name: 'work-settings', query: { tab: 'models' } })"
        >
          管理已启用模型 ›
        </button>
      </div>

      <input
        v-if="enabledModels.length > 6"
        v-model="modelSearch"
        type="text"
        placeholder="过滤已启用模型…"
        class="mb-2 w-full rounded-xl bg-surface px-2.5 py-1.5 text-[12px] text-fg outline-none placeholder:text-fg-faint"
      />

      <div class="max-h-60 space-y-2 overflow-y-auto custom-scrollbar pr-0.5">
        <div v-if="!groupedFilteredModels.length" class="px-2 py-4 text-center text-[12px] text-fg-faint">
          暂无匹配的已启用模型，请在设置中启用模型。
        </div>
        <div v-for="group in groupedFilteredModels" :key="group.providerID" class="space-y-0.5">
          <p class="px-2 pt-1 text-[10.5px] font-medium uppercase tracking-wider text-fg-faint">
            {{ group.providerID }}
          </p>
          <button
            v-for="m in group.items"
            :key="m.ref"
            type="button"
            class="flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12.5px] transition-colors"
            :class="
              effectiveModelRef === m.ref
                ? 'bg-active font-medium text-fg'
                : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
            "
            @click="selectModel(m)"
          >
            <span class="min-w-0 flex-1 truncate">{{ m.modelID }}</span>
            <span class="flex shrink-0 items-center gap-1 text-[10.5px] text-fg-faint">
              <span v-if="m.is_whitz" class="rounded bg-surface px-1.5 py-0.5">Whitz</span>
              <span v-if="m.variants?.length" class="rounded bg-surface px-1.5 py-0.5">{{ m.variants.length }} 档</span>
            </span>
          </button>
        </div>
      </div>

      <!-- Variant / Thinking Effort Strip -->
      <div v-if="availableVariants.length" class="mt-2 border-t border-line/50 pt-2">
        <div class="flex items-center justify-between gap-2 px-1">
          <span class="text-[11px] text-fg-faint">思考档位 (Variant)</span>
          <div class="flex flex-wrap gap-1">
            <button
              type="button"
              class="rounded-lg px-2 py-0.5 text-[11px] transition-colors"
              :class="!effectiveVariant ? 'bg-active font-medium text-fg' : 'text-fg-faint hover:text-fg'"
              @click="selectVariant(null)"
            >
              默认
            </button>
            <button
              v-for="v in availableVariants"
              :key="v"
              type="button"
              class="rounded-lg px-2 py-0.5 text-[11px] transition-colors"
              :class="effectiveVariant === v ? 'bg-active font-medium text-fg' : 'text-fg-faint hover:text-fg'"
              @click="selectVariant(v)"
            >
              {{ v }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Primary Agent Selector Popover -->
    <div
      v-if="agentMenuOpen"
      class="absolute bottom-full left-0 z-30 mb-2 w-64 rounded-2xl bg-canvas p-1.5 dark:bg-[#1a1a19]"
      style="box-shadow: var(--shadow)"
      @click.stop
    >
      <div class="flex items-center justify-between px-2.5 py-1 text-[11px] text-fg-faint">
        <span>切换主代理</span>
        <span class="font-mono text-[10px]">Tab</span>
      </div>
      <button
        v-for="a in primaryAgents"
        :key="a.name"
        type="button"
        class="flex w-full flex-col rounded-xl px-2.5 py-1.5 text-left transition-colors"
        :class="effectiveAgentName === a.name ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
        @click="selectAgent(a.name)"
      >
        <span class="text-[12.5px] font-medium capitalize">{{ a.name }}</span>
        <span v-if="a.description" class="truncate text-[11px] text-fg-faint">{{ a.description }}</span>
      </button>
    </div>

    <!-- Quick Slash Palette (button-triggered) -->
    <div
      v-if="slashPopoverOpen"
      class="absolute bottom-full left-24 z-30 mb-2 max-h-64 w-80 overflow-y-auto custom-scrollbar rounded-2xl bg-canvas p-1.5 dark:bg-[#1a1a19]"
      style="box-shadow: var(--shadow)"
      @click.stop
    >
      <button
        v-for="entry in slashEntries"
        :key="`pop-${entry.kind}-${entry.name}`"
        type="button"
        class="flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        @click="applySlashEntry(entry)"
      >
        <span class="font-mono font-medium text-fg">{{ entry.label }}</span>
        <span class="min-w-0 flex-1 truncate text-[11px] text-fg-faint">{{ entry.desc }}</span>
      </button>
    </div>

    <!-- Main Borderless Tonal Card (Identical Surface Styling to Web ChatInput.vue) -->
    <div
      class="relative rounded-3xl bg-surface p-2 transition-[box-shadow,background-color] duration-200 sm:px-4 sm:py-3.5"
    >
      <!-- Chips Row (Attachments + Selected Skills + Shell Mode Indicator) -->
      <div
        v-if="attachments.length || selectedSkills.length || isShellInput"
        class="mb-2 flex flex-wrap items-center gap-1.5 px-1"
      >
        <span
          v-if="isShellInput"
          class="inline-flex items-center gap-1.5 rounded-xl bg-accent-weak px-2.5 py-1 text-[11.5px] font-medium text-accent"
        >
          终端直接执行 (!shell)
        </span>

        <span
          v-for="att in attachments"
          :key="att.id"
          class="inline-flex max-w-[220px] items-center gap-1.5 rounded-xl bg-canvas/85 px-2.5 py-1 text-[12px] text-fg"
        >
          <img
            v-if="att.preview_url"
            :src="att.preview_url"
            alt=""
            class="h-5 w-5 shrink-0 rounded object-cover"
          />
          <span class="truncate">{{ att.name }}</span>
          <button
            type="button"
            class="text-fg-faint hover:text-fg"
            aria-label="移除文件"
            @click="removeAttachment(att.id)"
          >
            ×
          </button>
        </span>

        <span
          v-for="sk in selectedSkills"
          :key="`sk-${sk}`"
          class="inline-flex items-center gap-1.5 rounded-xl bg-accent-weak/85 px-2.5 py-1 text-[12px] text-fg"
        >
          <span>/{{ sk }}</span>
          <button
            type="button"
            class="text-fg-faint hover:text-fg"
            @click="selectedSkills = selectedSkills.filter((s) => s !== sk)"
          >
            ×
          </button>
        </span>
      </div>

      <!-- 2-Row Composer Grid Matching ChatInput.vue -->
      <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-end gap-x-1.5 sm:grid-cols-[1fr_auto] sm:grid-rows-[auto_auto] sm:gap-y-2">
        <div class="relative col-start-2 row-start-1 flex min-w-0 items-center sm:col-span-2 sm:col-start-1 sm:row-start-1">
          <textarea
            ref="area"
            v-model="text"
            rows="1"
            :disabled="disabled"
            :placeholder="
              streaming
                ? '输入新指令引导当前任务，或点右侧停止…'
                : '给 OpenCode 布置任务…（@ 引用文件/子代理，/ 使用指令，! 运行终端）'
            "
            class="chat-textarea custom-scrollbar block w-full resize-none bg-transparent px-1 py-1.5 text-[15px] leading-6 text-fg outline-none placeholder:text-fg-faint disabled:cursor-not-allowed sm:py-0.5 sm:leading-relaxed"
            :style="{ maxHeight: expanded ? '320px' : '160px' }"
            @input="updateTrigger"
            @keydown="onKeydown"
          />
        </div>

        <!-- Bottom Left Pills: + 文件 | Build/Plan ▾ | Model ▾ | / 指令 -->
        <div class="col-start-1 row-start-1 flex flex-wrap items-center gap-1 self-end sm:col-start-1 sm:row-start-2 sm:gap-1.5 sm:self-center">
          <button
            type="button"
            class="focus-ring flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:opacity-50"
            :disabled="disabled || streaming"
            title="附加本机文件或图片"
            @click="pickFiles"
          >
            <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M21.44 11.05l-8.49 8.49a5.5 5.5 0 01-7.78-7.78l8.49-8.49a3.5 3.5 0 114.95 4.95l-8.49 8.49a1.5 1.5 0 01-2.12-2.12l7.78-7.78"
              />
            </svg>
            <span class="hidden sm:inline">文件</span>
          </button>

          <!-- Agent Mode Switcher (Build / Plan / Custom, Tab to cycle) -->
          <button
            type="button"
            class="focus-ring flex h-8 items-center gap-1 rounded-full bg-canvas/70 px-2.5 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:opacity-50"
            :disabled="disabled || streaming"
            title="切换主代理模式 (Tab)"
            @click.stop="modelMenuOpen = false; slashPopoverOpen = false; agentMenuOpen = !agentMenuOpen"
          >
            <span
              class="h-1.5 w-1.5 rounded-full"
              :style="{ background: effectiveAgentName === 'plan' ? 'var(--warning)' : 'var(--work-accent)' }"
            />
            <span class="capitalize">{{ effectiveAgentName }}</span>
            <svg class="h-3 w-3 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6" />
            </svg>
          </button>

          <!-- Enabled Model + Variant Picker Pill -->
          <button
            type="button"
            class="focus-ring flex h-8 max-w-[200px] items-center gap-1.5 rounded-full bg-canvas/70 px-2.5 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:opacity-50"
            :disabled="disabled || streaming"
            :title="effectiveModelRef || '选择模型'"
            @click.stop="agentMenuOpen = false; slashPopoverOpen = false; modelMenuOpen = !modelMenuOpen"
          >
            <span class="truncate">{{ modelDisplayName }}</span>
            <span
              v-if="effectiveVariant"
              class="shrink-0 rounded bg-surface px-1 py-0.2 text-[10px] text-fg-faint"
            >
              {{ effectiveVariant }}
            </span>
            <svg class="h-3 w-3 shrink-0 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6" />
            </svg>
          </button>

          <!-- Slash Commands & Skills Picker -->
          <button
            type="button"
            class="focus-ring flex h-8 items-center gap-1 rounded-full px-2.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:opacity-50"
            :disabled="disabled || streaming"
            title="斜杠指令与 OpenCode 技能 (/)"
            @click.stop="modelMenuOpen = false; agentMenuOpen = false; slashPopoverOpen = !slashPopoverOpen"
          >
            <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3l1.7 4.6L18 9.3l-4.3 1.7L12 15.6l-1.7-4.6L6 9.3l4.3-1.7L12 3z" />
            </svg>
            <span class="hidden sm:inline">指令</span>
          </button>

          <!-- Full Command Mode Toggle (Allowed anytime, requires warning + consent to enable) -->
          <button
            type="button"
            class="focus-ring flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium transition-colors"
            :class="
              fullCommandMode
                ? 'bg-danger-weak text-danger hover:opacity-90'
                : 'text-fg-faint hover:bg-hover hover:text-fg'
            "
            :title="
              fullCommandMode
                ? '完全命令模式已开启：自动放行全部终端命令（点击关闭）'
                : '开启完全命令模式：自动批准全部终端命令（需风险确认）'
            "
            @click="toggleFullCommandMode"
          >
            <span
              class="h-1.5 w-1.5 rounded-full"
              :style="{ background: fullCommandMode ? 'var(--danger)' : 'var(--fg-faint)' }"
            />
            <span class="whitespace-nowrap">{{ fullCommandMode ? "完全命令" : "命令审批" }}</span>
          </button>
        </div>

        <FullCommandConfirmModal
          :open="fullCommandConfirmOpen"
          @close="fullCommandConfirmOpen = false"
          @confirm="confirmFullCommandMode"
        />

        <!-- Bottom Right: Expand + Send / Stop (Matches ChatInput.vue circular buttons) -->
        <div class="col-start-3 row-start-1 flex items-center justify-end gap-1.5 sm:col-start-2 sm:row-start-2 sm:self-center">
          <button
            v-if="canExpand || expanded"
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            :title="expanded ? '收起输入框' : '展开输入框'"
            @click="toggleExpand"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path
                v-if="expanded"
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M4 14h6v6M20 10h-6V4M14 10l7-7M10 14l-7 7"
              />
              <path
                v-else
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"
              />
            </svg>
          </button>

          <button
            v-if="streaming && text.trim()"
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-canvas text-fg transition-colors hover:bg-hover"
            title="引导发送（追发一条指导消息）"
            @click="submit"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M13 5l7 7-7 7" />
            </svg>
          </button>

          <button
            v-if="streaming"
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-danger text-white transition-opacity hover:opacity-90"
            aria-label="停止运行"
            title="停止运行"
            @click="emit('stop')"
          >
            <span class="h-3 w-3 rounded-[3px] bg-current" />
          </button>

          <button
            v-else
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-colors"
            :class="canSubmit ? 'bg-primary text-primary-fg hover:bg-primary-hover' : 'bg-canvas/70 text-fg-faint cursor-not-allowed'"
            :disabled="!canSubmit"
            aria-label="发送"
            title="发送 (Enter)"
            @click="submit"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
