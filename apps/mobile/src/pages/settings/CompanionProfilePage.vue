<script setup lang="ts">
import { ref, watch } from "vue";

import AppButton from "@/components/common/AppButton.vue";
import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { readPersonaView, type PersonaView } from "@/domain/persona-view";
import { errorText } from "@/services/http";
import { getPersona } from "@/services/persona";
import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();
const name = ref("");
const description = ref("");
const persona = ref<PersonaView | null>(null);
const loading = ref(true);
const saving = ref(false);
const error = ref("");
const personaNote = ref("");
const saved = ref("");

watch(
  () => workspace.companion,
  (companion) => {
    if (!companion) {
      return;
    }
    name.value = companion.name;
    description.value = companion.description ?? "";
  },
  { immediate: true },
);

watch(
  () => workspace.scope,
  (scope) => {
    if (!scope) {
      loading.value = workspace.phase === "loading";
      if (workspace.phase !== "loading") {
        error.value = workspace.error || "还没有连上陪伴者";
      }
      return;
    }
    loading.value = true;
    error.value = "";
    personaNote.value = "";
    void getPersona(scope)
      .then((current) => {
        persona.value = readPersonaView(current);
      })
      .catch((caught: unknown) => {
        persona.value = null;
        personaNote.value = errorText(caught);
      })
      .finally(() => {
        loading.value = false;
      });
  },
  { immediate: true },
);

async function save(): Promise<void> {
  const trimmed = name.value.trim();
  if (!trimmed) {
    error.value = "名字不能为空";
    return;
  }
  saving.value = true;
  error.value = "";
  saved.value = "";
  try {
    const current = workspace.companion?.description ?? "";
    const nextDescription = description.value.trim();
    await workspace.saveCompanion({
      name: trimmed,
      ...(nextDescription !== current ? { description: nextDescription } : {}),
    });
    saved.value = "已保存";
  } catch (caught) {
    error.value = errorText(caught);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <SettingsDetail title="角色资料">
    <p v-if="loading" class="hint">正在读取资料</p>
    <form v-else class="stack" @submit.prevent="save">
      <section class="panel panel-body">
        <label class="label" for="companion-name">名字</label>
        <input id="companion-name" v-model="name" type="text" maxlength="64" autocomplete="off" />
        <label class="label" for="companion-description">介绍</label>
        <textarea id="companion-description" v-model="description" rows="3" maxlength="200" />
        <p v-if="error" class="page-error">{{ error }}</p>
        <p v-else-if="saved" class="page-note">{{ saved }}</p>
        <AppButton type="submit" :loading="saving">保存</AppButton>
      </section>

      <section class="panel panel-body">
        <h2 class="kicker inner">人格</h2>
        <p v-if="personaNote" class="hint">{{ personaNote }}</p>
        <template v-else-if="persona">
          <p class="mbti">{{ persona.mbti }}</p>
          <p v-if="persona.summary" class="summary">{{ persona.summary }}</p>
          <ul v-if="persona.interests.length" class="interests">
            <li v-for="item in persona.interests" :key="item">{{ item }}</li>
          </ul>
        </template>
        <p class="hint stay">核心人格会一直保持，这里只展示现在的样子。</p>
      </section>
    </form>
  </SettingsDetail>
</template>

<style scoped>
.label {
  display: block;
  margin-bottom: 6px;
  color: #9a96a8;
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.label + input,
.label + textarea,
input + .label {
  margin-top: 12px;
}

input,
textarea {
  width: 100%;
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 0;
  border-radius: 14px;
  background: var(--color-input);
  font: inherit;
  resize: none;
}

.page-error,
.page-note {
  margin-bottom: 12px;
}

.inner {
  margin: 0 0 8px;
}

.mbti {
  display: inline-flex;
  margin-bottom: 8px;
  padding: 2px 10px;
  border-radius: var(--radius-round);
  background: var(--color-primary-soft);
  color: var(--color-primary-deep);
  font-weight: 700;
}

.summary {
  line-height: 1.6;
}

.interests {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.interests li {
  padding: 4px 10px;
  border-radius: var(--radius-round);
  background: #f6f4fb;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.stay {
  margin-top: 12px;
}
</style>
