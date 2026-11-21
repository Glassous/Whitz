<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useFilesStore } from "../../stores/files";
import type { ConversationFile } from "../../types";
import Spinner from "../ui/Spinner.vue";

const props = defineProps<{
  open: boolean;
  images: ConversationFile[];
  initialIndex?: number;
}>();

const emit = defineEmits<{
  close: [];
  download: [file: ConversationFile];
}>();

const filesStore = useFilesStore();

const currentIndex = ref(0);
const scale = ref(1);
const translateX = ref(0);
const translateY = ref(0);
const dragging = ref(false);
const resolvedUrls = ref<Record<string, string>>({});
const loadingUrl = ref(false);

let dragStartX = 0;
let dragStartY = 0;
let dragOriginX = 0;
let dragOriginY = 0;

const currentFile = computed<ConversationFile | null>(() => {
  if (!props.images.length) return null;
  const idx = Math.max(0, Math.min(props.images.length - 1, currentIndex.value));
  return props.images[idx] ?? null;
});

const currentUrl = computed(() => {
  const f = currentFile.value;
  if (!f) return null;
  return resolvedUrls.value[f.id] || f.preview_url || f.thumb_url || null;
});

function resetTransform() {
  scale.value = 1;
  translateX.value = 0;
  translateY.value = 0;
}

async function ensureCurrentUrl(force = false) {
  const f = currentFile.value;
  if (!f) return;
  if (!force && (resolvedUrls.value[f.id] || f.preview_url)) return;
  loadingUrl.value = true;
  try {
    const url = await filesStore.ensureFreshUrl(f, force);
    if (url) {
      resolvedUrls.value = { ...resolvedUrls.value, [f.id]: url };
    }
  } finally {
    loadingUrl.value = false;
  }
}

watch(
  [() => props.open, () => props.initialIndex, () => props.images.length],
  ([isOpen, initIdx]) => {
    if (isOpen) {
      currentIndex.value = Math.max(0, Math.min(props.images.length - 1, initIdx ?? 0));
      resetTransform();
      void ensureCurrentUrl();
    }
  },
  { immediate: true },
);

watch(currentIndex, () => {
  resetTransform();
  if (props.open) void ensureCurrentUrl();
});

function prev() {
  if (props.images.length <= 1) return;
  currentIndex.value = (currentIndex.value - 1 + props.images.length) % props.images.length;
}

function next() {
  if (props.images.length <= 1) return;
  currentIndex.value = (currentIndex.value + 1) % props.images.length;
}

function zoomBy(delta: number) {
  const nextScale = Math.max(0.5, Math.min(4, Math.round((scale.value + delta) * 100) / 100));
  scale.value = nextScale;
  if (nextScale <= 1) {
    translateX.value = 0;
    translateY.value = 0;
  }
}

function onWheel(e: WheelEvent) {
  e.preventDefault();
  zoomBy(e.deltaY < 0 ? 0.25 : -0.25);
}

function onPointerDown(e: PointerEvent) {
  if (scale.value <= 1) return;
  dragging.value = true;
  dragStartX = e.clientX;
  dragStartY = e.clientY;
  dragOriginX = translateX.value;
  dragOriginY = translateY.value;
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return;
  translateX.value = dragOriginX + (e.clientX - dragStartX);
  translateY.value = dragOriginY + (e.clientY - dragStartY);
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value) return;
  dragging.value = false;
  const el = e.currentTarget as HTMLElement;
  if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
}

function onKeydown(e: KeyboardEvent) {
  if (!props.open) return;
  if (e.key === "Escape") {
    e.preventDefault();
    emit("close");
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    prev();
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    next();
  } else if (e.key === "+" || e.key === "=") {
    e.preventDefault();
    zoomBy(0.25);
  } else if (e.key === "-") {
    e.preventDefault();
    zoomBy(-0.25);
  } else if (e.key === "0") {
    e.preventDefault();
    resetTransform();
  }
}

