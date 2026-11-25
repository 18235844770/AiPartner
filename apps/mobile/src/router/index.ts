import { createRouter, createWebHistory } from "vue-router";

import ChatPage from "@/pages/chat/ChatPage.vue";
import HomePage from "@/pages/home/HomePage.vue";
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

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/home" },
    { path: "/login", redirect: "/home" },
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
  ],
});
