<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../../stores/auth";
import type { PostQuotaSummary } from "../../types";
import AppIcon from "../ui/AppIcon.vue";
import BaseBadge from "../ui/BaseBadge.vue";
import Spinner from "../ui/Spinner.vue";

const props = defineProps<{
  quota: PostQuotaSummary | null;
  enabling?: boolean;
}>();

const emit = defineEmits<{
  enable: [];
}>();

const router = useRouter();
const auth = useAuthStore();
const agreed = ref(true);

const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");
const memoryCount = computed(() => props.quota?.memory_entry_count ?? 0);
const categoryCount = computed(() => props.quota?.active_collection_count ?? 0);
const estimatedDaily = computed(() => props.quota?.estimated_daily_count ?? 0);
const tierLabel = computed(() => props.quota?.tier_label || "Free");

function onEnableClick() {
  if (props.enabling || !agreed.value) return;
  emit("enable");
}

function goMemorySettings() {
  void router.push({ name: "settings", query: { tab: "memory" } });
}
</script>

<template>
  <div class="posts-onboarding relative overflow-hidden rounded-[28px] border border-line/80 bg-canvas p-6 shadow-sm sm:p-10 dark:bg-sidebar/70">
    <!-- Ambient animated aurora & subtle dot grid -->
    <div class="onboarding-grid pointer-events-none absolute inset-0 opacity-60 dark:opacity-35" aria-hidden="true" />
    <div class="onboarding-orb orb-a pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full blur-3xl" aria-hidden="true" />
    <div class="onboarding-orb orb-b pointer-events-none absolute -bottom-28 -right-20 h-80 w-80 rounded-full blur-3xl" aria-hidden="true" />

    <div class="relative z-10 grid items-center gap-8 lg:grid-cols-12">
      <!-- Left column: Pitch, features, credit notice, CTA -->
      <div class="space-y-6 lg:col-span-7">
        <div class="onboarding-fade-up inline-flex items-center gap-2 rounded-full border border-line bg-surface/90 px-3.5 py-1.5 text-[12px] font-medium text-fg-muted backdrop-blur-sm">
          <AppIcon name="sparkles" class="h-3.5 w-3.5 text-fg" :stroke-width="2" />
          <span>仅你可见的私人 AI 动态空间</span>
        </div>

        <div class="onboarding-fade-up space-y-3" style="animation-delay: 60ms">
          <h2 class="text-[26px] font-bold leading-tight tracking-tight text-fg sm:text-[32px]">
            让 {{ assistantName }} 顺着你的记忆，<br />
            每天联网为你写几条专属动态
          </h2>
          <p class="max-w-xl text-[14.5px] leading-relaxed text-fg-muted">
            它会从你的长期记忆与近期想法中捕捉你真正关心的话题，主动联网收集最新资讯，发表有态度的观点、深度观察或实用速递；你也可以随时发帖记录，{{ assistantName }} 会在片刻后像好友一样来点赞和留言。
          </p>
        </div>

        <!-- Feature pills -->
        <div class="onboarding-fade-up grid gap-2.5 sm:grid-cols-2" style="animation-delay: 120ms">
          <div class="flex items-start gap-2.5 rounded-2xl border border-line/70 bg-surface/75 p-3.5 backdrop-blur-sm">
            <span class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-canvas text-fg ring-1 ring-line">
              <AppIcon name="globe" class="h-4 w-4" :stroke-width="1.9" />
            </span>
            <div class="min-w-0">
              <p class="text-[13px] font-semibold text-fg">联网追踪兴趣话题</p>
              <p class="mt-0.5 text-[12px] text-fg-faint">自动检索最新公开信息并附带参考来源，不止空谈。</p>
            </div>
          </div>

          <div class="flex items-start gap-2.5 rounded-2xl border border-line/70 bg-surface/75 p-3.5 backdrop-blur-sm">
            <span class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-canvas text-fg ring-1 ring-line">
              <AppIcon name="shield" class="h-4 w-4" :stroke-width="1.9" />
            </span>
            <div class="min-w-0">
              <p class="text-[13px] font-semibold text-fg">严格仅当前用户可见</p>
              <p class="mt-0.5 text-[12px] text-fg-faint">你的发帖自动沉淀进长期记忆，绝不公开给他人。</p>
            </div>
          </div>

          <div class="flex items-start gap-2.5 rounded-2xl border border-line/70 bg-surface/75 p-3.5 backdrop-blur-sm">
            <span class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-canvas text-fg ring-1 ring-line">
              <AppIcon name="database" class="h-4 w-4" :stroke-width="1.9" />
            </span>
            <div class="min-w-0">
              <p class="text-[13px] font-semibold text-fg">数量由记忆与档位决定</p>
              <p class="mt-0.5 text-[12px] text-fg-faint">记忆分类越多、Plus/Pro 档位越高发得越多；0 记忆发 0 条。</p>
            </div>
          </div>

          <div class="flex items-start gap-2.5 rounded-2xl border border-line/70 bg-surface/75 p-3.5 backdrop-blur-sm">
            <span class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-canvas text-fg ring-1 ring-line">
              <AppIcon name="message-dots" class="h-4 w-4" :stroke-width="1.9" />
            </span>
            <div class="min-w-0">
              <p class="text-[13px] font-semibold text-fg">拟人化延迟互动</p>
              <p class="mt-0.5 text-[12px] text-fg-faint">你发帖或回复评论后，助手会隔一会儿来点赞与交流。</p>
            </div>
          </div>
        </div>

        <!-- Explicit Credit Consumption Notice -->
        <div
          class="onboarding-fade-up rounded-2xl border border-warning/35 bg-warning-weak/65 p-4 text-[13px] text-fg dark:bg-warning-weak/50"
          style="animation-delay: 180ms"
        >
          <div class="flex items-start gap-2.5">
            <AppIcon name="alert-circle" class="mt-0.5 h-4.5 w-4.5 shrink-0 text-warning" :stroke-width="2" />
            <div class="space-y-1.5">
              <p class="font-semibold text-fg">积分额度消耗说明（默认关闭，需手动开启）</p>
              <p class="leading-relaxed text-fg-muted">
                开启后，系统将在后台每日自动为你执行联网检索与 AI 动态生成，以及对你的新动态/评论进行延迟回复，上述模型调用均会<strong class="font-semibold text-fg">正常消耗你的账号积分额度</strong>。当记忆为 0 或额度不足时将自动跳过不消耗，你也可以随时一键关闭。
              </p>
              <div class="flex flex-wrap items-center gap-2 pt-1 text-[12px]">
                <BaseBadge tone="gray">当前档位：{{ tierLabel }}</BaseBadge>
                <BaseBadge tone="gray">已启用记忆：{{ memoryCount }} 条 / {{ categoryCount }} 个分类</BaseBadge>
                <BaseBadge :tone="estimatedDaily > 0 ? 'brand' : 'gray'">
                  开启后预计每日 {{ estimatedDaily }} 条
                </BaseBadge>
                <button
                  v-if="memoryCount === 0"
                  type="button"
                  class="text-[12px] font-medium text-fg underline decoration-line-strong underline-offset-4 hover:decoration-fg"
                  @click="goMemorySettings"
                >
                  去添加长期记忆 →
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Consent checkbox + Shimmer CTA -->
        <div class="onboarding-fade-up flex flex-col gap-3 pt-1 sm:flex-row sm:items-center" style="animation-delay: 240ms">
          <button
            type="button"
            class="onboarding-cta focus-ring relative inline-flex items-center justify-center gap-2 overflow-hidden rounded-full bg-primary px-6 py-3 text-[14px] font-semibold text-primary-fg shadow-sm transition-transform duration-150 hover:scale-[1.015] active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-55"
            :disabled="enabling || !agreed"
            @click="onEnableClick"
          >
            <Spinner v-if="enabling" class="h-4 w-4" />
            <AppIcon v-else name="sparkles" class="h-4 w-4" :stroke-width="2" />
            <span>{{ enabling ? "正在开启..." : "知晓额度消耗，开启私人动态" }}</span>
          </button>

          <label class="flex cursor-pointer select-none items-center gap-2 text-[12.5px] text-fg-muted">
            <input
              v-model="agreed"
              type="checkbox"
              class="h-4 w-4 rounded border-line-strong accent-primary"
            />
            <span>我已知晓开启后会消耗账号积分</span>
          </label>
        </div>
      </div>

      <!-- Right column: Floating animated preview card stack -->
      <div class="relative hidden lg:col-span-5 lg:block" aria-hidden="true">
        <div class="relative mx-auto flex max-w-[340px] flex-col gap-3.5 py-2">
          <!-- Preview Card 1: AI Opinion -->
          <div class="preview-card preview-float-1 rounded-2xl border border-line/80 bg-canvas/95 p-4 shadow-md backdrop-blur-md dark:bg-surface/90">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-[11px] font-bold text-primary-fg">
                  {{ assistantName.slice(0, 1).toUpperCase() }}
                </span>
                <div>
                  <p class="text-[12.5px] font-semibold text-fg">{{ assistantName }}</p>
                  <p class="text-[10.5px] text-fg-faint">来自「项目与工作」记忆 · 刚联网查阅</p>
                </div>
              </div>
              <span class="rounded-full bg-surface px-2 py-0.5 text-[10.5px] font-medium text-fg-muted ring-1 ring-line">观点</span>
            </div>
            <p class="mt-2.5 text-[12.5px] font-medium text-fg">关于你最近关注的新架构方向</p>
            <p class="mt-1 line-clamp-2 text-[12px] leading-relaxed text-fg-muted">
              刚翻到本周社区里关于轻量并发调度的讨论，结合你上周提到的系统拆分目标，我觉得先保持单库幂等锁会更稳妥……
            </p>
            <div class="mt-2.5 flex items-center gap-1.5 text-[10.5px] text-fg-faint">
              <AppIcon name="globe" class="h-3 w-3" />
              <span class="truncate">附 2 条本周联网参考来源</span>
            </div>
          </div>

          <!-- Preview Card 2: AI Curated Digest -->
          <div class="preview-card preview-float-2 ml-6 rounded-2xl border border-line/80 bg-canvas/95 p-4 shadow-md backdrop-blur-md dark:bg-surface/90">
            <div class="flex items-center justify-between gap-2">
              <span class="text-[12px] font-semibold text-fg">资讯速递 · 个人兴趣</span>
              <span class="rounded-full bg-surface px-2 py-0.5 text-[10.5px] font-medium text-fg-muted ring-1 ring-line">仅你可见</span>
            </div>
            <p class="mt-1.5 text-[12px] leading-relaxed text-fg-muted">
              帮你整理了这周 3 条与你收藏主题相关的新动态，顺手标出了最值得细看的一篇长文。
            </p>
            <div class="mt-2.5 flex items-center gap-3 text-[11px] text-fg-faint">
              <span class="inline-flex items-center gap-1"><AppIcon name="heart" class="h-3.5 w-3.5" /> 点赞</span>
              <span class="inline-flex items-center gap-1"><AppIcon name="bookmark" class="h-3.5 w-3.5" /> 收藏</span>
              <span class="inline-flex items-center gap-1"><AppIcon name="chat" class="h-3.5 w-3.5" /> 转去聊天</span>
            </div>
          </div>

          <!-- Preview Card 3: Delayed AI interaction toast -->
          <div class="preview-card preview-float-3 mr-4 flex items-center gap-3 rounded-2xl border border-line/80 bg-canvas/95 px-3.5 py-3 shadow-sm backdrop-blur-md dark:bg-surface/90">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-fg ring-1 ring-line">
              <AppIcon name="heart" class="h-4 w-4" :stroke-width="2" />
            </span>
            <div class="min-w-0">
              <p class="text-[12px] font-medium text-fg">{{ assistantName }} 刚刚赞了你的动态并回复</p>
              <p class="truncate text-[11px] text-fg-faint">“这个想法太赞了，我已经记进长期记忆里啦！”</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.onboarding-grid {
  background-image: radial-gradient(color-mix(in srgb, var(--fg) 14%, transparent) 1px, transparent 1px);
  background-size: 22px 22px;
  mask-image: radial-gradient(ellipse 80% 75% at 50% 40%, black 35%, transparent 100%);
}

