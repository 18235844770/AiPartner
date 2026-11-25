import { computed, onScopeDispose, ref, watch } from "vue";

import {
  clearMessages,
  createConversation,
  listMessages,
  type ConversationResponse,
  type ConversationScope,
  type MessageResponse,
} from "../services/conversations";
import { errorText } from "../services/http";
import { streamUserTurn, type TurnEvent } from "../services/turns";

export type ChatHooks = {
  onCompanionMessageCompleted?: (messageId: string, turnId: string) => void;
  onTurnInterrupted?: () => void;
};

export function useChat(getScope: () => ConversationScope | null, hooks: ChatHooks = {}) {
  const conversations = ref<ConversationResponse[]>([]);
  const messages = ref<MessageResponse[]>([]);
  const selectedId = ref<string | null>(null);
  const loadingList = ref(false);
  const loadingMessages = ref(false);
  const clearing = ref(false);
  const sending = ref(false);
  const error = ref("");
  let scopeGeneration = 0;
  let messageLoad = 0;
  let turnAbort: AbortController | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const selected = computed(
    () => conversations.value.find((item) => item.id === selectedId.value) ?? null,
  );

  async function ensureThread(): Promise<void> {
    const scope = getScope();
    if (!scope) {
      return;
    }
    const generation = scopeGeneration;
    loadingList.value = true;
    error.value = "";
    try {
      const conversation = await createConversation(scope, { title: null });
      if (generation !== scopeGeneration) {
        return;
      }
      conversations.value = [conversation];
      await openConversation(conversation.id);
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
    hooks.onTurnInterrupted?.();
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
    hooks.onTurnInterrupted?.();
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
        hooks.onCompanionMessageCompleted?.(messageId, textValue(event.data.turn_id));
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

  async function refreshOpenThread(): Promise<void> {
    const scope = getScope();
    const conversationId = selectedId.value;
    if (!scope || !conversationId || sending.value || loadingMessages.value) {
      return;
    }
    const generation = scopeGeneration;
    const load = messageLoad;
    try {
      const items = await listMessages(scope, conversationId);
      if (
        generation !== scopeGeneration ||
        load !== messageLoad ||
        selectedId.value !== conversationId ||
        sending.value
      ) {
        return;
      }
      messages.value = items;
    } catch {
      // 下一轮再拉。人离开界面时保留当前记录。
    }
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling(): void {
    stopPolling();
    pollTimer = setInterval(() => {
      void refreshOpenThread();
    }, 20_000);
  }

  function onVisible(): void {
    if (document.visibilityState === "visible") {
      void refreshOpenThread();
    }
  }

  document.addEventListener("visibilitychange", onVisible);
  onScopeDispose(() => {
    stopPolling();
    document.removeEventListener("visibilitychange", onVisible);
  });

  async function clearHistory(): Promise<void> {
    const scope = getScope();
    const conversation = selected.value;
    if (!scope || !conversation || clearing.value || sending.value) {
      return;
    }
    const generation = scopeGeneration;
    clearing.value = true;
    error.value = "";
    try {
      await clearMessages(scope, conversation.id);
      if (generation !== scopeGeneration) {
        return;
      }
      messages.value = [];
      await openConversation(conversation.id);
    } catch (caught) {
      if (generation === scopeGeneration) {
        error.value = errorText(caught);
      }
    } finally {
      if (generation === scopeGeneration) {
        clearing.value = false;
      }
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
      clearing.value = false;
      sending.value = false;
      conversations.value = [];
      messages.value = [];
      selectedId.value = null;
      error.value = "";
      stopPolling();
      if (key) {
        startPolling();
        void ensureThread();
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
    clearing,
    sending,
    error,
    sendMessage,
    stop,
    clearHistory,
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
