<script setup lang="ts">
import { ref, watch } from "vue";

import AppButton from "@/components/common/AppButton.vue";
import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { useClearChat } from "@/composables/useClearChat";
import { listConversations } from "@/services/conversations";
import { errorText } from "@/services/http";
import { useWorkspaceStore } from "@/stores/workspace";
import type { ConversationResponse } from "@/types/api";

const workspace = useWorkspaceStore();
const { confirming, clearing, error: clearError, notice, ask, cancel, confirm } = useClearChat();
const conversations = ref<ConversationResponse[]>([]);
const loading = ref(true);
const error = ref("");

function statusLabel(status: string): string {
  if (status === "active") {
    return "进行中";
  }
  if (status === "archived") {
    return "已归档";
  }
  return status;
}

function timeLabel(value: string | null): string {
  if (!value) {
    return "还没有消息";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "还没有消息";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

async function load(silent = false): Promise<void> {
  const scope = workspace.scope;
  if (!scope) {
    loading.value = workspace.phase === "loading";
    if (workspace.phase !== "loading") {
      error.value = workspace.error || "还没有连上陪伴者";
    }
    return;
  }
  if (!silent) {
    loading.value = true;
  }
  error.value = "";
  try {
    conversations.value = await listConversations(scope);
  } catch (caught) {
    error.value = errorText(caught);
  } finally {
    loading.value = false;
  }
}

async function confirmClear(): Promise<void> {
  await confirm();
  if (!clearError.value) {
    await load(true);
  }
}

watch(() => workspace.scope, () => void load(), { immediate: true });
</script>

<template>
  <SettingsDetail title="聊天设置">
    <p v-if="loading" class="hint">正在读取对话</p>
    <div v-else class="stack">
      <p v-if="error" class="page-error">{{ error }}</p>
      <p v-else-if="conversations.length === 0" class="hint">还没有对话</p>
      <div v-else class="panel">
        <article v-for="item in conversations" :key="item.id" class="row">
          <strong>{{ item.title || "当前对话" }}</strong>
          <span>{{ statusLabel(item.status) }} · {{ timeLabel(item.last_message_at) }}</span>
        </article>
      </div>
      <section class="panel panel-body">
        <p class="hint">清空后，聊天页里的记录会消失。陪伴者自己记住的内容仍留在系统里。</p>
        <p v-if="clearError" class="page-error">{{ clearError }}</p>
        <p v-else-if="notice" class="page-note">{{ notice }}</p>
        <div v-if="confirming" class="actions">
          <AppButton variant="secondary" :disabled="clearing" @click="cancel">留下</AppButton>
          <AppButton variant="danger" :loading="clearing" @click="confirmClear">确认清空</AppButton>
        </div>
        <AppButton v-else variant="danger" @click="ask">清空聊天记录</AppButton>
      </section>
    </div>
  </SettingsDetail>
</template>

<style scoped>
.row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 16px;
}

.row + .row {
  box-shadow: inset 0 1px 0 var(--color-border);
}

.row span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.hint,
.page-error,
.page-note {
  margin-bottom: 12px;
}

.actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
</style>
