<script setup lang="ts">
import type { HealthResponse, ServiceStatus } from "../services/api";

defineProps<{
  service: ServiceStatus | null;
  health: HealthResponse | null;
  error: string;
}>();

function serviceLabel(state: ServiceStatus["state"] | undefined): string {
  if (state === "starting") {
    return "启动中";
  }
  if (state === "running") {
    return "运行中";
  }
  if (state === "failed") {
    return "失败";
  }
  if (state === "browser") {
    return "浏览器";
  }
  return "检查中";
}

function probeLabel(value: string | undefined): string {
  if (value === "ok") {
    return "正常";
  }
  if (value === "down") {
    return "不可用";
  }
  if (value === "unknown") {
    return "未知";
  }
  if (value === "degraded") {
    return "降级";
  }
  return "—";
}
</script>

<template>
  <section class="status-page">
    <header>
      <p class="eyebrow">运行状态</p>
      <h2>本地服务</h2>
      <p class="lead">{{ service?.detail ?? "正在读取服务状态" }}</p>
    </header>

    <div class="grid">
      <article>
        <h3>Python 服务</h3>
        <p class="value">{{ serviceLabel(service?.state) }}</p>
        <p>{{ service?.apiBaseUrl ?? "http://127.0.0.1:8000" }}</p>
      </article>
      <article>
        <h3>接口</h3>
        <p class="value">{{ probeLabel(health?.api) }}</p>
        <p>整体：{{ probeLabel(health?.status) }}</p>
      </article>
      <article>
        <h3>PostgreSQL</h3>
        <p class="value">{{ probeLabel(health?.database) }}</p>
        <p>pgvector：{{ probeLabel(health?.pgvector) }}</p>
      </article>
      <article>
        <h3>Redis</h3>
        <p class="value">{{ probeLabel(health?.redis) }}</p>
        <p>调度和运行时辅助</p>
      </article>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
  </section>
</template>
