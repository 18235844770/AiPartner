import type { components } from "../types/api.generated";

import { requestJson } from "./http";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export type HealthResponse = components["schemas"]["HealthResponse"];

export type ServiceState = "starting" | "running" | "failed" | "browser";

export type ServiceStatus = {
  state: ServiceState;
  detail: string;
  apiBaseUrl: string;
};

export async function getServiceStatus(): Promise<ServiceStatus> {
  if (window.companion) {
    return window.companion.getServiceStatus();
  }
  return {
    state: "browser",
    detail: "当前在浏览器中打开，未由 Electron 托管 Python 服务",
    apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  };
}

export function fetchHealth(apiBaseUrl: string): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${apiBaseUrl}/health`);
}
