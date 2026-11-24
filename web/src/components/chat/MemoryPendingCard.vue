<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { MemoryPendingItem } from "../../types";
import BaseButton from "../ui/BaseButton.vue";
import AppIcon from "../ui/AppIcon.vue";

const props = defineProps<{
  item: MemoryPendingItem;
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
  resolve: [id: string, action: "approve" | "reject", content?: string];
}>();

const editing = ref(false);
const draftContent = ref(props.item.content);

watch(
  () => props.item.content,
  (val) => {
    draftContent.value = val;
    editing.value = false;
  },
);

const isDelete = computed(() => props.item.action === "remove" || props.item.action === "delete");
const targetLabel = computed(() => (props.item.target === "user" ? "个人偏好" : "长期记忆"));

const actionLabel = computed(() => {
  switch (props.item.action) {
    case "replace":
    case "update":
      return "替换";
    case "remove":
    case "delete":
      return "删除";
    default:
      return "新增";
  }
});

function approve() {
  const edited = editing.value ? draftContent.value.trim() : undefined;
  emit("resolve", props.item.id, "approve", edited && edited !== props.item.content ? edited : undefined);
}
</script>

<template>
  <div class="animate-rise rounded-2xl bg-surface p-4">
    <div class="flex gap-3">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-weak text-accent">
        <AppIcon name="lightbulb" motion="enter-pop" class="h-4 w-4" :stroke-width="1.95" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-1.5">
          <p class="text-sm font-semibold text-fg">记忆写入确认</p>
          <span class="rounded-full bg-canvas px-2 py-0.5 text-[11px] font-medium text-fg-muted">
            {{ targetLabel }}
          </span>
          <span
            class="rounded-full px-2 py-0.5 text-[11px] font-medium"
            :class="isDelete ? 'bg-danger-weak text-danger' : 'bg-accent-weak text-accent'"
          >
            {{ actionLabel }}
          </span>
        </div>

        <p v-if="item.reason" class="mt-1 text-[12.5px] leading-relaxed text-fg-muted">
          {{ item.reason }}
        </p>

        <div
          v-if="item.old_content"
          class="mt-2 rounded-lg bg-canvas/60 px-3 py-2 text-[12.5px] leading-relaxed text-fg-faint line-through"
        >
          {{ item.old_content }}
        </div>

        <div v-if="editing && !isDelete" class="mt-2">
          <textarea
            v-model="draftContent"
            rows="3"
            class="focus-ring w-full resize-y rounded-xl bg-canvas px-3 py-2 text-[13px] leading-relaxed text-fg"
          />
        </div>
        <p
          v-else
          class="mt-2 whitespace-pre-wrap break-words rounded-xl bg-canvas px-3 py-2 text-[13px] leading-relaxed text-fg"
        >
          {{ item.content }}
        </p>

        <p v-if="error" class="mt-2 text-[12px] text-danger">{{ error }}</p>

        <div class="mt-3 flex flex-wrap items-center gap-2">
          <BaseButton
            size="sm"
            :loading="busy && pendingAction !== 'reject'"
            :disabled="busy || (editing && !draftContent.trim())"
            @click="pendingAction = 'approve'; approve()"
          >
            {{ isDelete ? "确认删除" : "允许保存" }}
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
          <button
            v-if="!isDelete"
            type="button"
            class="focus-ring ml-auto rounded-lg px-2 py-1 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            :disabled="busy"
            @click="editing = !editing"
          >
            {{ editing ? "取消编辑" : "修改内容" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
