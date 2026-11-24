<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ACCEPT_ATTR, SUPPORTED_TYPES_SUMMARY, categoryLabel, formatFileSize, validateDragItems } from "../../lib/fileTypes";
import { isImageExt, serializeFileToken } from "../../lib/fileTokens";
import type { ConversationFile, RagMode, UploadTask } from "../../types";
import SkillPickerPopover from "./SkillPickerPopover.vue";
import AppIcon from "../ui/AppIcon.vue";
import Spinner from "../ui/Spinner.vue";

const props = defineProps<{
  streaming: boolean;
  sending?: boolean;
  stopping?: boolean;
  disabled?: boolean;
  uploading?: boolean;
  uploads?: UploadTask[];
  attachedFiles?: ConversationFile[];
  workspaceFiles?: ConversationFile[];
  selectedSkills?: string[];
  ragMode?: RagMode;
  assistantName?: string;
}>();

const emit = defineEmits<{
  send: [content: string, inlineFileIds: string[]];
  stop: [];
  upload: [files: FileList, dataTransfer?: DataTransfer | null];
  "paste-files": [files: File[]];
  "cancel-upload": [localId: string];
  "retry-upload": [localId: string];
  "dismiss-upload": [localId: string];
  "detach-file": [fileId: string];
  "update:selectedSkills": [skills: string[]];
  "update:ragMode": [mode: RagMode];
}>();

const RAG_MODE_META: Record<RagMode, { label: string; title: string; next: RagMode }> = {
  auto: {
    label: "智能融合",
    title: "RAG 模式：智能融合（自动检索资料库 + 记忆 + 历史对话）— 点击切换",
    next: "files_only",
  },
  files_only: {
    label: "严选资料",
    title: "RAG 模式：严选资料（仅严格基于已上传资料回答，防幻觉）— 点击切换",
    next: "off",
  },
  off: {
    label: "关闭检索",
    title: "RAG 模式：关闭自动检索（仅按需手动调用工具）— 点击切换",
    next: "auto",
  },
};

const currentRagMode = computed<RagMode>(() => props.ragMode ?? "auto");
const currentRagMeta = computed(() => RAG_MODE_META[currentRagMode.value]);

function cycleRagMode() {
  emit("update:ragMode", currentRagMeta.value.next);
}

const NORMAL_MAX_HEIGHT = 160;

const editorRef = ref<HTMLDivElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const queuedSend = ref(false);
const canExpand = ref(false);
const expanded = ref(false);
const hasEditorContent = ref(false);
const isComposing = ref(false);

const dragDepth = ref(0);
const dragValid = ref(true);
const dragReason = ref("");
const failedThumbIds = ref<Set<string>>(new Set());

// Saved caret range inside editorRef so external clicks (e.g. "Insert to input") land at exact cursor pos
let savedRange: Range | null = null;

// @ mention file picker state
const mentionOpen = ref(false);
const mentionQuery = ref("");
const mentionActiveIndex = ref(0);
let mentionTextNode: Text | null = null;
let mentionStartOffset = 0;

const isDragging = computed(() => dragDepth.value > 0);
const hasChips = computed(
  () =>
    (props.uploads?.length ?? 0) > 0 ||
    (props.attachedFiles?.length ?? 0) > 0 ||
    (props.selectedSkills?.length ?? 0) > 0,
);
const sendLockedByUpload = computed(() => !!props.uploading && !props.streaming);
const canSubmit = computed(
  () => hasEditorContent.value && !props.streaming && !props.sending && !props.disabled,
);

const mentionCandidates = computed<ConversationFile[]>(() => {
  const list = props.workspaceFiles ?? [];
  const q = mentionQuery.value.trim().toLowerCase();
  const filtered = q
    ? list.filter(
        (f) =>
          f.filename.toLowerCase().includes(q) ||
          (f.conversation_title ?? "").toLowerCase().includes(q),
      )
    : list;
  return filtered.slice(0, 8);
});

watch(mentionCandidates, (list) => {
  if (mentionActiveIndex.value >= list.length) {
    mentionActiveIndex.value = Math.max(0, list.length - 1);
  }
});

// Auto-fire queued send the moment active file uploads finish!
watch(
  () => props.uploading,
  (isUp) => {
    if (!isUp && queuedSend.value) {
      queuedSend.value = false;
      doSend();
    }
  },
);

function fileThumbUrl(f: ConversationFile): string | null {
  if (failedThumbIds.value.has(f.id)) return null;
  if (!isImageExt(f.ext, f.category)) return null;
  return f.thumb_url || f.preview_url || null;
}

function markThumbFailed(id: string) {
  const next = new Set(failedThumbIds.value);
  next.add(id);
  failedThumbIds.value = next;
}

