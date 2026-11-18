<script setup lang="ts">
import TitleBar from "./components/shell/TitleBar.vue";
import UpdateBanner from "./components/shell/UpdateBanner.vue";
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden bg-canvas text-fg">
    <TitleBar />
    <UpdateBanner />
    <main class="min-h-0 flex-1 overflow-hidden">
      <router-view />
    </main>
  </div>
</template>
