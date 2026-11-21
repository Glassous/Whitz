<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import BaseModal from "../ui/BaseModal.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseInput from "../ui/BaseInput.vue";
import AvatarCropModal from "../settings/AvatarCropModal.vue";

const props = defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  close: [];
}>();

const auth = useAuthStore();

const nameDraft = ref("");
const saving = ref(false);
const resettingAvatar = ref(false);
const error = ref<string | null>(null);
const feedback = ref<string | null>(null);
const avatarFailed = ref(false);

const fileInputRef = ref<HTMLInputElement | null>(null);
const cropOpen = ref(false);
const pendingFile = ref<File | null>(null);

const currentAvatarUrl = computed(() => auth.user?.assistant_avatar_url ?? null);
const currentName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      nameDraft.value = currentName.value;
      error.value = null;
      feedback.value = null;
      avatarFailed.value = false;
    }
  },
  { immediate: true },
);

watch(currentAvatarUrl, () => {
  avatarFailed.value = false;
});

function pickAvatar() {
  error.value = null;
  feedback.value = null;
  fileInputRef.value?.click();
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = "";
  if (!file) return;
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    error.value = "请选择 PNG、JPEG 或 WebP 格式的图片";
    return;
  }
  pendingFile.value = file;
  cropOpen.value = true;
}

function onAvatarUploaded() {
  feedback.value = "助手头像已更新";
}

async function resetAvatar() {
  resettingAvatar.value = true;
  error.value = null;
  feedback.value = null;
  try {
    await api.delete("/users/me/assistant/avatar");
    await auth.refreshUser();
    feedback.value = "已恢复默认 Whitz 图标";
  } catch (e: any) {
    error.value = typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "恢复默认图标失败");
  } finally {
    resettingAvatar.value = false;
  }
}

async function saveProfile() {
  saving.value = true;
  error.value = null;
  feedback.value = null;
  try {
    const nextName = nameDraft.value.trim() || "Whitz";
    await api.patch("/users/me/assistant", { assistant_name: nextName });
    await auth.refreshUser();
    nameDraft.value = nextName;
    emit("close");
  } catch (e: any) {
    error.value = typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "保存失败");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <BaseModal :open="open" title="自定义助手形象" width="28rem" @close="emit('close')">
    <input
      ref="fileInputRef"
      type="file"
      accept="image/png,image/jpeg,image/webp"
      class="sr-only"
      @change="onFileChange"
    />

    <div class="space-y-5">
      <!-- Avatar Row -->
      <div class="flex items-center gap-4">
        <div class="relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface ring-1 ring-line">
          <img
            v-if="currentAvatarUrl && !avatarFailed"
            :src="currentAvatarUrl"
            :alt="currentName"
            class="h-full w-full object-cover"
            @error="avatarFailed = true"
          />
          <span v-else class="brand-mark-tight h-[22px] w-[34px] text-fg" aria-hidden="true" />
        </div>

        <div class="min-w-0 flex-1 space-y-2">
          <p class="text-[13px] font-medium text-fg">助手头像</p>
          <div class="flex flex-wrap items-center gap-2">
            <BaseButton variant="secondary" size="sm" rounded="full" @click="pickAvatar">
              更换头像
            </BaseButton>
            <BaseButton
              v-if="currentAvatarUrl"
              variant="ghost"
              size="sm"
              rounded="full"
              :loading="resettingAvatar"
              @click="resetAvatar"
            >
              恢复默认图标
            </BaseButton>
          </div>
          <p class="text-[11.5px] text-fg-faint">支持 PNG、JPEG、WebP，默认使用 Whitz 图标。</p>
        </div>
      </div>

      <!-- Nickname Input -->
      <BaseInput
        v-model="nameDraft"
        label="助手昵称"
        placeholder="Whitz"
        :maxlength="80"
        rounded="full"
        soft
        @keydown.enter.prevent="saveProfile"
      />
      <p class="-mt-3 text-[12px] text-fg-faint">留空保存将恢复默认名称「Whitz」。</p>

      <p v-if="error" role="alert" class="text-[12.5px] text-danger">{{ error }}</p>
      <p v-else-if="feedback" role="status" aria-live="polite" class="text-[12.5px] text-success">{{ feedback }}</p>
    </div>

    <template #footer>
      <BaseButton variant="soft" rounded="full" :disabled="saving" @click="emit('close')">取消</BaseButton>
      <BaseButton rounded="full" :loading="saving" @click="saveProfile">保存</BaseButton>
    </template>
  </BaseModal>

  <AvatarCropModal
    :open="cropOpen"
    :file="pendingFile"
    endpoint="/users/me/assistant/avatar"
    title="裁切助手头像"
    @close="cropOpen = false; pendingFile = null"
    @uploaded="onAvatarUploaded"
  />
</template>
