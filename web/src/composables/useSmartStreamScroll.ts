import { onBeforeUnmount, ref, watch, type Ref } from "vue";

export interface SmartStreamScrollOptions {
  /** Re-engage auto-follow when user manually scrolls down within this distance of bottom (px). */
  reEngageThresholdPx?: number;
  /** Show the floating "Scroll to bottom" button once distance exceeds this value (px). */
  jumpShowThresholdPx?: number;
  /** Hide the floating "Scroll to bottom" button once distance falls below this value (px). */
  jumpHideThresholdPx?: number;
}

const UPWARD_KEYS = new Set(["ArrowUp", "PageUp", "Home"]);

/**
 * Gesture-first smart streaming scroll controller for Vue scroll containers.
 *
 * - Immediately disengages `autoFollow` on ANY upward user intent (wheel up, touch drag down,
 *   scrollbar drag up, or PageUp/ArrowUp/Home).
 * - Never swallows user scroll events with fragile timeout windows; uses synchronous write guards
 *   around rAF-paced programmatic `scrollTop` steps.
 * - Uses native `scrollend` (with debounced fallback) to re-engage `autoFollow` ONLY when the user
 *   actively scrolled downward back within `reEngageThresholdPx` of the bottom.
 */
export function useSmartStreamScroll(
  containerRef: Ref<HTMLElement | null>,
  options: SmartStreamScrollOptions = {},
) {
  const reEngageThresholdPx = options.reEngageThresholdPx ?? 48;
  const jumpShowThresholdPx = options.jumpShowThresholdPx ?? 84;
  const jumpHideThresholdPx = options.jumpHideThresholdPx ?? 36;

  const autoFollow = ref(true);
  const showJumpToBottom = ref(false);
  const isUserInteracting = ref(false);

  let isProgrammaticWrite = false;
  let lastScrollTop = 0;
  let lastTouchY: number | null = null;
  let lastUserDir: "up" | "down" | null = null;
  let chaseRafId: number | null = null;
  let scrollEndFallbackTimer: ReturnType<typeof setTimeout> | null = null;
  let boundEl: HTMLElement | null = null;

  const supportsScrollEnd = typeof window !== "undefined" && "onscrollend" in window;

  function distanceFromBottom(el: HTMLElement): number {
    return Math.max(0, el.scrollHeight - el.scrollTop - el.clientHeight);
  }

  function updateJumpVisibility(el: HTMLElement) {
    const dist = distanceFromBottom(el);
    if (showJumpToBottom.value) {
      if (dist <= jumpHideThresholdPx) showJumpToBottom.value = false;
    } else {
      if (dist > jumpShowThresholdPx) showJumpToBottom.value = true;
    }
  }

  function stopChase() {
    if (chaseRafId !== null) {
      cancelAnimationFrame(chaseRafId);
      chaseRafId = null;
    }
  }

  function writeScrollTop(el: HTMLElement, nextTop: number) {
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight);
    const clamped = Math.max(0, Math.min(maxTop, nextTop));
    isProgrammaticWrite = true;
    el.scrollTop = clamped;
    lastScrollTop = el.scrollTop;
    isProgrammaticWrite = false;
    updateJumpVisibility(el);
  }

  function disengage() {
    autoFollow.value = false;
    lastUserDir = "up";
    stopChase();
  }

  function onScrollSettled() {
    const el = boundEl;
    if (!el) return;
    updateJumpVisibility(el);
    if (!isUserInteracting.value && !autoFollow.value && lastUserDir === "down") {
      if (distanceFromBottom(el) <= reEngageThresholdPx) {
        autoFollow.value = true;
      }
    }
    lastUserDir = null;
  }

  function onScroll() {
    const el = boundEl;
    if (!el) return;
    if (isProgrammaticWrite) return;

    const currentTop = el.scrollTop;
    const delta = currentTop - lastScrollTop;
    lastScrollTop = currentTop;

    if (delta < -1.5) {
      // User moved upward (wheel, scrollbar thumb drag, trackpad, keyboard, etc.)
      disengage();
    } else if (delta > 1.5) {
      lastUserDir = "down";
    }

    updateJumpVisibility(el);

    if (!supportsScrollEnd) {
      if (scrollEndFallbackTimer !== null) clearTimeout(scrollEndFallbackTimer);
      scrollEndFallbackTimer = setTimeout(() => {
        scrollEndFallbackTimer = null;
        onScrollSettled();
      }, 100);
    }
  }

  function onWheel(e: WheelEvent) {
    if (e.deltaY < -1) {
      disengage();
    } else if (e.deltaY > 1) {
      lastUserDir = "down";
    }
  }

  function onTouchStart(e: TouchEvent) {
    isUserInteracting.value = true;
    stopChase();
    lastTouchY = e.touches[0]?.clientY ?? null;
  }

  function onTouchMove(e: TouchEvent) {
    const y = e.touches[0]?.clientY;
    if (y === undefined) return;
    if (lastTouchY !== null) {
      const dy = y - lastTouchY;
      // Dragging finger DOWN scrolls content UP toward older messages
      if (dy > 2) {
        disengage();
      } else if (dy < -2) {
        lastUserDir = "down";
      }
    }
    lastTouchY = y;
  }

  function onTouchEnd() {
    isUserInteracting.value = false;
    lastTouchY = null;
    if (autoFollow.value) {
      followBottomSmooth();
    }
  }

  function onPointerDown(e: PointerEvent) {
    // Detect scrollbar thumb dragging or holding pointer on touch/pen
    if (e.pointerType === "touch") {
      isUserInteracting.value = true;
      stopChase();
      return;
    }
    const el = boundEl;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const onVerticalScrollbar = e.clientX >= rect.left + el.clientWidth;
    if (onVerticalScrollbar) {
      isUserInteracting.value = true;
      stopChase();
    }
  }

  function onPointerUp() {
    if (!isUserInteracting.value) return;
    isUserInteracting.value = false;
    if (autoFollow.value) {
      followBottomSmooth();
    } else {
      onScrollSettled();
    }
  }

  function onKeyDown(e: KeyboardEvent) {
    if (UPWARD_KEYS.has(e.key)) {
      disengage();
    }
  }

  function followBottomSmooth() {
    const el = boundEl;
    if (!el || !autoFollow.value || isUserInteracting.value) return;
    if (chaseRafId !== null) return;

    const step = () => {
      chaseRafId = null;
      const target = boundEl;
      if (!target || !autoFollow.value || isUserInteracting.value) return;
      const dist = distanceFromBottom(target);
      if (dist <= 1) {
        if (dist > 0) writeScrollTop(target, target.scrollHeight);
        return;
      }
      // Large jump (e.g., big single chunk or newly rendered card): settle quickly
      if (dist > 900) {
        writeScrollTop(target, target.scrollHeight);
        return;
      }
      const delta = dist <= 2 ? dist : Math.max(dist * 0.34, 2.5);
      writeScrollTop(target, target.scrollTop + Math.min(dist, delta));
      if (distanceFromBottom(target) > 0.5 && autoFollow.value && !isUserInteracting.value) {
        chaseRafId = requestAnimationFrame(step);
      }
    };

    chaseRafId = requestAnimationFrame(step);
  }

  function jumpToBottom(behavior: "instant" | "smooth" = "smooth") {
    const el = boundEl;
    autoFollow.value = true;
    lastUserDir = null;
    stopChase();
    if (!el) return;
    if (behavior === "instant") {
      writeScrollTop(el, el.scrollHeight);
      showJumpToBottom.value = false;
      return;
    }
    const dist = distanceFromBottom(el);
    if (dist <= 2) {
      showJumpToBottom.value = false;
      return;
    }
    // Smooth rAF ease-out scroll (immune to browser smooth-scroll cancellation quirks)
    const startTop = el.scrollTop;
    const startDist = dist;
    const duration = Math.min(340, Math.max(160, Math.round(startDist * 0.18)));
    const startTime = performance.now();

    const animate = (now: number) => {
      chaseRafId = null;
      const target = boundEl;
      if (!target || !autoFollow.value || isUserInteracting.value) return;
      const t = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const maxTop = Math.max(0, target.scrollHeight - target.clientHeight);
      const nextTop = startTop + (maxTop - startTop) * eased;
      writeScrollTop(target, nextTop);
      if (t < 1) {
        chaseRafId = requestAnimationFrame(animate);
      } else {
        writeScrollTop(target, target.scrollHeight);
        showJumpToBottom.value = false;
      }
    };
    chaseRafId = requestAnimationFrame(animate);
  }

  function scrollToTopPosition(targetScrollTop: number) {
    const el = boundEl;
    if (!el) return;
    stopChase();
    writeScrollTop(el, targetScrollTop);
  }

  function bind(el: HTMLElement | null) {
    if (boundEl) {
      boundEl.removeEventListener("scroll", onScroll);
      boundEl.removeEventListener("wheel", onWheel);
      boundEl.removeEventListener("touchstart", onTouchStart);
      boundEl.removeEventListener("touchmove", onTouchMove);
      boundEl.removeEventListener("touchend", onTouchEnd);
      boundEl.removeEventListener("touchcancel", onTouchEnd);
      boundEl.removeEventListener("pointerdown", onPointerDown);
      boundEl.removeEventListener("keydown", onKeyDown);
      if (supportsScrollEnd) {
        boundEl.removeEventListener("scrollend", onScrollSettled);
      }
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    }
    boundEl = el;
    if (boundEl) {
      lastScrollTop = boundEl.scrollTop;
      boundEl.addEventListener("scroll", onScroll, { passive: true });
      boundEl.addEventListener("wheel", onWheel, { passive: true });
      boundEl.addEventListener("touchstart", onTouchStart, { passive: true });
      boundEl.addEventListener("touchmove", onTouchMove, { passive: true });
      boundEl.addEventListener("touchend", onTouchEnd, { passive: true });
      boundEl.addEventListener("touchcancel", onTouchEnd, { passive: true });
      boundEl.addEventListener("pointerdown", onPointerDown, { passive: true });
      boundEl.addEventListener("keydown", onKeyDown);
      if (supportsScrollEnd) {
        boundEl.addEventListener("scrollend", onScrollSettled, { passive: true });
      }
      window.addEventListener("pointerup", onPointerUp, { passive: true });
      window.addEventListener("pointercancel", onPointerUp, { passive: true });
      updateJumpVisibility(boundEl);
    }
  }

  watch(containerRef, (el) => bind(el), { immediate: true });

  onBeforeUnmount(() => {
    stopChase();
    if (scrollEndFallbackTimer !== null) {
      clearTimeout(scrollEndFallbackTimer);
      scrollEndFallbackTimer = null;
    }
    bind(null);
  });

  return {
    autoFollow,
    showJumpToBottom,
    isUserInteracting,
    distanceFromBottom: () => (boundEl ? distanceFromBottom(boundEl) : 0),
    followBottomSmooth,
    jumpToBottom,
    scrollToTopPosition,
    disengage,
    syncVisibility: () => {
      if (boundEl) updateJumpVisibility(boundEl);
    },
  };
}
