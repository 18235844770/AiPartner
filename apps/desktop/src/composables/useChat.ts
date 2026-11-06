import { computed, ref, watch } from "vue";

import { compareConversations } from "../domain/presentation";
import {
  archiveConversation,
  createConversation,
  listConversations,
  listMessages,
  type ConversationResponse,
  type ConversationScope,
  type MessageResponse,
} from "../services/conversations";
import { errorText } from "../services/http";
import { streamUserTurn, type TurnEvent } from "../services/turns";

export function useChat(getScope: () => ConversationScope | null) {
  const conversations = ref<ConversationResponse[]>([]);
  const messages = ref<MessageResponse[]>([]);
  const selectedId = ref<string | null>(null);
  const loadingList = ref(false);
  const loadingMessages = ref(false);
  const creating = ref(false);
  const sending = ref(false);
  const error = ref("");
  let scopeGeneration = 0;
  let messageLoad = 0;
  let turnAbort: AbortController | null = null;

  const selected = computed(
    () => conversations.value.find((item) => item.id === selectedId.value) ?? null,
  );

  function replaceConversation(conversation: ConversationResponse): void {
    const remaining = conversations.value.filter((item) => item.id !== conversation.id);
    conversations.value = [...remaining, conversation].sort(compareConversations);
  }

  async function refreshConversations(selectLatest: boolean): Promise<void> {
    const scope = getScope();
    if (!scope) {
      return;
    }
    const generation = scopeGeneration;
    loadingList.value = true;
    error.value = "";
    try {
      const items = await listConversations(scope);
      if (generation !== scopeGeneration) {
        return;
      }
      conversations.value = [...items].sort(compareConversations);
      if (selectedId.value && !conversations.value.some((item) => item.id === selectedId.value)) {
        selectedId.value = null;
        messages.value = [];
      }
      if (selectLatest && !selectedId.value) {
        const latest = conversations.value[0];
        if (latest) {
          await openConversation(latest.id);
        }
      }
    } catch (caught) {
      if (generation === scopeGeneration) {
        error.value = errorText(caught);
      }
    } finally {
      if (generation === scopeGeneration) {
        loadingList.value = false;
      }
    }
  }

  async function openConversation(conversationId: string): Promise<void> {
    const scope = getScope();
    if (!scope) {
      return;
    }
    const generation = scopeGeneration;
    const load = ++messageLoad;
    selectedId.value = conversationId;
    loadingMessages.value = true;
    error.value = "";
    try {
      const items = await listMessages(scope, conversationId);
      if (generation !== scopeGeneration || load !== messageLoad) {
        return;
      }
      messages.value = items;
    } catch (caught) {
      if (generation !== scopeGeneration || load !== messageLoad) {
        return;
      }
      messages.value = [];
      error.value = errorText(caught);
    } finally {
      if (generation === scopeGeneration && load === messageLoad) {
        loadingMessages.value = false;
      }
    }
  }

  async function startConversation(title: string): Promise<void> {
    const scope = getScope();
    if (!scope) {
      return;
    }
    const trimmed = title.trim();
    const generation = scopeGeneration;
    creating.value = true;
    error.value = "";
    try {
      const created = await createConversation(scope, { title: trimmed || null });
      if (generation !== scopeGeneration) {
        return;
      }
      replaceConversation(created);
      await openConversation(created.id);
    } catch (caught) {
      if (generation === scopeGeneration) {
        error.value = errorText(caught);
      }
    } finally {
      if (generation === scopeGeneration) {
        creating.value = false;
      }
    }
  }

  async function sendMessage(content: string): Promise<boolean> {
    const scope = getScope();
    const conversation = selected.value;
    const trimmed = content.trim();
    if (!scope || !conversation || !trimmed || sending.value) {
      return false;
    }
    const clientMessageId = crypto.randomUUID();
    const generation = scopeGeneration;
    const controller = new AbortController();
    turnAbort = controller;
    sending.value = true;
    error.value = "";
    let outcome = "";
    messages.value = [
      ...messages.value,
      {
        id: clientMessageId,
        conversation_id: conversation.id,
        sequence_number: conversation.next_sequence_number,
        client_message_id: clientMessageId,
        sender_type: "user",
        content_type: "text",
        content: trimmed,
        status: "recorded",
        metadata: {},
        created_at: new Date().toISOString(),
      },
    ];
    try {
      await streamUserTurn(scope, conversation.id, trimmed, clientMessageId, controller.signal, (event) => {
        if (generation !== scopeGeneration) {
          return;
        }
        outcome = applyTurnEvent(conversation.id, event, outcome);
      });
      const turnError = error.value;
      if (generation === scopeGeneration) {
        await openConversation(conversation.id);
        if (turnError) {
          error.value = turnError;
        }
      }
      return outcome === "replied" || outcome === "quiet";
    } catch (caught) {
      if (generation === scopeGeneration) {
        const message = isAbortError(caught) ? "已停止" : errorText(caught);
        await openConversation(conversation.id);
        error.value = message;
      }
      return false;
    } finally {
      if (turnAbort === controller) {
        turnAbort = null;
      }
      if (generation === scopeGeneration) {
        sending.value = false;
      }
    }
  }

  function stop(): void {
    turnAbort?.abort();
  }

  function applyTurnEvent(conversationId: string, event: TurnEvent, current: string): string {
    if (event.event === "message.started") {
      const messageId = textValue(event.data.message_id);
      if (messageId) {
        upsertCompanion(conversationId, messageId, "", "generating");
      }
      return current;
    }
    if (event.event === "message.delta") {
      const messageId = textValue(event.data.message_id);
      const delta = textValue(event.data.delta);
      if (messageId && delta) {
        const existing = messages.value.find((item) => item.id === messageId);
        upsertCompanion(conversationId, messageId, `${existing?.content ?? ""}${delta}`, "generating");
      }
      return current;
    }
    if (event.event === "message.completed") {
      const messageId = textValue(event.data.message_id);
      if (messageId) {
        messages.value = messages.value.map((item) =>
          item.id === messageId ? { ...item, status: "completed" } : item,
        );
      }
      return current;
    }
    if (event.event === "turn.completed") {
      return textValue(event.data.outcome) || current;
    }
    if (event.event === "turn.failed") {
      const message = errorMessage(event.data.error);
      error.value = message;
      const messageId = textValue(event.data.message_id);
      if (messageId) {
        messages.value = messages.value.map((item) =>
          item.id === messageId ? { ...item, status: "failed" } : item,
        );
      } else {
        messages.value = messages.value.map((item) =>
          item.sender_type === "companion" && item.status === "generating" ? { ...item, status: "failed" } : item,
        );
      }
      return "failed";
    }
    if (event.event === "turn.cancelled") {
      error.value = "已停止";
      return "cancelled";
    }
    return current;
  }

  function upsertCompanion(conversationId: string, messageId: string, content: string, status: string): void {
    const existing = messages.value.find((item) => item.id === messageId);
    if (existing) {
      messages.value = messages.value.map((item) =>
        item.id === messageId ? { ...item, content, status } : item,
      );
      return;
    }
    messages.value = [
      ...messages.value,
      {
        id: messageId,
        conversation_id: conversationId,
        sequence_number: Number.MAX_SAFE_INTEGER,
        client_message_id: null,
        sender_type: "companion",
        content_type: "text",
        content,
        status,
        metadata: {},
        created_at: new Date().toISOString(),
      },
    ];
  }

  async function archiveSelected(): Promise<void> {
    const scope = getScope();
    const conversation = selected.value;
    if (!scope || !conversation || conversation.status === "archived") {
      return;
    }
    error.value = "";
    try {
      const archived = await archiveConversation(scope, conversation.id);
      replaceConversation(archived);
    } catch (caught) {
      error.value = errorText(caught);
    }
  }

  watch(
    () => {
      const scope = getScope();
      return scope ? `${scope.apiBaseUrl}|${scope.userId}|${scope.companionId}` : "";
    },
    (key) => {
      scopeGeneration += 1;
      turnAbort?.abort();
      turnAbort = null;
      loadingList.value = false;
      loadingMessages.value = false;
      creating.value = false;
      sending.value = false;
      conversations.value = [];
      messages.value = [];
      selectedId.value = null;
      error.value = "";
      if (key) {
        void refreshConversations(true);
      }
    },
    { immediate: true },
  );

  return {
    conversations,
    messages,
    selected,
    loadingList,
    loadingMessages,
    creating,
    sending,
    error,
    openConversation,
    startConversation,
    sendMessage,
    stop,
    archiveSelected,
    refreshConversations,
  };
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function errorMessage(value: unknown): string {
  if (typeof value !== "object" || value === null) {
    return "这次交流没有完成";
  }
  const message = (value as { message?: unknown }).message;
  return typeof message === "string" && message ? message : "这次交流没有完成";
}

function isAbortError(caught: unknown): boolean {
  return caught instanceof DOMException && caught.name === "AbortError";
}
