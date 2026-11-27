<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { assets } from "@/assets/slices";
import Avatar from "@/components/avatar/Avatar.vue";
import AppButton from "@/components/common/AppButton.vue";
import AppTabBar from "@/components/layout/AppTabBar.vue";
import ScreenFrame from "@/components/layout/ScreenFrame.vue";
import { useDialogueStore } from "@/stores/dialogue";
import { useWorkspaceStore } from "@/stores/workspace";
import { useThemeStore } from "@/stores/theme";
import { midnightState } from "@/themes/midnight";
import { errorText } from "@/services/http";

interface SettingsItem {
  id: string;
  label: string;
  icon: string;
  to: string;
}

interface SettingsSection {
  id: string;
  title: string;
  items: SettingsItem[];
}

const router = useRouter();
const theme = useThemeStore();
const workspace = useWorkspaceStore();
const dialogue = useDialogueStore();
const signingOut = ref(false);
const logoutError = ref("");

async function signOut(): Promise<void> {
  signingOut.value = true;
  logoutError.value = "";
  try { await workspace.signOut(); }
  catch (caught) { logoutError.value = errorText(caught); }
  finally { signingOut.value = false; }
}

const settings = {
  profile: { id: "profile", label: "角色资料", icon: assets.profile, to: "/settings/profile" },
  appearance: { id: "appearance", label: "外观偏好", icon: assets.palette, to: "/settings/appearance" },
  chat: { id: "chat-settings", label: "聊天设置", icon: assets.chatSettings, to: "/settings/chat" },
  notifications: { id: "notifications", label: "通知设置", icon: assets.bell, to: "/settings/notifications" },
  theme: { id: "theme", label: "外观设置", icon: assets.moon, to: "/settings/theme" },
  privacy: { id: "privacy", label: "数据与隐私", icon: assets.privacy, to: "/settings/privacy" },
  about: { id: "about", label: "关于我们", icon: assets.info, to: "/settings/about" },
  support: { id: "support", label: "帮助与支持", icon: assets.support, to: "/settings/support" },
} satisfies Record<string, SettingsItem>;

const sections: SettingsSection[] = [
  { id: "companion", title: "陪伴者", items: [settings.profile, settings.appearance] },
  { id: "chat", title: "聊天体验", items: [settings.chat, settings.notifications] },
  { id: "app", title: "应用", items: [settings.theme, settings.privacy] },
  { id: "other", title: "其他", items: [settings.about, settings.support] },
];

</script>

<template>
  <ScreenFrame page="settings">
    <section class="settings" :class="{ midnight: theme.midnight }">
      <div class="scroll">
        <img v-if="!theme.midnight" class="mint" :src="assets.mintBlob" alt="" />
        <img v-if="!theme.midnight" class="rays" :src="assets.raysMint" alt="" />
        <h1>设置</h1>

        <button class="profile" type="button" @click="router.push('/settings/profile')">
          <span class="avatar-wrap">
            <Avatar :expression="dialogue.expression" :width="84" :motion="false"
              :midnight-state="theme.midnight ? midnightState(dialogue.emotion) : undefined" />
            <img v-if="!theme.midnight" class="crown" :src="assets.crown" alt="" />
          </span>
          <span class="profile-copy">
            <span class="name">
              {{ workspace.companion?.name ?? "遇见" }}
              <img class="chevron" :src="assets.chevron" alt="" />
            </span>
            <span v-if="workspace.companion?.description" class="line">
              {{ workspace.companion.description }}
            </span>
          </span>
        </button>

        <section v-for="section in sections" :key="section.id" class="group">
          <h2>{{ section.title }}</h2>
          <div class="card">
            <button v-for="item in section.items" :key="item.id" class="row" type="button" @click="router.push(item.to)">
              <img class="row-icon" :src="item.icon" alt="" />
              <span>{{ item.label }}</span>
              <img class="chevron" :src="assets.chevron" alt="" />
            </button>
          </div>
        </section>
        <section class="group">
          <p v-if="logoutError" class="page-error" role="alert">{{ logoutError }}</p>
          <AppButton variant="secondary" :loading="signingOut" @click="signOut">退出登录</AppButton>
        </section>
      </div>
      <AppTabBar />
    </section>
  </ScreenFrame>
</template>

<style scoped>
.settings {
  position: relative;
  height: 100%;
  background: #f6f4fb;
}

.scroll {
  position: relative;
  height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  padding: calc(env(safe-area-inset-top) + 22px) 20px calc(136px + env(safe-area-inset-bottom));
}

.mint,
.rays {
  position: absolute;
  height: auto;
  pointer-events: none;
}

.mint {
  width: 150px;
  right: -36px;
  top: 8px;
}

.rays {
  width: 46px;
  right: 28px;
  top: calc(env(safe-area-inset-top) + 18px);
}

h1 {
  position: relative;
  font-size: 28px;
  font-weight: 800;
}

.profile {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  margin-top: 18px;
  padding: 16px;
  border-radius: 24px;
  background: #fff;
  box-shadow: var(--shadow-card);
  text-align: left;
}

.avatar-wrap {
  position: relative;
  flex: none;
  display: grid;
  place-items: center;
  aspect-ratio: 1;
  width: 84px;
}

.crown {
  position: absolute;
  width: 34px;
  top: -6px;
  right: -4px;
}

.profile-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 18px;
  font-weight: 700;
}

.line {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #9b90c8;
  font-size: var(--font-size-sm);
  line-height: 1.45;
}


.group {
  margin-top: 18px;
}

h2 {
  margin: 0 4px 8px;
  color: #9a96a8;
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.card {
  border-radius: 22px;
  background: #fff;
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-height: 58px;
  padding: 0 16px;
  text-align: left;
  font-size: 15px;
}

.row + .row {
  box-shadow: inset 0 1px 0 var(--color-border);
}

.row:active,
.profile:active {
  background: #faf8ff;
}

.row span {
  flex: 1;
}

.row-icon {
  width: 32px;
  height: 32px;
  object-fit: contain;
}

.chevron {
  width: 16px;
  height: 16px;
  object-fit: contain;
  flex: none;
}

.settings.midnight { background: transparent; }
.midnight .scroll { z-index: 10; }
.midnight .profile,
.midnight .card {
  background: var(--theme-surface);
  box-shadow: inset 0 0 0 1px var(--theme-border);
}

.midnight h2,
.midnight .line {
  color: var(--theme-text-muted);
}

.midnight .row:active,
.midnight .profile:active {
  background: var(--theme-surface-raised);
}

.midnight .chevron,
.midnight .card .row-icon {
  filter: grayscale(1) sepia(0.25);
}
</style>
