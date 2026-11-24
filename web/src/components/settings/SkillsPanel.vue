<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "../../api/client";
import type { SkillItem, SkillPendingItem } from "../../types";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import FormError from "../ui/FormError.vue";
import Spinner from "../ui/Spinner.vue";
import AppIcon from "../ui/AppIcon.vue";

interface GithubPreviewResult {
  name: string;
  description: string;
  content: string;
  repo_url: string;
  ref?: string | null;
  path?: string | null;
}

type SourceFilter = "all" | "builtin" | "custom" | "github";

const skills = ref<SkillItem[]>([]);
const pending = ref<SkillPendingItem[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const feedback = ref<string | null>(null);

const searchQuery = ref("");
const sourceFilter = ref<SourceFilter>("all");
const togglingName = ref<string | null>(null);
const resolvingPendingId = ref<string | null>(null);

// View SKILL.md modal
const viewSkillTarget = ref<{
  name: string;
  title?: string | null;
  description?: string | null;
  source?: string;
  category?: string | null;
  repo_url?: string | null;
  content?: string | null;
} | null>(null);
const copiedSkillContent = ref(false);

// Delete confirmation modal
const deleteTarget = ref<SkillItem | null>(null);
const deleting = ref(false);
const deleteError = ref<string | null>(null);

// Create custom skill modal
const createModalOpen = ref(false);
const createName = ref("");
const createCategory = ref("");
const createDescription = ref("");
const createContent = ref("");
const createEnabled = ref(true);
const creating = ref(false);
const createError = ref<string | null>(null);

// Install from GitHub modal
const githubModalOpen = ref(false);
const githubUrl = ref("");
const githubRef = ref("");
const githubPath = ref("");
const githubPreview = ref<GithubPreviewResult | null>(null);
const githubInstallName = ref("");
const githubEnabled = ref(true);
const previewingGithub = ref(false);
const installingGithub = ref(false);
const githubError = ref<string | null>(null);

function extractError(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

function sourceCategory(source?: string): "builtin" | "github" | "custom" {
  if (source === "builtin") return "builtin";
  if (source === "github") return "github";
  return "custom";
}

function sourceLabel(source?: string): string {
  if (source === "builtin") return "内置";
  if (source === "github") return "GitHub";
  if (source === "assistant" || source === "agent") return "助理创建";
  return "自定义";
}

function sourceTone(source?: string): "gray" | "brand" | "green" | "blue" {
  if (source === "builtin") return "gray";
  if (source === "github") return "blue";
  return "green";
}

function safeHttpUrl(raw?: string | null): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (trimmed.startsWith("https://") || trimmed.startsWith("http://")) return trimmed;
  return null;
}

const counts = computed(() => {
  const res = { all: skills.value.length, builtin: 0, custom: 0, github: 0 };
  for (const s of skills.value) {
    res[sourceCategory(s.source)] += 1;
  }
  return res;
});

const filteredSkills = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  return skills.value.filter((s) => {
    if (sourceFilter.value !== "all" && sourceCategory(s.source) !== sourceFilter.value) {
      return false;
    }
    if (!q) return true;
    const hay = [s.name, s.title ?? "", s.description ?? "", s.category ?? "", ...(s.tags ?? [])]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
});

async function loadAll() {
  loading.value = true;
  error.value = null;
  try {
    const [skillList, pendingList] = await Promise.all([
      api.get<SkillItem[]>("/skills"),
      api.get<SkillPendingItem[]>("/skills/pending"),
    ]);
    skills.value = Array.isArray(skillList) ? skillList : [];
    pending.value = Array.isArray(pendingList) ? pendingList : [];
  } catch (e: any) {
    error.value = extractError(e, "加载技能列表失败");
  } finally {
    loading.value = false;
  }
}

async function toggleSkill(skill: SkillItem) {
  if (togglingName.value) return;
  togglingName.value = skill.name;
  error.value = null;
  feedback.value = null;
  const nextEnabled = !skill.enabled;
  try {
    await api.patch(`/skills/${encodeURIComponent(skill.name)}`, { enabled: nextEnabled });
    skill.enabled = nextEnabled;
    feedback.value = `技能「${skill.title || skill.name}」已${nextEnabled ? "启用" : "停用"}`;
  } catch (e: any) {
    error.value = extractError(e, "切换技能状态失败");
  } finally {
    togglingName.value = null;
  }
}

async function resolvePendingSkill(item: SkillPendingItem, action: "approve" | "reject") {
  resolvingPendingId.value = item.id;
  error.value = null;
  feedback.value = null;
  try {
    await api.post(`/skills/pending/${encodeURIComponent(item.id)}`, {
      action,
      enabled: true,
    });
    await loadAll();
    feedback.value = action === "approve" ? `已批准安装技能「${item.name}」` : `已拒绝技能请求「${item.name}」`;
  } catch (e: any) {
    error.value = extractError(e, "处理待确认技能请求失败");
  } finally {
    resolvingPendingId.value = null;
  }
}

function openViewModal(target: {
  name: string;
  title?: string | null;
  description?: string | null;
  source?: string;
  category?: string | null;
  repo_url?: string | null;
  content?: string | null;
}) {
  copiedSkillContent.value = false;
  viewSkillTarget.value = target;
}

async function copySkillMarkdown() {
  const text = viewSkillTarget.value?.content ?? "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    copiedSkillContent.value = true;
    window.setTimeout(() => {
      copiedSkillContent.value = false;
    }, 1800);
  } catch {
    /* ignore */
  }
}

