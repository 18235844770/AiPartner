<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import { avatarSource, type AvatarExpression } from "@/assets/slices";

const props = withDefaults(
  defineProps<{
    expression: AvatarExpression;
    width?: number;
    motion?: boolean;
  }>(),
  { width: 220, motion: true },
);

const paused = ref(false);

function syncVisibility(): void {
  paused.value = document.hidden;
}

onMounted(() => {
  document.addEventListener("visibilitychange", syncVisibility);
  syncVisibility();
});

onUnmounted(() => {
  document.removeEventListener("visibilitychange", syncVisibility);
});
</script>

<template>
  <div class="avatar" :class="{ motion: props.motion, paused }" :style="{ width: `${props.width}px` }">
    <img :src="avatarSource(props.expression)" alt="" draggable="false" />
  </div>
</template>

<style scoped>
.motion {
  animation: avatar-float 3.8s ease-in-out infinite;
}

.paused {
  animation-play-state: paused;
}

img {
  width: 100%;
  height: auto;
  user-select: none;
  -webkit-user-drag: none;
}
</style>
