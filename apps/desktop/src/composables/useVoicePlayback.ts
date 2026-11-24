import { ref } from "vue";

import { cancelAudioTask, synthesizeSpeech } from "../services/audio";
import { createAudioPlayer, type PlayerState } from "../services/audio-player";
import type { ConversationScope } from "../services/conversations";
import { errorText } from "../services/http";

/**
 * 播放策略：整段合成完成后一次播放。
 * 当前服务端仍是「先整段再分块」；分块用多个 HTMLAudioElement 接力会造成明显顿挫。
 */
export function useVoicePlayback(getScope: () => ConversationScope | null) {
  const enabled = ref(true);
  const playerState = ref<PlayerState>("idle");
  const activeMessageId = ref<string | null>(null);
  const activeTaskId = ref<string | null>(null);
  const error = ref("");
  const synthesizingIds = ref<Set<string>>(new Set());
  const queue: string[] = [];
  let draining = false;
  let ttsAbort: AbortController | null = null;

  const player = createAudioPlayer((state) => {
    playerState.value = state;
  });

  function markSynthesizing(messageId: string, on: boolean): void {
    const next = new Set(synthesizingIds.value);
    if (on) {
      next.add(messageId);
    } else {
      next.delete(messageId);
    }
    synthesizingIds.value = next;
  }

  async function speakMessage(messageId: string): Promise<void> {
    queue.length = 0;
    queue.push(messageId);
    await haltPlayback();
    if (!draining) {
      void drain();
    }
  }

  function enqueue(messageId: string): void {
    queue.push(messageId);
    if (!draining) {
      void drain();
    }
  }

  async function drain(): Promise<void> {
    if (draining) {
      return;
    }
    draining = true;
    try {
      while (queue.length > 0) {
        const messageId = queue.shift();
        if (messageId) {
          await playMessage(messageId);
        }
      }
    } finally {
      draining = false;
      if (queue.length > 0) {
        void drain();
      }
    }
  }

  async function playMessage(messageId: string): Promise<void> {
    const scope = getScope();
    if (!scope || !enabled.value) {
      return;
    }
    error.value = "";
    activeMessageId.value = messageId;
    markSynthesizing(messageId, true);
    const controller = new AbortController();
    ttsAbort = controller;
    try {
      const result = await synthesizeSpeech(scope, messageId, { signal: controller.signal });
      if (controller.signal.aborted) {
        return;
      }
      activeTaskId.value = result.task_id;
      if (!result.audio_url) {
        throw new Error("语音合成未返回音频地址");
      }
      const url = resolveAudioUrl(scope.apiBaseUrl, result.audio_url);
      await player.play(url);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        return;
      }
      error.value = errorText(caught);
      playerState.value = "failed";
    } finally {
      markSynthesizing(messageId, false);
      if (ttsAbort === controller) {
        ttsAbort = null;
      }
    }
  }

  async function haltPlayback(): Promise<void> {
    ttsAbort?.abort();
    ttsAbort = null;
    player.stop();
    const scope = getScope();
    const taskId = activeTaskId.value;
    activeTaskId.value = null;
    activeMessageId.value = null;
    if (scope && taskId) {
      try {
        await cancelAudioTask(scope, taskId);
      } catch {
        // 打断以本地停播为准。
      }
    }
  }

  async function interrupt(): Promise<void> {
    queue.length = 0;
    await haltPlayback();
  }

  function pause(): void {
    player.pause();
  }

  function resume(): void {
    player.resume();
  }

  function stop(): void {
    void interrupt();
  }

  return {
    enabled,
    playerState,
    activeMessageId,
    activeTaskId,
    error,
    synthesizingIds,
    speakMessage,
    enqueue,
    interrupt,
    pause,
    resume,
    stop,
  };
}

function resolveAudioUrl(apiBaseUrl: string, audioUrl: string): string {
  if (audioUrl.startsWith("http://") || audioUrl.startsWith("https://")) {
    return audioUrl;
  }
  const base = apiBaseUrl.replace(/\/$/, "");
  return audioUrl.startsWith("/") ? `${base}${audioUrl}` : `${base}/${audioUrl}`;
}
