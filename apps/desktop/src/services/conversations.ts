import type { components } from "../types/api.generated";

import { requestJson } from "./http";

export type ConversationResponse = components["schemas"]["ConversationResponse"];
export type MessageResponse = components["schemas"]["MessageResponse"];
export type CreateConversationRequest = components["schemas"]["CreateConversationRequest"];
export type CreateMessageRequest = components["schemas"]["CreateMessageRequest"];

export type ConversationScope = {
  apiBaseUrl: string;
  userId: string;
  companionId: string;
};

function conversationsUrl(scope: ConversationScope): string {
  return `${scope.apiBaseUrl}/api/users/${scope.userId}/companions/${scope.companionId}/conversations`;
}

export function listConversations(scope: ConversationScope): Promise<ConversationResponse[]> {
  return requestJson<ConversationResponse[]>(conversationsUrl(scope));
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

export function archiveConversation(
  scope: ConversationScope,
  conversationId: string,
): Promise<ConversationResponse> {
  return requestJson<ConversationResponse>(`${conversationsUrl(scope)}/${conversationId}/archive`, {
    method: "POST",
  });
}

export function listMessages(scope: ConversationScope, conversationId: string): Promise<MessageResponse[]> {
  return requestJson<MessageResponse[]>(`${conversationsUrl(scope)}/${conversationId}/messages`);
}

export function appendMessage(
  scope: ConversationScope,
  conversationId: string,
  body: CreateMessageRequest,
): Promise<MessageResponse> {
  return requestJson<MessageResponse>(`${conversationsUrl(scope)}/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