function requestDeleteSkill(skill: SkillItem) {
  deleteError.value = null;
  deleteTarget.value = skill;
}

async function confirmDeleteSkill() {
  const target = deleteTarget.value;
  if (!target) return;
  deleting.value = true;
  deleteError.value = null;
  feedback.value = null;
  try {
    await api.delete(`/skills/${encodeURIComponent(target.name)}`);
    skills.value = skills.value.filter((s) => s.name !== target.name);
    deleteTarget.value = null;
    feedback.value = `已删除技能「${target.title || target.name}」`;
  } catch (e: any) {
    deleteError.value = extractError(e, "删除技能失败");
  } finally {
    deleting.value = false;
  }
}

function openCreateModal() {
  createName.value = "";
  createCategory.value = "";
  createDescription.value = "";
  createContent.value = "";
  createEnabled.value = true;
  createError.value = null;
  createModalOpen.value = true;
}

async function submitCreateSkill() {
  createError.value = null;
  const cleanedName = createName.value.trim();
  const cleanedContent = createContent.value.trim();
  if (!cleanedName || cleanedName.includes("/") || cleanedName.includes("\\") || cleanedName.includes("..")) {
    createError.value = "请输入有效的技能名称（不能包含 /、\\ 或 ..）";
    return;
  }
  if (!cleanedContent) {
    createError.value = "请输入 SKILL.md 技能正文内容";
    return;
  }
  creating.value = true;
  feedback.value = null;
  try {
    await api.post("/skills", {
      name: cleanedName,
      description: createDescription.value.trim(),
      content: createContent.value,
      category: createCategory.value.trim() || null,
      enabled: createEnabled.value,
    });
    createModalOpen.value = false;
    await loadAll();
    feedback.value = `已创建自定义技能「${cleanedName}」`;
  } catch (e: any) {
    createError.value = extractError(e, "创建技能失败");
  } finally {
    creating.value = false;
  }
}

function openGithubModal() {
  githubUrl.value = "";
  githubRef.value = "";
  githubPath.value = "";
  githubPreview.value = null;
  githubInstallName.value = "";
  githubEnabled.value = true;
  githubError.value = null;
  githubModalOpen.value = true;
}

function onGithubInputChanged() {
  githubError.value = null;
  githubPreview.value = null;
}