.orb-a {
  background: radial-gradient(circle, color-mix(in srgb, var(--primary) 16%, transparent), transparent 70%);
  animation: orbDriftA 11s ease-in-out infinite alternate;
}

.orb-b {
  background: radial-gradient(circle, color-mix(in srgb, var(--warning) 18%, transparent), transparent 70%);
  animation: orbDriftB 13s ease-in-out infinite alternate;
}

.onboarding-fade-up {
  animation: fadeUpIn 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.preview-float-1 {
  animation: fadeUpIn 0.6s cubic-bezier(0.22, 1, 0.36, 1) 0.1s both, gentleFloat 7s ease-in-out 0.7s infinite;
}

.preview-float-2 {
  animation: fadeUpIn 0.6s cubic-bezier(0.22, 1, 0.36, 1) 0.22s both, gentleFloat 8.5s ease-in-out 1.4s infinite reverse;
}

.preview-float-3 {
  animation: fadeUpIn 0.6s cubic-bezier(0.22, 1, 0.36, 1) 0.34s both, gentleFloat 6.5s ease-in-out 0.9s infinite;
}

.onboarding-cta::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 25%, rgba(255, 255, 255, 0.22) 50%, transparent 75%);
  transform: translateX(-120%);
  transition: transform 0.65s ease;
}

.onboarding-cta:hover::after {
  transform: translateX(120%);
}

@keyframes orbDriftA {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(28px, 18px) scale(1.12); }
}

@keyframes orbDriftB {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(-24px, -22px) scale(1.1); }
}

@keyframes fadeUpIn {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes gentleFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

@media (prefers-reduced-motion: reduce) {
  .orb-a,
  .orb-b,
  .onboarding-fade-up,
  .preview-float-1,
  .preview-float-2,
  .preview-float-3 {
    animation: none !important;
  }
}
</style>
