<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { usePostsStore } from "../stores/posts";
import AppIcon from "../components/ui/AppIcon.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import Spinner from "../components/ui/Spinner.vue";

const router = useRouter();
const auth = useAuthStore();
const posts = usePostsStore();

const toggling = ref(false);
const error = ref<string | null>(null);

const isEnabled = computed(() => Boolean(auth.user?.ai_posts_enabled));
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");

onMounted(() => {
  void posts.fetchQuota();
});

async function toggleEnabled() {
  if (toggling.value) return;
  toggling.value = true;
  error.value = null;
  try {
    await posts.setAiPostsEnabled(!isEnabled.value);
  } catch (e: any) {
    error.value = e?.detail?.detail || e?.message || "操作失败，请稍后重试";
  } finally {
    toggling.value = false;
  }
}

function goBack() {
  void router.push({ name: "posts" });
}

function goMemorySettings() {
  void router.push({ name: "settings", query: { tab: "memory" } });
}
</script>

<template>
  <div class="relative flex min-w-0 flex-1 flex-col bg-canvas">
    <!-- Top Bar -->
    <div class="flex shrink-0 items-center justify-between border-b border-line/60 px-4 py-3 sm:px-6">
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="focus-ring flex h-9 w-9 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          aria-label="返回动态"
          @click="goBack"
        >
          <AppIcon name="chevron-left" class="h-5 w-5" :stroke-width="2" />
        </button>
        <h1 class="text-[16px] font-semibold text-fg">私人动态说明</h1>
      </div>
    </div>

    <div v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
      <div class="mx-auto w-full max-w-2xl space-y-5">
        <!-- Live Account Status & Toggle Card -->
        <section class="rounded-[22px] border border-line/80 bg-sidebar/75 p-5 dark:bg-surface/75">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="space-y-1">
              <div class="flex flex-wrap items-center gap-2">
                <h2 class="text-[15.5px] font-semibold text-fg">功能状态</h2>
                <BaseBadge :tone="isEnabled ? 'green' : 'gray'">{{ isEnabled ? "已开启" : "未开启" }}</BaseBadge>
                <BaseBadge tone="brand">{{ posts.quota?.tier_label || "Free" }}</BaseBadge>
              </div>
              <p class="text-[13px] text-fg-muted">
                已启用记忆 {{ posts.quota?.memory_entry_count ?? 0 }} 条（{{ posts.quota?.active_collection_count ?? 0 }} 个分类）· 预计每日 AI 发帖
                <strong class="font-semibold text-fg">{{ posts.quota?.estimated_daily_count ?? 0 }}</strong> /
                {{ posts.quota?.max_daily_cap ?? 2 }} 条
              </p>
            </div>

            <div class="flex items-center gap-2">
              <BaseButton size="sm" variant="ghost" @click="goMemorySettings">管理记忆</BaseButton>
              <BaseButton
                size="sm"
                :variant="isEnabled ? 'secondary' : 'primary'"
                :disabled="toggling"
                @click="toggleEnabled"
              >
                <Spinner v-if="toggling" class="mr-1.5 h-3.5 w-3.5" />
                <span>{{ isEnabled ? "关闭功能" : "开启私人动态" }}</span>
              </BaseButton>
            </div>
          </div>

          <p v-if="error" class="mt-3 text-[12.5px] text-danger">{{ error }}</p>
        </section>

        <!-- How it works -->
        <section class="rounded-[22px] border border-line/80 bg-canvas p-5 dark:bg-sidebar/60">
          <h2 class="text-[15px] font-semibold text-fg">核心机制</h2>
          <ul class="mt-3 space-y-3 text-[13.5px] leading-relaxed text-fg-muted">
            <li>
              <strong class="font-semibold text-fg">严格仅你可见：</strong>
              所有 AI 动态、你的私人动态与评论均与账号强隔离，不会公开或被其他用户看到。
            </li>
            <li>
              <strong class="font-semibold text-fg">记忆驱动 + 必须联网搜索：</strong>
              {{ assistantName }} 每日后台读取你已启用的长期记忆、近期动态与评论互动，围绕你感兴趣的话题主动联网检索最新资讯，生成观点、资讯速递或深度观察，并附带可点击参考来源。
            </li>
            <li>
              <strong class="font-semibold text-fg">发帖入记忆 &amp; 拟人化延迟互动：</strong>
              你发布的私人动态会自动同步进长期记忆；你发帖或回复评论后，{{ assistantName }} 不会机械秒回，而是间隔一段时间后像好友一样前来点赞与留言。
            </li>
          </ul>
        </section>

        <!-- Quota & Tier Table -->
        <section class="rounded-[22px] border border-line/80 bg-canvas p-5 dark:bg-sidebar/60">
          <h2 class="text-[15px] font-semibold text-fg">每日 AI 发帖数量规则</h2>
          <p class="mt-1.5 text-[13px] text-fg-muted">
            有效长期记忆为 0 条时，{{ assistantName }} 不知道发什么，当日固定发 0 条；记忆分类越多、记忆越丰富、会员档位越高，每日可发条数越多。
          </p>
          <div class="mt-3.5 overflow-hidden rounded-xl border border-line/80 text-[13px]">
            <table class="w-full border-collapse text-left">
              <thead class="bg-surface/80 text-fg-muted">
                <tr>
                  <th class="px-3.5 py-2 font-medium">会员档位</th>
                  <th class="px-3.5 py-2 font-medium">0 条记忆</th>
                  <th class="px-3.5 py-2 font-medium">每日上限</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line/60 text-fg">
                <tr>
                  <td class="px-3.5 py-2 font-medium">Free</td>
                  <td class="px-3.5 py-2 text-fg-muted">0 条</td>
                  <td class="px-3.5 py-2">最多 2 条 / 天</td>
                </tr>
                <tr>
                  <td class="px-3.5 py-2 font-medium">Plus</td>
                  <td class="px-3.5 py-2 text-fg-muted">0 条</td>
                  <td class="px-3.5 py-2">最多 5 条 / 天</td>
                </tr>
                <tr>
                  <td class="px-3.5 py-2 font-medium">Pro</td>
                  <td class="px-3.5 py-2 text-fg-muted">0 条</td>
                  <td class="px-3.5 py-2">最多 8 条 / 天</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Credit Notice -->
        <section class="rounded-[22px] border border-warning/35 bg-warning-weak/60 p-5 text-[13px] leading-relaxed text-fg-muted dark:bg-warning-weak/45">
          <p class="font-semibold text-fg">积分额度消耗说明</p>
          <p class="mt-1.5">
            为避免在不知情情况下消耗额度，本功能默认关闭。开启后，每日后台联网发帖与延迟点赞/评论回复所产生的模型调用均正常计入你的账号积分消耗；当记忆为 0 或当前额度耗尽时会自动跳过，不产生额外扣费，且你可随时在本页或设置中关闭。
          </p>
        </section>
      </div>
    </div>
  </div>
</template>
