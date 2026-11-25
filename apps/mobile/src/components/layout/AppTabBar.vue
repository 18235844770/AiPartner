<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import { assets } from "@/assets/slices";

type TabId = "chat" | "voice" | "more";

interface TabItem {
  id: TabId;
  label: string;
  to: string | null;
  icon: string;
  selectedIcon: string;
}

const tabs: TabItem[] = [
  {
    id: "chat",
    label: "聊天",
    to: "/home",
    icon: assets.chatDefault,
    selectedIcon: assets.chatSelected,
  },
  {
    id: "voice",
    label: "语音",
    to: "/voice",
    icon: assets.voiceDefault,
    selectedIcon: assets.voiceSelected,
  },
  {
    id: "more",
    label: "更多",
    to: "/settings",
    icon: assets.moreDefault,
    selectedIcon: assets.moreSelected,
  },
];

const route = useRoute();
const router = useRouter();

const active = computed<TabId | null>(() => {
  if (route.path === "/settings" || route.path.startsWith("/settings/")) {
    return "more";
  }
  if (route.path === "/voice") {
    return "voice";
  }
  if (route.path === "/home") {
    return "chat";
  }
  return null;
});

function openTab(tab: TabItem): void {
  if (!tab.to || route.path === tab.to) {
    return;
  }
  void router.push(tab.to);
}
</script>

<template>
  <nav class="tabbar" aria-label="主要功能">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      type="button"
      class="tab"
      :class="{ active: active === tab.id }"
      :aria-current="active === tab.id ? 'page' : undefined"
      @click="openTab(tab)"
    >
      <img :src="active === tab.id ? tab.selectedIcon : tab.icon" alt="" />
      <span>{{ tab.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.tabbar {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: calc(14px + env(safe-area-inset-bottom));
  z-index: 3;
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
</style>
