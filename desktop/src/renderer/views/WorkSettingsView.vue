<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { useRouter } from "vue-router";
import { clearChromeBack, setChromeBack } from "@web/host/chrome";
import { useDesktopStore } from "../stores/desktop";
import { useRuntimeStore } from "../stores/runtime";
import BaseButton from "@web/components/ui/BaseButton.vue";
import ModelForm from "../components/work/ModelForm.vue";

const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
let chromeBackToken: number | null = null;

onMounted(() => {
  chromeBackToken = setChromeBack({ label: "返回工作台", run: () => void router.push({ name: "work" }) });
  void runtime.loadSettings();
  void desktop.refreshPolicy();
});

onBeforeUnmount(() => {
  if (chromeBackToken !== null) clearChromeBack(chromeBackToken);
});

async function restart() {
  await runtime.restart().catch(() => undefined);
}

function openLogs() {
  void window.whitzDesktop?.runtime.openLogs();
}
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-[820px] px-8 py-9">
      <header>
        <p class="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-faint">Whitz Work</p>
        <h1 class="mt-2 text-[22px] font-semibold tracking-tight text-fg">本地设置</h1>
      </header>

      <section class="mt-7 rounded-2xl border border-line bg-canvas p-6">
        <h2 class="text-[15px] font-semibold text-fg">模型与额度</h2>
        <p class="mt-1 text-[12.5px] text-fg-muted">内置模型与账号共享额度；自带 Key 的调用不经过 Whitz 服务端。</p>
        <div class="mt-5">
          <ModelForm v-if="runtime.settings" :settings="runtime.settings" />
        </div>
      </section>

      <section class="mt-5 rounded-2xl border border-line bg-canvas p-6">
        <h2 class="text-[15px] font-semibold text-fg">运行时</h2>
        <dl class="mt-4 grid gap-3 text-[12.5px] sm:grid-cols-2">
          <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
            <dt class="text-[11px] text-fg-faint">状态</dt>
            <dd class="mt-0.5 text-fg">{{ runtime.status?.state ?? "未知" }}</dd>
          </div>
          <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
            <dt class="text-[11px] text-fg-faint">版本</dt>
            <dd class="mt-0.5 text-fg">{{ runtime.status?.version ?? "未安装" }}</dd>
          </div>
          <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
            <dt class="text-[11px] text-fg-faint">本地端口</dt>
            <dd class="mt-0.5 text-fg">{{ runtime.status?.port ?? "—" }}</dd>
          </div>
          <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
            <dt class="text-[11px] text-fg-faint">数据目录</dt>
            <dd class="mt-0.5 truncate text-fg" :title="runtime.status?.home_dir ?? ''">{{ runtime.status?.home_dir ?? "—" }}</dd>
          </div>
        </dl>
        <div class="mt-4 flex flex-wrap gap-2.5">
          <BaseButton size="sm" variant="secondary" :loading="runtime.busy" @click="restart">重启运行时</BaseButton>
          <BaseButton size="sm" variant="ghost" @click="runtime.stop()">停止</BaseButton>
          <BaseButton size="sm" variant="ghost" @click="openLogs">打开日志</BaseButton>
        </div>
      </section>

      <section class="mt-5 rounded-2xl border border-line bg-canvas p-6">
        <h2 class="text-[15px] font-semibold text-fg">账号</h2>
        <p class="mt-1 text-[12.5px] text-fg-muted">
          {{ desktop.loggedIn ? `已登录：${desktop.user?.display_name ?? ""}（${desktop.user?.email ?? ""}）` : "未登录，只能使用自带 Key 的本地模型。" }}
        </p>
        <div class="mt-4 flex gap-2.5">
          <BaseButton v-if="!desktop.loggedIn" size="sm" @click="router.push({ name: 'login' })">去登录</BaseButton>
          <BaseButton
            v-else
            size="sm"
            variant="secondary"
            @click="desktop.logout().then(() => router.push({ name: 'work' }))"
          >
            退出登录
          </BaseButton>
        </div>
      </section>

      <section class="mt-5 rounded-2xl border border-line bg-canvas p-6">
        <h2 class="text-[15px] font-semibold text-fg">桌面策略</h2>
        <p class="mt-1 text-[12.5px] text-fg-muted">
          Work 模式由服务端签名策略控制；校验失败或过期时按关闭处理，不影响 Chat。
        </p>
        <p class="mt-3 text-[12px] text-fg-faint">
          状态：{{ desktop.workEnabled ? "已启用" : "已禁用" }} · 来源：{{ desktop.policy?.source ?? "default" }} ·
          版本：{{ desktop.policy?.version ?? 0 }}
          <span v-if="desktop.policy?.disabled_reason"> · {{ desktop.policy.disabled_reason }}</span>
        </p>
        <BaseButton class="mt-4" size="sm" variant="ghost" @click="desktop.refreshPolicy()">重新拉取策略</BaseButton>
      </section>
    </div>
  </div>
</template>
