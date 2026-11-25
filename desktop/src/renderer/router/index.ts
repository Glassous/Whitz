import type { RouteRecordRaw } from "vue-router";
import { createWebHashHistory } from "vue-router";
import { createAppRouter } from "@web/router";
import { useAuthStore } from "@web/stores/auth";
import AppShellLayout from "@web/layouts/AppShellLayout.vue";
import ChatView from "@web/views/ChatView.vue";
import PostsView from "@web/views/PostsView.vue";
import PostsGuideView from "@web/views/PostsGuideView.vue";
import LibraryView from "@web/views/LibraryView.vue";
import SchedulesView from "@web/views/SchedulesView.vue";
import LoginView from "@web/views/LoginView.vue";
import RegisterView from "@web/views/RegisterView.vue";
import ForgotPasswordView from "@web/views/ForgotPasswordView.vue";
import SettingsView from "@web/views/SettingsView.vue";
import WorkView from "../views/WorkView.vue";
import WorkSetupView from "../views/WorkSetupView.vue";
import WorkSettingsView from "../views/WorkSettingsView.vue";
import ChatGateView from "../views/ChatGateView.vue";

export const desktopRoutes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: LoginView, meta: { guestOnly: true } },
  { path: "/register", name: "register", component: RegisterView, meta: { guestOnly: true } },
  { path: "/forgot", name: "forgot", component: ForgotPasswordView, meta: { guestOnly: true } },
  {
    path: "/",
    name: "home",
    redirect: () => (useAuthStore().isAuthenticated ? { name: "chat" } : { name: "work" }),
  },
  {
    path: "/",
    component: AppShellLayout,
    meta: { requiresAuth: true },
    children: [
      { path: "chat", name: "chat", component: ChatView },
      { path: "c/:id", name: "chat-conversation", component: ChatView },
      { path: "posts", name: "posts", component: PostsView },
      { path: "posts/guide", name: "posts-guide", component: PostsGuideView },
      { path: "library", name: "library", component: LibraryView },
      { path: "schedules", name: "schedules", component: SchedulesView },
    ],
  },
  { path: "/chat-gate", name: "chat-gate", component: ChatGateView },
  { path: "/work", name: "work", component: WorkView },
  { path: "/work/setup", name: "work-setup", component: WorkSetupView },
  { path: "/work/settings", name: "work-settings", component: WorkSettingsView },
  { path: "/settings", name: "settings", component: SettingsView, meta: { requiresAuth: true } },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

export function createDesktopRouter() {
  return createAppRouter({
    history: createWebHashHistory(),
    routes: desktopRoutes,
    authenticatedHome: { name: "chat" },
    onAuthRequired: ({ fullPath }) => ({ name: "chat-gate", query: { redirect: fullPath } }),
  });
}
