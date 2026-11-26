<script setup lang="ts">
import { computed } from "vue";

import ChatMessage from "@/components/chat/ChatMessage.vue";
import type { ChatMessageItem } from "@/types/chat";

const props = defineProps<{
  messages: ChatMessageItem[];
  typing: boolean;
}>();
const emit = defineEmits<{ retry: [turnId: string] }>();

const visible = computed(() =>
  props.messages.filter((message) => {
    if (!message.text.trim() && (message.status === "generating" || message.status === "failed")) {
      return false;
    }
    return message.role === "user" || message.text.trim().length > 0;
  }),
);

function isGrouped(index: number): boolean {
  const current = visible.value[index];
  const previous = visible.value[index - 1];
  return previous?.role === current?.role;
}
</script>

<template>
  <div class="list">
    <template v-for="(message, index) in visible" :key="message.id">
      <ChatMessage :role="message.role" :text="message.text" :grouped="isGrouped(index)" />
      <button v-if="message.retryTurnId" class="retry" type="button" @click="emit('retry', message.retryTurnId)">回复失败，重试</button>
    </template>
    <div v-if="typing" class="typing" aria-label="对方正在输入">
      <span />
      <span />
      <span />
    </div>
    <p v-if="visible.length === 0 && !typing" class="empty">说点什么吧</p>
  </div>
</template>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
}

.retry {
  align-self: flex-end;
  min-height: 36px;
  color: var(--color-primary-deep);
  font-size: var(--font-size-sm);
}

.typing {
  display: flex;
  align-items: center;
  gap: 5px;
  width: fit-content;
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 18px;
  border-bottom-left-radius: 8px;
  background: var(--color-companion-bubble);
}

.typing span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #b7a6ef;
  animation: typing-bounce 1.1s infinite ease-in-out;
}

.typing span:nth-child(2) {
  animation-delay: 0.15s;
}

.typing span:nth-child(3) {
  animation-delay: 0.3s;
}

.empty {
  margin: auto;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
