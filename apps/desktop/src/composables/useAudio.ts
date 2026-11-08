import { computed, ref } from "vue";

import type { ConversationScope } from "../services/conversations";
import { errorText } from "../services/http";
import { recognizeSpeech, type AsrRecognizeResponse } from "../services/audio";
import { startMicrophone, type MicrophoneHandle } from "../services/microphone";

export type VoiceUiState =
  | "idle"
  | "recording"
  | "recognizing"
  | "preview"
  | "failed";

export function useAudio(getScope: () => ConversationScope | null) {
  const state = ref<VoiceUiState>("idle");
  const previewText = ref("");
  const emotionHint = ref<string | null>(null);
  const error = ref("");
  const lastTaskId = ref<string | null>(null);
  let mic: MicrophoneHandle | null = null;
  let asrAbort: AbortController | null = null;

  const busy = computed(() => state.value === "recording" || state.value === "recognizing");
  const canConfirm = computed(() => state.value === "preview" && previewText.value.trim().length > 0);

  async function startRecording(): Promise<void> {
    if (state.value === "recording" || state.value === "recognizing") {
      return;
    }
    error.value = "";
    previewText.value = "";
    emotionHint.value = null;
    lastTaskId.value = null;
    try {
      mic = await startMicrophone();
      state.value = "recording";
    } catch (caught) {
      state.value = "failed";
      error.value = errorText(caught) || "无法打开麦克风";
      mic = null;
    }
  }

  async function stopAndRecognize(conversationId: string | null): Promise<AsrRecognizeResponse | null> {
    if (state.value !== "recording" || !mic) {
      return null;
    }
    const scope = getScope();
    if (!scope) {
      cancel();
      error.value = "尚未选择陪伴者";
      state.value = "failed";
      return null;
    }
    const handle = mic;
    mic = null;
    state.value = "recognizing";
    try {
      const blob = await handle.stop();
      if (blob.size < 100) {
        state.value = "failed";
        error.value = "录音太短，请重试";
        return null;
      }
      const controller = new AbortController();
      asrAbort = controller;
      const result = await recognizeSpeech(scope, blob, {
        conversationId,
        signal: controller.signal,
      });
      lastTaskId.value = result.task_id;
      previewText.value = result.text.trim();
      emotionHint.value = result.emotion;
      if (!previewText.value) {
        state.value = "failed";
        error.value = "没有识别到文字";
        return result;
      }
      state.value = "preview";
      return result;
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        state.value = "idle";
        return null;
      }
      state.value = "failed";
      error.value = errorText(caught);
      return null;
    } finally {
      asrAbort = null;
    }
  }

  function cancel(): void {
    asrAbort?.abort();
    asrAbort = null;
    mic?.cancel();
    mic = null;
    previewText.value = "";
    emotionHint.value = null;
    lastTaskId.value = null;
    error.value = "";
    state.value = "idle";
  }

  function discardPreview(): void {
    previewText.value = "";
    emotionHint.value = null;
    lastTaskId.value = null;
    error.value = "";
    state.value = "idle";
  }

  function takePreviewText(): string {
    const text = previewText.value.trim();
    discardPreview();
    return text;
  }

  return {
    state,
    previewText,
    emotionHint,
    error,
    lastTaskId,
    busy,
    canConfirm,
    startRecording,
    stopAndRecognize,
    cancel,
    discardPreview,
    takePreviewText,
  };
}
