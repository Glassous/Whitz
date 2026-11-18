import "./styles.css";
import "highlight.js/styles/github-dark.css";

function applyTheme() {
  try {
    const saved = localStorage.getItem("whitz_theme");
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute("content", saved === "light" || saved === "dark" ? saved : "light dark");
    const dark =
      saved === "dark" ||
      ((!saved || saved === "system") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
  } catch {
    /* ignore */
  }
}

window.addEventListener("error", (event) => {
  console.error("[renderer]", event.error?.stack ?? event.message);
});
window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason as { stack?: string; message?: string } | undefined;
  console.error("[renderer:promise]", reason?.stack ?? reason?.message ?? String(event.reason));
});
import { createWebHashHistory } from "vue-router";
import { bootstrapApp } from "@web/bootstrap";
import { setHost } from "@web/host";
import DesktopApp from "./DesktopApp.vue";
import { desktopRoutes } from "./router";
import { createDesktopHost } from "./host/desktopHost";
import { useDesktopStore } from "./stores/desktop";
import { useRuntimeStore } from "./stores/runtime";
import { useWorkStore } from "./stores/work";

async function start() {
  document.documentElement.classList.add("desktop-shell");
  applyTheme();
  const api = window.whitzDesktop;
  if (!api) {
    document.body.innerHTML = "<div style='padding:24px;font-family:system-ui'>桌面桥接加载失败，请重新安装 Whitz。</div>";
    return;
  }
  const info = await api.info();
  setHost(createDesktopHost(info.apiBase));

  await bootstrapApp({
    root: DesktopApp,
    routes: desktopRoutes,
    history: createWebHashHistory(),
    authenticatedHome: { name: "chat" },
    onAuthRequired: ({ fullPath }) => ({ name: "chat-gate", query: { redirect: fullPath } }),
    extraGuards: [
      (to) => {
        const desktop = useDesktopStore();
        if ((to.name === "chat" || to.name === "chat-conversation") && !desktop.online) {
          return { name: "chat-gate", query: { redirect: to.fullPath, offline: "1" } };
        }
        return true;
      },
    ],
    initialRoute: "/",
    beforeMount: async () => {
      const desktop = useDesktopStore();
      await desktop.init();
      const runtime = useRuntimeStore();
      await runtime.init();
      const work = useWorkStore();
      work.bindEvents();
      await work.loadList();
    },
  });
}

void start();
