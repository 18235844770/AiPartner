import type { components } from "../types/api.generated";

import type { ConversationScope } from "./conversations";
import { requestJson } from "./http";

export type PersonaResponse = components["schemas"]["PersonaResponse"];
export type MemoryResponse = components["schemas"]["MemoryResponse"];
export type AttentionTopicResponse = components["schemas"]["AttentionTopicResponse"];
export type WorkingMemoryResponse = components["schemas"]["WorkingMemoryResponse"];
export type StateResponse = components["schemas"]["StateResponse"];
export type StateEventResponse = components["schemas"]["StateEventResponse"];
export type DecisionResponse = components["schemas"]["DecisionResponse"];
export type ModelCallLogResponse = components["schemas"]["ModelCallLogResponse"];
export type BackgroundTaskResponse = components["schemas"]["BackgroundTaskResponse"];

function companionUrl(scope: ConversationScope, suffix: string): string {
  return `${scope.apiBaseUrl}/api/users/${scope.userId}/companions/${scope.companionId}${suffix}`;
}

export function getPersona(scope: ConversationScope): Promise<PersonaResponse> {
  return requestJson<PersonaResponse>(companionUrl(scope, "/persona"));
}

export function listMemories(scope: ConversationScope): Promise<MemoryResponse[]> {
  return requestJson<MemoryResponse[]>(companionUrl(scope, "/memories"));
}

export function listAttentionTopics(scope: ConversationScope): Promise<AttentionTopicResponse[]> {
  return requestJson<AttentionTopicResponse[]>(companionUrl(scope, "/attention-topics"));
}

export function getWorkingMemory(
  scope: ConversationScope,
  conversationId: string,
): Promise<WorkingMemoryResponse> {
  return requestJson<WorkingMemoryResponse>(
    companionUrl(scope, `/conversations/${conversationId}/working-memory`),
  );
}

export function getState(scope: ConversationScope): Promise<StateResponse> {
  return requestJson<StateResponse>(companionUrl(scope, "/state"));
}

export function listStateEvents(scope: ConversationScope): Promise<StateEventResponse[]> {
  return requestJson<StateEventResponse[]>(companionUrl(scope, "/state/events"));
}

export function listDecisions(scope: ConversationScope): Promise<DecisionResponse[]> {
  return requestJson<DecisionResponse[]>(companionUrl(scope, "/decisions"));
}

export function listModelCalls(scope: ConversationScope): Promise<ModelCallLogResponse[]> {
  return requestJson<ModelCallLogResponse[]>(companionUrl(scope, "/model-call-logs"));
}

export function listBackgroundTasks(scope: ConversationScope): Promise<BackgroundTaskResponse[]> {
  return requestJson<BackgroundTaskResponse[]>(companionUrl(scope, "/background-tasks"));
}
