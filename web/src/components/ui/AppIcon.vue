<script setup lang="ts">
import { computed } from "vue";

export type IconName =
  | "chat"
  | "search"
  | "book"
  | "clock"
  | "panel-left"
  | "panel-right"
  | "menu-lines"
  | "close"
  | "plus"
  | "minus"
  | "pin"
  | "more-horizontal"
  | "edit"
  | "trash"
  | "monitor"
  | "sun"
  | "moon"
  | "settings"
  | "chevron-right"
  | "chevron-left"
  | "chevron-down"
  | "sparkles"
  | "paperclip"
  | "lightbulb"
  | "file-check"
  | "rag-off"
  | "expand-diagonal"
  | "collapse-diagonal"
  | "stop"
  | "send"
  | "copy"
  | "check"
  | "check-circle"
  | "refresh"
  | "download"
  | "smile"
  | "file-text"
  | "file-upload"
  | "message-locate"
  | "message-dots"
  | "message-plus"
  | "external-link"
  | "maximize"
  | "minimize"
  | "camera"
  | "wrench"
  | "database"
  | "alert-triangle"
  | "alert-circle"
  | "eye"
  | "eye-off"
  | "user"
  | "folder"
  | "crown"
  | "shield"
  | "logout"
  | "smartphone"
  | "tablet"
  | "globe";

export type IconMotion =
  | "auto"
  | "none"
  | "pop"
  | "lift"
  | "right"
  | "left"
  | "down"
  | "up-right"
  | "plus"
  | "close"
  | "spin-nudge"
  | "gear"
  | "tilt-left"
  | "expand"
  | "chevron-r"
  | "chevron-d"
  | "check-draw"
  | "enter-pop"
  | "search-focus"
  | "folder"
  | "chat"
  | "search"
  | "book"
  | "clock"
  | "sparkle"
  | "shield"
  | "crown"
  | "user"
  | "wrench"
  | "message-plus"
  | "screen"
  | "sun"
  | "moon"
  | "trash"
  | "download"
  | "logout"
  | "copy"
  | "edit"
  | "bulb"
  | "file"
  | "panel-l"
  | "panel-r"
  | "menu"
  | "camera"
  | "database"
  | "eye"
  | "send"
  | "smile";

const AUTO_MOTION_MAP: Record<IconName, Exclude<IconMotion, "auto">> = {
  chat: "chat",
  search: "search",
  book: "book",
  clock: "clock",
  "panel-left": "panel-l",
  "panel-right": "panel-r",
  "menu-lines": "menu",
  close: "close",
  plus: "plus",
  minus: "pop",
  pin: "tilt-left",
  "more-horizontal": "pop",
  edit: "edit",
  trash: "trash",
  monitor: "screen",
  sun: "sun",
  moon: "moon",
  settings: "gear",
  "chevron-right": "right",
  "chevron-left": "left",
  "chevron-down": "down",
  sparkles: "sparkle",
  paperclip: "tilt-left",
  lightbulb: "bulb",
  "file-check": "file",
  "rag-off": "pop",
  "expand-diagonal": "expand",
  "collapse-diagonal": "expand",
  stop: "pop",
  send: "send",
  copy: "copy",
  check: "check-draw",
  "check-circle": "enter-pop",
  refresh: "spin-nudge",
  download: "download",
  smile: "smile",
  "file-text": "file",
  "file-upload": "enter-pop",
  "message-locate": "lift",
  "message-dots": "enter-pop",
  "message-plus": "message-plus",
  "external-link": "up-right",
  maximize: "expand",
  minimize: "expand",
  camera: "camera",
  wrench: "wrench",
  database: "database",
  "alert-triangle": "enter-pop",
  "alert-circle": "enter-pop",
  eye: "eye",
  "eye-off": "eye",
  user: "user",
  folder: "folder",
  crown: "crown",
  shield: "shield",
  logout: "logout",
  smartphone: "screen",
  tablet: "screen",
  globe: "pop",
};

const props = withDefaults(
  defineProps<{
    name: IconName;
    motion?: IconMotion;
    active?: boolean;
    strokeWidth?: number;
  }>(),
  {
    motion: "auto",
    active: false,
    strokeWidth: 1.85,
  },
);

