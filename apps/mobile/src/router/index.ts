import { createRouter, createWebHashHistory } from "vue-router";

import ChatPage from "@/pages/chat/ChatPage.vue";
import HomePage from "@/pages/home/HomePage.vue";
import LoginPage from "@/pages/login/LoginPage.vue";
import AboutPage from "@/pages/settings/AboutPage.vue";
import AppearancePage from "@/pages/settings/AppearancePage.vue";
import ChatSettingsPage from "@/pages/settings/ChatSettingsPage.vue";
import CompanionProfilePage from "@/pages/settings/CompanionProfilePage.vue";
import NotificationPage from "@/pages/settings/NotificationPage.vue";
import PrivacyPage from "@/pages/settings/PrivacyPage.vue";
import SettingsPage from "@/pages/settings/SettingsPage.vue";
import SupportPage from "@/pages/settings/SupportPage.vue";
import ThemePage from "@/pages/settings/ThemePage.vue";
import VoicePage from "@/pages/voice/VoicePage.vue";
import { useWorkspaceStore } from "@/stores/workspace";

export const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", redirect: "/home" },
    { path: "/login", name: "login", component: LoginPage },
    { path: "/home", component: HomePage },
    { path: "/chat", component: ChatPage },
    { path: "/voice", component: VoicePage },
    { path: "/settings", component: SettingsPage },
    { path: "/settings/profile", component: CompanionProfilePage },
    { path: "/settings/appearance", component: AppearancePage },
    { path: "/settings/chat", component: ChatSettingsPage },
    { path: "/settings/notifications", component: NotificationPage },
    { path: "/settings/theme", component: ThemePage },
    { path: "/settings/privacy", component: PrivacyPage },
    { path: "/settings/about", component: AboutPage },
    { path: "/settings/support", component: SupportPage },
    { path: "/:pathMatch(.*)*", redirect: "/home" },
  ],
});

export function afterLogin(destination: unknown): string {
  if (typeof destination === "string" && destination.startsWith("/") && !destination.startsWith("//")) {
    const resolved = router.resolve(destination);
    if (resolved.matched.some((record) => record.components && !record.redirect) && resolved.name !== "login") {
      return resolved.fullPath;
    }
  }
  return "/home";
}

export function registrationSetupRoute(destination: unknown) {
  return { path: "/settings/profile", query: { setup: "1", next: afterLogin(destination) } };
}

router.beforeEach(async (to) => {
  const workspace = useWorkspaceStore();
  await workspace.ensure();
  if (workspace.phase !== "ready" && to.name !== "login") {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (workspace.phase === "ready" && workspace.customizeAfterRegistration && to.query.setup !== "1") {
    return registrationSetupRoute(to.name === "login" ? to.query.redirect : to.fullPath);
  }
  if (workspace.phase === "ready" && to.name === "login") return afterLogin(to.query.redirect);
});
