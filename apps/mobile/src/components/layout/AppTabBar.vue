<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

import { assets } from "@/assets/slices";
import { useThemeStore } from "@/stores/theme";
import { midnightAssets } from "@/themes/midnight";

const tabs = [
  {
    id: "chat", label: "聊天", to: "/home",
    icons: [assets.chatDefault, assets.chatSelected],
    nightIcons: [midnightAssets.icons["chat-inactive"], midnightAssets.icons["chat-active"]],
  },
  {
    id: "voice", label: "语音", to: "/voice",
    icons: [assets.voiceDefault, assets.voiceSelected],
  },
  {
    id: "more", label: "更多", to: "/settings",
    icons: [assets.moreDefault, assets.moreSelected],
    nightIcons: [midnightAssets.icons["settings-inactive"], midnightAssets.icons["settings-active"]],
  },
] as const;

const theme = useThemeStore();
const route = useRoute();

const active = computed(() => {
  if (route.path === "/home" || route.path === "/chat") return "chat";
  if (route.path === "/voice") return "voice";
  if (route.path === "/settings" || route.path.startsWith("/settings/")) return "more";
  return null;
});

function tabIcon(tab: typeof tabs[number]): string {
  const icons = theme.midnight && "nightIcons" in tab ? tab.nightIcons : tab.icons;
  return icons[active.value === tab.id ? 1 : 0];
}
</script>

<template>
  <nav class="tabbar" :class="{ midnight: theme.midnight }" aria-label="主要功能">
    <RouterLink
      v-for="tab in tabs"
      :key="tab.id"
      :to="tab.to"
      class="tab"
      :class="{ active: active === tab.id }"
      :aria-current="active === tab.id ? 'page' : undefined"
    >
      <img :src="tabIcon(tab)" :class="{ 'voice-icon': tab.id === 'voice' }" alt="" />
      <span>{{ tab.label }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.tabbar {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: calc(14px + env(safe-area-inset-bottom));
  z-index: 20;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  height: 78px;
  padding: 8px 6px;
  border-radius: 28px;
  background: var(--color-surface);
  box-shadow: var(--shadow-float);
}

.tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 44px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  text-decoration: none;
}

.tab img {
  width: 32px;
  height: 32px;
  object-fit: contain;
}

.tab.active {
  color: var(--color-primary);
  font-weight: 600;
}

.tab:active {
  transform: scale(0.98);
}

.midnight {
  background: linear-gradient(180deg, rgba(26, 10, 17, 0.96), var(--theme-bg));
  box-shadow: inset 0 0 0 1px var(--theme-border), var(--shadow-float);
}

.midnight .tab { position: relative; }
.midnight .active { color: var(--theme-accent); }
.midnight .voice-icon { filter: grayscale(1) sepia(0.25); }
.midnight .active .voice-icon { filter: grayscale(1) sepia(1) saturate(2) hue-rotate(290deg); }
.midnight .active::after {
  content: "";
  position: absolute;
  bottom: 0;
  width: 32px;
  height: 2px;
  border-radius: 2px;
  background: var(--theme-accent);
  box-shadow: 0 0 10px 2px var(--theme-glow);
}
</style>
