<script setup lang="ts">
import { ref, watch } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import BaseTextarea from "../ui/BaseTextarea.vue";
import BaseButton from "../ui/BaseButton.vue";

const props = defineProps<{ persona: string }>();
const auth = useAuthStore();
const text = ref(props.persona);
const saving = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);

watch(
  () => props.persona,
  (v) => {
    text.value = v;
  },
);

async function save() {
  saving.value = true;
  message.value = null;
  error.value = null;
  try {
    await api.put("/users/me/persona", { persona: text.value });
    await auth.refreshUser();
    message.value = "已保存。新人设将在新对话中生效。";
  } catch (e: any) {
    error.value = e?.message ?? "保存失败";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="space-y-4">
    <BaseTextarea
      v-model="text"
      label="自定义人设"
      :rows="8"
      placeholder="例如：你是一位严谨的法律顾问，回答时引用法条……留空则使用默认助理人设。"
    />
    <div class="flex items-center justify-between gap-3">
      <p class="text-xs leading-relaxed text-fg-faint">人设会写入助理的 SOUL 文件，修改后对新建对话生效。</p>
      <span class="shrink-0 text-[11px] tabular-nums text-fg-faint">{{ text.length }} / 4000</span>
    </div>
    <p v-if="message" class="text-[13px] text-success">{{ message }}</p>
    <p v-if="error" class="text-[13px] text-danger">{{ error }}</p>
    <BaseButton :loading="saving" @click="save">保存人设</BaseButton>
  </div>
</template>
