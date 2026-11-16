import { ref } from "vue";

export type Theme = "light" | "dark";
export type ThemePreference = "system" | "light" | "dark";

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
}

apply(preference.value);

if (typeof window !== "undefined") {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", () => {
    if (preference.value === "system") {
      apply("system");
    }
  });
}

export function useTheme() {
  function set(next: ThemePreference) {
    preference.value = next;
    apply(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* ignore */
    }
  }

  function toggle() {
    set(theme.value === "dark" ? "light" : "dark");
  }

  return { theme, preference, set, toggle };
}
