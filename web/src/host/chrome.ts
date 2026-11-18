import { readonly, ref } from "vue";

/**
 * Registry for the back affordance shown by the desktop title bar.
 * Web builds never render a title bar, but the registry is harmless there and
 * keeps the shared views free of desktop-only imports.
 */
export interface ChromeBackAction {
  label: string;
  run: () => void;
}

interface ChromeBackEntry extends ChromeBackAction {
  id: number;
}

const state = ref<ChromeBackEntry | null>(null);
let sequence = 0;

export const chromeBack = readonly(state);

/** Register the current page's back action and return a token for cleanup. */
export function setChromeBack(action: ChromeBackAction): number {
  const id = ++sequence;
  state.value = { ...action, id };
  return id;
}

/** Clear only when the caller still owns the visible action. */
export function clearChromeBack(token?: number): void {
  if (token === undefined || state.value?.id === token) {
    state.value = null;
  }
}

export function isDesktopShell(): boolean {
  return typeof document !== "undefined" && document.documentElement.classList.contains("desktop-shell");
}
