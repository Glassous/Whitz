<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
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
const copied = ref(false);

const INSTALL_CMD = "npm install -g opencode-ai";

onMounted(() => {
  chromeBackToken = setChromeBack({ label: "返回工作台", run: () => void router.push({ name: "work" }) });
  void runtime.redetect().catch(() => undefined);
});

onBeforeUnmount(() => {
  if (chromeBackToken !== null) clearChromeBack(chromeBackToken);
});

const installed = computed(() => runtime.installed);

async function copyInstallCmd() {
  try {
    await navigator.clipboard.writeText(INSTALL_CMD);
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 1800);
  } catch {
    /* ignore */
  }
}

function openOfficialSite() {
  void window.whitzDesktop?.openExternal("https://opencode.ai/");
}

async function pickExe() {
  const picked = await runtime.pickExe();
  if (picked) {
    await runtime.saveSettings({ custom_opencode_exe: picked });
    await runtime.redetect();
  }
}

function finish() {
  void runtime.start().catch(() => undefined);
  void router.push({ name: "work" });
}
</script>

<template>
  <div class="work-glow h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-[880px] px-8 py-10">
      <header class="animate-rise">
        <div class="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-fg-faint">
          <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)"></span>
          Whitz Work · 本机 OpenCode 连接
        </div>
        <h1 class="mt-3 text-[26px] font-semibold tracking-tight text-fg">连接本机已安装的 OpenCode</h1>
        <p class="mt-2 max-w-[660px] text-[14px] leading-relaxed text-fg-muted">
          Whitz Work 不内置安装 OpenCode，直接连接你电脑上的 OpenCode CLI 与配置文件（<code class="rounded bg-surface px-1 py-0.5 text-[12px]">~/.config/opencode/opencode.json</code>）；本地会话与工作区记录保留在电脑，不上传云端。
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
              <h2 class="text-[15px] font-semibold text-fg">1 · 检测本机 OpenCode</h2>
              <p class="mt-1 text-[12.5px] text-fg-muted">
                配置目录：<code class="rounded bg-surface px-1.5 py-0.5 text-[11px]">{{ runtime.status?.home_dir ?? "~/.config/opencode" }}</code>
              </p>
            </div>
            <span
              class="shrink-0 rounded-full border border-line px-2.5 py-1 text-[11px]"
              :class="installed ? 'text-success' : 'text-warning'"
            >
              {{ installed ? `已检测到 ${runtime.status?.version ?? ""}` : "未检测到" }}
            </span>
          </div>

          <div v-if="installed" class="mt-4 rounded-xl border border-line bg-surface/40 px-4 py-3 text-[12px]">
            <p class="text-fg-muted">可执行路径：</p>
            <p class="mt-0.5 break-all font-mono text-[11.5px] text-fg">{{ runtime.status?.exe_path }}</p>
          </div>

          <div v-else class="mt-4 rounded-xl border border-line bg-surface/50 p-4 text-[12.5px]">
            <p class="font-medium text-fg">请先在本机安装 OpenCode（本应用仅做调用，不内置安装器）：</p>
            <p class="mt-1.5 text-fg-muted">在终端执行以下命令完成安装后点击「重新检测」：</p>
            <div class="mt-2.5 flex flex-wrap items-center gap-2 rounded-xl bg-code px-3 py-2 font-mono text-[11.5px] text-[#e6e5e0]">
              <span class="min-w-0 flex-1 break-all">{{ INSTALL_CMD }}</span>
              <button
                type="button"
                class="shrink-0 rounded-lg bg-white/10 px-2.5 py-1 text-[11px] text-white hover:bg-white/20"
                @click="copyInstallCmd"
              >
                {{ copied ? "已复制" : "复制命令" }}
              </button>
            </div>
          </div>

          <div class="mt-5 flex flex-wrap items-center gap-3">
            <BaseButton :loading="runtime.busy" @click="runtime.redetect()">重新检测</BaseButton>
            <BaseButton variant="secondary" @click="pickExe">手动选择 opencode.exe</BaseButton>
            <BaseButton v-if="!installed" variant="ghost" @click="openOfficialSite">打开 OpenCode 官网</BaseButton>
            <BaseButton variant="ghost" @click="router.push({ name: 'work-settings' })">Work 设置</BaseButton>
          </div>
        </section>

        <section class="mt-5 rounded-2xl border border-line bg-canvas p-6">
          <h2 class="text-[15px] font-semibold text-fg">2 · OpenCode 模型配置与 Whitz 本机服务</h2>
          <p class="mt-1 text-[12.5px] text-fg-muted">
            可直接使用本机已配置的 Provider，或接入 Whitz 常驻的本地 OpenAI 服务与 Chat 共享额度（支持一键写入 <code class="rounded bg-surface px-1 py-0.5 text-[11px]">opencode.json</code>）。
          </p>
          <div class="mt-5">
            <ModelForm v-if="runtime.settings" :settings="runtime.settings" />
            <p v-else class="text-[12.5px] text-fg-faint">正在读取本机配置…</p>
          </div>
        </section>

        <section class="mt-5 rounded-2xl border border-line bg-canvas p-6">
          <h2 class="text-[15px] font-semibold text-fg">3 · 进入工作台</h2>
          <p class="mt-1 text-[12.5px] text-fg-muted">
            OpenCode 服务自动常驻本机 127.0.0.1 随机端口，工作区代码与会话只保留在本机。
          </p>
          <div class="mt-4 flex flex-wrap items-center gap-3">
            <BaseButton size="lg" :disabled="!installed" @click="finish">进入 Work</BaseButton>
            <span v-if="runtime.status?.detail" class="text-[12px] text-fg-faint">{{ runtime.status.detail }}</span>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