function removeSkill(name: string) {
  emit(
    "update:selectedSkills",
    (props.selectedSkills ?? []).filter((s) => s !== name),
  );
}

const uploadStatusAnnouncement = computed(() => {
  const active = props.uploads?.filter((u) => u.status !== "error") ?? [];
  if (active.length) return `正在上传 ${active.length} 个文件，上传期间发送按钮已锁定`;
  return "";
});

function updateExpandState() {
  const el = editorRef.value;
  if (!el) return;
  canExpand.value = el.scrollHeight > NORMAL_MAX_HEIGHT;
  if (!canExpand.value && expanded.value) {
    expanded.value = false;
  }
}

function toggleExpand() {
  if (!canExpand.value && !expanded.value) return;
  expanded.value = !expanded.value;
  editorRef.value?.focus();
}

function refreshEditorContentState() {
  const el = editorRef.value;
  if (!el) {
    hasEditorContent.value = false;
    return;
  }
  const hasChip = Boolean(el.querySelector("[data-file-chip]"));
  const plain = (el.textContent ?? "").replace(/\u200B/g, "").trim();
  hasEditorContent.value = hasChip || plain.length > 0;
  // Clean stray <br> when completely empty so placeholder shows cleanly
  if (!hasChip && plain.length === 0 && el.innerHTML !== "") {
    el.innerHTML = "";
  }
  void nextTick(updateExpandState);
}

function saveSelection() {
  const el = editorRef.value;
  const sel = window.getSelection();
  if (!el || !sel || sel.rangeCount === 0) return;
  const range = sel.getRangeAt(0);
  if (el.contains(range.commonAncestorContainer)) {
    savedRange = range.cloneRange();
  }
}

function restoreOrEndRange(): Range | null {
  const el = editorRef.value;
  if (!el) return null;
  el.focus();
  const sel = window.getSelection();
  if (!sel) return null;
  if (savedRange && el.contains(savedRange.commonAncestorContainer)) {
    sel.removeAllRanges();
    sel.addRange(savedRange);
    return savedRange;
  }
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
  savedRange = range.cloneRange();
  return range;
}

function buildChipElement(opts: {
  fileId?: string;
  localId?: string;
  filename: string;
  category: string;
  ext: string;
  thumbUrl?: string | null;
  uploading?: boolean;
}): HTMLSpanElement {
  const isImg = isImageExt(opts.ext, opts.category) && Boolean(opts.thumbUrl);
  const span = document.createElement("span");
  span.contentEditable = "false";
  span.dataset.fileChip = "1";
  span.dataset.filename = opts.filename;
  span.dataset.category = opts.category;
  span.dataset.ext = opts.ext;
  if (opts.fileId) span.dataset.fileId = opts.fileId;
  if (opts.localId) span.dataset.localId = opts.localId;
  if (isImg) span.dataset.fileKind = "image";
  if (opts.uploading) span.dataset.uploading = "1";
  span.title = opts.filename;

  if (isImg) {
    span.className = "whitz-inline-img-chip";
    const img = document.createElement("img");
    img.src = opts.thumbUrl!;
    img.alt = opts.filename;
    img.draggable = false;
    img.className = "whitz-inline-img-thumb";
    span.appendChild(img);

    if (opts.uploading) {
      const overlay = document.createElement("span");
      overlay.className = "whitz-inline-img-loading";
      overlay.textContent = "…";
      span.appendChild(overlay);
    }
  } else {
    span.className = "whitz-inline-file-chip";
    const badge = document.createElement("span");
    badge.className = "whitz-inline-file-badge";
    badge.textContent = opts.uploading ? "上传中" : categoryLabel(opts.category, opts.ext);
    span.appendChild(badge);

    const nameEl = document.createElement("span");
    nameEl.className = "whitz-inline-file-name";
    nameEl.textContent = opts.filename;
    span.appendChild(nameEl);
  }

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.dataset.chipRemove = "1";
  removeBtn.className = isImg ? "whitz-inline-img-remove" : "whitz-inline-file-remove";
  removeBtn.setAttribute("aria-label", `移除 ${opts.filename}`);
  removeBtn.textContent = "×";
  span.appendChild(removeBtn);

  return span;
}

function insertNodeAtCaret(node: Node) {
  const el = editorRef.value;
  if (!el) return;
  const range = restoreOrEndRange();
  if (!range) return;

  range.deleteContents();
  const frag = document.createDocumentFragment();
  frag.appendChild(node);
  // Insert a trailing space text node so caret can cleanly continue typing after atomic chip
  const spacer = document.createTextNode("\u00A0");
  frag.appendChild(spacer);
  range.insertNode(frag);

  const afterRange = document.createRange();
  afterRange.setStartAfter(spacer);
  afterRange.collapse(true);
  const sel = window.getSelection();
  if (sel) {
    sel.removeAllRanges();
    sel.addRange(afterRange);
  }
  savedRange = afterRange.cloneRange();
  refreshEditorContentState();
}

