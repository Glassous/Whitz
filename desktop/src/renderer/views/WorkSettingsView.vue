<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { clearChromeBack, setChromeBack } from "@web/host/chrome";
import { useCreditsStore } from "@web/stores/credits";
import { useDesktopStore } from "../stores/desktop";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkStore } from "../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";
import ModelForm from "../components/work/ModelForm.vue";

type WorkTab = "model" | "workspace" | "runtime" | "skills" | "policy";

const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const work = useWorkStore();
const credits = useCreditsStore();

const activeTab = ref<WorkTab>("model");
let chromeBackToken: number | null = null;

const tabs: Array<{ key: WorkTab; label: string; desc: string }> = [
  { key: "model", label: "OpenCode 配置与额度", desc: "本机 OpenCode 配置、内置服务与共享额度" },
  { key: "workspace", label: "工作区目录", desc: "当前本地项目目录与文件入口" },
  { key: "runtime", label: "OpenCode 运行时", desc: "路径探测、AGENTS.md 与原始配置" },
  { key: "skills", label: "本地技能", desc: "本机 OpenCode 技能列表（独立于 Chat）" },
  { key: "policy", label: "策略与账号", desc: "桌面策略校验与账号关联" },
];

const customExe = ref("");
const agentsMd = ref("");
const rawJson = ref("");
const rawJsonError = ref<string | null>(null);
const savingRuntime = ref(false);
const runtimeMsg = ref<string | null>(null);

watch(
  () => runtime.settings,
  (s) => {
    if (!s) return;
    customExe.value = s.model.custom_opencode_exe ?? "";
  },
  { immediate: true, deep: true },
);

watch(
  () => runtime.opencodeConfig,
  (cfg) => {
    if (!cfg) return;
    agentsMd.value = cfg.agents_md;
    rawJson.value = cfg.raw_json;
  },
  { immediate: true, deep: true },
);

onMounted(() => {
  chromeBackToken = setChromeBack({ label: "返回工作台", run: () => void router.push({ name: "work" }) });
  void runtime.loadSettings();
  void runtime.loadOpenCodeConfig().catch(() => undefined);
  void desktop.refreshPolicy();
  void work.loadWorkspaceState();
  void work.loadSkills();
  if (desktop.loggedIn) void credits.fetch().catch(() => undefined);
});

onBeforeUnmount(() => {
  if (chromeBackToken !== null) clearChromeBack(chromeBackToken);
});

const sourceLabel = computed(() => {
  const s = runtime.status?.source;
  if (s === "custom") return "用户指定路径";
  if (s === "npm") return "本机 npm (opencode-ai)";
  if (s === "scoop") return "本机 Scoop";
  if (s === "winget") return "本机 WinGet";
  if (s === "system") return "本机 PATH 环境";
  return "未检测到";
});

async function pickCustomExe() {
  const picked = await runtime.pickExe();
  if (picked) customExe.value = picked;
}

async function saveRuntimeConfig() {
  savingRuntime.value = true;
  runtimeMsg.value = null;
  rawJsonError.value = null;
  try {
    await runtime.saveSettings({ custom_opencode_exe: customExe.value.trim() });
    await runtime.saveOpenCodeConfig({
      agents_md: agentsMd.value,
      raw_json: rawJson.value,
    });
    runtimeMsg.value = "已保存并同步至本机 OpenCode 配置";
  } catch (err) {
    rawJsonError.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    savingRuntime.value = false;
  }
}

async function restart() {
  await runtime.restart().catch(() => undefined);
}

function openLogs() {
  void window.whitzDesktop?.runtime.openLogs();
}
</script>

