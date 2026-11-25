<script setup lang="ts">
import { onMounted, ref } from "vue";

import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { fetchHealth } from "@/services/api";
import { errorText } from "@/services/http";
import type { HealthResponse } from "@/types/api";

const health = ref<HealthResponse | null>(null);
const loading = ref(true);
const error = ref("");

const labels: { key: keyof HealthResponse; label: string }[] = [
  { key: "api", label: "接口" },
  { key: "database", label: "数据库" },
  { key: "pgvector", label: "向量" },
  { key: "redis", label: "任务队列" },
];

function serviceLabel(value: string): string {
  if (value === "ok") {
    return "正常";
  }
  if (value === "degraded") {
    return "部分异常";
  }
  if (value === "down") {
    return "不可用";
  }
  if (value === "unknown") {
    return "未知";
  }
  return value;
}

onMounted(() => {
  void fetchHealth()
    .then((current) => {
      health.value = current;
    })
    .catch((caught: unknown) => {
      error.value = errorText(caught);
    })
    .finally(() => {
      loading.value = false;
    });
});
</script>

<template>
  <SettingsDetail title="关于我们">
    <section class="panel panel-body intro">
      <h2>遇见</h2>
      <p class="hint">一个有自己人格、会记住相处、也可以选择安静的陪伴者。</p>
    </section>
    <p v-if="loading" class="hint">正在检查服务</p>
    <p v-else-if="error" class="page-error">{{ error }}</p>
    <section v-else-if="health" class="panel">
      <div v-for="item in labels" :key="item.key" class="row">
        <span>{{ item.label }}</span>
        <strong :class="{ down: health[item.key] !== 'ok' }">{{ serviceLabel(health[item.key]) }}</strong>
      </div>
    </section>
  </SettingsDetail>
</template>

<style scoped>
.intro h2 {
  font-size: 22px;
  font-weight: 800;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 52px;
  padding: 0 16px;
}

.row + .row {
  box-shadow: inset 0 1px 0 var(--color-border);
}

.row span {
  color: var(--color-text-secondary);
}

.down {
  color: var(--color-danger);
}
</style>