function insertFile(file: ConversationFile) {
  const chip = buildChipElement({
    fileId: file.id,
    filename: file.filename,
    category: file.category,
    ext: file.ext,
    thumbUrl: fileThumbUrl(file),
    uploading: false,
  });
  insertNodeAtCaret(chip);
}

function insertUploadingChip(task: UploadTask) {
  const chip = buildChipElement({
    localId: task.localId,
    filename: task.filename,
    category: task.category,
    ext: task.ext,
    thumbUrl: task.localPreviewUrl ?? null,
    uploading: true,
  });
  insertNodeAtCaret(chip);
}

function resolveInlineUpload(localId: string, file: ConversationFile) {
  const el = editorRef.value;
  if (!el) return;
  const existing = el.querySelector<HTMLElement>(`[data-file-chip][data-local-id="${CSS.escape(localId)}"]`);
  if (!existing) return;
  const replacement = buildChipElement({
    fileId: file.id,
    filename: file.filename,
    category: file.category,
    ext: file.ext,
    thumbUrl: fileThumbUrl(file),
    uploading: false,
  });
  existing.replaceWith(replacement);
  refreshEditorContentState();
}

function failInlineUpload(localId: string) {
  const el = editorRef.value;
  if (!el) return;
  const existing = el.querySelector<HTMLElement>(`[data-file-chip][data-local-id="${CSS.escape(localId)}"]`);
  if (existing) {
    existing.remove();
    refreshEditorContentState();
  }
}

function serializeEditor(): { content: string; inlineFileIds: string[] } {
  const el = editorRef.value;
  if (!el) return { content: "", inlineFileIds: [] };

  const parts: string[] = [];
  const fileIds: string[] = [];
  const seenIds = new Set<string>();

  function walk(node: Node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const txt = (node.textContent ?? "").replace(/\u00A0/g, " ").replace(/\u200B/g, "");
      if (txt) parts.push(txt);
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const elem = node as HTMLElement;
    if (elem.dataset.fileChip === "1") {
      const fid = elem.dataset.fileId;
      const fname = elem.dataset.filename || "file";
      if (fid) {
        parts.push(serializeFileToken(fid, fname));
        if (!seenIds.has(fid)) {
          seenIds.add(fid);
          fileIds.push(fid);
        }
      }
      return;
    }
    if (elem.tagName === "BR") {
      parts.push("\n");
      return;
    }
    const isBlock = elem.tagName === "DIV" || elem.tagName === "P";
    if (isBlock && parts.length > 0 && !parts[parts.length - 1].endsWith("\n")) {
      parts.push("\n");
    }
    for (const child of Array.from(elem.childNodes)) {
      walk(child);
    }
  }

  for (const child of Array.from(el.childNodes)) {
    walk(child);
  }

  const content = parts.join("").trim();
  return { content, inlineFileIds: fileIds };
}

function clearEditor() {
  if (editorRef.value) {
    editorRef.value.innerHTML = "";
  }
  savedRange = null;
  mentionOpen.value = false;
  hasEditorContent.value = false;
  expanded.value = false;
  canExpand.value = false;
  void nextTick(updateExpandState);
}

function doSend() {
  if (props.streaming || props.sending || props.disabled) return;
  const { content, inlineFileIds } = serializeEditor();
  if (!content) return;
  const pop = document.getElementById("chat-skill-picker") as (HTMLElement & { hidePopover?: () => void }) | null;
  pop?.hidePopover?.();
  mentionOpen.value = false;
  emit("send", content, inlineFileIds);
  clearEditor();
}

function submit() {
  if (!hasEditorContent.value || props.streaming || props.sending || props.disabled) return;
  if (props.uploading) {
    queuedSend.value = true;
    return;
  }
  doSend();
}

function checkMentionTrigger() {
  const el = editorRef.value;
  const sel = window.getSelection();
  if (!el || !sel || sel.rangeCount === 0 || !sel.isCollapsed) {
    mentionOpen.value = false;
    return;
  }
  const range = sel.getRangeAt(0);
  if (!el.contains(range.startContainer) || range.startContainer.nodeType !== Node.TEXT_NODE) {
    mentionOpen.value = false;
    return;
  }
  const textNode = range.startContainer as Text;
  const before = textNode.data.slice(0, range.startOffset);
  const match = /(?:^|\s)@([^\s@]{0,40})$/.exec(before);
  if (match && (props.workspaceFiles?.length ?? 0) > 0) {
    mentionTextNode = textNode;
    mentionStartOffset = range.startOffset - match[1].length - 1;
    mentionQuery.value = match[1];
    mentionActiveIndex.value = 0;
    mentionOpen.value = true;
  } else {
    mentionOpen.value = false;
  }
}

