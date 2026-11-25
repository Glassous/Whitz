<script lang="ts">
import type { InjectionKey } from "vue";

export interface AppShellContext {
  openSearch: () => void;
  openMobileNav: () => void;
  registerChatRailToggle: (fn: (() => void) | null) => void;
}

export const APP_SHELL_KEY: InjectionKey<AppShellContext> = Symbol("app-shell");
</script>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, provide, ref } from "vue";
import { useRouter } from "vue-router";
import PrimaryNavRail from "../components/layout/PrimaryNavRail.vue";
import SearchModal from "../components/chat/SearchModal.vue";
import { useConversationsStore } from "../stores/conversations";
import { useCreditsStore } from "../stores/credits";
import { useRealtimeStore } from "../stores/realtime";

const router = useRouter();
const conversations = useConversationsStore();
const credits = useCreditsStore();
const realtime = useRealtimeStore();

const searchOpen = ref(false);
const mobileNavOpen = ref(false);
let chatRailToggleHandler: (() => void) | null = null;

function openSearch() {
  searchOpen.value = true;
}

function openMobileNav() {
  mobileNavOpen.value = true;
}

function registerChatRailToggle(fn: (() => void) | null) {
  chatRailToggleHandler = fn;
}

provide(APP_SHELL_KEY, {
  openSearch,
  openMobileNav,
  registerChatRailToggle,
});

function onClickChatWhenActive() {
  chatRailToggleHandler?.();
}

function onSelectFromSearch(conversationId: string, messageId: string | null) {
  searchOpen.value = false;
  void router.push({
    name: "chat-conversation",
    params: { id: conversationId },
    query: messageId ? { msg: messageId } : undefined,
  });
}

function onSelectFileFromSearch() {
  searchOpen.value = false;
  void router.push({ name: "library" });
}

function onSelectMemoryFromSearch() {
  searchOpen.value = false;
  void router.push({ name: "settings", query: { tab: "memory" } });
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    searchOpen.value = !searchOpen.value;
  }
}

onMounted(() => {
  window.addEventListener("keydown", onGlobalKeydown);
  realtime.start();
  void credits.fetch();
  if (conversations.conversations.length === 0) {
    void conversations.fetchList();
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
  realtime.stop();
});
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-canvas">
    <!-- Desktop Fixed Primary Icon Rail -->
    <div class="hidden h-full shrink-0 md:flex">
      <PrimaryNavRail
        @open-search="openSearch"
        @click-chat-when-active="onClickChatWhenActive"
      />
    </div>

    <!-- Mobile Navigation Rail Drawer (used by non-chat routes) -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="mobileNavOpen"
        class="fixed inset-0 z-40 bg-black/40 md:hidden"
        @click="mobileNavOpen = false"
      />
    </Transition>
    <Transition
      enter-active-class="transition duration-220 ease-[cubic-bezier(0.22,1,0.36,1)]"
      enter-from-class="-translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition duration-180 ease-in"
      leave-from-class="translate-x-0"
      leave-to-class="-translate-x-full"
    >
      <div v-if="mobileNavOpen" class="fixed inset-y-0 left-0 z-50 flex h-full md:hidden">
        <PrimaryNavRail
          @open-search="openSearch"
          @click-chat-when-active="mobileNavOpen = false"
          @navigate="mobileNavOpen = false"
        />
      </div>
    </Transition>

    <!-- Main Route Area (ChatView includes its own chat-history sidebar; all other routes own 100% of this area) -->
    <div class="relative flex min-w-0 flex-1 overflow-hidden">
      <router-view />
    </div>

    <SearchModal
      :open="searchOpen"
      :conversations="conversations.conversations"
      @close="searchOpen = false"
      @select="onSelectFromSearch"
      @select-file="onSelectFileFromSearch"
      @select-memory="onSelectMemoryFromSearch"
    />
  </div>
</template>
