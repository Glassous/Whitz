<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import BaseButton from "../ui/BaseButton.vue";

const props = defineProps<{ persona: string }>();
const auth = useAuthStore();
const text = ref(props.persona);
const saving = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);

const isDirty = computed(() => text.value !== props.persona);

watch(
  () => props.persona,
  (v) => {
    text.value = v;
  },
);

function resetDraft() {
  text.value = props.persona;
  message.value = null;
  error.value = null;
}

async function save() {
  saving.value = true;
  message.value = null;
  error.value = null;
  try {
    await api.put("/users/me/persona", { persona: text.value });
    await auth.refreshUser();
    message.value = "已保存，对新对话生效";
  } catch (e: any) {
    error.value = typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "保存失败");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <form
    method="POST"
    action="/api/users/me/persona"
    aria-labelledby="heading-persona"
    class="flex min-h-0 flex-1 flex-col"
    @submit.prevent="save"
  >
    <div class="mb-2.5 flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2">
        <h2 id="heading-persona" class="text-[15px] font-semibold text-fg">
          <label for="settings-persona" class="cursor-pointer">助理人设</label>
        </h2>
        <span class="shrink-0 rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-fg-muted dark:bg-canvas">
          新对话生效
        </span>
      </div>
      <span id="persona-help" class="shrink-0 text-[12px] tabular-nums text-fg-faint">{{ text.length }} / 4000</span>
    </div>

    <textarea
      id="settings-persona"
      v-model="text"
      v-scrollbar
      name="persona"
      maxlength="4000"
      aria-describedby="persona-help"
      placeholder="例如：你是一位严谨的法律顾问，回答时结构清晰并引用依据……留空则使用默认助理人设。"
      class="persona-textarea custom-scrollbar resize-y rounded-2xl border border-line/80 bg-canvas px-3.5 py-2.5 text-[14px] leading-relaxed text-fg outline-none transition-colors placeholder:text-fg-faint hover:border-line-strong focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1"
      @input="message = null; error = null"
    />

    <div class="mt-2.5 flex flex-wrap items-center justify-between gap-2">
      <div class="min-w-0 flex-1">
        <p v-if="error" role="alert" class="truncate text-[12.5px] text-danger">{{ error }}</p>
        <p v-else-if="message" role="status" aria-live="polite" class="truncate text-[12.5px] text-success">
          {{ message }}
        </p>
        <p v-else class="truncate text-[12px] text-fg-faint">写入助理 SOUL 配置，定制语气、角色与输出格式</p>
      </div>

      <div class="flex shrink-0 items-center gap-1.5">
        <BaseButton v-if="isDirty" type="button" variant="ghost" size="sm" rounded="full" @click="resetDraft">
          还原
        </BaseButton>
        <BaseButton type="submit" size="sm" rounded="full" :loading="saving">保存人设</BaseButton>
      </div>
    </div>
  </form>
</template>
