import { createApp, type Component } from "vue";
import { createPinia } from "pinia";
import type { RouteRecordRaw, RouterHistory } from "vue-router";
import App from "./App.vue";
import { createAppRouter, type CreateRouterOptions } from "./router";
import { setUnauthorizedHandler } from "./api/client";
import { useAuthStore } from "./stores/auth";
import { vScrollbar } from "./lib/scrollbar";

export interface BootstrapOptions {
  root?: Component;
  routes?: RouteRecordRaw[];
  history?: RouterHistory;
  authenticatedHome?: CreateRouterOptions["authenticatedHome"];
  onAuthRequired?: CreateRouterOptions["onAuthRequired"];
  extraGuards?: CreateRouterOptions["extraGuards"];
  /** Runs after auth resolution and router readiness, before mount. */
  beforeMount?: () => void | Promise<void>;
  /** Selects the initial route when none is present in the URL. */
  initialRoute?: string;
}

export async function bootstrapApp(options: BootstrapOptions = {}): Promise<void> {
  const app = createApp(options.root ?? App);
  const pinia = createPinia();
  app.use(pinia);
  app.directive("scrollbar", vScrollbar);
  app.config.errorHandler = (err, _instance, info) => {
    console.error("[vue:error]", info, err instanceof Error ? err.stack ?? err.message : String(err));
  };

  const auth = useAuthStore();
  await auth.init();

  const router = createAppRouter({
    history: options.history,
    routes: options.routes,
    authenticatedHome: options.authenticatedHome,
    onAuthRequired: options.onAuthRequired,
    extraGuards: options.extraGuards,
  });
  app.use(router);

  setUnauthorizedHandler(() => {
    const store = useAuthStore();
    store.forceLogout("expired");
    if (router.currentRoute.value.name !== "login") {
      const currentPath = router.currentRoute.value.fullPath;
      void router.push({
        name: "login",
        query: currentPath && currentPath !== "/" ? { redirect: currentPath } : undefined,
      });
    }
  });

  if (typeof window !== "undefined") {
    window.addEventListener("storage", (event) => {
      void useAuthStore().handleStorageSync(event, {
        onLoggedOut: () => {
          if (router.currentRoute.value.meta.requiresAuth) {
            void router.push({ name: "login" });
          }
        },
        onLoggedIn: () => {
          if (router.currentRoute.value.meta.guestOnly) {
            void router.push({ name: "chat" });
          }
        },
      });
    });
  }

  if (options.initialRoute && !window.location.hash && window.location.pathname === "/") {
    void router.replace(options.initialRoute);
  }

  await router.isReady();
  await options.beforeMount?.();
  app.mount("#app");
}
