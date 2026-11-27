<script setup lang="ts">
import { computed, ref } from "vue";

import { assets } from "@/assets/slices";
import { useThemeStore } from "@/stores/theme";
import { midnightAssets } from "@/themes/midnight";

const props = defineProps<{ send: (text: string) => Promise<void> }>();

const draft = defineModel<string>({ required: true });
const theme = useThemeStore();
const submitting = ref(false);

const canSend = computed(() => !submitting.value && draft.value.trim().length > 0);

async function submit(): Promise<void> {
  if (!canSend.value) return;
  submitting.value = true;
  try {
    await props.send(draft.value.trim());
  } finally {
    submitting.value = false;
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    void submit();
  }
}
</script>

<template>
  <form class="composer" :class="{ midnight: theme.midnight }" @submit.prevent="submit">
    <button class="tool" type="button" aria-label="图片">
      <img :src="assets.image" alt="" />
    </button>
    <input
      v-model="draft"
      type="text"
      maxlength="8000"
      enterkeyhint="send"
      placeholder="输入消息..."
      aria-label="输入消息"
      @keydown="onKeydown"
    />
    <button class="send" type="submit" :disabled="!canSend" :aria-busy="submitting || undefined" :aria-label="submitting ? '正在发送' : '发送'">
      <img :src="theme.midnight ? midnightAssets.icons.send : assets.send" alt="" />
    </button>
  </form>
</template>

<style scoped>
.composer {
  position: relative;
  z-index: 10;
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px calc(10px + env(safe-area-inset-bottom));
  background: linear-gradient(180deg, rgba(247, 246, 251, 0) 0%, #f7f6fb 28%);
}

.tool {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex: none;
}

.tool img {
  width: 28px;
  height: 28px;
  object-fit: contain;
}

input {
  width: 100%;
  min-width: 0;
  height: 46px;
  padding: 0 16px;
  border: 0;
  border-radius: var(--radius-round);
  outline: none;
  background: #f1eef6;
  font-size: 15px;
}

input::placeholder {
  color: var(--color-text-disabled);
}

input:focus {
  box-shadow: 0 0 0 1.5px var(--color-primary-light);
}

.send {
  width: 48px;
  height: 48px;
  flex: none;
  border-radius: 50%;
}

.send img {
  width: 48px;
  height: 48px;
  object-fit: contain;
}

.send:disabled {
  opacity: 0.45;
}

.send:active:not(:disabled) {
  transform: scale(0.96);
}

.midnight {
  box-shadow: inset 0 1px var(--theme-border);
  background: rgba(19, 7, 13, 0.91);
}
.midnight input { background: var(--theme-surface-raised); border: 1px solid var(--theme-border); }
.midnight .send { display: grid; place-items: center; background: var(--theme-surface-raised); }
.midnight .send img { width: 27px; height: 27px; }
.midnight .tool img { filter: grayscale(1) sepia(0.25); }
</style>
