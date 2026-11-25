import type { HealthResponse } from "@/types/api";

import { requestJson } from "./http";

export function apiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
}

export function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${apiBaseUrl()}/health`);
}
