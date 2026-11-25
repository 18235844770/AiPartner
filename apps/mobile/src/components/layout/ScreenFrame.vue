<script setup lang="ts">
withDefaults(
  defineProps<{
    scroll?: boolean;
  }>(),
  { scroll: false },
);
</script>

<template>
  <div class="frame" :class="{ scroll }">
    <slot />
  </div>
</template>

<style scoped>
.frame {
  width: min(100%, var(--page-width));
  height: calc(100dvh - var(--keyboard-inset));
  margin: 0 auto;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-background);
  color: var(--color-text-primary);
}

.scroll {
  display: block;
  overflow-x: hidden;
  overflow-y: auto;
}
</style>
