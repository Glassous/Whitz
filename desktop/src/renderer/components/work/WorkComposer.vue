<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { WorkAttachment } from "@shared/work-types";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore } from "../../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{
  streaming: boolean;
  sending: boolean;
  disabled: boolean;
  disabledReason: string | null;
}>();

const emit = defineEmits<{
  send: [payload: { content: string; skillNames: string[]; attachments: WorkAttachment[] }];
  steer: [string];
  stop: [];
}>();

const work = useWorkStore();
const runtime = useRuntimeStore();

const text = ref("");
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const selectedSkills = ref<string[]>([]);
const attachments = ref<WorkAttachment[]>([]);
const skillMenuOpen = ref(false);

// @file mention state
const mentionOpen = ref(false);
const mentionQuery = ref("");
const mentionStart = ref(-1);
const mentionResults = ref<string[]>([]);
const mentionIndex = ref(0);

const canSubmit = computed(() => !props.disabled && !props.sending && text.value.trim().length > 0);
const isBuiltin = computed(() => {
  const m = runtime.settings?.model;
  if (!m) return false;
  if (m.mode === "builtin") return true;
  return m.active_model_label.startsWith("whitz/");
});
const modelBadge = computed(() => {
  const m = runtime.settings?.model;
  if (!m) return "未配置模型";
  if (isBuiltin.value) return `Whitz 内置 (${m.active_model_label}) · 共享额度`;
  return `本机 OpenCode (${m.active_model_label})`;
});

