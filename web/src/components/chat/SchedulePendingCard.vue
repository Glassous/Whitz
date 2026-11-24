<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { ScheduledTaskPendingItem } from "../../types";
import BaseButton from "../ui/BaseButton.vue";
import AppIcon from "../ui/AppIcon.vue";

const props = defineProps<{
  item: ScheduledTaskPendingItem;
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
      return "修改定时任务";
    case "pause":
      return "暂停定时任务";
    case "resume":
      return "恢复定时任务";
    case "delete":
      return "删除定时任务";
    default:
      return "新建定时任务";
  }
});

const taskName = computed(() => String(props.item.payload?.name || "未命名定时任务"));
const taskPrompt = computed(() => String(props.item.payload?.prompt || ""));
const targetLabel = computed(() => {
  const mode = String(props.item.payload?.target_mode || "");
  if (mode === "main") return "投递到主聊天";
  if (mode === "conversation") return "投递到指定对话";
  if (mode === "dedicated") return "任务专属旁聊";
  return "";
});
</script>

<template>
  <div class="animate-rise rounded-2xl bg-surface p-4">
    <div class="flex gap-3">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-weak text-accent">
        <AppIcon name="clock" motion="enter-pop" class="h-4 w-4" :stroke-width="1.95" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-1.5">
          <p class="text-sm font-semibold text-fg">定时任务变更确认</p>
          <span
            class="rounded-full px-2 py-0.5 text-[11px] font-medium"
            :class="isDelete ? 'bg-danger-weak text-danger' : 'bg-accent-weak text-accent'"
          >
            {{ actionLabel }}
          </span>
          <span
            v-if="item.schedule_description"
            class="rounded-full bg-canvas px-2 py-0.5 text-[11px] font-medium text-fg-muted"
          >
            {{ item.schedule_description }}
          </span>
          <span
            v-if="targetLabel"
            class="rounded-full bg-canvas px-2 py-0.5 text-[11px] font-medium text-fg-muted"
          >
            {{ targetLabel }}
          </span>
        </div>

        <p class="mt-1.5 text-[13.5px] font-medium text-fg">{{ taskName }}</p>
        <p v-if="taskPrompt" class="mt-1 line-clamp-3 whitespace-pre-wrap text-[12.5px] leading-relaxed text-fg-muted">
          指令：{{ taskPrompt }}
        </p>
        <p v-if="item.reason" class="mt-1 text-[12px] text-fg-faint">
          说明：{{ item.reason }}
        </p>

        <p v-if="error" class="mt-2 text-[12px] text-danger">{{ error }}</p>

        <div class="mt-3 flex gap-2">
          <BaseButton
            size="sm"
            :loading="busy && pendingAction !== 'reject'"
            :disabled="busy"
            @click="pendingAction = 'approve'; emit('resolve', item.id, 'approve')"
          >
            {{ isDelete ? "确认删除" : "确认生效" }}
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
