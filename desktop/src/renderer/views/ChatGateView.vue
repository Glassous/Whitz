<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useDesktopStore } from "../stores/desktop";
import BaseButton from "@web/components/ui/BaseButton.vue";

const route = useRoute();
const router = useRouter();
const desktop = useDesktopStore();

const redirect = computed(() => {
  const raw = typeof route.query.redirect === "string" ? route.query.redirect : "/chat";
  return raw.startsWith("/") && !raw.startsWith("//") ? raw : "/chat";
});
const offline = computed(() => route.query.offline === "1" || !desktop.online);
const retrying = ref(false);

function goLogin() {
  void router.push({ name: "login", query: { redirect: redirect.value } });
}

function goWork() {
  void router.push({ name: "work" });
}

async function retry() {
  retrying.value = true;
  try {
    await desktop.refreshConnectivity();
    if (desktop.online && desktop.loggedIn) void router.push(redirect.value);
  } finally {
    retrying.value = false;
  }
}
</script>

<template>
  <div class="work-glow flex h-full items-center justify-center px-8">
    <section class="animate-rise w-full max-w-[560px] rounded-3xl border border-line bg-canvas/85 p-8 shadow-[var(--shadow)] backdrop-blur">
      <div class="flex items-center gap-3">
        <span class="brand-mark h-6 w-6 text-fg"></span>
        <span class="text-[12px] font-medium uppercase tracking-[0.18em] text-fg-faint">Whitz Chat</span>
      </div>
      <h1 class="mt-5 text-[24px] font-semibold leading-tight tracking-tight text-fg">
        {{ offline ? "当前处于离线状态" : desktop.loggedIn ? "Chat 暂不可用" : "登录后开始云端对话" }}
      </h1>
      <p class="mt-2 text-[14px] leading-relaxed text-fg-muted">
        <template v-if="offline">
          Whitz 服务暂时无法连接，云端 Chat 已禁用。你的本地会话不受影响，可以继续使用
          <span class="font-medium" style="color: var(--work-accent)">Whitz Work</span>。
        </template>
        <template v-else>
          云端会话、文件工作区、技能与内置模型额度需要 Whitz 账号。未登录时仍可以使用
          <span class="font-medium" style="color: var(--work-accent)">Whitz Work</span>
          ，把本机当作一个普通 Hermes Agent。
        </template>
      </p>

      <ul class="mt-6 space-y-2.5 text-[13.5px] text-fg-muted">
        <li class="flex items-start gap-2.5">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style="background: var(--success)"></span>
          会话与文件多端同步，随时从网页继续
        </li>
        <li class="flex items-start gap-2.5">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style="background: var(--success)"></span>
          使用账号共享的内置模型额度，无需自备 Key
        </li>
        <li class="flex items-start gap-2.5">
          <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style="background: var(--fg-faint)"></span>
          未登录时 Work 的对话与记忆只保存在本机
        </li>
      </ul>

      <div class="mt-7 flex flex-wrap items-center gap-3">
        <template v-if="offline">
          <BaseButton size="lg" :loading="retrying" @click="retry">重试连接</BaseButton>
          <BaseButton variant="secondary" size="lg" @click="goWork">
            {{ desktop.workEnabled ? "继续用 Work" : "返回首页" }}
          </BaseButton>
        </template>
        <template v-else>
          <BaseButton v-if="desktop.loggedIn" size="lg" @click="router.push(redirect)">进入 Chat</BaseButton>
          <BaseButton v-else size="lg" @click="goLogin">去登录</BaseButton>
          <BaseButton variant="secondary" size="lg" @click="goWork">
            {{ !desktop.workEnabled ? "返回首页" : desktop.loggedIn ? "继续用 Work" : "不登录，使用 Work 模式" }}
          </BaseButton>
        </template>
      </div>

      <p v-if="!desktop.loggedIn && desktop.workEnabled" class="mt-4 text-[12px] leading-relaxed text-fg-faint">
        Work 模式的数据只保存在本机；登录后可随时切换回云端 Chat，并解锁共享额度。
      </p>

      <p v-if="!desktop.workEnabled" class="mt-4 text-[12px] text-fg-faint">
        当前版本的 Work 模式未启用，请登录后使用 Chat。
      </p>
    </section>
  </div>
</template>