async function previewGithubSkill() {
  githubError.value = null;
  const url = githubUrl.value.trim();
  if (!url) {
    githubError.value = "请输入 GitHub 仓库地址或 owner/repo";
    return;
  }
  previewingGithub.value = true;
  try {
    const res = await api.post<GithubPreviewResult>("/skills/preview-github", {
      url,
      ref: githubRef.value.trim() || null,
      path: githubPath.value.trim() || null,
    });
    githubPreview.value = res;
    githubInstallName.value = res.name;
  } catch (e: any) {
    githubError.value = extractError(e, "预览解析 GitHub 技能失败");
    githubPreview.value = null;
  } finally {
    previewingGithub.value = false;
  }
}

async function installGithubSkill() {
  if (!githubPreview.value) return;
  githubError.value = null;
  const targetName = githubInstallName.value.trim() || githubPreview.value.name;
  if (!targetName || targetName.includes("/") || targetName.includes("\\") || targetName.includes("..")) {
    githubError.value = "技能名称无效";
    return;
  }
  installingGithub.value = true;
  feedback.value = null;
  try {
    await api.post("/skills/install-github", {
      url: githubUrl.value.trim(),
      name: targetName,
      ref: (githubPreview.value.ref ?? githubRef.value.trim()) || null,
      path: (githubPreview.value.path ?? githubPath.value.trim()) || null,
      enabled: githubEnabled.value,
    });
    githubModalOpen.value = false;
    await loadAll();
    feedback.value = `已从 GitHub 安装技能「${targetName}」`;
  } catch (e: any) {
    githubError.value = extractError(e, "安装 GitHub 技能失败");
  } finally {
    installingGithub.value = false;
  }
}

onMounted(() => {
  void loadAll();
});
</script>

