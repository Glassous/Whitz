import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "../stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: () => import("../views/LoginView.vue"), meta: { guestOnly: true } },
    { path: "/register", name: "register", component: () => import("../views/RegisterView.vue"), meta: { guestOnly: true } },
    { path: "/forgot", name: "forgot", component: () => import("../views/ForgotPasswordView.vue"), meta: { guestOnly: true } },
    { path: "/", name: "chat", component: () => import("../views/ChatView.vue"), meta: { requiresAuth: true } },
    { path: "/settings", name: "settings", component: () => import("../views/SettingsView.vue"), meta: { requiresAuth: true } },
    { path: "/admin", name: "admin", component: () => import("../views/AdminView.vue"), meta: { requiresAuth: true, adminOnly: true } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.adminOnly && !auth.isAdmin) {
    return { name: "chat" };
  }
  if (to.meta.guestOnly && auth.isAuthenticated) {
    return { name: "chat" };
  }
  return true;
});

export default router;