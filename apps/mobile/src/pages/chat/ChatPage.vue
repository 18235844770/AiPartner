<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { assets } from "@/assets/slices";
import Avatar from "@/components/avatar/Avatar.vue";
import ChatInput from "@/components/chat/ChatInput.vue";
import ChatMessageList from "@/components/chat/ChatMessageList.vue";
import ScreenFrame from "@/components/layout/ScreenFrame.vue";
import { useKeyboardInset } from "@/composables/useKeyboardInset";
import { useDialogueStore } from "@/stores/dialogue";
import { useWorkspaceStore } from "@/stores/workspace";

useKeyboardInset();

const router = useRouter();
const workspace = useWorkspaceStore();
const dialogue = useDialogueStore();
const scroller = ref<HTMLElement | null>(null);
let preservingScroll = false;

function scrollToEnd(): void {
  const element = scroller.value;
  if (!element) {
    return;
  }
  element.scrollTop = element.scrollHeight;
}

function send(text: string): Promise<boolean> {
  return dialogue.sendMessage(text).finally(() => {
    void nextTick(scrollToEnd);
  });
}

watch(
  () => dialogue.messages,
  () => {
    if (!preservingScroll) void nextTick(scrollToEnd);
  },
  { deep: true },
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
  <ScreenFrame>
    <section class="chat">
      <img class="wash left" :src="assets.lavenderBlob" alt="" />
      <img class="wash right" :src="assets.mintBlob" alt="" />

      <header>
        <button class="nav back" type="button" aria-label="返回" @click="router.push('/home')">
          <img :src="assets.back" alt="" />
        </button>
        <button class="nav more" type="button" aria-label="更多操作" @click="router.push('/settings/chat')">
          <img :src="assets.moreAction" alt="" />
        </button>
        <div class="identity">
          <div class="avatar-wrap">
            <img class="rays" :src="assets.raysPurple" alt="" />
            <Avatar :expression="dialogue.expression" :width="78" :motion="false" />
          </div>
          <h1>{{ workspace.companion?.name ?? "遇见" }}</h1>
          <p class="presence">
            <i class="dot" />
            {{ workspace.presence }}
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
      <ChatInput :send="send" />
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
}

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
</style>
