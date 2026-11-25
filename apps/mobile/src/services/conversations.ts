import type { ConversationResponse, CreateConversationRequest, MessageResponse } from "@/types/api";

import { apiBaseUrl } from "./api";
import { requestJson } from "./http";

export type ConversationScope = {
  userId: string;
  companionId: string;
};

function conversationsUrl(scope: ConversationScope): string {
  return `${apiBaseUrl()}/api/users/${scope.userId}/companions/${scope.companionId}/conversations`;
}

export function createConversation(
  scope: ConversationScope,
  body: CreateConversationRequest,
): Promise<ConversationResponse> {
  return requestJson<ConversationResponse>(conversationsUrl(scope), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listMessages(scope: ConversationScope, conversationId: string): Promise<MessageResponse[]> {
  return requestJson<MessageResponse[]>(`${conversationsUrl(scope)}/${conversationId}/messages`);
}

export function listConversations(scope: ConversationScope): Promise<ConversationResponse[]> {
  return requestJson<ConversationResponse[]>(conversationsUrl(scope));
}

export function clearMessages(scope: ConversationScope, conversationId: string): Promise<{ deleted_count: number }> {
  return requestJson<{ deleted_count: number }>(`${conversationsUrl(scope)}/${conversationId}/messages`, {
    method: "DELETE",
  });
}
