<script setup lang="ts">
import { computed, ref } from "vue";

import type { VoiceUiState } from "../composables/useAudio";

const props = defineProps<{
  state: VoiceUiState;
  previewText: string;
  emotionHint: string | null;
  error: string;
  disabled: boolean;
}>();

const emit = defineEmits<{
  start: [];
  stop: [];
  cancel: [];
  confirm: [];
  discard: [];
  "update:previewText": [value: string];
}>();

const pressStartedAt = ref(0);
const toggleArmed = ref(false);
const HOLD_MS = 350;

const statusLabel = computed(() => {
  switch (props.state) {
    case "recording":
      return "录音中：松开结束（长按），或再次点击结束";
    case "recognizing":
      return "正在识别…";
    case "preview":
      return "确认识别文字后发送";
    case "failed":
      return props.error || "语音输入失败";
    default:
      return "按住说话，或点击开始 / 再次点击结束";
  }
});

const recording = computed(() => props.state === "recording");
const preview = computed(() => props.state === "preview");

function onPointerDown(event: PointerEvent): void {
  if (props.disabled || props.state === "recognizing" || props.state === "preview") {
    return;
  }
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  pressStartedAt.value = Date.now();
  if (props.state === "recording" && toggleArmed.value) {
    return;
  }
  if (props.state === "idle" || props.state === "failed") {
    toggleArmed.value = false;
    emit("start");
  }
}

function onPointerUp(event: PointerEvent): void {
  try {
    (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
  } catch {
    // ignore
  }
  if (props.state !== "recording") {
    return;
  }
  const held = Date.now() - pressStartedAt.value;
  if (held >= HOLD_MS) {
    toggleArmed.value = false;
    emit("stop");
    return;
  }
  if (!toggleArmed.value) {
    toggleArmed.value = true;
    return;
  }
  toggleArmed.value = false;
  emit("stop");
}

function onCancel(): void {
  toggleArmed.value = false;
  emit("cancel");
}
</script>

<template>
  <div class="voice-input" :class="state">
    <div class="voice-controls">
      <button
        type="button"
        class="voice-mic"
        :class="{ recording, disabled }"
        :disabled="disabled || state === 'recognizing'"
        :aria-pressed="recording"
        :title="statusLabel"
        @pointerdown.prevent="onPointerDown"
        @pointerup.prevent="onPointerUp"
        @pointercancel.prevent="onCancel"
      >
        {{ recording ? "结束录音" : state === "recognizing" ? "识别中" : "语音" }}
      </button>
      <button
        v-if="state === 'recording' || state === 'recognizing' || state === 'failed'"
        type="button"
        class="text-button"
        @click="onCancel"
      >
        取消
      </button>
    </div>

    <p class="voice-status muted">{{ statusLabel }}</p>

    <div v-if="preview" class="voice-preview">
      <label>
        识别结果
        <textarea
          :value="previewText"
          rows="2"
          @input="emit('update:previewText', ($event.target as HTMLTextAreaElement).value)"
        ></textarea>
      </label>
      <p v-if="emotionHint" class="muted">语音情绪线索：{{ emotionHint }}（仅参考，不会改写陪伴者情绪）</p>
      <div class="voice-preview-actions">
        <button type="button" class="secondary" @click="emit('discard')">重录</button>
        <button type="button" class="primary" :disabled="!previewText.trim()" @click="emit('confirm')">
          发送识别文字
        </button>
      </div>
    </div>

    <p v-if="state === 'failed' && error" class="error">{{ error }}</p>
  </div>
</template>
