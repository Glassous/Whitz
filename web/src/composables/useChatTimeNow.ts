import { onBeforeUnmount, onMounted, ref } from "vue";

/**
 * Reactive current-time ticker (refreshes every minute and on tab visibility)
 * so relative day labels ("昨天", "星期X") stay accurate across midnight.
 */
export function useChatTimeNow() {
  const nowMs = ref(Date.now());
  let timer: ReturnType<typeof setInterval> | null = null;

  function refresh() {
    nowMs.value = Date.now();
  }

  function onVisibilityChange() {
    if (typeof document !== "undefined" && document.visibilityState === "visible") {
      refresh();
    }
  }

  onMounted(() => {
    refresh();
    timer = setInterval(refresh, 60_000);
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibilityChange);
    }
  });

  onBeforeUnmount(() => {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    if (typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", onVisibilityChange);
    }
  });

  return nowMs;
}
