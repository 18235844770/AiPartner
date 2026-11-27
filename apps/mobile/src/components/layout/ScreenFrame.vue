<script setup lang="ts">
import { computed } from "vue";

import { useThemeStore } from "@/stores/theme";
import { midnightAssets, type MidnightPage } from "@/themes/midnight";

import AmbientStars from "./AmbientStars.vue";

const theme = useThemeStore();
const props = withDefaults(
  defineProps<{
    scroll?: boolean;
    page?: MidnightPage;
  }>(),
  { scroll: false },
);
const background = computed(() => theme.midnight && props.page
  ? `url("${midnightAssets.backgrounds[props.page]}")` : undefined);
</script>

<template>
  <div class="frame" :class="{ scroll }" :style="{ backgroundImage: background }">
    <AmbientStars v-if="theme.midnight && page" :page="page" />
    <slot />
  </div>
</template>

<style scoped>
.frame {
  width: min(100%, var(--page-width));
  height: calc(100vh - var(--keyboard-inset));
  height: calc(100dvh - var(--keyboard-inset));
  margin: 0 auto;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-background);
  color: var(--color-text-primary);
  background-position: center;
  background-size: cover;
  isolation: isolate;
  container-type: size;
}

.scroll {
  display: block;
  overflow-x: hidden;
  overflow-y: auto;
}
</style>
