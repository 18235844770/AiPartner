<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

import { useAudio } from "../composables/useAudio";
import { useChat } from "../composables/useChat";
import { useVoicePlayback } from "../composables/useVoicePlayback";
import { fetchVoicePreset, fetchVoicePresets, saveVoicePreset, type VoicePreset } from "../services/audio";
import { errorText } from "../services/http";
import VoiceInput from "./VoiceInput.vue";
import VoicePlayer from "./VoicePlayer.vue";
import { formatTimestamp, messageStateLabel, senderLabel } from "../domain/presentation";

const props = defineProps<{
  apiBaseUrl: string;
  userId: string;
  companionId: string;
  companionName: string;
}>();

const scopeOf = () => ({
  apiBaseUrl: props.apiBaseUrl,
  userId: props.userId,
  companionId: props.companionId,
});

const voice = useVoicePlayback(scopeOf);
const presets = ref<VoicePreset[]>([]);
const presetId = ref("");
const presetBusy = ref(false);

async function loadVoicePresets(): Promise<void> {
  if (!props.apiBaseUrl || !props.userId || !props.companionId) {
    return;
  }
  try {
    const scope = scopeOf();
    const [catalog, selection] = await Promise.all([fetchVoicePresets(scope.apiBaseUrl), fetchVoicePreset(scope)]);
    presets.value = catalog;
    presetId.value = selection.preset_id ?? "";
  } catch (caught) {
    voice.error.value = errorText(caught);
  }
}

async function onPresetChange(event: Event): Promise<void> {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) {
    return;
  }
  const next = target.value;
  presetBusy.value = true;
  try {
    const saved = await saveVoicePreset(scopeOf(), next || null);
    presetId.value = saved.preset_id ?? "";
    voice.error.value = "";
  } catch (caught) {
    voice.error.value = errorText(caught);
    target.value = presetId.value;
  } finally {
    presetBusy.value = false;
  }
}

watch(() => [props.apiBaseUrl, props.userId, props.companionId] as const, () => {
  void loadVoicePresets();
}, { immediate: true });
let spokenTurn = "";
const chat = useChat(scopeOf, {
  onCompanionMessageCompleted: (messageId, turnId) => {
    if (turnId && turnId === spokenTurn) {
      voice.enqueue(messageId);
      return;
    }
    spokenTurn = turnId;
    void voice.speakMessage(messageId);
  },
  onTurnInterrupted: () => {
    void voice.interrupt();
  },
});
const audio = useAudio(scopeOf);

async function startVoiceRecording(): Promise<void> {
  await voice.interrupt();
  await audio.startRecording();
}

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
  const content = messageDraft.value;
  if (!content.trim() || chat.sending.value || !chat.selected.value) {
    return;
  }
  // 一点击发送就清空输入框，不必等整轮流式结束。
  messageDraft.value = "";
  await chat.sendMessage(content);
}

function onComposerKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void submitMessage();
  }
}

async function confirmVoice(): Promise<void> {
  const text = audio.takePreviewText();
  if (!text || chat.sending.value || !chat.selected.value) {
    return;
  }
  messageDraft.value = "";
  await chat.sendMessage(text);
}

function confirmClear(): void {
  if (chat.clearing.value || chat.sending.value || !chat.selected.value) {
    return;
  }
  const accepted = window.confirm("清空这个窗口里的聊天记录？长期记忆会留下，之后还是在这一个窗口里继续说。");
  if (!accepted) {
    return;
  }
  void chat.clearHistory();
}
</script>

<template>
  <section class="chat">
    <div class="thread-pane">
      <header class="thread-header">
        <div>
          <p class="eyebrow">对话</p>
          <h2>{{ companionName }}</h2>
          <p class="muted">始终是这一个窗口。人不在的时候，也会把主动说的话留在这里。</p>
        </div>
        <button
          type="button"
          class="secondary"
          :disabled="!chat.selected.value || chat.clearing.value || chat.sending.value || chat.messages.value.length === 0"
          @click="confirmClear"
        >
          {{ chat.clearing.value ? "清空中" : "清空记录" }}
        </button>
      </header>

      <div ref="threadRef" class="thread">
        <p v-if="chat.loadingMessages.value" class="muted">正在读取消息</p>
        <p v-else-if="chat.selected.value && chat.messages.value.length === 0" class="muted">还没有消息。想说的时候，从这里开始。</p>
        <article
          v-for="message in chat.messages.value"
          :key="message.id"
          class="bubble"
          :class="[message.sender_type, message.status]"
        >
          <p class="bubble-meta">
            {{ senderLabel(message.sender_type) }}
            <template v-if="messageStateLabel(message.status)"> · {{ messageStateLabel(message.status) }}</template>
            · {{ formatTimestamp(message.created_at) }}
            <template v-if="message.sequence_number < Number.MAX_SAFE_INTEGER"> · #{{ message.sequence_number }}</template>
          </p>
          <p v-if="message.content" class="bubble-content">{{ message.content }}</p>
          <VoicePlayer
            v-if="message.sender_type === 'companion' && message.status === 'completed' && message.content"
            :message-id="message.id"
            :active-message-id="voice.activeMessageId.value"
            :player-state="voice.playerState.value"
            :synthesizing="voice.synthesizingIds.value.has(message.id)"
            @play="voice.speakMessage(message.id)"
            @pause="voice.pause()"
            @resume="voice.resume()"
            @stop="voice.stop()"
          />
        </article>
      </div>

      <form class="composer" @submit.prevent="submitMessage">
        <textarea
          v-model="messageDraft"
          rows="3"
          placeholder="写下要发送的消息"
          :disabled="!chat.selected.value || chat.sending.value || audio.busy.value"
          @keydown="onComposerKeydown"
        ></textarea>
        <div class="voice-toolbar">
          <label class="voice-toggle">
            音色
            <select :value="presetId" :disabled="presetBusy || presets.length === 0" @change="onPresetChange">
              <option v-for="item in presets" :key="item.id" :value="item.id">
                {{ item.provider_label }} · {{ item.name }}
              </option>
            </select>
          </label>
          <label class="voice-toggle">
            <input v-model="voice.enabled.value" type="checkbox" />
            自动朗读回复
          </label>
        </div>
        <VoiceInput
          :state="audio.state.value"
          :preview-text="audio.previewText.value"
          :emotion-hint="audio.emotionHint.value"
          :error="audio.error.value"
          :disabled="!chat.selected.value || chat.sending.value"
          @start="startVoiceRecording()"
          @stop="audio.stopAndRecognize(chat.selected.value?.id ?? null)"
          @cancel="audio.cancel()"
          @discard="audio.discardPreview()"
          @confirm="confirmVoice()"
          @update:preview-text="audio.previewText.value = $event"
        />
        <div class="composer-bar">
          <p class="muted">Enter 发送，Shift + Enter 换行；也可语音输入。</p>
          <div class="composer-actions">
            <button v-if="chat.sending.value" class="secondary" type="button" @click="chat.stop()">停止</button>
            <button class="primary" type="submit" :disabled="!chat.selected.value || chat.sending.value || !messageDraft.trim()">
              {{ chat.sending.value ? "发送中" : "发送" }}
            </button>
          </div>
        </div>
      </form>
      <p v-if="chat.error.value" class="error">{{ chat.error.value }}</p>
      <p v-if="voice.error.value" class="error">{{ voice.error.value }}</p>
    </div>
  </section>
</template>
