<script setup lang="ts">
import type { PlayerState } from "../services/audio-player";

defineProps<{
  messageId: string;
  activeMessageId: string | null;
  playerState: PlayerState;
  synthesizing: boolean;
}>();

const emit = defineEmits<{
  play: [];
  pause: [];
  resume: [];
  stop: [];
}>();
</script>

<template>
  <div class="voice-player">
    <button
      v-if="synthesizing"
      type="button"
      class="text-button"
      disabled
    >
      合成中…
    </button>
    <template v-else-if="activeMessageId === messageId && (playerState === 'playing' || playerState === 'loading')">
      <button type="button" class="text-button" @click="emit('pause')">暂停</button>
      <button type="button" class="text-button" @click="emit('stop')">停止</button>
    </template>
    <template v-else-if="activeMessageId === messageId && playerState === 'paused'">
      <button type="button" class="text-button" @click="emit('resume')">继续</button>
      <button type="button" class="text-button" @click="emit('stop')">停止</button>
    </template>
    <button v-else type="button" class="text-button" @click="emit('play')">播放语音</button>
  </div>
</template>
