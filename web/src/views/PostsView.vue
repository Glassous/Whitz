<script setup lang="ts">
import { inject } from "vue";
import { useRouter } from "vue-router";
import PostsFeedPanel from "../components/posts/PostsFeedPanel.vue";
import { APP_SHELL_KEY } from "../layouts/AppShellLayout.vue";

const router = useRouter();
const shell = inject(APP_SHELL_KEY, null);

function onDiscussInChat(payload: { conversationId: string; prefillPrompt: string }) {
  void router.push({
    name: "chat-conversation",
    params: { id: payload.conversationId },
    query: payload.prefillPrompt ? { prefill: payload.prefillPrompt } : undefined,
  });
}

function onOpenGuide() {
  void router.push({ name: "posts-guide" });
}
</script>

<template>
  <div class="relative flex min-w-0 flex-1 flex-col bg-canvas">
    <PostsFeedPanel
      @open-mobile-nav="shell?.openMobileNav()"
      @open-guide="onOpenGuide"
      @discuss-in-chat="onDiscussInChat"
    />
  </div>
</template>