function selectMentionFile(file: ConversationFile) {
  const el = editorRef.value;
  const sel = window.getSelection();
  if (!el || !sel || !mentionTextNode || !el.contains(mentionTextNode)) {
    mentionOpen.value = false;
    insertFile(file);
    return;
  }
  const endOffset = sel.rangeCount > 0 && sel.getRangeAt(0).startContainer === mentionTextNode
    ? sel.getRangeAt(0).startOffset
    : Math.min(mentionTextNode.data.length, mentionStartOffset + 1 + mentionQuery.value.length);

  const range = document.createRange();
  range.setStart(mentionTextNode, Math.max(0, mentionStartOffset));
  range.setEnd(mentionTextNode, Math.max(mentionStartOffset, endOffset));
  sel.removeAllRanges();
  sel.addRange(range);
  savedRange = range.cloneRange();
  mentionOpen.value = false;
  mentionTextNode = null;
  insertFile(file);
}

function onEditorInput() {
  saveSelection();
  refreshEditorContentState();
  if (!isComposing.value) {
    checkMentionTrigger();
  }
}

function onEditorClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null;
  const removeBtn = target?.closest<HTMLElement>("[data-chip-remove]");
  if (removeBtn) {
    e.preventDefault();
    e.stopPropagation();
    const chip = removeBtn.closest<HTMLElement>("[data-file-chip]");
    const localId = chip?.dataset.localId;
    if (localId) {
      emit("cancel-upload", localId);
    }
    chip?.remove();
    refreshEditorContentState();
    editorRef.value?.focus();
    return;
  }
  saveSelection();
  checkMentionTrigger();
}

function onKeydown(e: KeyboardEvent) {
  if (mentionOpen.value && mentionCandidates.value.length > 0) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      mentionActiveIndex.value = (mentionActiveIndex.value + 1) % mentionCandidates.value.length;
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      mentionActiveIndex.value =
        (mentionActiveIndex.value - 1 + mentionCandidates.value.length) % mentionCandidates.value.length;
      return;
    }
    if ((e.key === "Enter" || e.key === "Tab") && !e.isComposing && !isComposing.value) {
      e.preventDefault();
      const chosen = mentionCandidates.value[mentionActiveIndex.value];
      if (chosen) selectMentionFile(chosen);
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      mentionOpen.value = false;
      return;
    }
  }

  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !isComposing.value) {
    e.preventDefault();
    submit();
  }
}

function buildPastedFilename(file: File, index: number): File {
  const name = (file.name || "").trim();
  // Screenshots / clipboard images often come as "image.png" or empty name
  if (name && name.toLowerCase() !== "image.png" && name.toLowerCase() !== "blob") {
    return file;
  }
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const mime = (file.type || "").toLowerCase();
  const ext =
    mime === "image/jpeg"
      ? ".jpg"
      : mime === "image/webp"
        ? ".webp"
        : mime === "image/gif"
          ? ".gif"
          : mime.startsWith("image/")
            ? ".png"
            : ".txt";
  const suffix = index > 0 ? `-${index + 1}` : "";
  return new File([file], `pasted-${stamp}${suffix}${ext}`, { type: file.type || "image/png" });
}

function onPaste(e: ClipboardEvent) {
  if (props.disabled) return;
  const dt = e.clipboardData;
  if (!dt) return;

  const pastedFiles: File[] = [];
  if (dt.files && dt.files.length > 0) {
    for (let i = 0; i < dt.files.length; i++) {
      pastedFiles.push(buildPastedFilename(dt.files[i], i));
    }
  } else if (dt.items) {
    for (let i = 0; i < dt.items.length; i++) {
      const item = dt.items[i];
      if (item.kind === "file") {
        const f = item.getAsFile();
        if (f) pastedFiles.push(buildPastedFilename(f, pastedFiles.length));
      }
    }
  }

  if (pastedFiles.length > 0) {
    e.preventDefault();
    saveSelection();
    emit("paste-files", pastedFiles);
    return;
  }

  // Plain-text paste only (strip rich HTML formatting from external pages)
  const plain = dt.getData("text/plain");
  if (plain) {
    e.preventDefault();
    if (document.queryCommandSupported?.("insertText")) {
      document.execCommand("insertText", false, plain);
    } else {
      const range = restoreOrEndRange();
      if (range) {
        range.deleteContents();
        const tn = document.createTextNode(plain);
        range.insertNode(tn);
        range.setStartAfter(tn);
        range.collapse(true);
      }
    }
    refreshEditorContentState();
  }
}

function openFilePicker() {
  if (props.disabled) return;
  fileInput.value?.click();
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files && input.files.length > 0) {
    emit("upload", input.files, null);
  }
  input.value = "";
}

