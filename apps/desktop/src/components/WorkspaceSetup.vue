<script setup lang="ts">
import { ref } from "vue";

import type { IdentityDraft } from "../composables/useWorkspace";
import type { UserResponse } from "../services/identity";

const props = defineProps<{
  user: UserResponse | null;
  busy: boolean;
  error: string;
}>();

const emit = defineEmits<{
  submit: [draft: IdentityDraft];
}>();

const displayName = ref("");
const timezone = ref(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
const locale = ref("zh-CN");
const companionName = ref("");
const companionDescription = ref("");
const companionIsDefault = ref(true);
const formError = ref("");

function submit(): void {
  formError.value = "";
  if (!props.user && !displayName.value.trim()) {
    formError.value = "显示名称不能为空";
    return;
  }
  if (!companionName.value.trim()) {
    formError.value = "陪伴者名称不能为空";
    return;
  }
  emit("submit", {
    displayName: displayName.value,
    timezone: timezone.value,
    locale: locale.value,
    companionName: companionName.value,
    companionDescription: companionDescription.value,
    companionIsDefault: companionIsDefault.value,
  });
}
</script>

<template>
  <section class="setup">
    <header>
      <p class="eyebrow">本地身份</p>
      <h2>建立调试身份</h2>
      <p class="lead">
        第一版没有账号登录。这里创建的用户和陪伴者只用于区分数据归属，并保存在这台电脑上。
      </p>
    </header>

    <form class="setup-form" @submit.prevent="submit">
      <template v-if="user">
        <p class="notice">用户已建立：{{ user.display_name }}。继续创建陪伴者。</p>
      </template>
      <template v-else>
        <label>
          显示名称
          <input v-model="displayName" maxlength="64" autocomplete="name" />
        </label>
        <div class="split">
          <label>
            时区
            <input v-model="timezone" maxlength="64" />
          </label>
          <label>
            语言
            <input v-model="locale" maxlength="16" />
          </label>
        </div>
      </template>

      <label>
        陪伴者名称
        <input v-model="companionName" maxlength="64" />
      </label>
      <label>
        简介
        <textarea v-model="companionDescription" rows="3" placeholder="可选"></textarea>
      </label>
      <label class="check">
        <input v-model="companionIsDefault" type="checkbox" />
        设为默认陪伴者
      </label>

      <p v-if="formError || error" class="error">{{ formError || error }}</p>
      <button class="primary" type="submit" :disabled="busy">
        {{ busy ? "正在保存" : user ? "创建陪伴者" : "建立身份" }}
      </button>
    </form>
  </section>
</template>
