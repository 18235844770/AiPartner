import type {
  CompanionResponse,
  CreateCompanionRequest,
  CreateUserRequest,
  UpdateCompanionRequest,
  UserResponse,
} from "@/types/api";

import { apiBaseUrl } from "./api";
import { ApiError, requestJson } from "./http";

function usersUrl(): string {
  return `${apiBaseUrl()}/api/users`;
}

export function createUser(body: CreateUserRequest): Promise<UserResponse> {
  return requestJson<UserResponse>(usersUrl(), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getUser(userId: string): Promise<UserResponse> {
  return requestJson<UserResponse>(`${usersUrl()}/${userId}`);
}

export function listCompanions(userId: string): Promise<CompanionResponse[]> {
  return requestJson<CompanionResponse[]>(`${usersUrl()}/${userId}/companions`);
}

export function updateCompanion(
  userId: string,
  companionId: string,
  body: UpdateCompanionRequest,
): Promise<CompanionResponse> {
  return requestJson<CompanionResponse>(`${usersUrl()}/${userId}/companions/${companionId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function createCompanion(userId: string, body: CreateCompanionRequest): Promise<CompanionResponse> {
  return requestJson<CompanionResponse>(`${usersUrl()}/${userId}/companions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

async function ensureCreated(url: string): Promise<void> {
  try {
    await requestJson(url);
  } catch (caught) {
    if (!(caught instanceof ApiError) || caught.status !== 404) {
      throw caught;
    }
    try {
      await requestJson(url, { method: "POST", body: "{}" });
    } catch (postError) {
      if (postError instanceof ApiError && postError.status === 409) {
        return;
      }
      throw postError;
    }
  }
}

export async function initializeCompanionBasics(userId: string, companionId: string): Promise<void> {
  const base = `${usersUrl()}/${userId}/companions/${companionId}`;
  await ensureCreated(`${base}/persona`);
  await ensureCreated(`${base}/state`);
}