function onDragEnter(e: DragEvent) {
  const check = validateDragItems(e.dataTransfer);
  if (!check.hasFiles) return;
  e.preventDefault();
  dragDepth.value += 1;
  dragValid.value = check.valid;
  dragReason.value = check.reason ?? "";
}

function onDragOver(e: DragEvent) {
  const check = validateDragItems(e.dataTransfer);
  if (!check.hasFiles) return;
  e.preventDefault();
  dragValid.value = check.valid;
  dragReason.value = check.reason ?? "";
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = check.valid && !props.disabled ? "copy" : "none";
  }
}

function onDragLeave(e: DragEvent) {
  if (dragDepth.value <= 0) return;
  const check = validateDragItems(e.dataTransfer);
  if (!check.hasFiles && dragDepth.value === 0) return;
  dragDepth.value = Math.max(0, dragDepth.value - 1);
  if (dragDepth.value === 0) {
    dragValid.value = true;
    dragReason.value = "";
  }
}

function onDrop(e: DragEvent) {
  const hadFiles = e.dataTransfer?.types?.includes("Files") || (e.dataTransfer?.files?.length ?? 0) > 0;
  dragDepth.value = 0;
  dragValid.value = true;
  dragReason.value = "";
  if (!hadFiles) return;
  e.preventDefault();
  if (props.disabled) return;
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    emit("upload", e.dataTransfer.files, e.dataTransfer);
  }
}

function uploadLabel(u: UploadTask): string {
  if (u.status === "signing") return "签名中…";
  if (u.status === "uploading") return `${u.progress}%`;
  if (u.status === "completing") return "确认中…";
  return "上传失败";
}

const isWideInput = ref(typeof window !== "undefined" ? window.innerWidth >= 640 : true);
let smQuery: MediaQueryList | null = null;
function onSmChange(e: MediaQueryListEvent) {
  isWideInput.value = e.matches;
}

const inputPlaceholder = computed(() => {
  const name = props.assistantName?.trim() || "Whitz";
  if (props.disabled) return "助理正在初始化，请稍候…";
  if (props.uploading) return isWideInput.value ? "文件正在上传，上传完成后自动发送…" : "文件上传中…";
  return isWideInput.value ? `给 ${name} 发送消息，粘贴/拖拽文件，或输入 @ 引用工作区文件…` : `给 ${name} 发送消息`;
});

function focus() {
  editorRef.value?.focus();
}

defineExpose({
  insertFile,
  insertUploadingChip,
  resolveInlineUpload,
  failInlineUpload,
  focus,
});

onMounted(() => {
  if (typeof window !== "undefined") {
    smQuery = window.matchMedia("(min-width: 640px)");
    isWideInput.value = smQuery.matches;
    smQuery.addEventListener("change", onSmChange);
  }
  void nextTick(updateExpandState);
});

onBeforeUnmount(() => {
  smQuery?.removeEventListener("change", onSmChange);
});
</script>

