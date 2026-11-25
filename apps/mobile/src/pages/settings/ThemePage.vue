<script setup lang="ts">
import SettingsDetail from "@/components/layout/SettingsDetail.vue";

const swatches = [
  { name: "主色", color: "#7b55f5" },
  { name: "淡紫", color: "#eee8ff" },
  { name: "薄荷", color: "#91dccb" },
  { name: "黄", color: "#ffd45d" },
  { name: "粉", color: "#f6a9d1" },
  { name: "蓝", color: "#a9c9fa" },
];
</script>

<template>
  <SettingsDetail title="外观设置">
    <section class="panel panel-body">
      <h2>Pastel Companion</h2>
      <p class="hint">现在整个应用用的是这一套柔和配色。</p>
      <ul>
        <li v-for="item in swatches" :key="item.name">
          <i :style="{ background: item.color }" />
          <span>{{ item.name }}</span>
        </li>
      </ul>
    </section>
  </SettingsDetail>
</template>

<style scoped>
h2 {
  font-size: 18px;
  font-weight: 800;
}

.hint {
  margin: 6px 0 14px;
}

ul {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

li {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

i {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  box-shadow: inset 0 0 0 1px rgba(36, 31, 56, 0.06);
}
</style>
