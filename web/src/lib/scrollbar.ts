import type { Directive } from "vue";

const timers = new WeakMap<HTMLElement, number>();
const handlers = new WeakMap<HTMLElement, () => void>();

export const vScrollbar: Directive<HTMLElement> = {
  mounted(el) {
    const onScroll = () => {
      el.classList.add("is-scrolling");
      const prev = timers.get(el);
      if (prev) window.clearTimeout(prev);
      timers.set(
        el,
        window.setTimeout(() => {
          el.classList.remove("is-scrolling");
          timers.delete(el);
        }, 900),
      );
    };
    handlers.set(el, onScroll);
    el.addEventListener("scroll", onScroll, { passive: true });
  },
  unmounted(el) {
    const onScroll = handlers.get(el);
    if (onScroll) el.removeEventListener("scroll", onScroll);
    const timer = timers.get(el);
    if (timer) window.clearTimeout(timer);
    handlers.delete(el);
    timers.delete(el);
  },
};
