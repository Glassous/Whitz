<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import { useConversationsStore } from "../../stores/conversations";
import { useSchedulesStore, type ScheduleFormPayload } from "../../stores/schedules";
import type {
  ScheduleModelRoute,
  SchedulePreviewResult,
  ScheduleTargetMode,
  ScheduleType,
  ScheduledTask,
  SkillItem,
} from "../../types";
import BaseButton from "../ui/BaseButton.vue";
import BaseInput from "../ui/BaseInput.vue";
import BaseModal from "../ui/BaseModal.vue";
import BaseTextarea from "../ui/BaseTextarea.vue";
import FormError from "../ui/FormError.vue";

const props = defineProps<{
  open: boolean;
  task: ScheduledTask | null;
  minIntervalMinutes: number;
}>();

const emit = defineEmits<{
  close: [];
  saved: [ScheduledTask];
}>();

const auth = useAuthStore();
const convs = useConversationsStore();
const schedules = useSchedulesStore();

const SCHEDULE_TYPES: { value: ScheduleType; label: string }[] = [
  { value: "daily", label: "每天" },
  { value: "weekly", label: "每周" },
  { value: "monthly", label: "每月" },
  { value: "interval", label: "固定间隔" },
  { value: "once", label: "单次" },
  { value: "cron", label: "Cron 表达式" },
];

const WEEKDAYS = [
  { value: 1, label: "一" },
  { value: 2, label: "二" },
  { value: 3, label: "三" },
  { value: 4, label: "四" },
  { value: 5, label: "五" },
  { value: 6, label: "六" },
  { value: 7, label: "日" },
];

const MODEL_ROUTES: { value: ScheduleModelRoute; label: string }[] = [
  { value: "auto", label: "自动路由" },
  { value: "default", label: "标准均衡" },
  { value: "fast", label: "快速响应" },
  { value: "reasoning", label: "深度思考" },
];

const name = ref("");
const prompt = ref("");
const scheduleType = ref<ScheduleType>("daily");
const onceDatetime = ref("");
const everyMinutes = ref(60);
const timeHHMM = ref("09:00");
const weekdays = ref<number[]>([1, 2, 3, 4, 5]);
const monthDay = ref(1);
const cronExpr = ref("0 9 * * 1-5");
const timezone = ref("Asia/Shanghai");
const targetMode = ref<ScheduleTargetMode>("dedicated");
const targetConvId = ref("");
const modelRoute = ref<ScheduleModelRoute>("auto");
const selectedSkills = ref<string[]>([]);
const availableSkills = ref<SkillItem[]>([]);

const saving = ref(false);
const error = ref<string | null>(null);
const preview = ref<SchedulePreviewResult | null>(null);
const previewing = ref(false);
let previewTimer: number | null = null;