<template>
  <div
    class="relative"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="fileInput"
      type="file"
      multiple
      :accept="ACCEPT_ATTR"
      class="sr-only"
      @change="onFileChange"
    />

    <span class="sr-only" role="status" aria-live="polite">{{ uploadStatusAnnouncement }}</span>

    <!-- @ Quick Mention Workspace File Popover -->
    <Transition
      enter-active-class="transition duration-120 ease-out"
      enter-from-class="translate-y-1 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="translate-y-1 opacity-0"
    >
      <div
        v-if="mentionOpen && mentionCandidates.length > 0"
        class="absolute bottom-full left-2 right-2 z-30 mb-2 max-w-md overflow-hidden rounded-2xl border border-line bg-canvas/98 p-1.5 shadow-xl backdrop-blur-md"
        role="listbox"
        aria-label="引用工作区文件"
      >
        <div class="px-2.5 py-1 text-[11px] font-medium text-fg-faint">
          引用工作区文件（↑↓ 选择，Enter 插入光标处）
        </div>
        <button
          v-for="(f, idx) in mentionCandidates"
          :key="f.id"
          type="button"
          role="option"
          :aria-selected="idx === mentionActiveIndex"
          class="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left transition-colors"
          :class="idx === mentionActiveIndex ? 'bg-accent-weak/80 text-fg' : 'text-fg hover:bg-hover'"
          @mousedown.prevent="selectMentionFile(f)"
          @mouseenter="mentionActiveIndex = idx"
        >
          <img
            v-if="fileThumbUrl(f)"
            :src="fileThumbUrl(f)!"
            :alt="f.filename"
            class="h-7 w-7 shrink-0 rounded-md bg-surface object-cover"
          />
          <span v-else class="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10px] font-medium text-fg-muted">
            {{ categoryLabel(f.category, f.ext) }}
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[12.5px] font-medium">{{ f.filename }}</span>
            <span v-if="f.conversation_title || f.qa_snippet" class="block truncate text-[11px] text-fg-faint">
              {{ f.conversation_title }}{{ f.qa_snippet ? ` · ${f.qa_snippet}` : "" }}
            </span>
          </span>
        </button>
      </div>
    </Transition>

    <div
      class="relative flex flex-col rounded-[24px] bg-surface p-2 shadow-sm transition-colors focus-within:bg-hover sm:rounded-[26px] sm:px-3.5 sm:pb-2.5 sm:pt-3"
      :class="isDragging ? (dragValid ? 'ring-2 ring-accent/60' : 'ring-2 ring-danger/70') : ''"
    >
      <!-- Uploading, attached file & selected skill chips -->
      <div v-if="hasChips" class="mb-2 flex flex-wrap items-center gap-1.5 px-1">
        <div
          v-for="u in uploads"
          :key="u.localId"
          class="flex max-w-[240px] flex-col gap-1 rounded-xl px-2.5 py-1.5 text-[12px]"
          :class="u.status === 'error' ? 'bg-danger-weak text-danger' : 'bg-canvas/85 text-fg'"
        >
          <div class="flex items-center gap-1.5">
            <img
              v-if="u.localPreviewUrl"
              :src="u.localPreviewUrl"
              :alt="u.filename"
              class="h-7 w-7 shrink-0 rounded-lg bg-surface object-cover"
            />
            <span v-else class="shrink-0 rounded bg-surface px-1 py-0.5 text-[10.5px] font-medium text-fg-muted">
              {{ categoryLabel(u.category, u.ext) }}
            </span>
            <span class="min-w-0 flex-1 truncate font-medium" :title="u.filename">{{ u.filename }}</span>
            <span class="inline-flex shrink-0 items-center gap-1 tabular-nums text-[11px] opacity-80">
              <Spinner v-if="u.status === 'signing' || u.status === 'completing'" :size="12" />
              {{ uploadLabel(u) }}
            </span>
            <button
              v-if="u.status === 'error'"
              type="button"
              class="focus-ring shrink-0 rounded px-1 py-0.5 text-[11px] font-medium text-danger underline hover:bg-danger/10"
              @click="emit('retry-upload', u.localId)"
            >
              重试
            </button>
            <button
              type="button"
              class="focus-ring flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              :aria-label="u.status === 'error' ? '关闭错误项' : '取消上传'"
              @click="u.status === 'error' ? emit('dismiss-upload', u.localId) : emit('cancel-upload', u.localId)"
            >
              <AppIcon name="close" class="h-3 w-3" :stroke-width="2.2" />
            </button>
          </div>
          <progress
            v-if="u.status !== 'error'"
            class="upload-progress h-1 w-full"
            :value="u.status === 'uploading' ? u.progress : undefined"
            max="100"
            :aria-label="`${u.filename} 上传进度`"
          />
          <p v-if="u.status === 'error' && u.error" class="truncate text-[11px]" :title="u.error">{{ u.error }}</p>
        </div>

        <template v-for="f in attachedFiles" :key="f.id">
          <!-- Image chip: pure image thumbnail without text clutter -->
          <div
            v-if="fileThumbUrl(f)"
            class="group/imgchip relative h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-canvas shadow-2xs"
            :title="f.filename"
          >
            <img
              :src="fileThumbUrl(f)!"
              :alt="f.filename"
              class="h-full w-full object-cover"
              @error="markThumbFailed(f.id)"
            />
            <button
              type="button"
              class="focus-ring absolute right-0.5 top-0.5 flex h-4.5 w-4.5 items-center justify-center rounded-full bg-black/65 text-white opacity-0 transition-opacity group-hover/imgchip:opacity-100 focus:opacity-100"
              aria-label="从本条消息移除图片"
              @click="emit('detach-file', f.id)"
            >
              <AppIcon name="close" class="h-2.5 w-2.5" :stroke-width="2.5" />
            </button>
          </div>

          <!-- Document / Code chip -->
          <div
            v-else
            class="inline-flex max-w-[240px] items-center gap-1.5 rounded-xl bg-canvas/85 px-2.5 py-1.5 text-[12px] text-fg"
            :title="`${f.filename} (${formatFileSize(f.size_bytes)})`"
          >
            <span class="shrink-0 rounded bg-surface px-1 py-0.5 text-[10.5px] font-medium text-fg-muted">
              {{ categoryLabel(f.category, f.ext) }}
            </span>
            <span class="min-w-0 flex-1 truncate font-medium">{{ f.filename }}</span>
            <span class="shrink-0 text-[11px] text-fg-faint">{{ formatFileSize(f.size_bytes) }}</span>
            <button
              type="button"
              class="focus-ring flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              aria-label="从本条消息移除标签（文件仍保留在工作区）"
              title="从本条消息移除标签（文件仍保留在工作区）"
              @click="emit('detach-file', f.id)"
            >
              <AppIcon name="close" class="h-3 w-3" :stroke-width="2.2" />
            </button>
          </div>
        </template>

        <div
          v-for="skillName in selectedSkills"
          :key="`skill-${skillName}`"
          class="inline-flex max-w-[220px] items-center gap-1.5 rounded-xl bg-accent-weak/85 px-2.5 py-1.5 text-[12px] text-fg"
          :title="`技能：${skillName}`"
        >
          <AppIcon name="sparkles" motion="enter-pop" class="h-3.5 w-3.5 shrink-0 text-accent" :stroke-width="1.95" />
          <span class="min-w-0 flex-1 truncate font-medium">{{ skillName }}</span>
          <button
            type="button"
            class="focus-ring flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
            :aria-label="`移除技能 ${skillName}`"
            title="移除技能"
            @click="removeSkill(skillName)"
          >
            <AppIcon name="close" class="h-3 w-3" :stroke-width="2.2" />
          </button>
        </div>
      </div>

      <!-- Mobile: single row [upload | editor | expand-above-send]; Desktop (sm+): 2 rows -->
      <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-end gap-x-1.5 sm:grid-cols-[1fr_auto] sm:grid-rows-[auto_auto] sm:gap-y-2">
        <!-- Rich Inline Contenteditable Editor -->
        <div class="relative col-start-2 row-start-1 flex min-w-0 items-center sm:col-span-2 sm:col-start-1 sm:row-start-1">
          <div
            ref="editorRef"
            v-scrollbar
            :contenteditable="disabled ? 'false' : 'true'"
            role="textbox"
            aria-multiline="true"
            :aria-label="inputPlaceholder"
            :data-placeholder="inputPlaceholder"
            class="whitz-rich-editor custom-scrollbar block w-full min-w-0 break-words bg-transparent px-1 py-1.5 text-[15px] leading-6 text-fg outline-none sm:py-0.5 sm:leading-relaxed"
            :class="{
              'is-expanded': expanded,
              'is-empty': !hasEditorContent,
              'cursor-not-allowed opacity-60': disabled,
            }"
            @input="onEditorInput"
            @keydown="onKeydown"
            @keyup="saveSelection"
            @mouseup="saveSelection"
            @blur="saveSelection"
            @click="onEditorClick"
            @paste="onPaste"
            @compositionstart="isComposing = true"
            @compositionend="isComposing = false; onEditorInput()"
          />
        </div>

        <!-- Left upload & skill buttons -->
        <div class="col-start-1 row-start-1 flex items-center gap-1 self-end sm:col-start-1 sm:row-start-2 sm:gap-1.5 sm:self-center">
          <button
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:gap-1.5 sm:px-2.5 sm:text-[13px] sm:font-medium"
            :disabled="disabled"
            aria-label="上传文件到对话工作区"
            :title="`上传文件到当前对话工作区（${SUPPORTED_TYPES_SUMMARY}）`"
            @click="openFilePicker"
          >
            <AppIcon name="paperclip" class="h-[18px] w-[18px]" :stroke-width="1.85" />
            <span class="hidden sm:inline">上传文件</span>
          </button>

          <button
            type="button"
            popovertarget="chat-skill-picker"
            class="skill-picker-anchor focus-ring relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:gap-1.5 sm:px-2.5 sm:text-[13px] sm:font-medium"
            :class="selectedSkills?.length ? 'bg-accent-weak/85 text-fg' : ''"
            :disabled="disabled"
            aria-label="选择技能"
            title="选择本轮对话附加技能"
          >
            <AppIcon name="sparkles" :active="Boolean(selectedSkills?.length)" class="h-[17px] w-[17px] shrink-0" :stroke-width="1.85" />
            <span class="hidden sm:inline">技能</span>
            <span
              v-if="selectedSkills?.length"
              class="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-fg tabular-nums sm:static"
            >
              {{ selectedSkills.length }}
            </span>
          </button>

          <button
            type="button"
            class="focus-ring flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-full px-2.5 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            :class="
              currentRagMode === 'files_only'
                ? 'bg-accent-weak/90 text-accent'
                : currentRagMode === 'off'
                  ? 'bg-canvas/70 text-fg-faint hover:bg-hover hover:text-fg'
                  : 'text-fg-muted hover:bg-hover hover:text-fg'
            "
            :disabled="disabled"
            :aria-label="currentRagMeta.title"
            :title="currentRagMeta.title"
            @click="cycleRagMode"
          >
            <Transition name="whitz-icon-swap" mode="out-in">
              <AppIcon
                v-if="currentRagMode === 'off'"
                key="rag-off"
                name="rag-off"
                class="h-[16px] w-[16px] shrink-0"
                :stroke-width="1.85"
              />
              <AppIcon
                v-else-if="currentRagMode === 'files_only'"
                key="rag-files"
                name="file-check"
                active
                class="h-[16px] w-[16px] shrink-0"
                :stroke-width="1.85"
              />
              <AppIcon
                v-else
                key="rag-auto"
                name="lightbulb"
                class="h-[16px] w-[16px] shrink-0"
                :stroke-width="1.85"
              />
            </Transition>
            <span class="hidden sm:inline">{{ currentRagMeta.label }}</span>
          </button>

          <span v-if="queuedSend && sendLockedByUpload" class="inline-flex items-center gap-1.5 text-[12px] text-accent">
            <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
            <span>等待上传完成自动发送…</span>
            <button type="button" class="underline hover:text-fg" @click="queuedSend = false">取消</button>
          </span>
          <span v-else-if="sendLockedByUpload" class="hidden text-[12px] text-fg-faint sm:inline">
            上传中，可点发送排队…
          </span>
        </div>

        <!-- Right actions -->
        <div class="col-start-3 row-start-1 flex flex-col items-center justify-end gap-1.5 self-stretch sm:col-start-2 sm:row-start-2 sm:flex-row sm:self-center">
          <Transition
            enter-active-class="transition duration-150 ease-out"
            enter-from-class="scale-75 opacity-0"
            enter-to-class="scale-100 opacity-100"
            leave-active-class="transition duration-100 ease-in"
            leave-from-class="scale-100 opacity-100"
            leave-to-class="scale-75 opacity-0"
          >
            <button
              v-if="canExpand || expanded"
              type="button"
              class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              :aria-label="expanded ? '收起输入框' : '展开输入框'"
              :title="expanded ? '收起输入框' : '加大输入框'"
              @click="toggleExpand"
            >
              <Transition name="whitz-icon-swap" mode="out-in">
                <AppIcon v-if="expanded" key="collapse" name="collapse-diagonal" class="h-4.5 w-4.5" :stroke-width="1.95" />
                <AppIcon v-else key="expand" name="expand-diagonal" class="h-4.5 w-4.5" :stroke-width="1.95" />
              </Transition>
            </button>
          </Transition>

          <button
            v-if="streaming"
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-canvas text-fg transition-colors hover:bg-hover disabled:cursor-wait disabled:opacity-75"
            :disabled="stopping"
            :aria-busy="stopping ? 'true' : undefined"
            :aria-label="stopping ? '正在停止生成' : '停止生成'"
            :title="stopping ? '正在停止…' : '停止生成'"
            @click="emit('stop')"
          >
            <Spinner v-if="stopping" :size="16" class="text-fg-muted" />
            <AppIcon v-else name="stop" class="h-3.5 w-3.5" />
          </button>
          <button
            v-else
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-fg transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-hover disabled:text-fg-faint"
            :disabled="!canSubmit"
            :aria-busy="sending || (queuedSend && sendLockedByUpload) ? 'true' : undefined"
            :aria-label="sending ? '正在发送' : queuedSend && sendLockedByUpload ? '等待上传完成后自动发送' : sendLockedByUpload ? '上传中，点击排队发送' : '发送'"
            :title="sending ? '发送中…' : queuedSend && sendLockedByUpload ? '已排队，上传完成后自动发送' : sendLockedByUpload ? '文件上传中，点击可排队自动发送' : '发送'"
            @click="submit"
          >
            <Spinner v-if="sending || (queuedSend && sendLockedByUpload) || sendLockedByUpload" :size="16" />
            <AppIcon v-else name="send" class="h-[18px] w-[18px]" :stroke-width="2.1" />
          </button>
        </div>
      </div>

      <!-- Full-area Drag Overlay -->
      <Transition
        enter-active-class="transition duration-150 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition duration-100 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="isDragging"
          class="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center rounded-[26px] border-2 border-dashed px-4 text-center backdrop-blur-[2px]"
          :class="
            dragValid
              ? 'border-accent bg-surface/92 text-fg'
              : 'border-danger bg-danger-weak/92 text-danger'
          "
        >
          <p class="text-[13.5px] font-medium">
            {{ dragValid ? "松开以上传到当前对话工作区" : "不支持的文件类型" }}
          </p>
          <p class="mt-0.5 max-w-md truncate text-[12px] opacity-80">
            {{ dragValid ? SUPPORTED_TYPES_SUMMARY : dragReason }}
          </p>
        </div>
      </Transition>
    </div>

    <SkillPickerPopover
      :selected-skills="selectedSkills ?? []"
      @update:selected-skills="emit('update:selectedSkills', $event)"
    />
  </div>
</template>
