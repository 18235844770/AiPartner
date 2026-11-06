import { ref, type Ref } from "vue";

import { compareConversations } from "../domain/presentation";
import { listConversations, type ConversationResponse, type ConversationScope } from "../services/conversations";
import { ApiError, errorText } from "../services/http";
import {
  getPersona,
  getState,
  getWorkingMemory,
  listAttentionTopics,
  listBackgroundTasks,
  listDecisions,
  listMemories,
  listModelCalls,
  listStateEvents,
  type AttentionTopicResponse,
  type BackgroundTaskResponse,
  type DecisionResponse,
  type MemoryResponse,
  type ModelCallLogResponse,
  type PersonaResponse,
  type StateEventResponse,
  type StateResponse,
  type WorkingMemoryResponse,
} from "../services/inspection";

export type DebugSection = "persona" | "memory" | "state" | "decisions" | "models";

export function useInspection(
  section: Ref<DebugSection>,
  getScope: () => ConversationScope | null,
) {
  const loading = ref(false);
  const error = ref("");
  const missing = ref("");
  const persona = ref<PersonaResponse | null>(null);
  const memories = ref<MemoryResponse[]>([]);
  const topics = ref<AttentionTopicResponse[]>([]);
  const conversations = ref<ConversationResponse[]>([]);
  const workingConversationId = ref("");
  const working = ref<WorkingMemoryResponse | null>(null);
  const workingMissing = ref(false);
  const state = ref<StateResponse | null>(null);
  const events = ref<StateEventResponse[]>([]);
  const decisions = ref<DecisionResponse[]>([]);
  const calls = ref<ModelCallLogResponse[]>([]);
  const tasks = ref<BackgroundTaskResponse[]>([]);
  let generation = 0;

  function reset(): void {
    persona.value = null;
    memories.value = [];
    topics.value = [];
    conversations.value = [];
    working.value = null;
    workingMissing.value = false;
    state.value = null;
    events.value = [];
    decisions.value = [];
    calls.value = [];
    tasks.value = [];
  }

  async function loadWorking(scope: ConversationScope, ticket: number): Promise<void> {
    const conversationId = workingConversationId.value;
    if (!conversationId) {
      working.value = null;
      workingMissing.value = false;
      return;
    }
    try {
      const row = await getWorkingMemory(scope, conversationId);
      if (ticket !== generation) {
        return;
      }
      working.value = row;
      workingMissing.value = false;
    } catch (caught) {
      if (ticket !== generation) {
        return;
      }
      working.value = null;
      if (caught instanceof ApiError && caught.status === 404) {
        workingMissing.value = true;
        return;
      }
      error.value = errorText(caught);
    }
  }

  async function reload(): Promise<void> {
    const scope = getScope();
    const ticket = ++generation;
    if (!scope) {
      reset();
      return;
    }
    loading.value = true;
    error.value = "";
    missing.value = "";
    try {
      if (section.value === "persona") {
        persona.value = await getPersona(scope);
      } else if (section.value === "memory") {
        const [memoryRows, topicRows, conversationRows] = await Promise.all([
          listMemories(scope),
          listAttentionTopics(scope),
          listConversations(scope),
        ]);
        if (ticket !== generation) {
          return;
        }
        memories.value = memoryRows;
        topics.value = topicRows;
        conversations.value = [...conversationRows].sort(compareConversations);
        if (
          workingConversationId.value &&
          !conversations.value.some((item) => item.id === workingConversationId.value)
        ) {
          workingConversationId.value = "";
        }
        if (!workingConversationId.value && conversations.value[0]) {
          workingConversationId.value = conversations.value[0].id;
        }
        await loadWorking(scope, ticket);
      } else if (section.value === "state") {
        const [current, history] = await Promise.all([getState(scope), listStateEvents(scope)]);
        if (ticket !== generation) {
          return;
        }
        state.value = current;
        events.value = history;
      } else if (section.value === "decisions") {
        decisions.value = await listDecisions(scope);
      } else {
        const [callRows, taskRows] = await Promise.all([
          listModelCalls(scope),
          listBackgroundTasks(scope),
        ]);
        if (ticket !== generation) {
          return;
        }
        calls.value = callRows;
        tasks.value = taskRows;
      }
    } catch (caught) {
      if (ticket !== generation) {
        return;
      }
      reset();
      if (caught instanceof ApiError && caught.status === 404) {
        missing.value = caught.message;
        return;
      }
      error.value = errorText(caught);
    } finally {
      if (ticket === generation) {
        loading.value = false;
      }
    }
  }

  async function selectWorking(conversationId: string): Promise<void> {
    const scope = getScope();
    workingConversationId.value = conversationId;
    if (!scope) {
      return;
    }
    const ticket = generation;
    error.value = "";
    await loadWorking(scope, ticket);
  }

  return {
    loading,
    error,
    missing,
    persona,
    memories,
    topics,
    conversations,
    workingConversationId,
    working,
    workingMissing,
    state,
    events,
    decisions,
    calls,
    tasks,
    reload,
    selectWorking,
  };
}