const resolvedMotion = computed(() =>
  props.motion === "auto" ? AUTO_MOTION_MAP[props.name] : props.motion,
);

const motionClass = computed(() => [
  "icon-m",
  `icon-m-${resolvedMotion.value}`,
  props.active ? "is-active" : "",
]);
</script>

<template>
  <svg
    :class="motionClass"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- Chat Bubble: 3 typing dots wave in on hover -->
    <template v-if="name === 'chat'">
      <path
        class="icon-duotone-fill"
        d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3.5 20.5l1.4-5.2a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z"
      />
      <path
        d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3.5 20.5l1.4-5.2a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z"
      />
      <circle class="icon-bloom" cx="9" cy="11.5" r="1.05" fill="currentColor" stroke="none" />
      <circle class="icon-bloom icon-d1" cx="12.5" cy="11.5" r="1.05" fill="currentColor" stroke="none" />
      <circle class="icon-bloom icon-d2" cx="16" cy="11.5" r="1.05" fill="currentColor" stroke="none" />
    </template>

    <!-- Search Magnifier: lens glint arc grows in on hover/focus -->
    <template v-else-if="name === 'search'">
      <circle class="icon-duotone-fill" cx="11" cy="11" r="7" />
      <circle cx="11" cy="11" r="7" />
      <path class="icon-grow" pathLength="1" d="M7.6 10.6A3.6 3.6 0 0 1 10.8 7.5" />
      <path d="M20 20l-3.8-3.8" />
    </template>

    <!-- Book (长期记忆 / 引用): inner lines re-draw & bookmark ribbon grows -->
    <template v-else-if="name === 'book'">
      <path class="icon-duotone-fill" d="M6.5 2.5H19.5V17H6.5A2.5 2.5 0 0 0 4 19.5V5A2.5 2.5 0 0 1 6.5 2.5Z" />
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H19.5" />
      <path d="M6.5 2.5H19.5V21.5H6.5A2.5 2.5 0 0 1 4 19V5A2.5 2.5 0 0 1 6.5 2.5Z" />
      <path class="icon-redraw" pathLength="1" d="M8.5 7.5h6.5" />
      <path class="icon-redraw icon-d1" pathLength="1" d="M8.5 11.5h4.5" />
      <path class="icon-grow icon-d1" pathLength="1" d="M15 2.5v4.5l1.5-1.1L18 7V2.5" />
    </template>

    <!-- Folder (资料库): front flap dips, inner file sheet rises & lines grow -->
    <template v-else-if="name === 'folder'">
      <!-- Back body -->
      <path class="icon-duotone-fill" d="M3 7a2 2 0 0 1 2-2h4.2l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
      <path d="M3 9V7a2 2 0 0 1 2-2h4.2l2 2H19a2 2 0 0 1 2 2v1" />
      <!-- Rising inner document sheet with growing lines -->
      <g class="icon-part-sheet">
        <path class="icon-grow" pathLength="1" d="M7.5 11.5V6.5a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v5" />
        <path class="icon-grow icon-d1" pathLength="1" d="M10 8.4h4" />
        <path class="icon-grow icon-d2" pathLength="1" d="M10 10.8h2.8" />
      </g>
      <!-- Front flap -->
      <g class="icon-part icon-part-flap">
        <path d="M3 9.5h18v7.5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9.5Z" />
      </g>
    </template>

    <!-- Clock (定时任务): two-hand tick + top-right pulse arc grows -->
    <template v-else-if="name === 'clock'">
      <circle class="icon-duotone-fill" cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="9" />
      <path class="icon-grow" pathLength="1" d="M17.5 3.4A10.2 10.2 0 0 1 20.6 6.5" />
      <g class="icon-part icon-part-hour">
        <path d="M12 12l3.1 1.9" />
      </g>
      <g class="icon-part icon-part-min">
        <path d="M12 7v5" />
      </g>
    </template>

    <!-- Panel Left (Sidebar Collapse) -->
    <template v-else-if="name === 'panel-left'">
      <g class="icon-part icon-part-bar">
        <rect class="icon-duotone-fill" x="3.5" y="4.5" width="5.5" height="15" rx="1.5" />
        <path d="M9 4.5v15" />
      </g>
      <rect x="3" y="4" width="18" height="16" rx="3" />
    </template>

    <!-- Panel Right (Task Panel Toggle) -->
    <template v-else-if="name === 'panel-right'">
      <g class="icon-part icon-part-bar">
        <rect class="icon-duotone-fill" x="15" y="4.5" width="5.5" height="15" rx="1.5" />
        <path d="M15 4.5v15" />
      </g>
      <rect x="3" y="4" width="18" height="16" rx="3" />
    </template>

    <!-- Menu Lines (Sidebar Toggle): bottom bar extends smoothly -->
    <template v-else-if="name === 'menu-lines'">
      <path d="M4 8.5h16" />
      <g class="icon-part icon-part-bar">
        <path d="M4 15.5h10.5" />
      </g>
      <path class="icon-grow" pathLength="1" d="M14.5 15.5h5.5" />
    </template>

    <!-- Close (X) -->
    <template v-else-if="name === 'close'">
      <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
    </template>

    <!-- Plus (+) -->
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>

    <!-- Minus (-) -->
    <template v-else-if="name === 'minus'">
      <path d="M5 12h14" />
    </template>

    <!-- Pin -->
    <template v-else-if="name === 'pin'">
      <path
        class="icon-duotone-fill"
        d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1v3.76Z"
      />
      <path
        d="M12 17v5M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1v3.76Z"
      />
    </template>

    <!-- More Horizontal (...) -->
    <template v-else-if="name === 'more-horizontal'">
      <circle cx="5.5" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="18.5" cy="12" r="1.5" fill="currentColor" stroke="none" />
    </template>

    <!-- Edit / Pencil: pen tilts & writing line grows inside -->
    <template v-else-if="name === 'edit'">
      <path class="icon-duotone-fill" d="M5 6a2 2 0 0 1 2-2h4.5L19 11.5V18a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6Z" />
      <path d="M11 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5" />
      <path class="icon-grow icon-d1" pathLength="1" d="M8.5 16.8h6.5" />
      <g class="icon-part icon-part-pen">
        <path d="M18.3 2.7a2.12 2.12 0 0 1 3 3L12.5 14.5l-4 1 1-4 8.8-8.8Z" />
      </g>
    </template>

    <!-- Trash: lid swings open & bin subtly shifts -->
    <template v-else-if="name === 'trash'">
      <g class="icon-part icon-part-lid">
        <path d="M4 6.5h16M9 6.5V4.8A1.3 1.3 0 0 1 10.3 3.5h3.4A1.3 1.3 0 0 1 15 4.8v1.7" />
      </g>
      <g class="icon-part icon-part-bin">
        <path class="icon-duotone-fill" d="M6.2 7h11.6l-.9 12.2a2 2 0 0 1-2 1.8H9.1a2 2 0 0 1-2-1.8L6.2 7Z" />
        <path d="M6.2 6.5l.9 12.7a2 2 0 0 0 2 1.8h5.8a2 2 0 0 0 2-1.8l.9-12.7" />
        <path d="M10.2 11v5.5M13.8 11v5.5" />
      </g>
    </template>

    <!-- Monitor / Desktop / System Theme: screen UI lines grow in -->
    <template v-else-if="name === 'monitor'">
      <rect class="icon-duotone-fill" x="3" y="4" width="18" height="12" rx="2.5" />
      <rect x="3" y="4" width="18" height="12" rx="2.5" />
      <path class="icon-grow" pathLength="1" d="M7 8.5h5.5" />
      <path class="icon-grow icon-d1" pathLength="1" d="M7 11.8h9.5" />
      <path d="M8 20h8M12 16v4" />
    </template>

    <!-- Sun (Light Theme) -->
    <template v-else-if="name === 'sun'">
      <g class="icon-part icon-part-core">
        <circle class="icon-duotone-fill" cx="12" cy="12" r="4.2" />
        <circle cx="12" cy="12" r="4.2" />
      </g>
      <g class="icon-part icon-part-rays">
        <path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </g>
    </template>

    <!-- Moon (Dark Theme): rocks gently & 2 stars bloom beside crescent -->
    <template v-else-if="name === 'moon'">
      <g class="icon-part icon-part-crescent">
        <path class="icon-duotone-fill" d="M20.5 13.2A8.5 8.5 0 1 1 10.8 3.5a6.8 6.8 0 0 0 9.7 9.7Z" />
        <path d="M20.5 13.2A8.5 8.5 0 1 1 10.8 3.5a6.8 6.8 0 0 0 9.7 9.7Z" />
      </g>
      <circle class="icon-bloom" cx="18.2" cy="5.5" r="1.15" fill="currentColor" stroke="none" />
      <circle class="icon-bloom icon-d1" cx="21" cy="8.4" r="0.8" fill="currentColor" stroke="none" />
    </template>

    <!-- Settings Gear -->
    <template v-else-if="name === 'settings'">
      <circle class="icon-duotone-fill" cx="12" cy="12" r="3.2" />
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1.08 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
    </template>

    <!-- Chevrons -->
    <template v-else-if="name === 'chevron-right'">
      <path d="M9.5 6.5L15 12l-5.5 5.5" />
    </template>

    <template v-else-if="name === 'chevron-left'">
      <path d="M14.5 6.5L9 12l5.5 5.5" />
    </template>

    <template v-else-if="name === 'chevron-down'">
      <path d="M6.5 9.5L12 15l5.5-5.5" />
    </template>

    <!-- Sparkles (AI / Skills): 3rd hidden mini-star blooms on hover -->
    <template v-else-if="name === 'sparkles'">
      <g class="icon-part icon-part-main">
        <path class="icon-duotone-fill" d="M12 3l1.75 4.75L18.5 9.5l-4.75 1.75L12 16l-1.75-4.75L5.5 9.5l4.75-1.75L12 3Z" />
        <path d="M12 3l1.75 4.75L18.5 9.5l-4.75 1.75L12 16l-1.75-4.75L5.5 9.5l4.75-1.75L12 3Z" />
      </g>
      <g class="icon-part icon-part-sub">
        <path d="M18.8 15.2l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z" />
      </g>
      <path class="icon-bloom icon-d1" d="M5.2 16.6l.55 1.45 1.45.55-1.45.55-.55 1.45-.55-1.45-1.45-.55 1.45-.55.55-1.45Z" fill="currentColor" stroke="none" />
    </template>

    <!-- Paperclip (Upload) -->
    <template v-else-if="name === 'paperclip'">
      <path d="M21 11.2l-8.3 8.3a5.25 5.25 0 0 1-7.42-7.42l8.3-8.3a3.5 3.5 0 1 1 4.95 4.95l-8.3 8.3a1.75 1.75 0 0 1-2.48-2.48l7.5-7.5" />
    </template>

    <!-- Lightbulb (RAG Auto / Memory): 3 light rays grow outward on hover -->
    <template v-else-if="name === 'lightbulb'">
      <path class="icon-duotone-fill" d="M12 4.2a6 6 0 0 0-3.5 10.9v1.7a1.2 1.2 0 0 0 1.2 1.2h4.6a1.2 1.2 0 0 0 1.2-1.2v-1.7A6 6 0 0 0 12 4.2Z" />
      <path d="M12 4.2a6 6 0 0 0-3.5 10.9v1.7a1.2 1.2 0 0 0 1.2 1.2h4.6a1.2 1.2 0 0 0 1.2-1.2v-1.7A6 6 0 0 0 12 4.2ZM9.4 21h5.2" />
      <path class="icon-grow" pathLength="1" d="M12 1.4v1.4" />
      <path class="icon-grow icon-d1" pathLength="1" d="M4.2 5.2l1.2 1" />
      <path class="icon-grow icon-d1" pathLength="1" d="M19.8 5.2l-1.2 1" />
    </template>

    <!-- File Check (RAG Files Only): checkmark re-draws on hover -->
    <template v-else-if="name === 'file-check'">
      <path class="icon-duotone-fill" d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8L14 2.5Z" />
      <path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8L14 2.5Z" />
      <path d="M14 2.5V8h5.5" />
      <path class="icon-redraw" pathLength="1" d="M9.2 14.5l1.8 1.8 3.8-3.8" />
    </template>

    <!-- RAG Off -->
    <template v-else-if="name === 'rag-off'">
      <path d="M3 3l18 18M10.6 10.6a3 3 0 0 0 4.24 4.24M9.5 4.2A7 7 0 0 1 18 11c0 1.4-.4 2.7-1.1 3.8M6.1 6.1A7 7 0 0 0 4 11a7 7 0 0 0 9.9 6.4" />
    </template>

    <!-- Expand / Collapse Diagonal -->
    <template v-else-if="name === 'expand-diagonal'">
      <path d="M15 3.5h5.5V9M9 20.5H3.5V15M20.5 3.5L14 10M3.5 20.5L10 14" />
    </template>

    <template v-else-if="name === 'collapse-diagonal'">
      <path d="M4 14h6v6M20 10h-6V4M14 10l6.5-6.5M10 14l-6.5 6.5" />
    </template>

    <!-- Stop -->
    <template v-else-if="name === 'stop'">
      <rect x="6" y="6" width="12" height="12" rx="3" fill="currentColor" stroke="none" />
    </template>

    <!-- Send Arrow: shaft re-draws & arrow glides -->
    <template v-else-if="name === 'send'">
      <path class="icon-redraw" pathLength="1" d="M5 12h14" />
      <path d="M13 6l6 6-6 6" />
    </template>

    <!-- Copy: front sheet glides & 2 mini lines grow inside -->
    <template v-else-if="name === 'copy'">
      <path d="M5.5 15H4.8A1.8 1.8 0 0 1 3 13.2V4.8A1.8 1.8 0 0 1 4.8 3h8.4A1.8 1.8 0 0 1 15 4.8v.7" />
      <g class="icon-part icon-part-front">
        <rect class="icon-duotone-fill" x="9" y="9" width="11.5" height="11.5" rx="2.5" />
        <rect x="9" y="9" width="11.5" height="11.5" rx="2.5" />
        <path class="icon-grow" pathLength="1" d="M12.2 13.2h5.2" />
        <path class="icon-grow icon-d1" pathLength="1" d="M12.2 16.2h3.4" />
      </g>
    </template>

    <!-- Check -->
    <template v-else-if="name === 'check'">
      <path class="icon-check-path" d="M5 12.8l4.4 4.4L19 7.5" />
    </template>

    <!-- Check Circle -->
    <template v-else-if="name === 'check-circle'">
      <circle class="icon-duotone-fill" cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="9" />
      <path class="icon-check-path" d="M8.5 12.5l2.3 2.3 4.7-5" />
    </template>

    <!-- Refresh / Regenerate -->
    <template v-else-if="name === 'refresh'">
      <path d="M3.5 12a8.5 8.5 0 0 1 14.5-6l2.5 2.3M20.5 3.8v4.5H16M20.5 12a8.5 8.5 0 0 1-14.5 6L3.5 15.7M3.5 20.2v-4.5H8" />
    </template>

    <!-- Download: arrow drops into tray & tray re-draws -->
    <template v-else-if="name === 'download'">
      <g class="icon-part icon-part-arrow">
        <path d="M12 3.5v11m0 0l-4-4m4 4l4-4" />
      </g>
      <path class="icon-redraw" pathLength="1" d="M4 17v1.5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V17" />
    </template>

    <!-- Smile (Reaction) -->
    <template v-else-if="name === 'smile'">
      <circle class="icon-duotone-fill" cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="9" />
      <g class="icon-part icon-part-mouth">
        <path d="M8.6 14.4s1.3 2 3.4 2 3.4-2 3.4-2" />
      </g>
      <circle cx="9.2" cy="9.8" r="0.85" fill="currentColor" stroke="none" />
      <circle cx="14.8" cy="9.8" r="0.85" fill="currentColor" stroke="none" />
    </template>

    <!-- File Text: text lines re-draw on hover -->
    <template v-else-if="name === 'file-text'">
      <path class="icon-duotone-fill" d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8L14 2.5Z" />
      <path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8L14 2.5Z" />
      <path d="M14 2.5V8h5.5" />
      <path class="icon-redraw" pathLength="1" d="M8.5 13h7" />
      <path class="icon-redraw icon-d1" pathLength="1" d="M8.5 16.5h4.5" />
    </template>

    <!-- File Upload (Empty State) -->
    <template v-else-if="name === 'file-upload'">
      <path class="icon-duotone-fill" d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8L14 2.5Z" />
      <path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8L14 2.5Z" />
      <path d="M14 2.5V8h5.5M12 18v-6m0 0l-2.5 2.5M12 12l2.5 2.5" />
    </template>

    <!-- Message Locate -->
    <template v-else-if="name === 'message-locate'">
      <path class="icon-duotone-fill" d="M20.5 14.8a2.2 2.2 0 0 1-2.2 2.2H7.5l-4 3.5V5.7a2.2 2.2 0 0 1 2.2-2.2h12.6a2.2 2.2 0 0 1 2.2 2.2v9.1Z" />
      <path d="M20.5 14.8a2.2 2.2 0 0 1-2.2 2.2H7.5l-4 3.5V5.7a2.2 2.2 0 0 1 2.2-2.2h12.6a2.2 2.2 0 0 1 2.2 2.2v9.1Z" />
    </template>

    <!-- Message Dots (Clarify) -->
    <template v-else-if="name === 'message-dots'">
      <path class="icon-duotone-fill" d="M20.5 12a8 8 0 0 1-11.5 7.2L4 20l1-5.1A8 8 0 1 1 20.5 12Z" />
      <path d="M20.5 12a8 8 0 0 1-11.5 7.2L4 20l1-5.1A8 8 0 1 1 20.5 12Z" />
      <circle cx="9" cy="12" r="0.85" fill="currentColor" stroke="none" />
      <circle cx="12.5" cy="12" r="0.85" fill="currentColor" stroke="none" />
      <circle cx="16" cy="12" r="0.85" fill="currentColor" stroke="none" />
    </template>

    <!-- Message Plus (Feedback): inner + spins 90deg on hover -->
    <template v-else-if="name === 'message-plus'">
      <path class="icon-duotone-fill" d="M20.5 14.8a2.2 2.2 0 0 1-2.2 2.2H7.5l-4 3.5V5.7a2.2 2.2 0 0 1 2.2-2.2h12.6a2.2 2.2 0 0 1 2.2 2.2v9.1Z" />
      <path d="M20.5 14.8a2.2 2.2 0 0 1-2.2 2.2H7.5l-4 3.5V5.7a2.2 2.2 0 0 1 2.2-2.2h12.6a2.2 2.2 0 0 1 2.2 2.2v9.1Z" />
      <g class="icon-part icon-part-plus" style="transform-origin: 12px 10.2px">
        <path d="M9.4 10.2h5.2M12 7.6v5.2" />
      </g>
    </template>

    <!-- External Link -->
    <template v-else-if="name === 'external-link'">
      <path d="M14.5 3.5h6v6M10.5 13.5l10-10M20.5 14v4.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2H10" />
    </template>

    <!-- Maximize / Minimize (Fullscreen) -->
    <template v-else-if="name === 'maximize'">
      <path d="M8 3.5H5.5a2 2 0 0 0-2 2V8M20.5 8V5.5a2 2 0 0 0-2-2H16M16 20.5h2.5a2 2 0 0 0 2-2V16M3.5 16v2.5a2 2 0 0 0 2 2H8" />
    </template>

    <template v-else-if="name === 'minimize'">
      <path d="M8.5 3.5V6a2.5 2.5 0 0 1-2.5 2.5H3.5M20.5 8.5H18A2.5 2.5 0 0 1 15.5 6V3.5M15.5 20.5V18a2.5 2.5 0 0 1 2.5-2.5h2.5M3.5 15.5H6A2.5 2.5 0 0 1 8.5 18v2.5" />
    </template>

    <!-- Camera: lens zooms & flash dot blooms -->
    <template v-else-if="name === 'camera'">
      <path class="icon-duotone-fill" d="M3 9a2.5 2.5 0 0 1 2.5-2.5h1.3a2 2 0 0 0 1.7-.95l.45-.75a1.2 1.2 0 0 1 1.03-.5h4.04a1.2 1.2 0 0 1 1.03.5l.45.75a2 2 0 0 0 1.7.95h1.3A2.5 2.5 0 0 1 21 9v7.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5V9Z" />
      <path d="M3 9a2.5 2.5 0 0 1 2.5-2.5h1.3a2 2 0 0 0 1.7-.95l.45-.75a1.2 1.2 0 0 1 1.03-.5h4.04a1.2 1.2 0 0 1 1.03.5l.45.75a2 2 0 0 0 1.7.95h1.3A2.5 2.5 0 0 1 21 9v7.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5V9Z" />
      <g class="icon-part icon-part-lens" style="transform-origin: 12px 12.6px">
        <circle cx="12" cy="12.6" r="3.3" />
      </g>
      <circle class="icon-bloom" cx="17.8" cy="9.4" r="0.95" fill="currentColor" stroke="none" />
    </template>

    <!-- Wrench (Tools / Skills): twists & spark lines grow -->
    <template v-else-if="name === 'wrench'">
      <g class="icon-part icon-part-tool">
        <path class="icon-duotone-fill" d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.55-3.55a5.8 5.8 0 0 1-7.72 7.72l-6.68 6.68a2.12 2.12 0 0 1-3-3l6.68-6.68a5.8 5.8 0 0 1 7.72-7.72L14.7 6.3Z" />
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.55-3.55a5.8 5.8 0 0 1-7.72 7.72l-6.68 6.68a2.12 2.12 0 0 1-3-3l6.68-6.68a5.8 5.8 0 0 1 7.72-7.72L14.7 6.3Z" />
      </g>
      <path class="icon-grow" pathLength="1" d="M5 5l2 2" />
      <path class="icon-grow icon-d1" pathLength="1" d="M8.5 3.2v2.2" />
    </template>

    <!-- Database (Memory State): rings breathe apart -->
    <template v-else-if="name === 'database'">
      <g class="icon-part icon-part-top">
        <ellipse class="icon-duotone-fill" cx="12" cy="6.8" rx="8.5" ry="3.6" />
        <path d="M3.5 6.8c0 2 3.8 3.6 8.5 3.6s8.5-1.6 8.5-3.6c0-2-3.8-3.6-8.5-3.6S3.5 4.8 3.5 6.8Z" />
      </g>
      <path d="M3.5 6.8v10.4c0 2 3.8 3.6 8.5 3.6s8.5-1.6 8.5-3.6V6.8" />
      <g class="icon-part icon-part-mid">
        <path d="M3.5 12c0 2 3.8 3.6 8.5 3.6s8.5-1.6 8.5-3.6" />
      </g>
    </template>

    <!-- Alert Triangle -->
    <template v-else-if="name === 'alert-triangle'">
      <path class="icon-duotone-fill" d="M10.3 3.9L2 18a2 2 0 0 0 1.7 3h16.6A2 2 0 0 0 22 18L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <path d="M10.3 3.9L2 18a2 2 0 0 0 1.7 3h16.6A2 2 0 0 0 22 18L13.7 3.9a2 2 0 0 0-3.4 0ZM12 9.2v4.3M12 17h.01" />
    </template>

    <!-- Alert Circle -->
    <template v-else-if="name === 'alert-circle'">
      <circle class="icon-duotone-fill" cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4.5M12 16.2h.01" />
    </template>

    <!-- Eye / Eye Off -->
    <template v-else-if="name === 'eye'">
      <path class="icon-duotone-fill" d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z" />
      <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z" />
      <g class="icon-part icon-part-pupil">
        <circle cx="12" cy="12" r="2.8" />
      </g>
    </template>

    <template v-else-if="name === 'eye-off'">
      <path class="icon-redraw" pathLength="1" d="M3 3l18 18" />
      <path d="M10.6 5.9A10.8 10.8 0 0 1 12 5.8c6 0 9.5 6.2 9.5 6.2a17 17 0 0 1-3.2 3.9M6.5 7.4A17.3 17.3 0 0 0 2.5 12S6 18.2 12 18.2c1.6 0 3-.5 4.3-1.2M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </template>

    <!-- User Profile: head nods/lifts & shoulders re-draw -->
    <template v-else-if="name === 'user'">
      <g class="icon-part icon-part-head" style="transform-origin: 12px 8px">
        <circle class="icon-duotone-fill" cx="12" cy="8" r="3.8" />
        <circle cx="12" cy="8" r="3.8" />
      </g>
      <path class="icon-redraw" pathLength="1" d="M4.5 20c0-3.4 3.4-5.8 7.5-5.8s7.5 2.4 7.5 5.8" />
    </template>

    <!-- Crown (Membership): lifts, band grows & 3 jewels bloom -->
    <template v-else-if="name === 'crown'">
      <path class="icon-duotone-fill" d="M3.5 8.5l4 3 4.5-6 4.5 6 4-3-1.8 10.5H5.3L3.5 8.5Z" />
      <path d="M3.5 8.5l4 3 4.5-6 4.5 6 4-3-1.8 10.5H5.3L3.5 8.5Z" />
      <path class="icon-grow" pathLength="1" d="M6.5 15.8h11" />
      <circle class="icon-bloom" cx="12" cy="3.1" r="1.05" fill="currentColor" stroke="none" />
      <circle class="icon-bloom icon-d1" cx="3.5" cy="6.2" r="0.85" fill="currentColor" stroke="none" />
      <circle class="icon-bloom icon-d1" cx="20.5" cy="6.2" r="0.85" fill="currentColor" stroke="none" />
    </template>

    <!-- Shield (Admin): verification checkmark grows inside -->
    <template v-else-if="name === 'shield'">
      <path class="icon-duotone-fill" d="M12 3.2l7 3.8v5c0 4.4-3 8.2-7 9-4-.8-7-4.6-7-9V7l7-3.8Z" />
      <path d="M12 3.2l7 3.8v5c0 4.4-3 8.2-7 9-4-.8-7-4.6-7-9V7l7-3.8Z" />
      <path class="icon-grow" pathLength="1" d="M9 12.2l2.1 2.1 4-4.2" />
    </template>

    <!-- Logout -->
    <template v-else-if="name === 'logout'">
      <path d="M9.5 20.5H5.5a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2h4" />
      <g class="icon-part icon-part-arrow">
        <path d="M16 16.5l4.5-4.5L16 7.5M20.5 12H9.5" />
      </g>
    </template>

    <!-- Smartphone: inner screen lines grow -->
    <template v-else-if="name === 'smartphone'">
      <rect class="icon-duotone-fill" x="7" y="2.8" width="10" height="18.4" rx="2.4" />
      <rect x="7" y="2.8" width="10" height="18.4" rx="2.4" />
      <path class="icon-grow" pathLength="1" d="M10 8.5h4" />
      <path class="icon-grow icon-d1" pathLength="1" d="M10 11.5h3" />
      <path d="M11 18h2" />
    </template>

    <!-- Tablet: inner screen lines grow -->
    <template v-else-if="name === 'tablet'">
      <rect class="icon-duotone-fill" x="4.5" y="3" width="15" height="18" rx="2.4" />
      <rect x="4.5" y="3" width="15" height="18" rx="2.4" />
      <path class="icon-grow" pathLength="1" d="M8.5 8.5h7" />
      <path class="icon-grow icon-d1" pathLength="1" d="M8.5 11.8h4.5" />
      <path d="M11 17.8h2" />
    </template>

    <!-- Globe (Unknown Device) -->
    <template v-else-if="name === 'globe'">
      <circle class="icon-duotone-fill" cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="9" />
      <path d="M3.5 9h17M3.5 15h17M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </template>
  </svg>
</template>
