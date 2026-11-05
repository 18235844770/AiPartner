import { computed, onMounted, onUnmounted, ref } from "vue";

import { fetchHealth, getServiceStatus, type HealthResponse, type ServiceStatus } from "../services/api";
import { errorText } from "../services/http";

export function useServiceStatus() {
  const service = ref<ServiceStatus | null>(null);
  const health = ref<HealthResponse | null>(null);
  const error = ref("");
  const apiBaseUrl = computed(() => service.value?.apiBaseUrl ?? "");

  async function refresh(): Promise<void> {
    try {
      service.value = await getServiceStatus();
      health.value = await fetchHealth(service.value.apiBaseUrl);
      error.value = "";
    } catch (caught) {
      health.value = null;
      error.value = errorText(caught);
    }
  }

  let timer = 0;

  onMounted(() => {
    void refresh();
    timer = window.setInterval(() => {
      void refresh();
    }, 5000);
  });

  onUnmounted(() => {
    window.clearInterval(timer);
  });

  return { service, health, error, apiBaseUrl, refresh };
}
