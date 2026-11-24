<script setup lang="ts">
import type { PendingControl } from "../../types";
import BaseButton from "../ui/BaseButton.vue";
import AppIcon from "../ui/AppIcon.vue";

defineProps<{
  control: PendingControl;
  submittingChoice?: "once" | "deny" | null;
}>();
const emit = defineEmits<{ decide: ["once" | "deny"] }>();
</script>

<template>
  <div class="animate-rise rounded-2xl bg-surface p-4">
    <div class="flex gap-3">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning-weak text-warning">
        <AppIcon name="alert-triangle" class="h-4 w-4" :stroke-width="1.95" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">需要你的批准</p>
        <p class="mt-1 text-[13px] leading-relaxed text-fg-muted">
          助理请求执行操作<span v-if="control.tool" class="font-medium text-fg">「{{ control.tool }}」</span>，是否允许？
        </p>
        <pre
          v-if="control.preview"
          class="mt-3 max-h-40 overflow-auto rounded-lg bg-surface p-2.5 font-mono text-[12px] leading-relaxed text-fg-muted"
        >{{ control.preview }}</pre>
        <div class="mt-3 flex gap-2">
          <BaseButton
            size="sm"
            :loading="submittingChoice === 'once'"
            :disabled="!!submittingChoice"
            @click="emit('decide', 'once')"
          >
            {{ submittingChoice === "once" ? "批准中…" : "允许一次" }}
          </BaseButton>
          <BaseButton
            size="sm"
            variant="secondary"
            :loading="submittingChoice === 'deny'"
            :disabled="!!submittingChoice"
            @click="emit('decide', 'deny')"
          >
            {{ submittingChoice === "deny" ? "拒绝中…" : "拒绝" }}
          </BaseButton>
        </div>
      </div>
    </div>
  </div>
</template>
