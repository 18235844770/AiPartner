<script setup lang="ts">
import { ref, watch } from "vue";

import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import {
  fetchAudioHealth,
  getVoicePreset,
  listVoicePresets,
  setVoicePreset,
  type VoicePreset,
} from "@/services/audio";
import { errorText } from "@/services/http";
import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();
const presets = ref<VoicePreset[]>([]);
const selectedId = ref("");
const healthLabel = ref("");
const loading = ref(true);
const savingId = ref("");
const error = ref("");

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
    void Promise.all([listVoicePresets(), getVoicePreset(scope)])
      .then(([catalog, selection]) => {
        presets.value = catalog;
        selectedId.value = selection.preset_id ?? selection.preset?.id ?? "";
      })
      .catch((caught: unknown) => {
        error.value = errorText(caught);
      })
      .finally(() => {
        loading.value = false;
      });
    void fetchAudioHealth()
      .then((health) => {
        healthLabel.value = health.status === "ok" && health.worker.reachable ? "语音服务可用" : "语音服务暂时不可用";
      })
      .catch(() => {
        healthLabel.value = "语音服务暂时不可用";
      });
  },
  { immediate: true },
);

async function choose(preset: VoicePreset): Promise<void> {
  const scope = workspace.scope;
  if (!scope || savingId.value || preset.id === selectedId.value) {
    return;
  }
  const previous = selectedId.value;
  savingId.value = preset.id;
  error.value = "";
  try {
    const selection = await setVoicePreset(scope, preset.id);
    selectedId.value = selection.preset_id ?? preset.id;
  } catch (caught) {
    selectedId.value = previous;
    error.value = errorText(caught);
  } finally {
    savingId.value = "";
  }
}
</script>

<template>
  <SettingsDetail title="语音" :show-back="false" tab>
    <p v-if="loading" class="hint">正在读取音色</p>
    <div v-else class="stack">
      <p v-if="healthLabel" class="hint">{{ healthLabel }}</p>
      <p v-if="error" class="page-error">{{ error }}</p>
      <div v-if="presets.length" class="panel">
        <button
          v-for="preset in presets"
          :key="preset.id"
          type="button"
          class="row"
          :class="{ selected: preset.id === selectedId }"
          :disabled="Boolean(savingId)"
          :aria-pressed="preset.id === selectedId"
          @click="choose(preset)"
        >
          <span>
            <strong>{{ preset.name }}</strong>
            <small>{{ preset.provider_label }}</small>
          </span>
          <i v-if="preset.id === selectedId" />
        </button>
      </div>
      <p v-else-if="!error" class="hint">还没有可选音色</p>
    </div>
  </SettingsDetail>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-height: 64px;
  padding: 10px 16px;
  text-align: left;
}

.row + .row {
  box-shadow: inset 0 1px 0 var(--color-border);
}

.row span {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

small {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.row.selected strong {
  color: var(--color-primary-deep);
}

.row i {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-primary);
  flex: none;
}

.row:disabled {
  opacity: 0.7;
}
</style>
