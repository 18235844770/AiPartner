import type { PersonaResponse } from "@/types/api";

import { apiBaseUrl } from "./api";
import type { ConversationScope } from "./conversations";
import { requestJson } from "./http";

export function getPersona(scope: ConversationScope): Promise<PersonaResponse> {
  return requestJson<PersonaResponse>(
    `${apiBaseUrl()}/api/users/${scope.userId}/companions/${scope.companionId}/persona`,
  );
}
