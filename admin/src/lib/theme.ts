import { ref } from "vue";

export type Theme = "light" | "dark";

const KEY = "whitz_theme";

function initial(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

const theme = ref<Theme>(initial());

function apply(t: Theme) {
  document.documentElement.classList.toggle("dark", t === "dark");
}

apply(theme.value);

export function useTheme() {
  function set(t: Theme) {
    theme.value = t;
    apply(t);
    try {
      localStorage.setItem(KEY, t);
    } catch {
      /* ignore */
    }
  }

  function toggle() {
    set(theme.value === "dark" ? "light" : "dark");
  }

  return { theme, set, toggle };
}
