import type { StateResponse } from "@/types/api";

import { apiBaseUrl } from "./api";
import type { ConversationScope } from "./conversations";
import { ApiError, requestJson } from "./http";

export async function getState(scope: ConversationScope): Promise<StateResponse | null> {
  try {
    return await requestJson<StateResponse>(
      `${apiBaseUrl()}/api/users/${scope.userId}/companions/${scope.companionId}/state`,
    );
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) {
      return null;
    }
    throw caught;
  }
}
