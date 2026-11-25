<script setup lang="ts">
import { computed } from "vue";
import { useAuthStore } from "../../stores/auth";
import AppIcon from "../ui/AppIcon.vue";
import Spinner from "../ui/Spinner.vue";

const props = defineProps<{
  enabling?: boolean;
}>();

const emit = defineEmits<{
  enable: [];
  "open-guide": [];
}>();

const auth = useAuthStore();
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");
</script>

<template>
  <div class="relative flex flex-1 flex-col items-center justify-center overflow-hidden px-6 py-16 text-center">
    <!-- Subtle ambient breathing glow -->
    <div class="onboarding-orb pointer-events-none absolute h-72 w-72 rounded-full blur-3xl" aria-hidden="true" />

    <div class="onboarding-enter relative z-10 flex w-full max-w-sm flex-col items-center">
      <div
        class="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-line bg-surface/90 text-fg shadow-xs"
      >
        <AppIcon name="compass" class="h-7 w-7" :stroke-width="1.75" />
      </div>

      <h2 class="text-[22px] font-bold tracking-tight text-fg">私人动态</h2>
      <p class="mt-2.5 text-[14px] leading-relaxed text-fg-muted">
        {{ assistantName }} 根据你的长期记忆，每日联网为你写动态；你也可以随时发帖，严格仅你可见。
      </p>

      <p class="mt-3 text-[12px] leading-relaxed text-fg-faint">
        默认关闭 · 开启后自动生成与互动会正常消耗账号积分，0 记忆自动跳过，随时可关闭
      </p>

      <div class="mt-7 flex w-full flex-col gap-2.5 sm:flex-row sm:justify-center">
        <button
          type="button"
          class="onboarding-cta focus-ring relative inline-flex h-10 items-center justify-center gap-2 overflow-hidden rounded-full bg-primary px-6 text-[13.5px] font-semibold text-primary-fg shadow-xs transition-transform duration-150 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-60"
          :disabled="enabling"
          @click="emit('enable')"
        >
          <Spinner v-if="enabling" class="h-4 w-4" />
          <AppIcon v-else name="sparkles" class="h-4 w-4" :stroke-width="2" />
          <span>{{ enabling ? "正在开启..." : "开启私人动态" }}</span>
        </button>

        <button
          type="button"
          class="focus-ring inline-flex h-10 items-center justify-center gap-1.5 rounded-full border border-line bg-canvas px-5 text-[13.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          @click="emit('open-guide')"
        >
          <AppIcon name="info" class="h-4 w-4" :stroke-width="1.85" />
          <span>功能说明</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.onboarding-orb {
  background: radial-gradient(circle, color-mix(in srgb, var(--primary) 12%, transparent), transparent 70%);
  animation: orbPulse 9s ease-in-out infinite alternate;
}

.onboarding-enter {
  animation: fadeUp 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.onboarding-cta::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 25%, rgba(255, 255, 255, 0.22) 50%, transparent 75%);
  transform: translateX(-120%);
  transition: transform 0.6s ease;
}

.onboarding-cta:hover::after {
  transform: translateX(120%);
}

@keyframes orbPulse {
  0% { transform: scale(0.95); opacity: 0.7; }
  100% { transform: scale(1.12); opacity: 1; }
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .onboarding-orb,
  .onboarding-enter {
    animation: none !important;
  }
}
</style>
