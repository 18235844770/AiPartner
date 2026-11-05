import { computed, ref, watch } from "vue";

import { compareConversations } from "../domain/presentation";
import {
  appendMessage,
  archiveConversation,
  createConversation,
  listConversations,
  listMessages,
  type ConversationResponse,
  type ConversationScope,
  type MessageResponse,
} from "../services/conversations";
import { errorText } from "../services/http";

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
  let pendingSend: { conversationId: string; content: string; clientMessageId: string } | null = null;

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
    if (
      pendingSend?.conversationId !== conversation.id ||
      pendingSend.content !== trimmed
    ) {
      pendingSend = {
        conversationId: conversation.id,
        content: trimmed,
        clientMessageId: crypto.randomUUID(),
      };
    }
    const generation = scopeGeneration;
    sending.value = true;
    error.value = "";
    try {
      const message = await appendMessage(scope, conversation.id, {
        sender_type: "user",
        content: trimmed,
        client_message_id: pendingSend.clientMessageId,
      });
      if (generation !== scopeGeneration) {
        return false;
      }
      pendingSend = null;
      if (!messages.value.some((item) => item.id === message.id)) {
        messages.value = [...messages.value, message].sort(
          (left, right) => left.sequence_number - right.sequence_number,
        );
        replaceConversation({
          ...conversation,
          last_message_at: message.created_at,
          next_sequence_number: conversation.next_sequence_number + 1,
        });
      }
      return true;
    } catch (caught) {
      if (generation === scopeGeneration) {
        error.value = errorText(caught);
      }
      return false;
    } finally {
      if (generation === scopeGeneration) {
        sending.value = false;
      }
    }
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
      pendingSend = null;
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
    archiveSelected,
    refreshConversations,
  };
}
