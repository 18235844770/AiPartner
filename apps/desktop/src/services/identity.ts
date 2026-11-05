import type { components } from "../types/api.generated";

import { requestJson } from "./http";

export type UserResponse = components["schemas"]["UserResponse"];
export type CompanionResponse = components["schemas"]["CompanionResponse"];
export type CreateUserRequest = components["schemas"]["CreateUserRequest"];
export type CreateCompanionRequest = components["schemas"]["CreateCompanionRequest"];

function usersUrl(apiBaseUrl: string): string {
  return `${apiBaseUrl}/api/users`;
}

export function createUser(apiBaseUrl: string, body: CreateUserRequest): Promise<UserResponse> {
  return requestJson<UserResponse>(usersUrl(apiBaseUrl), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getUser(apiBaseUrl: string, userId: string): Promise<UserResponse> {
  return requestJson<UserResponse>(`${usersUrl(apiBaseUrl)}/${userId}`);
}

export function listCompanions(apiBaseUrl: string, userId: string): Promise<CompanionResponse[]> {
  return requestJson<CompanionResponse[]>(`${usersUrl(apiBaseUrl)}/${userId}/companions`);
}

export function createCompanion(
  apiBaseUrl: string,
  userId: string,
  body: CreateCompanionRequest,
): Promise<CompanionResponse> {
  return requestJson<CompanionResponse>(`${usersUrl(apiBaseUrl)}/${userId}/companions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
