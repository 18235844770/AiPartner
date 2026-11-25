<script setup lang="ts">
import { useRouter } from "vue-router";

import AppButton from "@/components/common/AppButton.vue";
import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { useDialogueStore } from "@/stores/dialogue";
import { useWorkspaceStore } from "@/stores/workspace";

const router = useRouter();
const dialogue = useDialogueStore();
const workspace = useWorkspaceStore();
</script>

<template>
  <SettingsDetail title="通知设置">
    <section class="panel panel-body stack">
      <p class="hint">{{ workspace.companion?.name ?? "陪伴者" }}的回复会留在聊天里。</p>
      <p v-if="dialogue.loading" class="hint">正在读取最近的回复</p>
      <p v-else-if="dialogue.statusLine" class="latest">{{ dialogue.statusLine }}</p>
      <p v-else class="hint">还没有新的回复。</p>
      <p class="hint">对方选择安静时，聊天里不会多出一条空消息。</p>
      <AppButton variant="secondary" @click="router.push('/chat')">打开聊天</AppButton>
    </section>
  </SettingsDetail>
</template>

<style scoped>
.latest {
  padding: 12px 14px;
  border-radius: 16px;
  background: var(--color-companion-bubble);
  line-height: 1.55;
}
</style>
