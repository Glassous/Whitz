<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { api, readableError } from "../api/client";
import type { InviteCode } from "../types";
import BaseButton from "./ui/BaseButton.vue";
import BaseInput from "./ui/BaseInput.vue";

const emit = defineEmits<{ created: [] }>();

const tier = ref<"plus" | "pro">("plus");
const duration = ref("30");
const maxUses = ref("1");
const expiresLocal = ref("");
const note = ref("");
const creating = ref(false);
const formError = ref<string | null>(null);
const createdCode = ref<string | null>(null);
const copied = ref(false);
let copyTimer: number | null = null;

const createdHint = computed(() => "已生成，复制后发送给用户");

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = true;
    if (copyTimer) window.clearTimeout(copyTimer);
    copyTimer = window.setTimeout(() => {
      copied.value = false;
    }, 1200);
  } catch {
    copied.value = false;
  }
}

async function createCode() {
  formError.value = null;
  createdCode.value = null;
  const days = Number(duration.value);
  const uses = Number(maxUses.value);
  if (!Number.isFinite(days) || days < 1 || days > 365) {
    formError.value = "有效天数需在 1–365 之间";
    return;
  }
  if (!Number.isFinite(uses) || uses < 1 || uses > 1000) {
    formError.value = "可用次数需在 1–1000 之间";
    return;
  }
  creating.value = true;
  try {
    const row = await api.post<InviteCode>("/admin/invite-codes", {
      tier: tier.value,
      duration_days: days,
      max_uses: uses,
      expires_at: expiresLocal.value ? new Date(expiresLocal.value).toISOString() : null,
      note: note.value.trim() || null,
    });
    createdCode.value = row.code;
    note.value = "";
    emit("created");
  } catch (e: unknown) {
    formError.value = readableError(e);
  } finally {
    creating.value = false;
  }
}

onBeforeUnmount(() => {
  if (copyTimer) window.clearTimeout(copyTimer);
});
</script>

<template>
  <section class="h-fit rounded-2xl border border-line bg-canvas p-5">
    <h2 class="text-[13.5px] font-medium text-fg">生成兑换码</h2>
    <p class="mt-1 text-[11.5px] leading-relaxed text-fg-faint">
      同一档位续期会累加有效期，跨档兑换从生效时刻重新计算积分周期。
    </p>

    <div class="mt-4 space-y-3">
      <div>
        <p class="mb-1.5 text-[13px] font-medium text-fg-muted">会员档位</p>
        <div class="grid grid-cols-2 gap-2">
          <button
            v-for="option in (['plus', 'pro'] as const)"
            :key="option"
            type="button"
            class="focus-ring flex h-10 items-center justify-center gap-2 rounded-xl border text-[13px] font-medium capitalize transition-colors"
            :class="
              tier === option
                ? 'border-accent bg-accent-weak text-accent'
                : 'border-line text-fg-muted hover:bg-hover hover:text-fg'
            "
            @click="tier = option"
          >
            {{ option }}
          </button>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-2">
        <BaseInput v-model="duration" label="有效天数" type="number" placeholder="30" />
        <BaseInput v-model="maxUses" label="可用次数" type="number" placeholder="1" />
      </div>
      <BaseInput v-model="expiresLocal" label="邀请码过期时间（可选）" type="datetime-local" />
      <BaseInput v-model="note" label="备注（可选）" placeholder="例如：内测用户批次 A" />

      <p v-if="formError" class="text-[12px] text-danger">{{ formError }}</p>
      <p v-if="createdCode" class="rounded-xl bg-success-weak px-3 py-2 text-[12px] text-success">
        {{ createdHint }}
        <button
          class="ml-1 font-mono font-semibold underline-offset-2 hover:underline"
          @click="copy(createdCode ?? '')"
        >
          {{ createdCode }}
        </button>
        <span v-if="copied" class="ml-1 text-[11px]">已复制</span>
      </p>

      <BaseButton block :loading="creating" @click="createCode">生成邀请码</BaseButton>
    </div>
  </section>
</template>
