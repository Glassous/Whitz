import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { setUnauthorizedHandler } from "./api/client";
import { useAuthStore } from "./stores/auth";
import "./styles/main.css";
import "highlight.js/styles/github-dark.css";

async function bootstrap() {
  const app = createApp(App);
  const pinia = createPinia();
  app.use(pinia);

  // Resolve the session before the router performs its first navigation so
  // route guards (adminOnly / requiresAuth) see a fresh user, not stale localStorage.
  const auth = useAuthStore();
  await auth.init();

  setUnauthorizedHandler(() => {
    useAuthStore().forceLogout();
    void router.push({ name: "login" });
  });

  app.use(router);
  await router.isReady();
  app.mount("#app");
}

void bootstrap();
