import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import { expressionForEmotion } from "@/domain/expression";
import type { AvatarExpression } from "@/assets/slices";
import { createConversation, listMessages, type ConversationScope } from "@/services/conversations";
import { errorText } from "@/services/http";
import { getState } from "@/services/state";
import { streamUserTurn, type TurnEvent } from "@/services/turns";
import type { MessageResponse } from "@/types/api";
import type { ChatMessageItem } from "@/types/chat";

import { useWorkspaceStore } from "./workspace";

export const useDialogueStore = defineStore("dialogue", () => {
  const workspace = useWorkspaceStore();
  const messages = ref<ChatMessageItem[]>([]);
  const loading = ref(false);
  const sending = ref(false);
  const error = ref("");
  const emotionPrimary = ref("");
  let generation = 0;
  let turnAbort: AbortController | null = null;

  const expression = computed<AvatarExpression>(() => {
    if (sending.value) {
      return "thinking";
    }
    return expressionForEmotion(emotionPrimary.value);
  });

  const statusLine = computed(() => {
    const latest = [...messages.value]
      .reverse()
      .find((item) => item.role === "companion" && item.status !== "failed" && item.text.trim());
    return latest?.text ?? "";
  });

  const typing = computed(() => {
    if (!sending.value) {
      return false;
    }
    const generating = [...messages.value].reverse().find((item) => item.role === "companion" && item.status === "generating");
    return !generating || !generating.text;
  });

  function scopeKey(scope: ConversationScope | null): string {
    return scope ? `${scope.userId}|${scope.companionId}` : "";
  }

  async function refreshEmotion(scope: ConversationScope, current: number): Promise<void> {
    try {
      const state = await getState(scope);
      if (current !== generation) {
        return;
      }
      emotionPrimary.value = state?.emotion.primary ?? "";
    } catch {
      if (current === generation) {
        emotionPrimary.value = "";
      }
    }
  }

  async function open(scope: ConversationScope, current: number): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      const conversation = await createConversation(scope, { title: null });
      if (current !== generation) {
        return;
      }
      const items = await listMessages(scope, conversation.id);
      if (current !== generation) {
        return;
      }
      messages.value = sortMessages(items);
      void refreshEmotion(scope, current);
    } catch (caught) {
      if (current === generation) {
        messages.value = [];
        error.value = errorText(caught);
      }
    } finally {
      if (current === generation) {
        loading.value = false;
      }
    }
  }

  async function reload(scope: ConversationScope, conversationId: string, current: number): Promise<void> {
    const items = await listMessages(scope, conversationId);
    if (current !== generation) {
      return;
    }
    messages.value = sortMessages(items);
  }

  async function sendMessage(text: string): Promise<void> {
    const scope = workspace.scope;
    const trimmed = text.trim();
    if (!scope || !trimmed) {
      error.value = workspace.error || "还没有连上陪伴者";
      return;
    }
    const current = generation;
    turnAbort?.abort();
    const controller = new AbortController();
    turnAbort = controller;
    sending.value = true;
    error.value = "";
    const clientMessageId = crypto.randomUUID();
    let conversationId = "";
    try {
      const conversation = await createConversation(scope, { title: null });
      if (current !== generation || turnAbort !== controller) {
        return;
      }
      conversationId = conversation.id;
      messages.value = [
        ...messages.value,
        {
          id: clientMessageId,
          role: "user",
          text: trimmed,
          status: "recorded",
        },
      ];
      await streamUserTurn(scope, conversation.id, trimmed, clientMessageId, controller.signal, (event) => {
        if (current !== generation) {
          return;
        }
        applyTurnEvent(event);
      });
      if (current === generation && conversationId) {
        const turnError = error.value;
        await reload(scope, conversationId, current);
        if (turnError) {
          error.value = turnError;
        }
        void refreshEmotion(scope, current);
      }
    } catch (caught) {
      if (current !== generation || turnAbort !== controller) {
        return;
      }
      error.value = isAbortError(caught) ? "已停止" : errorText(caught);
      if (conversationId) {
        await reload(scope, conversationId, current).catch(() => undefined);
      }
    } finally {
      if (turnAbort === controller) {
        turnAbort = null;
        sending.value = false;
      }
    }
  }

  function applyTurnEvent(event: TurnEvent): void {
    if (event.event === "message.started") {
      const messageId = textValue(event.data.message_id);
      if (messageId) {
        upsertCompanion(messageId, "", "generating");
      }
      return;
    }
    if (event.event === "message.delta") {
      const messageId = textValue(event.data.message_id);
      const delta = textValue(event.data.delta);
      if (messageId && delta) {
        const existing = messages.value.find((item) => item.id === messageId);
        upsertCompanion(messageId, `${existing?.text ?? ""}${delta}`, "generating");
      }
      return;
    }
    if (event.event === "message.completed") {
      const messageId = textValue(event.data.message_id);
      if (messageId) {
        messages.value = messages.value.map((item) =>
          item.id === messageId ? { ...item, status: "completed" } : item,
        );
      }
      return;
    }
    if (event.event === "turn.failed") {
      error.value = errorMessage(event.data.error);
      const messageId = textValue(event.data.message_id);
      messages.value = messages.value.map((item) => {
        if (messageId && item.id === messageId) {
          return { ...item, status: "failed" };
        }
        if (!messageId && item.role === "companion" && item.status === "generating") {
          return { ...item, status: "failed" };
        }
        return item;
      });
      return;
    }
    if (event.event === "turn.cancelled") {
      error.value = "已停止";
    }
  }

  function upsertCompanion(messageId: string, text: string, status: string): void {
    const existing = messages.value.find((item) => item.id === messageId);
    if (existing) {
      messages.value = messages.value.map((item) => (item.id === messageId ? { ...item, text, status } : item));
      return;
    }
    messages.value = [...messages.value, { id: messageId, role: "companion", text, status }];
  }

  watch(
    () => (workspace.scope ? scopeKey(workspace.scope) : ""),
    (key) => {
      generation += 1;
      turnAbort?.abort();
      turnAbort = null;
      sending.value = false;
      messages.value = [];
      emotionPrimary.value = "";
      error.value = "";
      const scope = workspace.scope;
      if (key && scope) {
        void open(scope, generation);
      }
    },
    { immediate: true },
  );

  function refresh(): void {
    generation += 1;
    turnAbort?.abort();
    turnAbort = null;
    sending.value = false;
    const scope = workspace.scope;
    if (scope) {
      void open(scope, generation);
    }
  }

  return { messages, loading, sending, error, expression, statusLine, typing, sendMessage, refresh };
});

function sortMessages(items: MessageResponse[]): ChatMessageItem[] {
  return [...items]
    .sort((left, right) => left.sequence_number - right.sequence_number)
    .map(toChatItem)
    .filter((item): item is ChatMessageItem => item !== null);
}

function toChatItem(message: MessageResponse): ChatMessageItem | null {
  if (message.sender_type !== "user" && message.sender_type !== "companion") {
    return null;
  }
  return {
    id: message.id,
    role: message.sender_type,
    text: message.content,
    status: message.status,
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
