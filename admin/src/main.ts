import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { setUnauthorizedHandler } from "./api/client";
import { useAuthStore } from "./stores/auth";
import "./styles/main.css";

async function bootstrap() {
  const app = createApp(App);
  const pinia = createPinia();
  app.use(pinia);

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
