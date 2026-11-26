import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import { expressionForEmotion } from "@/domain/expression";
import { getChatState, listHistory, readChatStream, retryChat, sendChat, type AccountMessage, type TurnStatus } from "@/services/chat";
import { errorText } from "@/services/http";
import type { StateResponse } from "@/types/api";
import type { ChatMessageItem } from "@/types/chat";

import { useWorkspaceStore } from "./workspace";

export const useDialogueStore = defineStore("dialogue", () => {
  const workspace = useWorkspaceStore();
  const history = ref(new Map<string, AccountMessage>());
  const previews = ref(new Map<string, ChatMessageItem>());
  const turns = ref(new Map<string, TurnStatus>());
  const loading = ref(false);
  const submitting = ref(false);
  const error = ref("");
  const emotion = ref("");
  const hasOlder = ref(false);
  const loadingOlder = ref(false);
  let streamController = new AbortController();
  let cursor = 0;
  let sendAttempt: { content: string; id: string } | undefined;

  const sortedHistory = computed(() => [...history.value.values()].sort((a, b) => a.sequence_number - b.sequence_number));
  const messages = computed<ChatMessageItem[]>(() => {
    const items = sortedHistory.value.flatMap((message): ChatMessageItem[] => {
      if (message.sender_type !== "user" && message.sender_type !== "companion") return [];
      const turn = message.turn_id ? turns.value.get(message.turn_id) : undefined;
      return [{
        id: message.id, role: message.sender_type, text: message.content, status: message.status,
        retryTurnId: message.sender_type === "user" && turn?.status === "failed" ? turn.turn_id : undefined,
      }];
    });
    return [...items, ...previews.value.values()];
  });
  const sending = computed(() => submitting.value || [...turns.value.values()].some((turn) => ["pending", "running"].includes(turn.status)));
  const typing = computed(() => sending.value && !previews.value.size);
  const expression = computed(() => sending.value ? "thinking" : expressionForEmotion(emotion.value));
  const statusLine = computed(() => [...sortedHistory.value].reverse()
    .find((item) => item.sender_type === "companion" && item.status === "completed")?.content ?? "");

  function merge(message: AccountMessage, advance = false): void {
    history.value.set(message.id, message);
    previews.value.delete(message.id);
    if (advance) cursor = Math.max(cursor, message.sequence_number);
  }

  function applyEvent(event: string, data: string): void {
    if (event === "message.persisted") merge(JSON.parse(data), true);
    if (event === "state.updated") emotion.value = (JSON.parse(data) as StateResponse).emotion.primary;
    if (event === "turn.status") {
      const turn = JSON.parse(data) as TurnStatus;
      turns.value.set(turn.turn_id, turn);
    }
    if (event === "message.delta") {
      const { message_id: id, delta } = JSON.parse(data) as { message_id: string; delta: string };
      if (!history.value.has(id)) {
        const previous = previews.value.get(id)?.text ?? "";
        previews.value.set(id, { id, role: "companion", text: previous + delta, status: "generating" });
      }
    }
  }

  async function follow(signal: AbortSignal): Promise<void> {
    while (!signal.aborted) {
      try {
        await readChatStream(cursor, signal, (event, data) => {
          if (!signal.aborted) applyEvent(event, data);
        });
      } catch {
        // Persisted messages are recovered from the same cursor on the next connection.
      }
      if (signal.aborted) return;
      previews.value.clear();
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
    }
  }

  async function open(signal: AbortSignal): Promise<void> {
    loading.value = true;
    try {
      const page = await listHistory(signal);
      if (!signal.aborted) {
        page.messages.forEach((message) => merge(message, true));
        hasOlder.value = page.has_more;
      }
    } catch (caught) {
      if (!signal.aborted) error.value = errorText(caught);
    } finally {
      if (!signal.aborted) loading.value = false;
    }
    if (!signal.aborted) {
      const state = await getChatState(signal).catch(() => null);
      if (!signal.aborted && state) emotion.value = state.emotion.primary;
    }
    if (!signal.aborted) void follow(signal);
  }

  async function loadOlder(): Promise<void> {
    const before = sortedHistory.value[0]?.sequence_number;
    if (!before || !hasOlder.value || loadingOlder.value) return;
    const signal = streamController.signal;
    loadingOlder.value = true;
    try {
      const page = await listHistory(signal, before);
      if (!signal.aborted) {
        page.messages.forEach((message) => merge(message));
        hasOlder.value = page.has_more;
      }
    } catch (caught) {
      if (!signal.aborted) error.value = errorText(caught);
    } finally {
      if (!signal.aborted) loadingOlder.value = false;
    }
  }

  async function sendMessage(text: string): Promise<boolean> {
    const content = text.trim();
    if (!workspace.scope || !content || submitting.value) return false;
    const signal = streamController.signal;
    submitting.value = true;
    error.value = "";
    if (sendAttempt?.content !== content) sendAttempt = { content, id: crypto.randomUUID() };
    try {
      const { message, turn_id, status } = await sendChat(content, sendAttempt.id);
      if (signal.aborted) return false;
      sendAttempt = undefined;
      merge(message);
      if (!turns.value.has(turn_id)) turns.value.set(turn_id, { turn_id, status, trigger_sequence: message.sequence_number });
      return true;
    } catch (caught) {
      if (!signal.aborted) error.value = errorText(caught);
      return false;
    } finally {
      if (!signal.aborted) submitting.value = false;
    }
  }

  async function retry(turnId: string): Promise<void> {
    const signal = streamController.signal;
    try {
      const status = await retryChat(turnId);
      if (!signal.aborted) turns.value.set(turnId, status);
    } catch (caught) {
      if (!signal.aborted) error.value = errorText(caught);
    }
  }

  watch(() => workspace.scope?.userId, (userId) => {
    streamController.abort();
    streamController = new AbortController();
    cursor = 0;
    sendAttempt = undefined;
    history.value.clear();
    previews.value.clear();
    turns.value.clear();
    error.value = emotion.value = "";
    loading.value = submitting.value = hasOlder.value = loadingOlder.value = false;
    if (userId) void open(streamController.signal);
  }, { immediate: true, flush: "sync" });

  return { messages, loading, error, expression, statusLine, typing, hasOlder, loadingOlder, loadOlder, sendMessage, retry };
});
