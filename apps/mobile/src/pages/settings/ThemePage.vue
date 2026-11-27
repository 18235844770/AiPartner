<script setup lang="ts">
import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { themes, useThemeStore } from "@/stores/theme";

const theme = useThemeStore();
</script>

<template>
  <SettingsDetail title="主题">
    <div class="stack" aria-label="主题">
      <button v-for="(option, id) in themes" :key="id" type="button" class="panel option"
        :aria-pressed="theme.id === id" @click="theme.select(id)">
        <span class="sample" :style="{ background: option.colors[0] }" aria-hidden="true">
          <i v-for="color in option.colors.slice(1)" :key="color" :style="{ background: color }" />
        </span>
        <span class="copy">
          <strong>{{ option.name }}</strong>
          <small>{{ option.description }}</small>
        </span>
        <span v-if="theme.id === id" class="selected">已选</span>
      </button>
    </div>
  </SettingsDetail>
</template>

<style scoped>
.option {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 14px;
  min-height: 74px;
  padding: 12px 16px;
  text-align: left;
}

.sample {
  display: flex;
  flex: none;
  align-items: center;
  gap: 4px;
  padding: 8px;
  border-radius: 10px;
}

.sample i { width: 14px; height: 14px; border-radius: 50%; }
.copy { display: grid; flex: 1; min-width: 0; }
.copy small { color: var(--color-text-secondary); }
.selected { flex: none; color: var(--color-primary-deep); font-size: var(--font-size-sm); }

.option[aria-pressed="true"] {
  box-shadow: inset 0 0 0 1.5px var(--color-primary-light);
}
</style>
