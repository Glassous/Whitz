<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import BaseButton from "@web/components/ui/BaseButton.vue";

const version = ref<string | null>(null);
const error = ref<string | null>(null);
let unsubscribe: (() => void) | null = null;

onMounted(() => {
  unsubscribe = window.whitzDesktop?.onUpdateDownloaded((payload) => {
    version.value = payload.version;
  }) ?? null;
});

onUnmounted(() => unsubscribe?.());

async function install() {
  error.value = null;
  try {
    await window.whitzDesktop?.updater.install();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "更新失败";
  }
}
</script>

<template>
  <div
    v-if="version"
    class="fixed inset-x-0 top-10 z-40 flex items-center justify-center gap-3 border-b border-line bg-surface/90 px-4 py-1.5 text-[12px] text-fg-muted backdrop-blur"
  >
    <span>Whitz {{ version }} 已下载完成</span>
    <BaseButton size="sm" variant="secondary" @click="install">立即重启更新</BaseButton>
    <button type="button" class="focus-ring rounded px-1 text-fg-faint hover:text-fg" @click="version = null">稍后</button>
    <span v-if="error" class="text-danger">{{ error }}</span>
  </div>
</template>
