<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { avatarSource, type AvatarExpression } from "@/assets/slices";

import { midnightAssets, type MidnightState } from "@/themes/midnight";

const props = withDefaults(
  defineProps<{
    expression: AvatarExpression;
    width?: number;
    motion?: boolean;
    midnightState?: MidnightState | "default";
  }>(),
  { width: 220, motion: true },
);

const paused = ref(false);
const failed = ref(false);
watch(() => props.midnightState, () => { failed.value = false; });
const source = computed(() => {
  if (!props.midnightState) return avatarSource(props.expression);
  return failed.value ? midnightAssets.avatars.idle : midnightAssets.avatars[props.midnightState];
});

function syncVisibility(): void {
  paused.value = document.hidden;
}

watch(() => props.motion && !props.midnightState, (active, _, onCleanup) => {
  if (!active) return;
  syncVisibility();
  document.addEventListener("visibilitychange", syncVisibility);
  onCleanup(() => document.removeEventListener("visibilitychange", syncVisibility));
}, { immediate: true });
</script>

<template>
  <div class="avatar" :class="{ motion: props.motion && !props.midnightState, paused }" :style="{ width: `${props.width}px` }">
    <img :key="source" :src="source" :class="{ midnight: props.midnightState }" @error="failed = true" alt="" draggable="false" />
  </div>
</template>

<style scoped>
.motion {
  animation: avatar-float 3.8s ease-in-out infinite;
}

.paused {
  animation-play-state: paused;
}

.midnight {
  aspect-ratio: 1;
  object-fit: contain;
}

img {
  width: 100%;
  height: auto;
  user-select: none;
  -webkit-user-drag: none;
}
</style>
