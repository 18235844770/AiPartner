<script setup lang="ts">
import { ref } from "vue";

import AppButton from "@/components/common/AppButton.vue";
import AppInput from "@/components/common/AppInput.vue";
import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { errorText } from "@/services/http";
import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();
const confirming = ref(false);
const deleting = ref(false);
const password = ref("");
const error = ref("");

function cancel(): void {
  confirming.value = false;
  password.value = error.value = "";
}

async function confirm(): Promise<void> {
  if (!password.value || deleting.value) return;
  deleting.value = true;
  error.value = "";
  try { await workspace.deleteAccount(password.value); }
  catch (caught) { error.value = errorText(caught); }
  finally { deleting.value = false; }
}

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
        <span>用户名</span>
        <strong>{{ workspace.user?.username || "—" }}</strong>
      </div>
      <div v-if="formatJoined(workspace.user?.created_at)" class="row">
        <span>开始使用</span>
        <strong>{{ formatJoined(workspace.user?.created_at) }}</strong>
      </div>
    </section>
    <section class="panel panel-body">
      <p class="hint">注销后将删除账号、伴侣和聊天记录。</p>
      <form v-if="confirming" class="stack" @submit.prevent="confirm">
        <AppInput v-model="password" type="password" autocomplete="current-password" placeholder="确认密码" :disabled="deleting" />
        <p v-if="error" class="page-error" role="alert">{{ error }}</p>
        <div class="actions">
          <AppButton variant="secondary" :disabled="deleting" @click="cancel">取消</AppButton>
          <AppButton type="submit" variant="danger" :disabled="!password" :loading="deleting">确认注销</AppButton>
        </div>
      </form>
      <AppButton v-else variant="danger" @click="confirming = true">注销账号</AppButton>
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
