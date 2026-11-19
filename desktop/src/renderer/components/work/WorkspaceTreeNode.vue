<script setup lang="ts">
import { computed } from "vue";
import type { WorkspaceEntry } from "@shared/work-types";
import { useWorkStore } from "../../stores/work";

const props = defineProps<{
  entry: WorkspaceEntry;
  depth?: number;
}>();

const emit = defineEmits<{
  insertPath: [string];
}>();

const work = useWorkStore();
const depth = computed(() => props.depth ?? 0);
const isDir = computed(() => props.entry.kind === "dir");
const isExpanded = computed(() => isDir.value && work.expandedDirs.has(props.entry.rel_path));
const children = computed(() => (isDir.value ? work.childrenByDir[props.entry.rel_path] ?? [] : []));
const isSelected = computed(() => work.previewFile?.rel_path === props.entry.rel_path);

async function onClick() {
  if (isDir.value) {
    await work.toggleDir(props.entry.rel_path);
  } else {
    await work.openFilePreview(props.entry.rel_path);
  }
}
</script>

<template>
  <div>
    <div
      class="group flex items-center gap-1.5 rounded-lg pr-1.5 text-[12px] transition-colors"
      :class="isSelected ? 'bg-active text-fg font-medium' : 'text-fg-muted hover:bg-hover/70 hover:text-fg'"
      :style="{ paddingLeft: `${8 + depth * 14}px` }"
    >
      <button
        type="button"
        class="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left"
        :title="entry.rel_path"
        @click="onClick"
      >
        <svg
          v-if="isDir"
          class="h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform"
          :class="isExpanded ? 'rotate-90' : ''"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
        </svg>
        <svg
          v-else
          class="h-3.5 w-3.5 shrink-0 text-fg-faint"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M14 2H7a2 2 0 00-2 2v16a2 2 0 002 2h10a2 2 0 002-2V7l-5-5z" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M14 2v5h5" />
        </svg>
        <span class="truncate">{{ entry.name }}</span>
      </button>

      <button
        v-if="!isDir"
        type="button"
        class="hidden shrink-0 rounded px-1 py-0.5 text-[10.5px] text-fg-faint hover:bg-surface hover:text-fg group-hover:block"
        title="引用路径到输入框 (@)"
        @click.stop="emit('insertPath', entry.rel_path)"
      >
        @
      </button>
    </div>

    <template v-if="isDir && isExpanded">
      <WorkspaceTreeNode
        v-for="child in children"
        :key="child.rel_path"
        :entry="child"
        :depth="depth + 1"
        @insert-path="emit('insertPath', $event)"
      />
      <p
        v-if="!children.length"
        class="py-1 text-[11px] text-fg-faint"
        :style="{ paddingLeft: `${28 + depth * 14}px` }"
      >
        空目录
      </p>
    </template>
  </div>
</template>
