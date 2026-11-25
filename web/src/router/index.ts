import {
  createRouter,
  createWebHistory,
  type NavigationGuard,
  type RouteLocationRaw,
  type RouteRecordRaw,
  type RouterHistory,
} from "vue-router";
import { useAuthStore } from "../stores/auth";

export const appRoutes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: () => import("../views/LoginView.vue"), meta: { guestOnly: true } },
  { path: "/register", name: "register", component: () => import("../views/RegisterView.vue"), meta: { guestOnly: true } },
  { path: "/forgot", name: "forgot", component: () => import("../views/ForgotPasswordView.vue"), meta: { guestOnly: true } },
  {
    path: "/",
    component: () => import("../layouts/AppShellLayout.vue"),
    meta: { requiresAuth: true },
    children: [
      { path: "", name: "chat", component: () => import("../views/ChatView.vue") },
      { path: "c/:id", name: "chat-conversation", component: () => import("../views/ChatView.vue") },
      { path: "posts", name: "posts", component: () => import("../views/PostsView.vue") },
      { path: "posts/guide", name: "posts-guide", component: () => import("../views/PostsGuideView.vue") },
      { path: "library", name: "library", component: () => import("../views/LibraryView.vue") },
      { path: "schedules", name: "schedules", component: () => import("../views/SchedulesView.vue") },
    ],
  },
  { path: "/settings", name: "settings", component: () => import("../views/SettingsView.vue"), meta: { requiresAuth: true } },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

export interface CreateRouterOptions {
  history?: RouterHistory;
  routes?: RouteRecordRaw[];
  authenticatedHome?: RouteLocationRaw;
  onAuthRequired?: (to: { fullPath: string }) => RouteLocationRaw;
  extraGuards?: NavigationGuard[];
}

export function createAppRouter(options: CreateRouterOptions = {}) {
  const router = createRouter({
    history: options.history ?? createWebHistory(),
    routes: options.routes ?? appRoutes,
  });

  router.beforeEach((to) => {
    const auth = useAuthStore();
    if (to.meta.requiresAuth && !auth.isAuthenticated) {
      if (options.onAuthRequired) return options.onAuthRequired({ fullPath: to.fullPath });
      return { name: "login", query: { redirect: to.fullPath } };
    }
    if (to.meta.guestOnly && auth.isAuthenticated) {
      const rawRedirect = typeof to.query.redirect === "string" ? to.query.redirect : "";
      if (rawRedirect.startsWith("/") && !rawRedirect.startsWith("//")) {
        return rawRedirect;
      }
      return options.authenticatedHome ?? { name: "chat" };
    }
    return true;
  });

  for (const guard of options.extraGuards ?? []) {
    router.beforeEach(guard);
  }

  return router;
}

const router = createAppRouter();

export default router;
