<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

import { useChat } from "../composables/useChat";
import { conversationStatusLabel, conversationTitle, formatTimestamp, senderLabel } from "../domain/presentation";

const props = defineProps<{
  apiBaseUrl: string;
  userId: string;
  companionId: string;
  companionName: string;
}>();

const chat = useChat(() => ({
  apiBaseUrl: props.apiBaseUrl,
  userId: props.userId,
  companionId: props.companionId,
}));

const titleDraft = ref("");
const messageDraft = ref("");
const threadRef = ref<HTMLElement | null>(null);

watch(
  () => chat.messages.value.map((item) => item.id).join(","),
  async () => {
    await nextTick();
    const thread = threadRef.value;
    if (thread) {
      thread.scrollTop = thread.scrollHeight;
    }
  },
);

async function submitMessage(): Promise<void> {
  const sent = await chat.sendMessage(messageDraft.value);
  if (sent) {
    messageDraft.value = "";
  }
}

function onComposerKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void submitMessage();
  }
}
</script>

<template>
  <section class="chat">
    <aside class="session-list">
      <form class="new-session" @submit.prevent="chat.startConversation(titleDraft)">
        <label>
          新会话
          <input v-model="titleDraft" maxlength="128" placeholder="标题，可留空" />
        </label>
        <button class="primary" type="submit" :disabled="chat.creating.value">
          {{ chat.creating.value ? "创建中" : "创建" }}
        </button>
      </form>

      <div class="session-toolbar">
        <h2>会话</h2>
        <button type="button" class="text-button" :disabled="chat.loadingList.value" @click="chat.refreshConversations(false)">
          刷新
        </button>
      </div>

      <p v-if="chat.loadingList.value" class="muted">正在读取会话</p>
      <p v-else-if="chat.conversations.value.length === 0" class="muted">还没有会话。</p>
      <ul v-else>
        <li v-for="item in chat.conversations.value" :key="item.id">
          <button
            type="button"
            class="session"
            :class="{ active: chat.selected.value?.id === item.id }"
            @click="chat.openConversation(item.id)"
          >
            <span class="session-title">{{ conversationTitle(item) }}</span>
            <span class="session-meta">
              {{ conversationStatusLabel(item.status) }}
              <template v-if="item.last_message_at"> · {{ formatTimestamp(item.last_message_at) }}</template>
            </span>
          </button>
        </li>
      </ul>
    </aside>

    <div class="thread-pane">
      <header v-if="chat.selected.value" class="thread-header">
        <div>
          <p class="eyebrow">{{ companionName }}</p>
          <h2>{{ conversationTitle(chat.selected.value) }}</h2>
          <p class="muted">{{ conversationStatusLabel(chat.selected.value.status) }} · 原始对话记录</p>
        </div>
        <button
          v-if="chat.selected.value.status !== 'archived'"
          type="button"
          class="secondary"
          @click="chat.archiveSelected()"
        >
          归档
        </button>
      </header>
      <header v-else class="thread-header">
        <div>
          <p class="eyebrow">{{ companionName }}</p>
          <h2>选择一个会话</h2>
        </div>
      </header>

      <div ref="threadRef" class="thread">
        <p v-if="chat.loadingMessages.value" class="muted">正在读取消息</p>
        <p v-else-if="chat.selected.value && chat.messages.value.length === 0" class="muted">这条会话还没有消息。</p>
        <article
          v-for="message in chat.messages.value"
          :key="message.id"
          class="bubble"
          :class="message.sender_type"
        >
          <p class="bubble-meta">
            {{ senderLabel(message.sender_type) }}
            · {{ formatTimestamp(message.created_at) }}
            · #{{ message.sequence_number }}
          </p>
          <p class="bubble-content">{{ message.content }}</p>
        </article>
      </div>

      <form class="composer" @submit.prevent="submitMessage">
        <textarea
          v-model="messageDraft"
          rows="3"
          placeholder="写下要发送的消息"
          :disabled="!chat.selected.value || chat.sending.value"
          @keydown="onComposerKeydown"
        ></textarea>
        <div class="composer-bar">
          <p class="muted">Enter 发送，Shift + Enter 换行。当前写入用户消息。</p>
          <button class="primary" type="submit" :disabled="!chat.selected.value || chat.sending.value || !messageDraft.trim()">
            {{ chat.sending.value ? "发送中" : "发送" }}
          </button>
        </div>
      </form>
      <p v-if="chat.error.value" class="error">{{ chat.error.value }}</p>
    </div>
  </section>
</template>
