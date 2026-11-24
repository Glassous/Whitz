<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { SkillPendingItem } from "../../types";
import BaseButton from "../ui/BaseButton.vue";
import AppIcon from "../ui/AppIcon.vue";

const props = defineProps<{
  item: SkillPendingItem;
  busy?: boolean;
  error?: string | null;
}>();
const pendingAction = ref<"approve" | "reject" | null>(null);
watch(
  () => props.busy,
  (isBusy) => {
    if (!isBusy) pendingAction.value = null;
  },
);

const emit = defineEmits<{
  resolve: [id: string, action: "approve" | "reject"];
}>();

const isDelete = computed(() => props.item.action === "delete");

const actionLabel = computed(() => {
  switch (props.item.action) {
    case "update":
      return "更新技能";
    case "delete":
      return "删除技能";
    default:
      return "安装技能";
  }
});

const sourceLabel = computed(() => {
  switch (props.item.source) {
    case "github":
      return "GitHub";
    case "agent":
    case "assistant":
      return "助理建议";
    default:
      return props.item.source || "";
  }
});
</script>

<template>
  <div class="animate-rise rounded-2xl bg-surface p-4">
    <div class="flex gap-3">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-weak text-accent">
        <AppIcon name="sparkles" motion="enter-pop" class="h-4 w-4" :stroke-width="1.95" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-1.5">
          <p class="text-sm font-semibold text-fg">技能变更确认</p>
          <span
            class="rounded-full px-2 py-0.5 text-[11px] font-medium"
            :class="isDelete ? 'bg-danger-weak text-danger' : 'bg-accent-weak text-accent'"
          >
            {{ actionLabel }}
          </span>
          <span
            v-if="sourceLabel"
            class="rounded-full bg-canvas px-2 py-0.5 text-[11px] font-medium text-fg-muted"
          >
            {{ sourceLabel }}
          </span>
        </div>

        <p class="mt-1.5 text-[13.5px] font-medium text-fg">{{ item.name }}</p>
        <p v-if="item.description" class="mt-0.5 text-[12.5px] leading-relaxed text-fg-muted">
          {{ item.description }}
        </p>
        <p v-if="item.reason" class="mt-1 text-[12px] text-fg-faint">
          原因：{{ item.reason }}
        </p>

        <details v-if="item.content" class="disclosure-card mt-2 overflow-hidden rounded-xl bg-canvas">
          <summary class="focus-ring flex cursor-pointer items-center justify-between px-3 py-2 text-[12px] font-medium text-fg-muted hover:text-fg">
            <span>查看 SKILL.md 内容</span>
            <AppIcon name="chevron-down" motion="chevron-d" class="h-3.5 w-3.5 text-fg-faint" :stroke-width="2" />
          </summary>
          <pre class="custom-scrollbar max-h-48 overflow-auto border-t border-line px-3 py-2 font-mono text-[11.5px] leading-relaxed text-fg-muted">{{ item.content }}</pre>
        </details>

        <p v-if="error" class="mt-2 text-[12px] text-danger">{{ error }}</p>

        <div class="mt-3 flex gap-2">
          <BaseButton
            size="sm"
            :loading="busy && pendingAction !== 'reject'"
            :disabled="busy"
            @click="pendingAction = 'approve'; emit('resolve', item.id, 'approve')"
          >
            {{ isDelete ? "确认删除" : "确认安装" }}
          </BaseButton>
          <BaseButton
            size="sm"
            variant="secondary"
            :loading="busy && pendingAction === 'reject'"
            :disabled="busy"
            @click="pendingAction = 'reject'; emit('resolve', item.id, 'reject')"
          >
            拒绝
          </BaseButton>
        </div>
      </div>
    </div>
  </div>
</template>
