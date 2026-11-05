<script setup lang="ts">
import { computed, ref, watch } from "vue";

import ChatPanel from "./components/ChatPanel.vue";
import StatusPanel from "./components/StatusPanel.vue";
import WorkspaceSetup from "./components/WorkspaceSetup.vue";
import { useServiceStatus } from "./composables/useServiceStatus";
import { useWorkspace, type CompanionDraft, type IdentityDraft } from "./composables/useWorkspace";

const { service, health, error: serviceError, apiBaseUrl } = useServiceStatus();
const {
  phase,
  user,
  companion,
  companions,
  error: workspaceError,
  busy,
  restore,
  createIdentity,
  addCompanion,
  selectCompanion,
  forget,
} = useWorkspace();

const view = ref<"chat" | "status">("chat");
const companionName = ref("");
const companionDescription = ref("");
const companionIsDefault = ref(false);

const connectionLabel = computed(() => {
  if (serviceError.value) {
    return "未连接";
  }
  if (!health.value) {
    return "检查中";
  }
  return health.value.status === "ok" ? "服务正常" : "服务降级";
});

watch(
  apiBaseUrl,
  (url) => {
    if (url) {
      void restore(url);
    }
  },
  { immediate: true },
);

function submitIdentity(draft: IdentityDraft): void {
  if (!apiBaseUrl.value) {
    return;
  }
  void createIdentity(apiBaseUrl.value, draft);
}

function submitCompanion(): void {
  if (!apiBaseUrl.value || !companionName.value.trim()) {
    return;
  }
  const draft: CompanionDraft = {
    name: companionName.value,
    description: companionDescription.value,
    isDefault: companionIsDefault.value,
  };
  void addCompanion(apiBaseUrl.value, draft).then(() => {
    if (!workspaceError.value) {
      companionName.value = "";
      companionDescription.value = "";
      companionIsDefault.value = false;
    }
  });
}

function onSelectCompanion(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLSelectElement) {
    selectCompanion(target.value);
  }
}

function retryWorkspace(): void {
  if (apiBaseUrl.value) {
    void restore(apiBaseUrl.value);
  }
}
</script>

<template>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <p class="eyebrow">AI Companion</p>
        <h1>调试台</h1>
      </div>

      <nav class="nav" aria-label="调试台">
        <button type="button" :class="{ active: view === 'chat' }" @click="view = 'chat'">会话</button>
        <button type="button" :class="{ active: view === 'status' }" @click="view = 'status'">系统</button>
      </nav>

      <div class="sidebar-foot">
      <section v-if="user" class="identity">
        <p class="identity-label">用户</p>
        <p class="identity-name">{{ user.display_name }}</p>
        <label v-if="companions.length > 0">
          陪伴者
          <select :value="companion?.id ?? ''" @change="onSelectCompanion">
            <option v-for="item in companions" :key="item.id" :value="item.id">
              {{ item.name }}{{ item.is_default ? " · 默认" : "" }}
            </option>
          </select>
        </label>

        <details>
          <summary>新建陪伴者</summary>
          <form class="stack" @submit.prevent="submitCompanion">
            <input v-model="companionName" maxlength="64" placeholder="名称" />
            <input v-model="companionDescription" placeholder="简介，可选" />
            <label class="check">
              <input v-model="companionIsDefault" type="checkbox" />
              设为默认
            </label>
            <button class="secondary" type="submit" :disabled="busy || !companionName.trim()">创建</button>
          </form>
        </details>
        <p v-if="phase === 'ready' && workspaceError" class="error">{{ workspaceError }}</p>
        <button type="button" class="text-button" @click="forget">清除本地身份</button>
      </section>

      <p class="connection" :data-state="health?.status ?? 'unknown'">{{ connectionLabel }}</p>
      </div>
    </aside>

    <main class="workspace">
      <StatusPanel v-if="view === 'status'" :service="service" :health="health" :error="serviceError" />
      <p v-else-if="phase === 'loading'" class="workspace-message">正在读取本地身份</p>
      <section v-else-if="phase === 'unavailable'" class="setup">
        <header>
          <p class="eyebrow">本地身份</p>
          <h2>暂时读不到已保存的身份</h2>
          <p class="lead">{{ workspaceError }}</p>
        </header>
        <button class="primary" type="button" @click="retryWorkspace">重试</button>
      </section>
      <WorkspaceSetup
        v-else-if="phase === 'setup'"
        :user="user"
        :busy="busy"
        :error="workspaceError"
        @submit="submitIdentity"
      />
      <ChatPanel
        v-else-if="companion && apiBaseUrl"
        :api-base-url="apiBaseUrl"
        :user-id="user?.id ?? ''"
        :companion-id="companion.id"
        :companion-name="companion.name"
      />
    </main>
  </div>
</template>