onMounted(() => {
  window.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open && currentFile"
        class="fixed inset-0 z-[100] flex flex-col bg-black/88 text-white backdrop-blur-sm select-none"
        role="dialog"
        aria-modal="true"
        aria-label="图片预览画廊"
        @click.self="emit('close')"
      >
        <!-- Top Bar -->
        <div class="flex shrink-0 items-center justify-between gap-3 px-4 py-3">
          <div class="flex min-w-0 items-center gap-2.5">
            <span v-if="images.length > 1" class="rounded-full bg-white/12 px-2.5 py-0.5 text-[12px] tabular-nums">
              {{ currentIndex + 1 }} / {{ images.length }}
            </span>
            <span class="truncate text-[13px] text-white/80" :title="currentFile.filename">
              {{ currentFile.filename }}
            </span>
          </div>

          <div class="flex shrink-0 items-center gap-1">
            <button
              type="button"
              class="flex h-8 w-8 items-center justify-center rounded-lg text-white/80 transition-colors hover:bg-white/15 hover:text-white"
              title="缩小 (-)"
              @click="zoomBy(-0.25)"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" d="M5 12h14" />
              </svg>
            </button>
            <button
              type="button"
              class="rounded-lg px-2 py-1 text-[12px] tabular-nums text-white/85 hover:bg-white/15"
              title="重置缩放 (0)"
              @click="resetTransform"
            >
              {{ Math.round(scale * 100) }}%
            </button>
            <button
              type="button"
              class="flex h-8 w-8 items-center justify-center rounded-lg text-white/80 transition-colors hover:bg-white/15 hover:text-white"
              title="放大 (+)"
              @click="zoomBy(0.25)"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" d="M12 5v14M5 12h14" />
              </svg>
            </button>
            <button
              type="button"
              class="flex h-8 w-8 items-center justify-center rounded-lg text-white/80 transition-colors hover:bg-white/15 hover:text-white"
              title="下载原图"
              @click="emit('download', currentFile)"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
              </svg>
            </button>
            <button
              type="button"
              class="flex h-8 w-8 items-center justify-center rounded-lg text-white/80 transition-colors hover:bg-white/15 hover:text-white"
              aria-label="关闭画廊"
              @click="emit('close')"
            >
              <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Main Image Stage -->
        <div
          class="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden px-12"
          @wheel.prevent="onWheel"
          @click.self="emit('close')"
        >
          <button
            v-if="images.length > 1"
            type="button"
            class="absolute left-3 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-white/12 text-white transition-colors hover:bg-white/25"
            aria-label="上一张"
            @click.stop="prev"
          >
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
            </svg>
          </button>

          <Spinner v-if="loadingUrl && !currentUrl" :size="24" />
          <img
            v-else-if="currentUrl"
            :src="currentUrl"
            :alt="currentFile.filename"
            draggable="false"
            class="max-h-full max-w-full rounded-lg object-contain transition-transform duration-75"
            :class="scale > 1 ? (dragging ? 'cursor-grabbing' : 'cursor-grab') : 'cursor-zoom-in'"
            :style="{ transform: `translate(${translateX}px, ${translateY}px) scale(${scale})` }"
            @dblclick="scale > 1 ? resetTransform() : zoomBy(1)"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerUp"
            @error="ensureCurrentUrl(true)"
          />

          <button
            v-if="images.length > 1"
            type="button"
            class="absolute right-3 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-white/12 text-white transition-colors hover:bg-white/25"
            aria-label="下一张"
            @click.stop="next"
          >
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
            </svg>
          </button>
        </div>

        <!-- Bottom Thumbnail Strip -->
        <div
          v-if="images.length > 1"
          class="flex shrink-0 items-center justify-center gap-2 overflow-x-auto px-4 py-3"
        >
          <button
            v-for="(img, idx) in images"
            :key="img.id"
            type="button"
            class="h-12 w-12 shrink-0 overflow-hidden rounded-lg border-2 transition-all"
            :class="idx === currentIndex ? 'border-white scale-105' : 'border-transparent opacity-55 hover:opacity-90'"
            @click="currentIndex = idx"
          >
            <img
              v-if="resolvedUrls[img.id] || img.thumb_url || img.preview_url"
              :src="resolvedUrls[img.id] || img.thumb_url || img.preview_url!"
              :alt="img.filename"
              class="h-full w-full object-cover"
            />
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
