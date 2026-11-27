<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import { midnightAssets, type MidnightState } from "@/themes/midnight";

const props = defineProps<{ state: MidnightState; animate?: boolean }>();
const motionAllowed = ref(false);
const failed = ref(new Set<string>());
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const connection = (navigator as Navigator & { connection?: EventTarget & { saveData?: boolean } }).connection;

function syncMotion(): void {
  motionAllowed.value = !document.hidden && !motionPreference.matches && !connection?.saveData
    && (navigator.hardwareConcurrency || 4) > 2;
}

onMounted(() => {
  if (!props.animate || !midnightAssets.curiousMotion) return;
  syncMotion();
  document.addEventListener("visibilitychange", syncMotion);
  motionPreference.addEventListener("change", syncMotion);
  connection?.addEventListener("change", syncMotion);
});

onUnmounted(() => {
  document.removeEventListener("visibilitychange", syncMotion);
  motionPreference.removeEventListener("change", syncMotion);
  connection?.removeEventListener("change", syncMotion);
});

watch(() => props.state, () => failed.value.clear());

const source = computed(() => [
  props.animate && motionAllowed.value && props.state === "curious" ? midnightAssets.curiousMotion : undefined,
  props.state === "curious" ? midnightAssets.curiousStill : undefined,
  midnightAssets.characters[props.state],
  midnightAssets.characters.idle,
].find((url) => url && !failed.value.has(url)));

function onError(event: Event): void {
  const url = (event.currentTarget as HTMLImageElement).getAttribute("src");
  if (url) failed.value.add(url);
}
</script>

<template>
  <img v-if="source" :key="source" class="character" :src="source" alt="" draggable="false" @error="onError" />
</template>

<style scoped>
.character {
  display: block;
  width: 100%;
  height: 100%;
  aspect-ratio: 1;
  object-fit: contain;
  object-position: center bottom;
  user-select: none;
}
</style>
