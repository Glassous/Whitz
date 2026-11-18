<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { useDesktopStore } from "../stores/desktop";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkStore } from "../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";
import WorkSidebar from "../components/work/WorkSidebar.vue";
import WorkMessageList from "../components/work/WorkMessageList.vue";
import WorkComposer from "../components/work/WorkComposer.vue";
import RuntimePanel from "../components/work/RuntimePanel.vue";
import ApprovalSheet from "../components/work/ApprovalSheet.vue";

const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const work = useWorkStore();

onMounted(async () => {
  await work.loadList();
  if (!work.current && work.conversations[0]) await work.select(work.conversations[0].id);
});

const title = computed(() => work.current?.conversation.title ?? "本地工作台");
const blockedReason = computed(() => {
  if (!runtime.installed) return "尚未安装本地运行时";
  if (runtime.status?.state === "disabled") return "Whitz Work 已被禁用";
  if (!runtime.ready) return "本地运行时未启动，请先在右侧面板启动";
  if (runtime.settings?.model.protocol === "builtin" && !desktop.loggedIn) return "内置模型需要登录，请在设置中改用自带 Key";
  return null;
});
const disabled = computed(() => Boolean(blockedReason.value));

async function send(content: string) {
  await work.send(content);
}

async function exportConversation() {
  if (!work.current) return;
  const result = await window.whitzDesktop?.work.export(work.current.conversation.id);
  if (result?.path) window.alert(`已导出到：${result.path}`);
}
</script>

<template>
  <div v-if="!desktop.workEnabled" class="work-glow flex h-full items-center justify-center px-8">
    <section class="max-w-[520px] rounded-3xl border border-line bg-canvas/85 p-8 shadow-[var(--shadow)]">
      <p class="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-faint">Whitz Work</p>
      <h1 class="mt-3 text-[22px] font-semibold text-fg">该模式当前不可用</h1>
      <p class="mt-2 text-[13.5px] leading-relaxed text-fg-muted">
        {{ desktop.policy?.disabled_reason || "服务端策略已关闭 Work 模式。本地智能体不会启动，你仍可以正常使用 Chat。" }}
      </p>
      <div class="mt-5 flex gap-2.5">
        <BaseButton @click="router.push({ name: 'chat-gate' })">使用 Chat</BaseButton>
        <BaseButton variant="secondary" @click="router.push({ name: 'work-settings' })">查看策略</BaseButton>
      </div>
    </section>
  </div>

  <div v-else class="flex h-full min-h-0">
    <WorkSidebar />

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-12 shrink-0 items-center gap-3 border-b border-line px-5">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <h2 class="truncate text-[13.5px] font-medium text-fg">{{ title }}</h2>
            <span
              class="shrink-0 rounded-full border px-2 py-0.5 text-[10.5px]"
              style="border-color: color-mix(in srgb, var(--work-accent) 35%, var(--line)); color: var(--work-accent)"
            >
              仅本地
            </span>
          </div>
        </div>
        <BaseButton v-if="work.current" size="sm" variant="ghost" @click="exportConversation">导出</BaseButton>
        <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-settings' })">设置</BaseButton>
      </header>

      <div v-if="!runtime.installed" class="flex min-h-0 flex-1 items-center justify-center px-8">
        <section class="max-w-[520px] rounded-2xl border border-line bg-canvas p-7 text-center">
          <h3 class="text-[17px] font-semibold text-fg">还没有本地运行时</h3>
          <p class="mt-2 text-[13px] leading-relaxed text-fg-muted">
            安装 Hermes Agent 后即可在本地执行完整的智能体能力，所有记录只保存在这台电脑。
          </p>
          <BaseButton class="mt-5" @click="router.push({ name: 'work-setup' })">前往安装</BaseButton>
        </section>
      </div>

      <template v-else>
        <div v-if="work.error" class="border-b border-line bg-danger-weak/50 px-5 py-2 text-[12px] text-danger">
          {{ work.error }}
        </div>
        <WorkMessageList
          :messages="work.messages"
          :active-assistant-id="work.activeAssistantId"
          :streaming="work.streaming"
        />
        <WorkComposer
          :streaming="work.streaming"
          :sending="work.sending"
          :disabled="disabled"
          :disabled-reason="blockedReason"
          @send="send"
          @stop="work.stop()"
        />
      </template>
    </div>

    <RuntimePanel class="hidden 2xl:flex" />
  </div>

  <ApprovalSheet
    v-if="work.pendingControl"
    :kind="work.pendingControl.kind"
    :tool="work.pendingControl.tool"
    :preview="work.pendingControl.preview"
    @approve="work.approve"
    @clarify="work.clarify"
  />
</template>
