<script setup lang="ts">
import type { MessageRole } from "@/types/chat";

defineProps<{
  role: MessageRole;
  text: string;
  grouped: boolean;
}>();
</script>

<template>
  <div class="row" :class="[role, { grouped }]">
    <p class="bubble">{{ text }}</p>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  max-width: 100%;
  margin-top: 14px;
}

.user {
  justify-content: flex-end;
}

.companion {
  justify-content: flex-start;
}

.bubble {
  max-width: 82%;
  padding: 12px 16px;
  border-radius: 18px;
  font-size: 15px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.user .bubble {
  background: var(--color-user-bubble);
  color: #3a315c;
  border-bottom-right-radius: 8px;
}

.companion .bubble {
  background: var(--color-companion-bubble);
  color: var(--color-text-primary);
  border-bottom-left-radius: 8px;
}

.grouped {
  margin-top: 6px;
}
</style>