<template>
  <div class="space-y-5">
    <!-- Top Actions & Search -->
    <section class="space-y-4 rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-[15.5px] font-semibold text-fg">已安装技能</h2>
            <BaseBadge tone="gray">{{ skills.length }} 个</BaseBadge>
          </div>
          <p class="mt-1 text-[13px] text-fg-muted">
            启用后的技能可在对话输入框中选择并注入任务指令，支持自定义创建与从 GitHub 仓库导入。
          </p>
        </div>

        <div class="flex shrink-0 flex-wrap items-center gap-2">
          <BaseButton variant="secondary" size="sm" rounded="full" @click="openGithubModal">
            <AppIcon name="download" class="h-3.5 w-3.5" :stroke-width="2" />
            <span>从 GitHub 安装技能</span>
          </BaseButton>
          <BaseButton size="sm" rounded="full" @click="openCreateModal">
            <AppIcon name="plus" class="h-3.5 w-3.5" :stroke-width="2.1" />
            <span>新建自定义技能</span>
          </BaseButton>
        </div>
      </div>

      <!-- Search & Source Filter -->
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div class="icon-search-group relative min-w-0 flex-1">
          <AppIcon
            name="search"
            motion="search-focus"
            class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-faint"
            :stroke-width="2"
          />
          <input
            v-model="searchQuery"
            type="search"
            placeholder="搜索技能名称、分类或描述…"
            aria-label="搜索技能"
            class="focus-ring h-9.5 w-full rounded-xl border border-line/80 bg-canvas pl-9 pr-3 text-[13.5px] text-fg placeholder:text-fg-faint hover:border-line-strong"
          />
        </div>

        <div class="flex flex-wrap items-center gap-1.5">
          <button
            v-for="tab in [
              { value: 'all', label: `全部 (${counts.all})` },
              { value: 'builtin', label: `内置 (${counts.builtin})` },
              { value: 'custom', label: `自定义 (${counts.custom})` },
              { value: 'github', label: `GitHub (${counts.github})` },
            ] as const"
            :key="tab.value"
            type="button"
            class="focus-ring rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors"
            :class="
              sourceFilter === tab.value
                ? 'bg-primary text-primary-fg'
                : 'bg-canvas text-fg-muted hover:bg-hover hover:text-fg'
            "
            @click="sourceFilter = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>
    </section>

    <FormError :message="error" />
    <div
      v-if="feedback"
      role="status"
      aria-live="polite"
      class="rounded-2xl bg-success-weak px-4 py-2.5 text-[13px] text-success"
    >
      {{ feedback }}
    </div>

    <!-- Pending Agent Skill Requests -->
    <section
      v-if="pending.length > 0"
      class="space-y-3 rounded-[24px] bg-sidebar p-5 ring-1 ring-warning/35 sm:p-6 dark:bg-surface"
    >
      <div class="flex items-center gap-2">
        <h2 class="text-[15.5px] font-semibold text-fg">待确认的技能安装请求</h2>
        <BaseBadge tone="amber">{{ pending.length }} 个待审批</BaseBadge>
      </div>

      <div class="space-y-2.5">
        <article
          v-for="item in pending"
          :key="item.id"
          class="flex flex-col gap-3 rounded-2xl bg-canvas p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-mono text-[13.5px] font-semibold text-fg">{{ item.name }}</span>
              <BaseBadge tone="amber">{{ item.action === "update" ? "更新请求" : "安装请求" }}</BaseBadge>
              <BaseBadge tone="gray">{{ sourceLabel(item.source) }}</BaseBadge>
            </div>
            <p class="mt-1 text-[13px] text-fg-muted">{{ item.description || "AI 助理提议安装的技能" }}</p>
          </div>

          <div class="flex shrink-0 flex-wrap items-center gap-2">
            <BaseButton
              variant="ghost"
              size="sm"
              rounded="full"
              @click="
                openViewModal({
                  name: item.name,
                  description: item.description,
                  source: item.source,
                  content: item.content,
                })
              "
            >
              查看 SKILL.md
            </BaseButton>
            <BaseButton
              variant="soft"
              size="sm"
              rounded="full"
              :disabled="resolvingPendingId === item.id"
              @click="resolvePendingSkill(item, 'reject')"
            >
              拒绝
            </BaseButton>
            <BaseButton
              size="sm"
              rounded="full"
              :loading="resolvingPendingId === item.id"
              @click="resolvePendingSkill(item, 'approve')"
            >
              批准安装
            </BaseButton>
          </div>
        </article>
      </div>
    </section>

    <!-- Loading / Empty / Installed Skills Grid -->
    <div
      v-if="loading && !skills.length"
      class="flex items-center justify-center gap-2 rounded-[24px] bg-sidebar py-12 text-[13.5px] text-fg-muted dark:bg-surface"
    >
      <Spinner :size="18" />
      <span>正在加载技能列表…</span>
    </div>

    <div
      v-else-if="!filteredSkills.length"
      class="rounded-[24px] bg-sidebar px-6 py-10 text-center text-[13.5px] text-fg-muted dark:bg-surface"
    >
      {{ skills.length ? "没有匹配的技能，请尝试调整搜索词或筛选条件。" : "暂无可用技能，点击上方「新建自定义技能」或「从 GitHub 安装技能」添加。" }}
    </div>

    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <article
        v-for="skill in filteredSkills"
        :key="skill.name"
        class="flex flex-col justify-between gap-3 rounded-[24px] bg-sidebar p-5 transition-colors dark:bg-surface"
        :class="skill.enabled ? '' : 'opacity-75'"
      >
        <div class="space-y-2">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-1.5">
                <h3 class="truncate text-[14.5px] font-semibold text-fg">
                  {{ skill.title || skill.name }}
                </h3>
                <BaseBadge :tone="sourceTone(skill.source)">{{ sourceLabel(skill.source) }}</BaseBadge>
                <BaseBadge v-if="skill.category" tone="gray">{{ skill.category }}</BaseBadge>
              </div>
              <p v-if="skill.title && skill.title !== skill.name" class="mt-0.5 truncate font-mono text-[11.5px] text-fg-faint">
                {{ skill.name }}
              </p>
            </div>

            <button
              type="button"
              role="switch"
              :aria-checked="skill.enabled"
              :aria-label="`切换技能 ${skill.name}`"
              :disabled="togglingName === skill.name"
              class="focus-ring relative mt-0.5 inline-flex h-6.5 w-11 shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              :class="skill.enabled ? 'bg-primary' : 'bg-line-strong'"
              @click="toggleSkill(skill)"
            >
              <span
                class="h-5.5 w-5.5 rounded-full bg-canvas shadow-xs transition-transform"
                :class="skill.enabled ? 'translate-x-4.5' : 'translate-x-0'"
              />
            </button>
          </div>

          <p class="line-clamp-2 text-[13px] leading-relaxed text-fg-muted">
            {{ skill.description || "暂无技能简介" }}
          </p>

          <a
            v-if="safeHttpUrl(skill.repo_url)"
            :href="safeHttpUrl(skill.repo_url)!"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex max-w-full items-center gap-1 truncate text-[12px] text-fg-faint underline-offset-2 hover:text-fg hover:underline"
          >
            <span class="truncate">{{ skill.repo_url }}</span>
          </a>
        </div>

        <div class="flex items-center justify-between gap-2 border-t border-line/60 pt-3">
          <span class="text-[12px] font-medium" :class="skill.enabled ? 'text-success' : 'text-fg-faint'">
            {{ skill.enabled ? "已启用" : "已停用" }}
          </span>
          <div class="flex items-center gap-1.5">
            <BaseButton variant="soft" size="sm" rounded="full" @click="openViewModal(skill)">
              查看 SKILL.md
            </BaseButton>
            <BaseButton
              v-if="skill.source !== 'builtin'"
              variant="ghost"
              size="sm"
              rounded="full"
              class="text-danger hover:bg-danger-weak hover:text-danger"
              @click="requestDeleteSkill(skill)"
            >
              删除
            </BaseButton>
          </div>
        </div>
      </article>
    </div>

    <!-- View SKILL.md Modal -->
    <BaseModal
      :open="!!viewSkillTarget"
      :title="viewSkillTarget ? `${viewSkillTarget.title || viewSkillTarget.name} · SKILL.md` : 'SKILL.md'"
      width="44rem"
      @close="viewSkillTarget = null"
    >
      <div v-if="viewSkillTarget" class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="font-mono text-[12.5px] text-fg-muted">{{ viewSkillTarget.name }}</span>
            <BaseBadge v-if="viewSkillTarget.source" :tone="sourceTone(viewSkillTarget.source)">
              {{ sourceLabel(viewSkillTarget.source) }}
            </BaseBadge>
            <BaseBadge v-if="viewSkillTarget.category" tone="gray">{{ viewSkillTarget.category }}</BaseBadge>
          </div>
          <BaseButton
            v-if="viewSkillTarget.content"
            variant="soft"
            size="sm"
            rounded="full"
            @click="copySkillMarkdown"
          >
            {{ copiedSkillContent ? "已复制" : "复制全文" }}
          </BaseButton>
        </div>

        <p v-if="viewSkillTarget.description" class="text-[13px] text-fg-muted">
          {{ viewSkillTarget.description }}
        </p>

        <pre
          v-scrollbar
          class="custom-scrollbar max-h-[55dvh] overflow-auto rounded-2xl bg-surface p-4 font-mono text-[12.5px] leading-relaxed text-fg whitespace-pre-wrap break-words dark:bg-canvas"
        >{{ viewSkillTarget.content || "该技能未提供可预览的 SKILL.md 内容。" }}</pre>
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" @click="viewSkillTarget = null">关闭</BaseButton>
      </template>
    </BaseModal>

    <!-- Create Custom Skill Modal -->
    <BaseModal
      :open="createModalOpen"
      title="新建自定义技能"
      width="42rem"
      @close="createModalOpen = false"
    >
      <form class="space-y-3.5" @submit.prevent="submitCreateSkill">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label for="skill-create-name" class="mb-1 block text-[13px] font-medium text-fg-muted">
              技能标识（英文 / 短横线）
            </label>
            <input
              id="skill-create-name"
              v-model="createName"
              type="text"
              maxlength="80"
              placeholder="例如：weekly-report"
              class="focus-ring h-10 w-full rounded-xl border border-line bg-canvas px-3 font-mono text-[13.5px] text-fg placeholder:font-sans placeholder:text-fg-faint"
            />
          </div>
          <div>
            <label for="skill-create-category" class="mb-1 block text-[13px] font-medium text-fg-muted">
              分类（可选）
            </label>
            <input
              id="skill-create-category"
              v-model="createCategory"
              type="text"
              maxlength="64"
              placeholder="例如：办公效率 / 开发"
              class="focus-ring h-10 w-full rounded-xl border border-line bg-canvas px-3 text-[13.5px] text-fg placeholder:text-fg-faint"
            />
          </div>
        </div>

        <div>
          <label for="skill-create-desc" class="mb-1 block text-[13px] font-medium text-fg-muted">
            简短描述
          </label>
          <input
            id="skill-create-desc"
            v-model="createDescription"
            type="text"
            maxlength="500"
            placeholder="说明该技能的适用场景与输出规范"
            class="focus-ring h-10 w-full rounded-xl border border-line bg-canvas px-3 text-[13.5px] text-fg placeholder:text-fg-faint"
          />
        </div>

        <div>
          <div class="mb-1 flex items-center justify-between">
            <label for="skill-create-content" class="text-[13px] font-medium text-fg-muted">SKILL.md 正文内容</label>
            <span class="text-[11.5px] tabular-nums text-fg-faint">{{ createContent.length }} / 64000</span>
          </div>
          <textarea
            id="skill-create-content"
            v-model="createContent"
            rows="9"
            maxlength="64000"
            placeholder="# 技能说明&#10;&#10;当用户请求生成周报时，请按「本周完成、关键数据、下周计划、风险阻塞」四个模块输出。"
            class="focus-ring w-full resize-y rounded-xl border border-line bg-canvas px-3.5 py-2.5 font-mono text-[13px] leading-relaxed text-fg placeholder:font-sans placeholder:text-fg-faint"
          />
        </div>

        <label class="inline-flex cursor-pointer items-center gap-2 text-[13px] text-fg-muted">
          <input v-model="createEnabled" type="checkbox" class="h-4 w-4 accent-accent" />
          <span>创建后立即启用该技能</span>
        </label>

        <FormError :message="createError" />
      </form>

      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="creating" @click="createModalOpen = false">
          取消
        </BaseButton>
        <BaseButton rounded="full" :loading="creating" @click="submitCreateSkill">
          保存并创建
        </BaseButton>
      </template>
    </BaseModal>

    <!-- Install from GitHub Modal -->
    <BaseModal
      :open="githubModalOpen"
      title="从 GitHub 安装技能"
      width="44rem"
      @close="githubModalOpen = false"
    >
      <div class="space-y-3.5">
        <p class="text-[13px] leading-relaxed text-fg-muted">
          支持输入 <code class="rounded bg-surface px-1 py-0.5 text-[12px]">owner/repo</code> 或完整 GitHub 仓库/目录链接。安装前需先点击「预览解析」校验仓库中的 <code class="rounded bg-surface px-1 py-0.5 text-[12px]">SKILL.md</code> 与安全扫描结果。
        </p>

        <div>
          <label for="gh-skill-url" class="mb-1 block text-[13px] font-medium text-fg-muted">
            GitHub URL 或 owner/repo
          </label>
          <input
            id="gh-skill-url"
            v-model="githubUrl"
            type="text"
            maxlength="500"
            placeholder="例如：owner/repo 或 https://github.com/owner/repo/tree/main/skills/my-skill"
            class="focus-ring h-10 w-full rounded-xl border border-line bg-canvas px-3 text-[13.5px] text-fg placeholder:text-fg-faint"
            @input="onGithubInputChanged"
          />
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label for="gh-skill-ref" class="mb-1 block text-[13px] font-medium text-fg-muted">
              分支 / Tag（可选）
            </label>
            <input
              id="gh-skill-ref"
              v-model="githubRef"
              type="text"
              maxlength="120"
              placeholder="默认自动识别（如 main）"
              class="focus-ring h-10 w-full rounded-xl border border-line bg-canvas px-3 text-[13.5px] text-fg placeholder:text-fg-faint"
              @input="onGithubInputChanged"
            />
          </div>
          <div>
            <label for="gh-skill-path" class="mb-1 block text-[13px] font-medium text-fg-muted">
              子目录路径（可选）
            </label>
            <input
              id="gh-skill-path"
              v-model="githubPath"
              type="text"
              maxlength="300"
              placeholder="例如：skills/code-review"
              class="focus-ring h-10 w-full rounded-xl border border-line bg-canvas px-3 text-[13.5px] text-fg placeholder:text-fg-faint"
              @input="onGithubInputChanged"
            />
          </div>
        </div>

        <div class="flex justify-end">
          <BaseButton
            variant="secondary"
            size="sm"
            rounded="full"
            :loading="previewingGithub"
            :disabled="installingGithub"
            @click="previewGithubSkill"
          >
            预览解析
          </BaseButton>
        </div>

        <FormError :message="githubError" />

        <!-- Parsed Preview Box -->
        <div v-if="githubPreview" class="space-y-3 rounded-2xl border border-line bg-surface/65 p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <BaseBadge tone="green">解析通过</BaseBadge>
              <span class="text-[12px] text-fg-faint">{{ githubPreview.repo_url }}</span>
            </div>
          </div>

          <div>
            <label for="gh-install-name" class="mb-1 block text-[12.5px] font-medium text-fg-muted">
              安装后的技能名称
            </label>
            <input
              id="gh-install-name"
              v-model="githubInstallName"
              type="text"
              maxlength="80"
              class="focus-ring h-9.5 w-full rounded-xl border border-line bg-canvas px-3 font-mono text-[13px] text-fg"
            />
          </div>

          <p v-if="githubPreview.description" class="text-[13px] text-fg-muted">
            {{ githubPreview.description }}
          </p>

          <div>
            <p class="mb-1 text-[12px] font-medium text-fg-faint">SKILL.md 内容预览</p>
            <pre
              v-scrollbar
              class="custom-scrollbar max-h-56 overflow-auto rounded-xl bg-canvas p-3 font-mono text-[12px] leading-relaxed text-fg whitespace-pre-wrap break-words"
            >{{ githubPreview.content }}</pre>
          </div>

          <label class="inline-flex cursor-pointer items-center gap-2 text-[13px] text-fg-muted">
            <input v-model="githubEnabled" type="checkbox" class="h-4 w-4 accent-accent" />
            <span>安装后立即启用</span>
          </label>
        </div>
      </div>

      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="previewingGithub || installingGithub" @click="githubModalOpen = false">
          取消
        </BaseButton>
        <BaseButton
          rounded="full"
          :disabled="!githubPreview || previewingGithub"
          :loading="installingGithub"
          @click="installGithubSkill"
        >
          确认安装
        </BaseButton>
      </template>
    </BaseModal>

    <!-- Delete Skill Confirmation Modal -->
    <BaseModal
      :open="!!deleteTarget"
      title="删除技能"
      @close="deleteTarget = null"
    >
      <div v-if="deleteTarget" class="space-y-3">
        <p class="text-[14px] leading-relaxed text-fg-muted">
          确定要删除技能 <strong class="font-medium text-fg">{{ deleteTarget.title || deleteTarget.name }}</strong> 吗？删除后将无法在对话中使用此技能。
        </p>
        <FormError :message="deleteError" />
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="deleting" @click="deleteTarget = null">
          取消
        </BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="deleting" @click="confirmDeleteSkill">
          确认删除
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
