<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useDesktopStore } from "../stores/desktop";
import { useRuntimeStore } from "../stores/runtime";
import BaseButton from "@web/components/ui/BaseButton.vue";
import ModelForm from "../components/work/ModelForm.vue";

const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();

const progress = computed(() => runtime.progress);
const installed = computed(() => runtime.installed);
const percent = computed(() => Math.round(progress.value?.percent ?? (installed.value ? 100 : 0)));

async function install() {
  await runtime.install().catch(() => undefined);
}

async function finish() {
  await runtime.start().catch(() => undefined);
  if (runtime.ready) void router.push({ name: "work" });
}
</script>

<template>
  <div class="work-glow h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-[880px] px-8 py-10">
      <header class="animate-rise">
        <div class="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-fg-faint">
          <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)"></span>
          Whitz Work · 本地
        </div>
        <h1 class="mt-3 text-[26px] font-semibold tracking-tight text-fg">先准备好你的本地智能体</h1>
        <p class="mt-2 max-w-[620px] text-[14px] leading-relaxed text-fg-muted">
          Work 模式在本机运行完整的 Hermes Agent，对话与记忆只保存在这台电脑。首次使用需要安装运行时，之后可离线启动。
        </p>
      </header>

      <section v-if="!desktop.workEnabled" class="mt-8 rounded-2xl border border-line bg-canvas p-6">
        <h2 class="text-[15px] font-semibold text-fg">Work 模式当前不可用</h2>
        <p class="mt-1.5 text-[13px] text-fg-muted">
          {{ desktop.policy?.disabled_reason || "远程策略已禁用该模式。请先使用 Whitz Chat。" }}
        </p>
        <BaseButton class="mt-4" variant="secondary" @click="router.push({ name: 'chat-gate' })">返回 Chat</BaseButton>
      </section>

      <template v-else>
        <section class="mt-8 rounded-2xl border border-line bg-canvas p-6">
          <div class="flex items-start justify-between gap-6">
            <div>
              <h2 class="text-[15px] font-semibold text-fg">1 · 安装本地运行时</h2>
              <p class="mt-1 text-[12.5px] text-fg-muted">
                Hermes Agent · MIT 开源 · 安装到 <code class="rounded bg-surface px-1 py-0.5 text-[11px]">%LOCALAPPDATA%\\Whitz\\hermes</code>
              </p>
            </div>
            <span
              class="rounded-full border px-2.5 py-1 text-[11px]"
              :class="installed ? 'border-line text-success' : 'border-line text-fg-muted'"
            >
              {{ installed ? `已安装 ${runtime.status?.version ?? ""}` : "未安装" }}
            </span>
          </div>

          <div v-if="runtime.installing || progress" class="mt-5">
            <div class="h-1.5 overflow-hidden rounded-full bg-surface">
              <div
                class="h-full rounded-full transition-[width] duration-300"
                :style="{
                  width: `${percent}%`,
                  background: progress?.phase === 'error' ? 'var(--danger)' : 'var(--work-accent)',
                }"
              ></div>
            </div>
            <p class="mt-2 text-[12px]" :class="progress?.phase === 'error' ? 'text-danger' : 'text-fg-muted'">
              {{ progress?.message || "准备中…" }} · {{ percent }}%
            </p>
          </div>

          <div class="mt-5 flex flex-wrap items-center gap-3">
            <BaseButton v-if="!installed" :loading="runtime.busy" :disabled="runtime.installing" @click="install">
              {{ runtime.installing ? "正在安装…" : "下载并安装" }}
            </BaseButton>
            <BaseButton v-else variant="secondary" :loading="runtime.busy" @click="install">检查更新 / 重装</BaseButton>
            <BaseButton variant="ghost" @click="runtime.status && router.push({ name: 'work-settings' })">
              高级设置
            </BaseButton>
            <span v-if="runtime.error" class="text-[12px] text-danger">{{ runtime.error }}</span>
          </div>
          <p class="mt-3 text-[11.5px] text-fg-faint">
            安装过程通过官方安装器准备 uv / Python / Node 依赖，需要一次联网；失败会自动保留日志供诊断。
          </p>
        </section>

        <section class="mt-5 rounded-2xl border border-line bg-canvas p-6">
          <h2 class="text-[15px] font-semibold text-fg">2 · 选择模型</h2>
          <p class="mt-1 text-[12.5px] text-fg-muted">
            登录后可用账号额度；未登录时可接入自己的 OpenAI / Anthropic / Google 原生协议或任意兼容端点。
          </p>
          <div class="mt-5">
            <ModelForm v-if="runtime.settings" :settings="runtime.settings" />
            <p v-else class="text-[12.5px] text-fg-faint">正在读取本机配置…</p>
          </div>
        </section>

        <section class="mt-5 rounded-2xl border border-line bg-canvas p-6">
          <h2 class="text-[15px] font-semibold text-fg">3 · 启动本地智能体</h2>
          <p class="mt-1 text-[12.5px] text-fg-muted">
            运行时只监听 127.0.0.1 的随机端口，外部无法访问；退出应用时会清理子进程。
          </p>
          <div class="mt-4 flex flex-wrap items-center gap-3">
            <BaseButton size="lg" :loading="runtime.busy" :disabled="!installed" @click="finish">
              {{ runtime.ready ? "进入 Work" : "启动并进入 Work" }}
            </BaseButton>
            <span v-if="runtime.status?.detail" class="text-[12px] text-fg-faint">{{ runtime.status.detail }}</span>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
