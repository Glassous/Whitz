<script setup lang="ts">
import { nextTick, onMounted, ref, useId, watch } from "vue";

const props = defineProps<{ open: boolean; title?: string; width?: string }>();
const emit = defineEmits<{ close: [] }>();

const titleId = useId();
const dialogRef = ref<HTMLDialogElement | null>(null);
const rendered = ref(props.open);
let pressedOutside = false;

let supportsDisplayTransition: boolean | undefined;
function canTransitionDisplay(): boolean {
  if (supportsDisplayTransition !== undefined) return supportsDisplayTransition;
  if (!window.CSS?.supports?.("transition-behavior", "allow-discrete") || !document.body) {
    return false;
  }
  const probe = document.createElement("div");
  probe.style.cssText = "transition: display 1s allow-discrete !important; display: block;";
  document.body.appendChild(probe);
  getComputedStyle(probe).display;
  probe.style.display = "none";
  supportsDisplayTransition = getComputedStyle(probe).display === "block";
  probe.remove();
  return supportsDisplayTransition;
}

function supportsTopLayerExit(): boolean {
  return Boolean(window.CSS?.supports?.("overlay", "auto") && canTransitionDisplay());
}

function isOutside(e: PointerEvent, dialog: HTMLDialogElement): boolean {
  const r = dialog.getBoundingClientRect();
  return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
}

async function openDialog() {
  rendered.value = true;
  await nextTick();
  const dialog = dialogRef.value;
  if (dialog && !dialog.open) {
    dialog.removeAttribute("data-closing");
    dialog.showModal();
  }
}

async function closeDialog() {
  const dialog = dialogRef.value;
  if (!dialog || !dialog.open) {
    rendered.value = false;
    return;
  }
  if (!supportsTopLayerExit()) {
    dialog.setAttribute("data-closing", "");
    const animations = dialog.getAnimations({ subtree: true });
    if (animations.length > 0) {
      await Promise.race([
        Promise.allSettled(animations.map((a) => a.finished)),
        new Promise((r) => setTimeout(r, 400)),
      ]);
    }
    if (!dialog.hasAttribute("data-closing")) return;
    dialog.removeAttribute("data-closing");
  }
  if (dialog.open) dialog.close();
  rendered.value = false;
}

function onCancel(e: Event) {
  e.preventDefault();
  emit("close");
}

function onNativeClose() {
  if (props.open) emit("close");
  rendered.value = false;
}

function onPointerdown(e: PointerEvent) {
  const dialog = dialogRef.value;
  if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
  pressedOutside = isOutside(e, dialog);
}

function onPointerup(e: PointerEvent) {
  const dialog = dialogRef.value;
  if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
  if (pressedOutside && isOutside(e, dialog)) emit("close");
  pressedOutside = false;
}

watch(
  () => props.open,
  (val) => {
    if (val) {
      void openDialog();
    } else {
      void closeDialog();
    }
  },
);

onMounted(() => {
  if (props.open) void openDialog();
});
</script>

<template>
  <dialog
    ref="dialogRef"
    class="whitz-dialog w-full"
    :style="{ maxWidth: width ?? '32rem' }"
    closedby="any"
    :aria-labelledby="title ? titleId : undefined"
    @cancel="onCancel"
    @close="onNativeClose"
    @pointerdown="onPointerdown"
    @pointerup="onPointerup"
  >
    <div
      v-if="rendered"
      class="max-h-[85dvh] w-full overflow-y-auto rounded-2xl border border-line bg-canvas"
      style="box-shadow: var(--shadow)"
    >
      <div v-if="title" class="sticky top-0 flex items-center justify-between border-b border-line bg-canvas px-5 py-4">
        <h3 :id="titleId" class="text-[15px] font-semibold text-fg">{{ title }}</h3>
        <button
          type="button"
          class="focus-ring -mr-1 rounded-lg p-1.5 text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          aria-label="关闭"
          @click="emit('close')"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <div class="px-5 py-4"><slot /></div>
      <div v-if="$slots.footer" class="flex justify-end gap-2 border-t border-line px-5 py-4">
        <slot name="footer" />
      </div>
    </div>
  </dialog>
</template>
