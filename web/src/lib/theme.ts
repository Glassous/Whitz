import { ref } from "vue";

export type Theme = "light" | "dark";
export type ThemePreference = "system" | "light" | "dark";
export type ThemeTransitionOrigin = "bottom-left" | "top-left";

const KEY = "whitz_theme";

function readPreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "system" || saved === "light" || saved === "dark") return saved;
    return "system";
  } catch {
    return "system";
  }
}

function systemTheme(): Theme {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

function resolveTheme(pref: ThemePreference): Theme {
  return pref === "system" ? systemTheme() : pref;
}

const preference = ref<ThemePreference>(readPreference());
const theme = ref<Theme>(resolveTheme(preference.value));

function apply(pref: ThemePreference) {
  const resolved = resolveTheme(pref);
  theme.value = resolved;
  document.documentElement.classList.toggle("dark", resolved === "dark");
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta) {
    meta.setAttribute("content", pref === "system" ? "light dark" : pref);
  }
}

apply(preference.value);

if (typeof window !== "undefined") {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", () => {
    if (preference.value === "system") {
      apply("system");
    }
  });
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) {
      const next = readPreference();
      preference.value = next;
      apply(next);
    }
  });
}

export function useTheme() {
  function persistPreference(next: ThemePreference) {
    try {
      if (next === "system") {
        localStorage.removeItem(KEY);
      } else {
        localStorage.setItem(KEY, next);
      }
    } catch {
      /* ignore */
    }
  }

  function set(next: ThemePreference, origin: ThemeTransitionOrigin = "bottom-left") {
    const prevResolved = theme.value;
    const nextResolved = resolveTheme(next);
    preference.value = next;
    persistPreference(next);

    const reduceMotion =
      typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (
      prevResolved === nextResolved ||
      reduceMotion ||
      typeof document === "undefined" ||
      !("startViewTransition" in document)
    ) {
      apply(next);
      return;
    }

    const x = 0;
    const y = origin === "top-left" ? 0 : window.innerHeight;
    const endRadius = Math.hypot(window.innerWidth, window.innerHeight);

    const transition = (
      document as Document & { startViewTransition: (cb: () => void) => { ready: Promise<void> } }
    ).startViewTransition(() => {
      apply(next);
    });

    void transition.ready.then(() => {
      document.documentElement.animate(
        {
          clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${endRadius}px at ${x}px ${y}px)`],
        },
        {
          duration: 460,
          easing: "cubic-bezier(0.22, 1, 0.36, 1)",
          pseudoElement: "::view-transition-new(root)",
        },
      );
    });
  }

  function toggle(origin: ThemeTransitionOrigin = "bottom-left") {
    set(theme.value === "dark" ? "light" : "dark", origin);
  }

  return { theme, preference, set, toggle };
}
