import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { setUnauthorizedHandler } from "./api/client";
import { useAuthStore } from "./stores/auth";
import { vScrollbar } from "./lib/scrollbar";
import "./styles/main.css";
import "highlight.js/styles/github-dark.css";

async function bootstrap() {
  const app = createApp(App);
  const pinia = createPinia();
  app.use(pinia);
  app.directive("scrollbar", vScrollbar);

  // Resolve the session before the router performs its first navigation so
  // route guards see a fresh user, not stale localStorage.
  const auth = useAuthStore();
  await auth.init();

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

  app.use(router);
  await router.isReady();
  app.mount("#app");
}

void bootstrap();
