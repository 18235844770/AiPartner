<script setup lang="ts">
import AppButton from "@/components/common/AppButton.vue";
import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { useClearChat } from "@/composables/useClearChat";
import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();
const { confirming, clearing, error, notice, ask, cancel, confirm } = useClearChat();

function formatJoined(value: string | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric" }).format(date);
}
</script>

<template>
  <SettingsDetail title="数据与隐私">
    <section class="panel">
      <div class="row">
        <span>称呼</span>
        <strong>{{ workspace.user?.display_name || "—" }}</strong>
      </div>
      <div class="row">
        <span>时区</span>
        <strong>{{ workspace.user?.timezone || "—" }}</strong>
      </div>
      <div class="row">
        <span>语言</span>
        <strong>{{ workspace.user?.locale || "—" }}</strong>
      </div>
      <div v-if="formatJoined(workspace.user?.created_at)" class="row">
        <span>开始使用</span>
        <strong>{{ formatJoined(workspace.user?.created_at) }}</strong>
      </div>
    </section>
    <section class="panel panel-body">
      <p class="hint">清空只会删掉这段聊天记录。记忆、情绪和关系仍由陪伴者自己维护。</p>
      <p v-if="error" class="page-error">{{ error }}</p>
      <p v-else-if="notice" class="page-note">{{ notice }}</p>
      <div v-if="confirming" class="actions">
        <AppButton variant="secondary" :disabled="clearing" @click="cancel">留下</AppButton>
        <AppButton variant="danger" :loading="clearing" @click="confirm">确认清空</AppButton>
      </div>
      <AppButton v-else variant="danger" @click="ask">清空聊天记录</AppButton>
    </section>
  </SettingsDetail>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 52px;
  padding: 0 16px;
}

.row + .row {
  box-shadow: inset 0 1px 0 var(--color-border);
}

.row span {
  color: var(--color-text-secondary);
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