function resizeTextarea() {
  void nextTick(() => {
    const el = textareaRef.value;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(200, Math.max(26, el.scrollHeight))}px`;
  });
}

watch(text, () => {
  resizeTextarea();
});

function insertPath(relPath: string) {
  const token = `@${relPath} `;
  const el = textareaRef.value;
  if (!el) {
    text.value = text.value ? `${text.value.trimEnd()} ${token}` : token;
    return;
  }
  const pos = el.selectionStart ?? text.value.length;
  const before = text.value.slice(0, pos);
  const after = text.value.slice(pos);
  const needsSpace = before.length > 0 && !/\s$/.test(before);
  text.value = `${before}${needsSpace ? " " : ""}${token}${after}`;
  void nextTick(() => {
    el.focus();
  });
}

async function onInput() {
  if (!work.activeWorkspace) {
    mentionOpen.value = false;
    return;
  }
  const el = textareaRef.value;
  const cursor = el?.selectionStart ?? text.value.length;
  const before = text.value.slice(0, cursor);
  const match = /(?:^|\s)@([^\s@]*)$/.exec(before);
  if (!match) {
    mentionOpen.value = false;
    return;
  }
  mentionStart.value = cursor - match[1].length - 1;
  mentionQuery.value = match[1];
  mentionIndex.value = 0;
  try {
    mentionResults.value = await (window.whitzDesktop?.workspace.searchFiles(match[1]) ?? Promise.resolve([]));
    mentionOpen.value = mentionResults.value.length > 0;
  } catch {
    mentionOpen.value = false;
  }
}

function applyMention(filePath: string) {
  const el = textareaRef.value;
  const cursor = el?.selectionStart ?? text.value.length;
  const start = mentionStart.value >= 0 ? mentionStart.value : cursor;
  const next = `${text.value.slice(0, start)}@${filePath} ${text.value.slice(cursor)}`;
  text.value = next;
  mentionOpen.value = false;
  void nextTick(() => {
    if (el) {
      const targetPos = start + filePath.length + 2;
      el.focus();
      el.setSelectionRange(targetPos, targetPos);
    }
  });
}

async function openSkills() {
  skillMenuOpen.value = !skillMenuOpen.value;
  if (skillMenuOpen.value) {
    await work.loadSkills();
  }
}

function toggleSkill(name: string) {
  if (selectedSkills.value.includes(name)) {
    selectedSkills.value = selectedSkills.value.filter((s) => s !== name);
  } else {
    selectedSkills.value = [...selectedSkills.value, name];
  }
}

async function pickFiles() {
  const picked = await window.whitzDesktop?.work.pickAttachments();
  if (picked?.length) {
    attachments.value = [...attachments.value, ...picked].slice(0, 8);
  }
}

function removeAttachment(id: string) {
  attachments.value = attachments.value.filter((a) => a.id !== id);
}

function submit() {
  if (!canSubmit.value) return;
  const value = text.value.trim();
  text.value = "";
  mentionOpen.value = false;
  if (props.streaming) {
    emit("steer", value);
    return;
  }
  const skills = [...selectedSkills.value];
  const files = [...attachments.value];
  selectedSkills.value = [];
  attachments.value = [];
  emit("send", { content: value, skillNames: skills, attachments: files });
}

function onKeydown(event: KeyboardEvent) {
  if (mentionOpen.value && mentionResults.value.length) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      mentionIndex.value = (mentionIndex.value + 1) % mentionResults.value.length;
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      mentionIndex.value = (mentionIndex.value - 1 + mentionResults.value.length) % mentionResults.value.length;
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      applyMention(mentionResults.value[mentionIndex.value]);
      return;
    }
    if (event.key === "Escape") {
      mentionOpen.value = false;
      return;
    }
  }
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}

defineExpose({ insertPath });
</script>

<template>
  <div class="relative border-t border-line bg-canvas/85 px-5 py-3.5 backdrop-blur sm:px-6">
    <div class="mx-auto max-w-[860px]">
      <!-- @file Autocomplete Popover -->
      <div
        v-if="mentionOpen && mentionResults.length"
        class="mb-2 max-h-52 overflow-y-auto custom-scrollbar rounded-xl border border-line bg-canvas p-1.5 shadow-lg dark:bg-[#161615]"
        style="box-shadow: var(--shadow)"
      >
        <p class="px-2 pb-1 text-[10.5px] font-medium text-fg-faint">工作区文件引用</p>
        <button
          v-for="(item, idx) in mentionResults"
          :key="item"
          type="button"
          class="flex w-full items-center rounded-lg px-2.5 py-1.5 text-left font-mono text-[12px] transition-colors"
          :class="idx === mentionIndex ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @mousedown.prevent="applyMention(item)"
        >
          {{ item }}
        </button>
      </div>

      <!-- Selected Skills & Attachments Pills -->
      <div v-if="selectedSkills.length || attachments.length" class="mb-2 flex flex-wrap gap-1.5">
        <span
          v-for="skill in selectedSkills"
          :key="`s-${skill}`"
          class="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11.5px]"
          style="border-color: color-mix(in srgb, var(--work-accent) 40%, var(--line)); color: var(--work-accent)"
        >
          /{{ skill }}
          <button type="button" class="hover:opacity-70" @click="toggleSkill(skill)">×</button>
        </span>
        <span
          v-for="att in attachments"
          :key="att.id"
          class="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-0.5 text-[11.5px] text-fg-muted"
        >
          <span>{{ att.kind === "image" ? "🖼" : "📄" }} {{ att.name }}</span>
          <button type="button" class="hover:text-danger" @click="removeAttachment(att.id)">×</button>
        </span>
      </div>

      <div
        class="rounded-2xl border bg-canvas px-3.5 py-2.5 transition-colors"
        :class="disabled ? 'border-line opacity-75' : 'border-line focus-within:border-line-strong'"
      >
        <textarea
          ref="textareaRef"
          v-model="text"
          rows="1"
          class="chat-textarea block max-h-[200px] w-full resize-none border-0 bg-transparent text-[14px] leading-relaxed text-fg outline-none placeholder:text-fg-faint"
          :placeholder="
            disabled
              ? disabledReason ?? '当前不可用'
              : streaming
                ? '运行中：输入指令点击「引导」可补充要求或调整 OpenCode 方向…'
                : work.activeWorkspace
                  ? `在「${work.activeWorkspace.name}」中交代编码任务，输入 @ 引用文件…`
                  : '交代任务，或先在侧栏选择本地工作区文件夹…'
          "
          :disabled="disabled"
          @input="onInput"
          @keydown="onKeydown"
        ></textarea>

        <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              class="focus-ring rounded-lg border border-line px-2 py-1 text-[11.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:opacity-50"
              :disabled="disabled || streaming"
              title="附加本地文件或图片"
              @click="pickFiles"
            >
              + 文件
            </button>

            <div class="relative">
              <button
                type="button"
                class="focus-ring rounded-lg border border-line px-2 py-1 text-[11.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:opacity-50"
                :disabled="disabled || streaming"
                title="选择本地 OpenCode 技能"
                @click="openSkills"
              >
                / 技能{{ selectedSkills.length ? ` (${selectedSkills.length})` : "" }}
              </button>

              <div
                v-if="skillMenuOpen"
                class="absolute bottom-full left-0 z-30 mb-1.5 w-64 rounded-xl border border-line bg-canvas p-1.5 shadow-lg dark:bg-[#161615]"
                style="box-shadow: var(--shadow)"
              >
                <div class="flex items-center justify-between px-2 py-1">
                  <span class="text-[11px] font-medium text-fg-faint">本地 OpenCode 技能</span>
                  <button type="button" class="text-[11px] text-fg-faint hover:text-fg" @click="skillMenuOpen = false">关闭</button>
                </div>
                <div class="max-h-48 overflow-y-auto custom-scrollbar">
                  <button
                    v-for="skill in work.skills"
                    :key="skill.name"
                    type="button"
                    class="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] transition-colors hover:bg-hover"
                    @click="toggleSkill(skill.name)"
                  >
                    <span class="mt-0.5 text-[11px]">{{ selectedSkills.includes(skill.name) ? "✓" : "·" }}</span>
                    <div class="min-w-0 flex-1">
                      <p class="truncate font-medium text-fg">{{ skill.name }}</p>
                      <p v-if="skill.description" class="truncate text-[10.5px] text-fg-faint">{{ skill.description }}</p>
                    </div>
                  </button>
                  <p v-if="!work.skills.length" class="px-2 py-3 text-center text-[11.5px] text-fg-faint">
                    暂无可用本地技能（启动运行时后自动加载）
                  </p>
                </div>
              </div>
            </div>

            <span class="hidden text-[11px] sm:inline" :class="isBuiltin ? 'text-fg-muted' : 'text-fg-faint'">
              {{ modelBadge }}
            </span>
          </div>

          <div class="flex items-center gap-2">
            <BaseButton v-if="streaming" size="sm" variant="secondary" @click="emit('stop')">停止</BaseButton>
            <BaseButton size="sm" :disabled="!canSubmit" @click="submit">
              {{ streaming ? "引导" : "发送" }}
            </BaseButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
