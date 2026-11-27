<script setup lang="ts">
import type { CSSProperties } from "vue";

import { midnightAssets, type MidnightPage } from "@/themes/midnight";

defineProps<{ page: MidnightPage }>();

const placements = {
  home: [[14, 18, 17], [62, 11, 8], [87, 26, 8], [21, 39, 12], [83, 55, 16], [12, 78, 12], [89, 82, 10]],
  chat: [[10, 13, 13], [77, 9, 12], [93, 34, 16], [8, 57, 11], [91, 68, 12]],
  settings: [[19, 8, 12], [78, 6, 17], [91, 49, 10], [12, 77, 15], [78, 83, 7]],
  login: [[15, 14, 8], [87, 13, 14], [17, 24, 13], [83, 31, 14], [12, 48, 17], [89, 48, 11], [17, 84, 12], [82, 87, 10]],
};

function position([x, y, size]: number[], index: number): CSSProperties {
  return { left: `${x}%`, top: `${y}%`, width: `${size}px`,
    animationDuration: `${3 + index * 0.4}s`, animationDelay: `${index * -1.37}s` };
}
</script>

<template>
  <div class="ambient" aria-hidden="true">
    <img v-for="(star, index) in placements[page]" :key="index" :src="midnightAssets.decorations.star" :style="position(star, index)" alt="" />
  </div>
</template>

<style scoped>
.ambient {
  position: absolute;
  z-index: 1;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

img {
  position: absolute;
  height: auto;
  opacity: 0.6;
  animation: shimmer infinite ease-in-out alternate;
}

@keyframes shimmer {
  from { opacity: 0.15; }
  to { opacity: 0.9; }
}

@media (prefers-reduced-motion: reduce) {
  img { animation: none; }
}
</style>
