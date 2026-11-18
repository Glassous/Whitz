<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useDesktopStore } from "../../stores/desktop";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore } from "../../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";

const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const work = useWorkStore();

const stateLabel = computed(() => {
  const state = runtime.status?.state;
  return (
    {
      ready: "运行中",
      starting: "启动中",
      installing: "安装中",
      stopped: "已停止",
      error: "异常",
      disabled: "已禁用",
      idle: "待机",
    } as Record<string, string>
  )[state ?? "idle"] ?? "未知";
});

const stateColor = computed(() => {
  if (runtime.ready) return "var(--success)";
  if (runtime.status?.state === "error") return "var(--danger)";
  if (runtime.status?.state === "starting") return "var(--warning)";
  return "var(--fg-faint)";
});

const planItems = computed(() => {
  const items = (work.plan?.items ?? []) as Array<Record<string, unknown>>;
  return Array.isArray(items) ? items : [];
});

async function start() {
  await runtime.start().catch(() => undefined);
}
</script>

<template>
  <aside class="flex h-full w-[318px] shrink-0 flex-col gap-3 overflow-y-auto custom-scrollbar border-l border-line bg-sidebar/40 px-3.5 py-3.5">
    <section class="rounded-2xl border border-line bg-canvas p-3.5">
      <div class="flex items-center justify-between">
        <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">本地运行时</span>
        <span class="flex items-center gap-1.5 text-[11.5px]" :style="{ color: stateColor }">
          <span
            class="h-1.5 w-1.5 rounded-full"
            :class="{ 'work-dot-live': runtime.ready }"
            :style="{ background: stateColor }"
          ></span>
          {{ stateLabel }}
        </span>
      </div>
      <p class="mt-2.5 truncate text-[12.5px] text-fg" :title="runtime.status?.version ?? ''">
        Hermes {{ runtime.status?.version ?? "未安装" }}
      </p>
      <p class="mt-0.5 truncate text-[11.5px] text-fg-faint">
        {{ runtime.status?.model || "未选择模型" }}
        <span v-if="runtime.status?.port"> · :{{ runtime.status.port }}</span>
      </p>

      <div class="mt-3 flex flex-wrap gap-2">
        <BaseButton v-if="!runtime.ready" size="sm" :loading="runtime.busy" @click="start">启动</BaseButton>
        <BaseButton v-else size="sm" variant="secondary" :loading="runtime.busy" @click="runtime.restart()">重启</BaseButton>
        <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-settings' })">设置</BaseButton>
      </div>
      <p v-if="runtime.status?.detail" class="mt-2 text-[11.5px] text-warning">{{ runtime.status.detail }}</p>
    </section>

    <section class="rounded-2xl border border-line bg-canvas p-3.5">
      <div class="flex items-center justify-between">
        <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">计划</span>
        <span class="text-[11px] text-fg-faint">{{ planItems.length }} 步</span>
      </div>
      <ol v-if="planItems.length" class="mt-2.5 space-y-2">
        <li v-for="(item, index) in planItems" :key="String(item.id ?? index)" class="flex items-start gap-2">
          <span
            class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
            :style="{
              background:
                item.status === 'completed'
                  ? 'var(--success)'
                  : item.status === 'in_progress'
                    ? 'var(--work-accent)'
                    : 'var(--line-strong)',
            }"
          ></span>
          <span
            class="text-[12px] leading-relaxed"
            :class="item.status === 'completed' ? 'text-fg-faint line-through' : 'text-fg-muted'"
          >
            {{ String(item.content ?? "") }}
          </span>
        </li>
      </ol>
      <p v-else class="mt-2.5 text-[11.5px] leading-relaxed text-fg-faint">
        复杂任务会自动拆解步骤，进度会实时显示在这里。
      </p>
    </section>

    <section class="rounded-2xl border border-line bg-canvas p-3.5">
      <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">数据位置</span>
      <p class="mt-2 break-all text-[11.5px] leading-relaxed text-fg-muted">
        {{ runtime.status?.home_dir ?? "—" }}
      </p>
      <p class="mt-1.5 text-[11px] leading-relaxed text-fg-faint">
        会话、消息与记忆仅存本机 SQLite；内置模型请求会带账号额度计量，但不会上传对话内容。
      </p>
      <p v-if="!desktop.loggedIn" class="mt-2 text-[11.5px] text-warning">
        当前未登录：内置模型不可用，请使用自带 Key。
      </p>
    </section>
  </aside>
</template>
