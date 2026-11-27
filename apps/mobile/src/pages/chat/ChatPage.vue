<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { assets } from "@/assets/slices";
import Avatar from "@/components/avatar/Avatar.vue";
import ChatInput from "@/components/chat/ChatInput.vue";
import ChatMessageList from "@/components/chat/ChatMessageList.vue";
import AppTabBar from "@/components/layout/AppTabBar.vue";
import ScreenFrame from "@/components/layout/ScreenFrame.vue";
import { useKeyboardInset } from "@/composables/useKeyboardInset";
import { useDialogueStore } from "@/stores/dialogue";
import { useWorkspaceStore } from "@/stores/workspace";
import { useThemeStore } from "@/stores/theme";
import { midnightAssets, midnightState } from "@/themes/midnight";

useKeyboardInset();

const router = useRouter();
const workspace = useWorkspaceStore();
const dialogue = useDialogueStore();
const theme = useThemeStore();
const state = computed(() => dialogue.sending ? "curious" : midnightState(dialogue.emotion));
const scroller = ref<HTMLElement | null>(null);
let preservingScroll = false;

function scrollToEnd(): void {
  const element = scroller.value;
  if (!element) {
    return;
  }
  element.scrollTop = element.scrollHeight;
}

async function send(text: string): Promise<void> {
  const originalDraft = dialogue.draft;
  scrollToEnd();
  if (await dialogue.sendMessage(text) && dialogue.draft === originalDraft) {
    dialogue.draft = "";
  }
}

watch(
  [() => dialogue.messages, () => dialogue.typing, () => dialogue.loading, () => theme.id],
  () => {
    const element = scroller.value;
    if (!element || preservingScroll) return;
    const remaining = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (remaining < 48) void nextTick(scrollToEnd);
  },
);

async function loadOlder(): Promise<void> {
  const element = scroller.value;
  if (!element || preservingScroll) return;
  const previousHeight = element.scrollHeight;
  const previousPosition = element.scrollTop;
  preservingScroll = true;
  try {
    await dialogue.loadOlder();
    await nextTick();
    element.scrollTop = previousPosition + element.scrollHeight - previousHeight;
  } finally {
    preservingScroll = false;
  }
}

</script>

<template>
  <ScreenFrame page="chat">
    <section class="chat" :class="{ midnight: theme.midnight }">
      <img v-if="!theme.midnight" class="wash left" :src="assets.lavenderBlob" alt="" />
      <img v-if="!theme.midnight" class="wash right" :src="assets.mintBlob" alt="" />

      <header>
        <button class="nav back" type="button" aria-label="返回" @click="router.push('/home')">
          <img :src="theme.midnight ? midnightAssets.icons.back : assets.back" alt="" />
        </button>
        <button class="nav more" type="button" aria-label="更多操作" @click="router.push('/settings/chat')">
          <img :src="theme.midnight ? midnightAssets.icons.more : assets.moreAction" alt="" />
        </button>
        <div class="identity">
          <div class="avatar-wrap">
            <img v-if="!theme.midnight" class="rays" :src="assets.raysPurple" alt="" />
            <Avatar :expression="dialogue.expression" :width="78" :motion="false"
              :midnight-state="theme.midnight ? state : undefined" :class="{ thinking: theme.midnight && dialogue.sending }" />
          </div>
          <h1>{{ workspace.companion?.name ?? "遇见" }}</h1>
          <p class="presence" role="status">
            <i class="dot" />
            {{ dialogue.sending ? "正在回复" : workspace.presence }}
          </p>
        </div>
      </header>

      <div ref="scroller" class="transcript">
        <p v-if="dialogue.loading" class="state">正在读取对话</p>
        <template v-else>
          <button v-if="dialogue.hasOlder" class="state older" type="button" :disabled="dialogue.loadingOlder" @click="loadOlder">加载较早消息</button>
          <ChatMessageList :messages="dialogue.messages" :typing="dialogue.typing" @retry="dialogue.retry" />
        </template>
      </div>
      <p v-if="dialogue.error" class="error">{{ dialogue.error }}</p>
      <ChatInput v-model="dialogue.draft" :send="send" />
      <AppTabBar />
    </section>
  </ScreenFrame>
</template>

<style scoped>
.chat {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #fbfbfe;
}

.wash {
  position: absolute;
  height: auto;
  pointer-events: none;
  opacity: 0.55;
}

.left {
  width: 180px;
  left: -70px;
  top: -20px;
}

.right {
  width: 140px;
  right: -50px;
  top: 80px;
}

header {
  position: relative;
  z-index: 1;
  padding: calc(env(safe-area-inset-top) + 8px) 8px 8px;
}

.nav {
  position: absolute;
  top: calc(env(safe-area-inset-top) + 8px);
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  z-index: 2;
}

.back {
  left: 8px;
}

.more {
  right: 8px;
}

.nav img {
  width: 28px;
  height: 28px;
  object-fit: contain;
}

.identity {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.avatar-wrap {
  position: relative;
  display: grid;
  place-items: center;
  width: 78px;
  aspect-ratio: 1;
}

.avatar-wrap :deep(.avatar) { max-width: 100%; }

.rays {
  position: absolute;
  width: 36px;
  right: -6px;
  top: -4px;
  pointer-events: none;
}

h1 {
  font-size: 17px;
  font-weight: 700;
}

.presence {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-online);
}

.transcript {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 16px 8px;
}

.state,
.error {
  position: relative;
  z-index: 1;
  margin: 0 16px 8px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  text-align: center;
}

.error {
  color: var(--color-danger);
}

.chat.midnight { background: transparent; }
.midnight header {
  box-shadow: inset 0 -1px var(--theme-border);
  background: linear-gradient(transparent, rgba(25, 7, 15, 0.8));
}
.midnight .avatar-wrap :deep(.avatar) {
  padding: 3px;
  border: 1px solid var(--theme-border);
  border-radius: 50%;
  background: radial-gradient(circle at 45% 30%, #411622, var(--theme-bg));
}
.midnight h1 { font-family: var(--theme-heading-font); }
.midnight .thinking { filter: drop-shadow(0 0 7px var(--theme-accent)); }
.midnight header, .midnight .transcript, .midnight .error { z-index: 10; }

.chat > .tabbar {
  position: relative;
  inset: auto;
  flex: none;
  margin: 0 16px calc(14px + env(safe-area-inset-bottom));
}

@container (max-height: 480px) {
  .chat > .tabbar { display: none; }
  .chat header { padding-bottom: 4px; }
  .chat .avatar-wrap { width: 48px; }
}
</style>
