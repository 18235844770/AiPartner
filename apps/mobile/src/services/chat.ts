import type { MessageResponse, StateResponse } from "@/types/api";

import { accountFetch, accountJson } from "./account";

export type AccountMessage = MessageResponse & { audio_url: string | null; turn_id: string | null };
export type TurnStatus = { turn_id: string; trigger_sequence: number; status: string };

export function listHistory(signal: AbortSignal, before?: number): Promise<{ messages: AccountMessage[]; has_more: boolean }> {
  return accountJson(`/chat/messages${before === undefined ? "" : `?before_sequence=${before}`}`, { signal });
}

export function sendChat(content: string, clientMessageId: string): Promise<{ message: AccountMessage; turn_id: string; status: string }> {
  return accountJson("/chat/messages", { method: "POST", body: JSON.stringify({ content, client_message_id: clientMessageId }) });
}

export function retryChat(turnId: string): Promise<TurnStatus> {
  return accountJson(`/chat/turns/${turnId}/retry`, { method: "POST" });
}

export function getChatState(signal: AbortSignal): Promise<StateResponse> {
  return accountJson("/companion/state", { signal });
}

export async function readChatStream(
  after: number, signal: AbortSignal, onEvent: (event: string, data: string) => void,
): Promise<void> {
  const response = await accountFetch(`/chat/stream?after_sequence=${after}`, { signal, headers: { Accept: "text/event-stream" } });
  if (!response.body) return;
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let pending = "";
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) return;
      const blocks = (pending + value).split("\n\n");
      pending = blocks.pop() ?? "";
      for (const block of blocks) {
        const event = block.match(/^event: (.+)$/m)?.[1];
        const data = block.match(/^data: (.+)$/m)?.[1];
        if (event && data) onEvent(event, data);
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
