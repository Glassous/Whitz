<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import BaseModal from "../ui/BaseModal.vue";
import BaseButton from "../ui/BaseButton.vue";

const props = defineProps<{
  open: boolean;
  file: File | null;
}>();

const emit = defineEmits<{
  close: [];
  uploaded: [];
}>();

const CROP_SIZE = 272;
const OUTPUT_SIZE = 256;

const auth = useAuthStore();

const imgSrc = ref<string | null>(null);
const imgEl = ref<HTMLImageElement | null>(null);
const naturalW = ref(0);
const naturalH = ref(0);
const zoom = ref(1);
const offsetX = ref(0);
const offsetY = ref(0);
const uploading = ref(false);
const error = ref<string | null>(null);

let objectUrl: string | null = null;
let dragging = false;
let dragStartX = 0;
let dragStartY = 0;
let startOffsetX = 0;
let startOffsetY = 0;

const baseScale = computed(() => {
  if (!naturalW.value || !naturalH.value) return 1;
  return CROP_SIZE / Math.min(naturalW.value, naturalH.value);
});

const totalScale = computed(() => baseScale.value * zoom.value);

const maxOffsetX = computed(() => {
  const renderedW = naturalW.value * totalScale.value;
  return Math.max(0, (renderedW - CROP_SIZE) / 2);
});

const maxOffsetY = computed(() => {
  const renderedH = naturalH.value * totalScale.value;
  return Math.max(0, (renderedH - CROP_SIZE) / 2);
});

function clampOffsets() {
  const mx = maxOffsetX.value;
  const my = maxOffsetY.value;
  offsetX.value = Math.max(-mx, Math.min(mx, offsetX.value));
  offsetY.value = Math.max(-my, Math.min(my, offsetY.value));
}

function revokeUrl() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
}

watch(
  () => [props.open, props.file] as const,
  ([isOpen, file]) => {
    error.value = null;
    if (!isOpen || !file) {
      revokeUrl();
      imgSrc.value = null;
      naturalW.value = 0;
      naturalH.value = 0;
      return;
    }
    revokeUrl();
    objectUrl = URL.createObjectURL(file);
    imgSrc.value = objectUrl;
    zoom.value = 1;
    offsetX.value = 0;
    offsetY.value = 0;
  },
  { immediate: true },
);

watch(zoom, () => {
  clampOffsets();
});

function onImageLoad(e: Event) {
  const el = e.target as HTMLImageElement;
  imgEl.value = el;
  naturalW.value = el.naturalWidth;
  naturalH.value = el.naturalHeight;
  zoom.value = 1;
  offsetX.value = 0;
  offsetY.value = 0;
}

function onPointerDown(e: PointerEvent) {
  const target = e.currentTarget as HTMLElement;
  target.setPointerCapture(e.pointerId);
  dragging = true;
  dragStartX = e.clientX;
  dragStartY = e.clientY;
  startOffsetX = offsetX.value;
  startOffsetY = offsetY.value;
}

function onPointerMove(e: PointerEvent) {
  if (!dragging) return;
  offsetX.value = startOffsetX + (e.clientX - dragStartX);
  offsetY.value = startOffsetY + (e.clientY - dragStartY);
  clampOffsets();
}

function onPointerUp(e: PointerEvent) {
  if (!dragging) return;
  dragging = false;
  const target = e.currentTarget as HTMLElement;
  if (target.hasPointerCapture(e.pointerId)) {
    target.releasePointerCapture(e.pointerId);
  }
}

function onWheel(e: WheelEvent) {
  const delta = e.deltaY > 0 ? -0.1 : 0.1;
  zoom.value = Math.max(1, Math.min(3, Number((zoom.value + delta).toFixed(2))));
}

const imageStyle = computed(() => ({
  width: `${naturalW.value}px`,
  height: `${naturalH.value}px`,
  transform: `translate(-50%, -50%) translate(${offsetX.value}px, ${offsetY.value}px) scale(${totalScale.value})`,
}));

function renderCroppedDataUrl(): string | null {
  const el = imgEl.value;
  if (!el || !naturalW.value || !naturalH.value) return null;

  const canvas = document.createElement("canvas");
  canvas.width = OUTPUT_SIZE;
  canvas.height = OUTPUT_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";

  const scale = totalScale.value;
  const srcSize = CROP_SIZE / scale;
  const srcCenterX = naturalW.value / 2 - offsetX.value / scale;
  const srcCenterY = naturalH.value / 2 - offsetY.value / scale;
  const sx = Math.max(0, Math.min(naturalW.value - srcSize, srcCenterX - srcSize / 2));
  const sy = Math.max(0, Math.min(naturalH.value - srcSize, srcCenterY - srcSize / 2));

  ctx.drawImage(el, sx, sy, srcSize, srcSize, 0, 0, OUTPUT_SIZE, OUTPUT_SIZE);

  const webp = canvas.toDataURL("image/webp", 0.9);
  if (webp.startsWith("data:image/webp")) return webp;
  return canvas.toDataURL("image/jpeg", 0.9);
}

async function confirmUpload() {
  error.value = null;
  const dataUrl = renderCroppedDataUrl();
  if (!dataUrl) {
    error.value = "图片尚未加载完成，请稍候";
    return;
  }
  uploading.value = true;
  try {
    await api.put("/users/me/avatar", { data_url: dataUrl });
    await auth.refreshUser();
    emit("uploaded");
    emit("close");
  } catch (e: any) {
    error.value = typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "头像上传失败");
  } finally {
    uploading.value = false;
  }
}

onBeforeUnmount(revokeUrl);
</script>

<template>
  <BaseModal :open="open" title="裁切头像" @close="emit('close')">
    <div class="flex flex-col items-center gap-4">
      <div
        class="relative touch-none select-none overflow-hidden rounded-2xl bg-surface ring-1 ring-line"
        :style="{ width: `${CROP_SIZE}px`, height: `${CROP_SIZE}px` }"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @wheel.prevent="onWheel"
      >
        <img
          v-if="imgSrc"
          :src="imgSrc"
          alt="待裁切头像"
          draggable="false"
          class="pointer-events-none absolute left-1/2 top-1/2 max-w-none origin-center select-none"
          :style="imageStyle"
          @load="onImageLoad"
        />
        <!-- 1:1 & circular safe-zone guide -->
        <div
          class="pointer-events-none absolute inset-0 rounded-full ring-1 ring-white/80"
          style="box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.36)"
          aria-hidden="true"
        />
      </div>

      <div class="flex w-full max-w-[272px] items-center gap-3">
        <span class="text-[12px] text-fg-muted">缩放</span>
        <input
          v-model.number="zoom"
          type="range"
          min="1"
          max="3"
          step="0.01"
          aria-label="缩放比例"
          class="h-1.5 flex-1 cursor-pointer accent-accent"
        />
        <span class="w-10 text-right text-[12px] tabular-nums text-fg-faint">{{ Math.round(zoom * 100) }}%</span>
      </div>

      <p class="text-[12px] text-fg-faint">拖拽图片调整位置，滚轮或滑块缩放。</p>
      <p v-if="error" role="alert" class="text-[12.5px] text-danger">{{ error }}</p>
    </div>

    <template #footer>
      <BaseButton variant="soft" rounded="full" :disabled="uploading" @click="emit('close')">取消</BaseButton>
      <BaseButton rounded="full" :loading="uploading" @click="confirmUpload">保存头像</BaseButton>
    </template>
  </BaseModal>
</template>