<template>
  <div class="flex h-full w-full overflow-hidden bg-canvas text-fg">
    <!-- Left Independent Work Settings Navigation -->
    <aside class="hidden w-[280px] shrink-0 flex-col border-r border-line bg-sidebar/60 p-4 md:flex">
      <div class="mb-4 px-2">
        <p class="text-[11px] font-medium uppercase tracking-[0.18em]" style="color: var(--work-accent)">
          Whitz Work · OpenCode 工作台
        </p>
        <h1 class="mt-1 text-[18px] font-semibold tracking-tight text-fg">Work 设置</h1>
        <p class="mt-1 text-[11.5px] leading-relaxed text-fg-faint">
          模型与权限直接同步本机 OpenCode 配置，工作台会话保留在本机，与 Chat 相互独立。
        </p>
      </div>

      <nav class="flex-1 space-y-1 overflow-y-auto custom-scrollbar">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          type="button"
          class="focus-ring flex w-full flex-col rounded-2xl px-3.5 py-2.5 text-left transition-colors"
          :class="activeTab === tab.key ? 'bg-hover/90 text-fg dark:bg-active' : 'text-fg-muted hover:bg-hover/65 hover:text-fg'"
          @click="activeTab = tab.key"
        >
          <span class="text-[14px] font-medium">{{ tab.label }}</span>
          <span class="mt-0.5 truncate text-[11.5px] text-fg-faint">{{ tab.desc }}</span>
        </button>
      </nav>

      <div class="mt-4 rounded-xl border border-line bg-canvas/70 p-3 text-[11.5px] text-fg-faint">
        <p class="font-medium text-fg-muted">需要修改云端 Chat 设置？</p>
        <button
          type="button"
          class="mt-1 text-[11.5px] underline underline-offset-2 hover:text-fg"
          @click="router.push({ name: 'settings' })"
        >
          前往 Chat 设置页 →
        </button>
      </div>
    </aside>

    <!-- Main Settings Content -->
    <div class="min-w-0 flex-1 overflow-y-auto custom-scrollbar">
      <div class="flex gap-1.5 overflow-x-auto border-b border-line px-4 py-2.5 md:hidden">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          type="button"
          class="shrink-0 rounded-full px-3 py-1 text-[12px] font-medium"
          :class="activeTab === tab.key ? 'bg-active text-fg' : 'text-fg-muted'"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="mx-auto max-w-[780px] px-6 py-8 sm:px-8">
        <!-- Tab 1: Model, Local Gateway & OpenCode Config -->
        <section v-if="activeTab === 'model'" class="rounded-2xl border border-line bg-canvas p-6">
          <h2 class="text-[16px] font-semibold text-fg">OpenCode 配置与额度策略</h2>
          <p class="mt-1 text-[12.5px] leading-relaxed text-fg-muted">
            Whitz 会常驻启动本地 OpenAI 兼容服务；选择「Whitz 内置」或配置调用该服务时与 Chat 共享账号额度，其他本机 OpenCode 模型直连消耗你自己的配置与密钥。
          </p>

          <div
            v-if="desktop.loggedIn && credits.status"
            class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface/50 px-4 py-2.5 text-[12px]"
          >
            <span class="text-fg-muted">
              当前账号共享额度（{{ credits.tierLabel }}）：本周剩余
              <strong class="text-fg">{{ credits.status.weekly.limit ? `${credits.weeklyPercent}%` : "不限" }}</strong>
              <template v-if="credits.tier !== 'pro'">
                · 5 小时剩余 <strong class="text-fg">{{ credits.fiveHourPercent }}%</strong>
              </template>
            </span>
            <span class="text-[11px] text-fg-faint">仅 Whitz 内置服务计入</span>
          </div>

          <div class="mt-5">
            <ModelForm v-if="runtime.settings" :settings="runtime.settings" />
          </div>
        </section>

        <!-- Tab 2: Workspace -->
        <section v-else-if="activeTab === 'workspace'" class="space-y-5">
          <div class="rounded-2xl border border-line bg-canvas p-6">
            <h2 class="text-[16px] font-semibold text-fg">当前本地工作区</h2>
            <p class="mt-1 text-[12.5px] text-fg-muted">
              选定的本地文件夹会作为 OpenCode 的目标 <code class="rounded bg-surface px-1 py-0.5 text-[11px]">directory</code>，所有代码搜索、读写与终端命令均在该目录下执行。
            </p>
            <div class="mt-4 rounded-xl border border-line bg-surface/40 px-4 py-3 text-[12.5px]">
              <p class="font-medium text-fg">{{ work.activeWorkspace?.name ?? "尚未选择工作区" }}</p>
              <p class="mt-0.5 break-all text-[11.5px] text-fg-faint">
                {{ work.activeWorkspace?.path ?? "未选择文件夹时默认在用户工作目录执行" }}
              </p>
            </div>
            <div class="mt-4 flex flex-wrap gap-2.5">
              <BaseButton size="sm" @click="work.pickWorkspace()">选择本地文件夹</BaseButton>
              <BaseButton v-if="work.activeWorkspace" size="sm" variant="secondary" @click="work.openInExplorer()">
                在资源管理器中打开
              </BaseButton>
            </div>
          </div>
        </section>

        <!-- Tab 3: OpenCode Runtime, AGENTS.md & Raw JSON -->
        <section v-else-if="activeTab === 'runtime'" class="space-y-5">
          <div class="rounded-2xl border border-line bg-canvas p-6">
            <h2 class="text-[16px] font-semibold text-fg">本地 OpenCode 运行时</h2>
            <dl class="mt-4 grid gap-3 text-[12.5px] sm:grid-cols-2">
              <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
                <dt class="text-[11px] text-fg-faint">状态</dt>
                <dd class="mt-0.5 text-fg">{{ runtime.status?.state ?? "未知" }}</dd>
              </div>
              <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
                <dt class="text-[11px] text-fg-faint">版本 / 来源</dt>
                <dd class="mt-0.5 text-fg">{{ runtime.status?.version ?? "未安装" }} · {{ sourceLabel }}</dd>
              </div>
              <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5 sm:col-span-2">
                <dt class="text-[11px] text-fg-faint">可执行文件</dt>
                <dd class="mt-0.5 break-all font-mono text-[11.5px] text-fg">{{ runtime.status?.exe_path ?? "—" }}</dd>
              </div>
              <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
                <dt class="text-[11px] text-fg-faint">OpenCode 服务端口</dt>
                <dd class="mt-0.5 text-fg">{{ runtime.status?.port ?? "—" }}</dd>
              </div>
              <div class="rounded-xl border border-line bg-surface/40 px-3.5 py-2.5">
                <dt class="text-[11px] text-fg-faint">配置目录 (.config/opencode)</dt>
                <dd class="mt-0.5 truncate text-fg" :title="runtime.status?.home_dir ?? ''">{{ runtime.status?.home_dir ?? "—" }}</dd>
              </div>
            </dl>
            <div class="mt-4 flex flex-wrap gap-2.5">
              <BaseButton size="sm" variant="secondary" :loading="runtime.busy" @click="restart">重启 OpenCode</BaseButton>
              <BaseButton size="sm" variant="ghost" @click="runtime.redetect()">重新检测</BaseButton>
              <BaseButton size="sm" variant="ghost" @click="openLogs">打开日志</BaseButton>
              <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-setup' })">安装指引</BaseButton>
            </div>
          </div>

          <div class="rounded-2xl border border-line bg-canvas p-6 space-y-4">
            <h2 class="text-[16px] font-semibold text-fg">可执行路径、全局指令 (AGENTS.md) 与原始配置</h2>
            <div>
              <span class="text-[12px] font-medium text-fg-muted">自定义 OpenCode 可执行文件路径（留空自动探测）</span>
              <div class="mt-1.5 flex gap-2">
                <input
                  v-model="customExe"
                  type="text"
                  placeholder="自动探测（PATH / npm / scoop / winget）"
                  class="focus-ring min-w-0 flex-1 rounded-xl border border-line bg-canvas px-3 py-2 font-mono text-[12px] text-fg placeholder:text-fg-faint"
                />
                <BaseButton size="sm" variant="secondary" @click="pickCustomExe">浏览</BaseButton>
                <BaseButton v-if="customExe" size="sm" variant="ghost" @click="customExe = ''">清空</BaseButton>
              </div>
            </div>

            <label class="block">
              <span class="text-[12px] font-medium text-fg-muted">全局系统指令 (~/.config/opencode/AGENTS.md)</span>
              <textarea
                v-model="agentsMd"
                rows="4"
                placeholder="直接读写 OpenCode 全局 AGENTS.md…"
                class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[12.5px] leading-relaxed text-fg placeholder:text-fg-faint"
              ></textarea>
            </label>

            <label class="block">
              <span class="text-[12px] font-medium text-fg-muted">原始 opencode.json（直接读写本机配置文件）</span>
              <textarea
                v-model="rawJson"
                rows="10"
                spellcheck="false"
                class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-code px-3 py-2 font-mono text-[12px] leading-relaxed text-[#e6e5e0]"
              ></textarea>
            </label>

            <p v-if="rawJsonError" class="text-[12px] text-danger">{{ rawJsonError }}</p>
            <div class="flex items-center gap-3">
              <BaseButton size="sm" :loading="savingRuntime" @click="saveRuntimeConfig">保存并同步 OpenCode</BaseButton>
              <span v-if="runtimeMsg" class="text-[12px]" style="color: var(--success)">{{ runtimeMsg }}</span>
            </div>
          </div>
        </section>

        <!-- Tab 4: Skills -->
        <section v-else-if="activeTab === 'skills'" class="space-y-5">
          <div class="rounded-2xl border border-line bg-canvas p-6">
            <div class="flex items-center justify-between">
              <div>
                <h2 class="text-[16px] font-semibold text-fg">本机 OpenCode 技能</h2>
                <p class="mt-1 text-[12.5px] text-fg-muted">
                  直接由本机 OpenCode 扫描 <code class="rounded bg-surface px-1 py-0.5 text-[11px]">/skill</code> 提供，独立于云端 Chat 技能。
                </p>
              </div>
              <BaseButton size="sm" variant="ghost" @click="work.loadSkills()">刷新</BaseButton>
            </div>

            <div v-if="work.skills.length" class="mt-4 grid gap-2 sm:grid-cols-2">
              <div
                v-for="skill in work.skills"
                :key="skill.name"
                class="rounded-xl border border-line bg-surface/35 p-3"
              >
                <div class="flex items-center justify-between gap-2">
                  <span class="text-[13px] font-medium text-fg">{{ skill.name }}</span>
                </div>
                <p v-if="skill.description" class="mt-1 line-clamp-2 text-[11.5px] text-fg-muted">{{ skill.description }}</p>
                <p v-if="skill.source" class="mt-1 truncate font-mono text-[10px] text-fg-faint">{{ skill.source }}</p>
              </div>
            </div>
            <p v-else class="mt-4 rounded-xl border border-dashed border-line p-6 text-center text-[12.5px] text-fg-faint">
              {{ runtime.ready ? "当前目录尚未发现 OpenCode 技能。" : "OpenCode 就绪后自动加载本机技能列表。" }}
            </p>
          </div>
        </section>

        <!-- Tab 5: Policy & Account -->
        <section v-else class="space-y-5">
          <div class="rounded-2xl border border-line bg-canvas p-6">
            <h2 class="text-[16px] font-semibold text-fg">账号状态</h2>
            <p class="mt-1 text-[12.5px] text-fg-muted">
              {{ desktop.loggedIn ? `已登录：${desktop.user?.display_name ?? ""}（${desktop.user?.email ?? ""}）` : "未登录：仍可使用本机 OpenCode 自有模型，Whitz 内置模型不可用。" }}
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
          </div>

          <div class="rounded-2xl border border-line bg-canvas p-6">
            <h2 class="text-[16px] font-semibold text-fg">桌面签名策略</h2>
            <p class="mt-1 text-[12.5px] text-fg-muted">
              Work 模式由服务端签名策略控制；校验失败或过期时按关闭处理，不影响 Chat。
            </p>
            <p class="mt-3 text-[12px] text-fg-faint">
              状态：{{ desktop.workEnabled ? "已启用" : "已禁用" }} · 来源：{{ desktop.policy?.source ?? "default" }} ·
              版本：{{ desktop.policy?.version ?? 0 }}
              <span v-if="desktop.policy?.disabled_reason"> · {{ desktop.policy.disabled_reason }}</span>
            </p>
            <BaseButton class="mt-4" size="sm" variant="ghost" @click="desktop.refreshPolicy()">重新拉取策略</BaseButton>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
