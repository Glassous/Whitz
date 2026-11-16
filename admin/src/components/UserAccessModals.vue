<script setup lang="ts">
import { ref, watch } from "vue";
import { api, readableError } from "../api/client";
import type { AdminUser, MembershipTier } from "../types";
import BaseButton from "./ui/BaseButton.vue";
import BaseInput from "./ui/BaseInput.vue";
import BaseModal from "./ui/BaseModal.vue";

const props = defineProps<{
  memberTarget: AdminUser | null;
  creditTarget: AdminUser | null;
}>();

const emit = defineEmits<{
  closeMember: [];
  closeCredit: [];
  saved: [];
}>();

const memberTier = ref<MembershipTier>("free");
const memberExpiry = ref("");
const memberSaving = ref(false);
const memberError = ref<string | null>(null);

const creditAmount = ref("100");
const creditNote = ref("");
const creditSaving = ref(false);
const creditError = ref<string | null>(null);

function tierLabel(tier: MembershipTier): string {
  return tier === "pro" ? "Pro" : tier === "plus" ? "Plus" : "Free";
}

function toLocalInput(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

watch(
  () => props.memberTarget,
  (user) => {
    if (!user) return;
    memberTier.value = user.membership_tier;
    memberExpiry.value = toLocalInput(user.membership_expires_at);
    memberError.value = null;
  },
);

watch(
  () => props.creditTarget,
  (user) => {
    if (!user) return;
    creditAmount.value = "100";
    creditNote.value = "";
    creditError.value = null;
  },
);

async function saveMembership() {
  const target = props.memberTarget;
  if (!target) return;
  memberError.value = null;
  memberSaving.value = true;
  try {
    await api.patch(`/admin/users/${target.id}/membership`, {
      tier: memberTier.value,
      expires_at:
        memberTier.value === "free" || !memberExpiry.value
          ? null
          : new Date(memberExpiry.value).toISOString(),
    });
    emit("saved");
    emit("closeMember");
  } catch (e: unknown) {
    memberError.value = readableError(e);
  } finally {
    memberSaving.value = false;
  }
}

async function saveCredits() {
  const target = props.creditTarget;
  if (!target) return;
  const amount = Number(creditAmount.value);
  if (!Number.isFinite(amount) || amount === 0) {
    creditError.value = "请输入非 0 的整数积分";
    return;
  }
  creditError.value = null;
  creditSaving.value = true;
  try {
    await api.post(`/admin/users/${target.id}/credits`, {
      credits: Math.trunc(amount),
      note: creditNote.value.trim() || null,
    });
    emit("saved");
    emit("closeCredit");
  } catch (e: unknown) {
    creditError.value = readableError(e);
  } finally {
    creditSaving.value = false;
  }
}
</script>

<template>
  <BaseModal :open="!!memberTarget" title="调整会员" width="30rem" @close="emit('closeMember')">
    <p class="text-[12.5px] leading-relaxed text-fg-muted">
      为
      <span class="font-medium text-fg">{{ memberTarget?.display_name }}</span>
      设置档位与有效期。切换档位会以当前时刻重新计算积分窗口。
    </p>
    <div class="mt-4 space-y-4">
      <div>
        <p class="mb-1.5 text-[13px] font-medium text-fg-muted">会员档位</p>
        <div class="grid grid-cols-3 gap-2">
          <button
            v-for="option in (['free', 'plus', 'pro'] as const)"
            :key="option"
            type="button"
            class="focus-ring h-10 rounded-xl border text-[13px] font-medium transition-colors"
            :class="
              memberTier === option
                ? 'border-accent bg-accent-weak text-accent'
                : 'border-line text-fg-muted hover:bg-hover hover:text-fg'
            "
            @click="memberTier = option"
          >
            {{ tierLabel(option) }}
          </button>
        </div>
      </div>
      <div v-if="memberTier !== 'free'">
        <BaseInput v-model="memberExpiry" label="有效期至（留空按默认 30 天）" type="datetime-local" />
      </div>
      <p v-if="memberTier === 'free'" class="rounded-xl bg-surface px-3 py-2 text-[12px] text-fg-muted">
        降为 Free 后将清除会员有效期，并立即按免费额度重新计算。
      </p>
      <p v-if="memberError" class="text-[12px] text-danger">{{ memberError }}</p>
    </div>
    <template #footer>
      <BaseButton variant="secondary" @click="emit('closeMember')">取消</BaseButton>
      <BaseButton :loading="memberSaving" @click="saveMembership">保存</BaseButton>
    </template>
  </BaseModal>

  <BaseModal :open="!!creditTarget" title="调整积分" width="28rem" @close="emit('closeCredit')">
    <p class="text-[12.5px] leading-relaxed text-fg-muted">
      {{ creditTarget?.display_name }} 当前剩余
      <span class="font-medium text-fg">{{ creditTarget?.credits?.remaining.toFixed(1) ?? "—" }}</span>
      积分。调整会立即计入当前周/月窗口，负数表示扣减。
    </p>
    <div class="mt-4 space-y-3">
      <div class="flex items-center gap-2">
        <BaseInput v-model="creditAmount" label="调整积分" type="number" />
        <div class="mt-5 flex gap-1">
          <BaseButton
            v-for="v in ['100', '500', '-100']"
            :key="v"
            size="sm"
            variant="secondary"
            @click="creditAmount = v"
          >
            {{ Number(v) > 0 ? "+" : "" }}{{ v }}
          </BaseButton>
        </div>
      </div>
      <BaseInput v-model="creditNote" label="备注（可选）" placeholder="例如：客服补偿" />
      <p v-if="creditError" class="text-[12px] text-danger">{{ creditError }}</p>
    </div>
    <template #footer>
      <BaseButton variant="secondary" @click="emit('closeCredit')">取消</BaseButton>
      <BaseButton :loading="creditSaving" @click="saveCredits">确认调整</BaseButton>
    </template>
  </BaseModal>
</template>
