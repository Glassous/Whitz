<script setup lang="ts">
import ThemeToggle from "./ui/ThemeToggle.vue";

defineProps<{ title: string; subtitle?: string }>();

const features = [
  {
    title: "多步骤任务规划",
    desc: "自动拆解目标，执行进度实时同步",
    path: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  },
  {
    title: "流式响应，过程可见",
    desc: "边思考边输出，随时可以打断",
    path: "M13 2L4.5 13.5H11L10 22l8.5-11.5H12L13 2z",
  },
  {
    title: "独立空间与专属记忆",
    desc: "每位用户独立配置，互不干扰",
    path: "M12 3l7 3v5c0 4.6-3 8.1-7 10-4-1.9-7-5.4-7-10V6l7-3z",
  },
];
</script>

<template>
  <div class="relative min-h-dvh bg-canvas lg:grid lg:grid-cols-[1.08fr_0.92fr]">
    <aside
      class="relative hidden overflow-hidden border-r border-line bg-sidebar lg:flex lg:flex-col lg:px-12 lg:py-10 xl:px-16"
    >
      <div class="pointer-events-none absolute inset-0">
        <div class="absolute -left-32 -top-32 h-[28rem] w-[28rem] rounded-full bg-accent-weak opacity-80 blur-3xl" />
        <div
          class="absolute inset-0 opacity-60"
          style="
            background-image: linear-gradient(var(--line) 1px, transparent 1px),
              linear-gradient(90deg, var(--line) 1px, transparent 1px);
            background-size: 48px 48px;
            -webkit-mask-image: radial-gradient(ellipse 75% 65% at 28% 22%, black 8%, transparent 72%);
            mask-image: radial-gradient(ellipse 75% 65% at 28% 22%, black 8%, transparent 72%);
          "
        />
      </div>

      <div class="relative flex items-center gap-2.5">
        <div class="flex h-9 w-9 items-center justify-center rounded-[11px] bg-primary text-primary-fg">
          <span class="text-[14px] font-semibold tracking-tight">W</span>
        </div>
        <span class="text-[15px] font-semibold tracking-tight text-fg">Whitz</span>
        <span
          class="ml-1 rounded-full border border-line bg-canvas px-2 py-0.5 text-[10px] font-medium tracking-wide text-fg-muted"
        >
          个人 AI 助理
        </span>
      </div>

      <div class="relative my-auto max-w-[30rem] py-12">
        <p class="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent">个人 AI 助理 · 多任务规划</p>
        <h2 class="mt-4 text-[clamp(28px,2.8vw,38px)] font-semibold leading-[1.18] tracking-tight text-fg">
          更聪明的对话，<br />更专注的工作。
        </h2>
        <p class="mt-4 max-w-[25rem] text-sm leading-relaxed text-fg-muted">
          复杂任务自动规划、逐步执行，工具调用与进度全程可见。随时打断，随时继续。
        </p>

        <ul class="mt-10 space-y-5">
          <li v-for="f in features" :key="f.title" class="flex items-start gap-3.5">
            <span
              class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] border border-line bg-canvas text-fg"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                <path stroke-linecap="round" stroke-linejoin="round" :d="f.path" />
              </svg>
            </span>
            <div>
              <p class="text-[13.5px] font-medium text-fg">{{ f.title }}</p>
              <p class="mt-0.5 text-[12.5px] leading-relaxed text-fg-muted">{{ f.desc }}</p>
            </div>
          </li>
        </ul>
      </div>

      <p class="relative text-[11px] text-fg-faint">© 2026 Whitz · 你的个人 AI 助理</p>
    </aside>

    <main class="relative flex min-h-dvh flex-col">
      <div class="flex items-center justify-between px-5 py-4 sm:px-8 lg:justify-end">
        <div class="flex items-center gap-2 lg:hidden">
          <div class="flex h-8 w-8 items-center justify-center rounded-[10px] bg-primary text-primary-fg">
            <span class="text-[12px] font-semibold tracking-tight">W</span>
          </div>
          <span class="text-[14px] font-semibold tracking-tight text-fg">Whitz</span>
        </div>
        <ThemeToggle />
      </div>

      <div class="flex flex-1 items-center justify-center px-5 pb-10 pt-2 sm:px-8">
        <div class="animate-rise w-full max-w-[380px]">
          <h1 class="text-[26px] font-semibold leading-tight tracking-tight text-fg">{{ title }}</h1>
          <p v-if="subtitle" class="mt-2 text-sm leading-relaxed text-fg-muted">{{ subtitle }}</p>
          <div class="mt-8">
            <slot />
          </div>
          <div class="mt-7 text-center text-[13px] text-fg-muted">
            <slot name="footer" />
          </div>
        </div>
      </div>

      <p class="pb-6 text-center text-[11px] text-fg-faint lg:hidden">© 2026 Whitz</p>
    </main>
  </div>
</template>