function defaultOnceLocalInput(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function isoToLocalInput(iso?: string | null): string {
  if (!iso) return defaultOnceLocalInput();
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return defaultOnceLocalInput();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function ensureSkillsLoaded() {
  if (availableSkills.value.length) return;
  try {
    const res = await api.get<SkillItem[]>("/skills");
    availableSkills.value = (Array.isArray(res) ? res : []).filter((s) => s.enabled);
  } catch {
    availableSkills.value = [];
  }
}

function hydrateForm() {
  error.value = null;
  preview.value = null;
  const t = props.task;
  if (!t) {
    name.value = "";
    prompt.value = "";
    scheduleType.value = "daily";
    onceDatetime.value = defaultOnceLocalInput();
    everyMinutes.value = Math.max(60, props.minIntervalMinutes);
    timeHHMM.value = "09:00";
    weekdays.value = [1, 2, 3, 4, 5];
    monthDay.value = 1;
    cronExpr.value = "0 9 * * 1-5";
    timezone.value = auth.user?.timezone || "Asia/Shanghai";
    targetMode.value = "dedicated";
    targetConvId.value = "";
    modelRoute.value = "auto";
    selectedSkills.value = [];
    return;
  }
  name.value = t.name;
  prompt.value = t.prompt;
  scheduleType.value = t.schedule_type;
  timezone.value = t.timezone || auth.user?.timezone || "Asia/Shanghai";
  targetMode.value = t.target_mode || "dedicated";
  targetConvId.value = t.conversation_id || "";
  modelRoute.value = t.model_route || "auto";
  selectedSkills.value = [...(t.skill_names || [])];

  const cfg = t.schedule_config || {};
  const pad = (n: number) => String(n).padStart(2, "0");
  if (t.schedule_type === "once") {
    onceDatetime.value = isoToLocalInput(cfg.run_at);
  } else {
    onceDatetime.value = defaultOnceLocalInput();
  }
  if (t.schedule_type === "interval") {
    everyMinutes.value = Number(cfg.every_minutes || Math.max(60, props.minIntervalMinutes));
  } else {
    everyMinutes.value = Math.max(60, props.minIntervalMinutes);
  }
  if (t.schedule_type === "daily" || t.schedule_type === "weekly" || t.schedule_type === "monthly") {
    timeHHMM.value = `${pad(Number(cfg.hour ?? 9))}:${pad(Number(cfg.minute ?? 0))}`;
  } else {
    timeHHMM.value = "09:00";
  }
  if (t.schedule_type === "weekly" && Array.isArray(cfg.weekdays)) {
    weekdays.value = cfg.weekdays.map((n: any) => Number(n)).filter((n: number) => n >= 1 && n <= 7);
  }
  if (t.schedule_type === "monthly") {
    monthDay.value = Number(cfg.day || 1);
  }
  if (t.schedule_type === "cron") {
    cronExpr.value = String(cfg.expr || "0 9 * * 1-5");
  }
}

function buildScheduleConfig(): Record<string, any> {
  const [hhRaw, mmRaw] = (timeHHMM.value || "09:00").split(":");
  const hour = Math.max(0, Math.min(23, Number(hhRaw ?? 9) || 0));
  const minute = Math.max(0, Math.min(59, Number(mmRaw ?? 0) || 0));

  switch (scheduleType.value) {
    case "once": {
      const dt = new Date(onceDatetime.value);
      return { run_at: Number.isNaN(dt.getTime()) ? onceDatetime.value : dt.toISOString() };
    }
    case "interval":
      return { every_minutes: Math.max(1, Number(everyMinutes.value) || 60) };
    case "daily":
      return { hour, minute };
    case "weekly":
      return { weekdays: weekdays.value.length ? [...weekdays.value].sort((a, b) => a - b) : [1], hour, minute };
    case "monthly":
      return { day: Math.max(1, Math.min(31, Number(monthDay.value) || 1)), hour, minute };
    case "cron":
      return { expr: cronExpr.value.trim() };
  }
}

async function runPreview() {
  if (!props.open) return;
  previewing.value = true;
  try {
    preview.value = await schedules.preview({
      schedule_type: scheduleType.value,
      schedule_config: buildScheduleConfig(),
      timezone: timezone.value.trim() || "Asia/Shanghai",
      count: 5,
    });
  } catch {
    preview.value = null;
  } finally {
    previewing.value = false;
  }
}

function schedulePreviewDebounced() {
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => {
    void runPreview();
  }, 220);
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      hydrateForm();
      void ensureSkillsLoaded();
      void runPreview();
    }
  },
);

watch(
  [scheduleType, onceDatetime, everyMinutes, timeHHMM, weekdays, monthDay, cronExpr, timezone],
  () => {
    if (props.open) schedulePreviewDebounced();
  },
  { deep: true },
);

function toggleWeekday(day: number) {
  if (weekdays.value.includes(day)) {
    if (weekdays.value.length > 1) {
      weekdays.value = weekdays.value.filter((d) => d !== day);
    }
  } else {
    weekdays.value = [...weekdays.value, day].sort((a, b) => a - b);
  }
}

function toggleSkill(skillName: string) {
  if (selectedSkills.value.includes(skillName)) {
    selectedSkills.value = selectedSkills.value.filter((s) => s !== skillName);
  } else if (selectedSkills.value.length < 10) {
    selectedSkills.value = [...selectedSkills.value, skillName];
  }
}

const sideConvs = computed(() => convs.sideConversations);

function formatPreviewTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    timeZone: timezone.value.trim() || "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function onSubmit() {
  error.value = null;
  const trimmedName = name.value.trim();
  const trimmedPrompt = prompt.value.trim();
  if (!trimmedName) {
    error.value = "请输入任务名称";
    return;
  }
  if (!trimmedPrompt) {
    error.value = "请输入任务执行指令";
    return;
  }
  if (targetMode.value === "conversation" && !targetConvId.value) {
    error.value = "请选择要投递的目标旁聊";
    return;
  }

  const payload: ScheduleFormPayload = {
    name: trimmedName,
    prompt: trimmedPrompt,
    schedule_type: scheduleType.value,
    schedule_config: buildScheduleConfig(),
    timezone: timezone.value.trim() || "Asia/Shanghai",
    target_mode: targetMode.value,
    conversation_id: targetMode.value === "conversation" ? targetConvId.value : null,
    model_route: modelRoute.value,
    skill_names: selectedSkills.value,
  };

  saving.value = true;
  try {
    const saved = props.task
      ? await schedules.updateTask(props.task.id, payload)
      : await schedules.createTask({ ...payload, enabled: true });
    emit("saved", saved);
    emit("close");
  } catch (e: any) {
    const detail = e?.detail;
    error.value =
      typeof detail === "string"
        ? detail
        : typeof detail?.detail === "string"
          ? detail.detail
          : e?.message ?? "保存定时任务失败";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <BaseModal
    :open="open"
    :title="task ? '编辑定时任务' : '新建定时任务'"
    width="max-w-2xl"
    @close="emit('close')"
  >
    <form class="space-y-4" @submit.prevent="onSubmit">
      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <label class="mb-1 block text-[12.5px] font-medium text-fg">任务名称</label>
          <BaseInput v-model="name" placeholder="例如：每日 AI 早报" maxlength="120" />
        </div>
        <div>
          <label class="mb-1 block text-[12.5px] font-medium text-fg">调度时区</label>
          <BaseInput v-model="timezone" placeholder="Asia/Shanghai" maxlength="64" />
        </div>
      </div>

      <div>
        <label class="mb-1 block text-[12.5px] font-medium text-fg">执行指令（到点自动发送给助理）</label>
        <BaseTextarea
          v-model="prompt"
          :rows="3"
          placeholder="例如：联网搜索今天最新的大模型与 Agent 开源进展，整理 5 条核心动态并附来源链接。"
        />
      </div>

      <div>
        <label class="mb-1.5 block text-[12.5px] font-medium text-fg">调度周期</label>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="opt in SCHEDULE_TYPES"
            :key="opt.value"
            type="button"
            class="rounded-xl px-3 py-1.5 text-[12.5px] font-medium transition-colors"
            :class="
              scheduleType === opt.value
                ? 'bg-primary text-primary-fg'
                : 'bg-surface text-fg-muted hover:bg-hover hover:text-fg'
            "
            @click="scheduleType = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>

        <div class="mt-3 rounded-xl border border-line bg-canvas p-3.5">
          <div v-if="scheduleType === 'once'" class="space-y-1.5">
            <label class="block text-[12px] text-fg-muted">执行时间（本地时间）</label>
            <input
              v-model="onceDatetime"
              type="datetime-local"
              class="focus-ring w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-fg"
            />
          </div>

          <div v-else-if="scheduleType === 'interval'" class="flex flex-wrap items-center gap-2.5">
            <span class="text-[13px] text-fg-muted">每隔</span>
            <input
              v-model.number="everyMinutes"
              type="number"
              :min="minIntervalMinutes"
              max="43200"
              class="focus-ring w-28 rounded-xl border border-line bg-surface px-3 py-1.5 text-[13px] text-fg"
            />
            <span class="text-[13px] text-fg-muted">分钟执行一次（当前档位最小 {{ minIntervalMinutes }} 分钟）</span>
          </div>

          <div v-else-if="scheduleType === 'daily'" class="flex items-center gap-2.5">
            <span class="text-[13px] text-fg-muted">每天</span>
            <input
              v-model="timeHHMM"
              type="time"
              class="focus-ring rounded-xl border border-line bg-surface px-3 py-1.5 text-[13px] text-fg"
            />
            <span class="text-[13px] text-fg-muted">触发</span>
          </div>

          <div v-else-if="scheduleType === 'weekly'" class="space-y-3">
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="wd in WEEKDAYS"
                :key="wd.value"
                type="button"
                class="flex h-8 w-8 items-center justify-center rounded-lg text-[12.5px] font-medium transition-colors"
                :class="
                  weekdays.includes(wd.value)
                    ? 'bg-accent text-white'
                    : 'bg-surface text-fg-muted hover:bg-hover hover:text-fg'
                "
                @click="toggleWeekday(wd.value)"
              >
                {{ wd.label }}
              </button>
            </div>
            <div class="flex items-center gap-2.5">
              <span class="text-[13px] text-fg-muted">触发时间</span>
              <input
                v-model="timeHHMM"
                type="time"
                class="focus-ring rounded-xl border border-line bg-surface px-3 py-1.5 text-[13px] text-fg"
              />
            </div>
          </div>

          <div v-else-if="scheduleType === 'monthly'" class="flex flex-wrap items-center gap-3">
            <div class="flex items-center gap-2">
              <span class="text-[13px] text-fg-muted">每月</span>
              <input
                v-model.number="monthDay"
                type="number"
                min="1"
                max="31"
                class="focus-ring w-20 rounded-xl border border-line bg-surface px-3 py-1.5 text-[13px] text-fg"
              />
              <span class="text-[13px] text-fg-muted">日</span>
            </div>
            <input
              v-model="timeHHMM"
              type="time"
              class="focus-ring rounded-xl border border-line bg-surface px-3 py-1.5 text-[13px] text-fg"
            />
          </div>

          <div v-else-if="scheduleType === 'cron'" class="space-y-1.5">
            <label class="block text-[12px] text-fg-muted">标准 5 段 Cron（分 时 日 月 周）</label>
            <BaseInput v-model="cronExpr" placeholder="0 9 * * 1-5" />
            <p class="text-[11.5px] text-fg-faint">例如 `0 9 * * 1-5` 表示工作日每天 09:00；`*/30 * * * *` 表示每 30 分钟。</p>
          </div>

          <!-- Live Next Runs Preview -->
          <div class="mt-3 border-t border-line/70 pt-2.5">
            <div class="flex items-center justify-between text-[12px]">
              <span class="font-medium text-fg-muted">执行时间预览</span>
              <span v-if="previewing" class="text-fg-faint">校验中…</span>
              <span v-else-if="preview?.valid" class="text-accent">{{ preview.schedule_description }}</span>
            </div>
            <p v-if="preview && !preview.valid && preview.error" class="mt-1 text-[12px] text-danger">
              {{ preview.error }}
            </p>
            <div v-else-if="preview?.next_runs?.length" class="mt-1.5 flex flex-wrap gap-1.5">
              <span
                v-for="(iso, i) in preview.next_runs"
                :key="i"
                class="rounded-lg bg-surface px-2 py-0.5 text-[11.5px] text-fg-muted"
              >
                {{ formatPreviewTime(iso) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <label class="mb-1 block text-[12.5px] font-medium text-fg">结果投递会话</label>
          <select
            v-model="targetMode"
            class="focus-ring w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-fg"
          >
            <option value="dedicated">任务专属旁聊（推荐）</option>
            <option value="main">主聊天</option>
            <option value="conversation">指定已有旁聊</option>
          </select>
        </div>

        <div>
          <label class="mb-1 block text-[12.5px] font-medium text-fg">模型策略</label>
          <select
            v-model="modelRoute"
            class="focus-ring w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-fg"
          >
            <option v-for="mr in MODEL_ROUTES" :key="mr.value" :value="mr.value">
              {{ mr.label }}
            </option>
          </select>
        </div>
      </div>

      <div v-if="targetMode === 'conversation'">
        <label class="mb-1 block text-[12.5px] font-medium text-fg">选择目标旁聊</label>
        <select
          v-model="targetConvId"
          class="focus-ring w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-fg"
        >
          <option value="" disabled>请选择一个旁聊…</option>
          <option v-for="c in sideConvs" :key="c.id" :value="c.id">
            {{ c.title }}
          </option>
        </select>
      </div>

      <div v-if="availableSkills.length">
        <label class="mb-1.5 block text-[12.5px] font-medium text-fg">关联技能（可选）</label>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="sk in availableSkills"
            :key="sk.name"
            type="button"
            class="rounded-full border px-2.5 py-1 text-[12px] transition-colors"
            :class="
              selectedSkills.includes(sk.name)
                ? 'border-accent bg-accent-weak text-accent'
                : 'border-line bg-surface text-fg-muted hover:text-fg'
            "
            @click="toggleSkill(sk.name)"
          >
            {{ sk.title || sk.name }}
          </button>
        </div>
      </div>

      <FormError :message="error" />

      <div class="flex justify-end gap-2 pt-2">
        <BaseButton type="button" variant="secondary" @click="emit('close')">取消</BaseButton>
        <BaseButton type="submit" :loading="saving">
          {{ task ? "保存修改" : "创建并启用" }}
        </BaseButton>
      </div>
    </form>
  </BaseModal>
</template>
