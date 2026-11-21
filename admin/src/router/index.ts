import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "../stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("../views/LoginView.vue"),
      meta: { guestOnly: true },
    },
    {
      path: "/",
      component: () => import("../components/AdminLayout.vue"),
      meta: { requiresAuth: true },
      children: [
        { path: "", name: "overview", component: () => import("../views/OverviewView.vue") },
        { path: "ops", name: "ops", component: () => import("../views/OpsDashboardView.vue") },
        { path: "quant", name: "quant", component: () => import("../views/QuantDashboardView.vue") },
        { path: "automation", name: "automation", component: () => import("../views/AutomationDashboardView.vue") },
        { path: "users", name: "users", component: () => import("../views/UsersView.vue") },
        {
          path: "invite-codes",
          name: "invite-codes",
          component: () => import("../views/InviteCodesView.vue"),
        },
        { path: "audit", name: "audit", component: () => import("../views/AuditView.vue") },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.guestOnly && auth.isAuthenticated) {
    return { name: "overview" };
  }
  return true;
});

export default router;
