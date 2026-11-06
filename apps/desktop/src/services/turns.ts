import type { ConversationScope } from "./conversations";
import { ApiError, errorFromResponse } from "./http";

export type TurnEventName =
  | "turn.started"
  | "message.started"
  | "message.delta"
  | "message.completed"
  | "turn.completed"
  | "turn.failed"
  | "turn.cancelled";

export type TurnEvent = {
  event: TurnEventName;
  data: Record<string, unknown>;
};

const EVENT_NAMES = new Set<TurnEventName>([
  "turn.started",
  "message.started",
  "message.delta",
  "message.completed",
  "turn.completed",
  "turn.failed",
  "turn.cancelled",
]);

function isEventName(value: string): value is TurnEventName {
  return EVENT_NAMES.has(value as TurnEventName);
}

export function parseSseBlock(block: string): TurnEvent | null {
  let eventName = "";
  let dataText = "";
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataText += line.slice("data:".length).trim();
    }
  }
  if (!isEventName(eventName) || !dataText) {
    return null;
  }
  const parsed: unknown = JSON.parse(dataText);
  if (typeof parsed !== "object" || parsed === null) {
    throw new ApiError("交流事件无法识别", 0, "invalid_event");
  }
  return { event: eventName, data: parsed as Record<string, unknown> };
}

export async function streamUserTurn(
  scope: ConversationScope,
  conversationId: string,
  content: string,
  clientMessageId: string,
  signal: AbortSignal,
  onEvent: (event: TurnEvent) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(
      `${scope.apiBaseUrl}/api/users/${scope.userId}/companions/${scope.companionId}/conversations/${conversationId}/turns`,
      {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content, client_message_id: clientMessageId }),
        signal,
      },
    );
  } catch (caught) {
    if (isAbort(caught)) {
      throw caught;
    }
    throw new ApiError("无法连接本地服务", 0, "network_error");
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  if (!response.body) {
    throw new ApiError("没有收到交流事件", response.status, "empty_stream");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastSequence = -1;
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) {
      break;
    }
    buffer += decoder.decode(chunk.value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = parseSseBlock(block);
      if (!event) {
        continue;
      }
      const sequence = event.data.sequence;
      if (typeof sequence === "number") {
        if (sequence <= lastSequence) {
          continue;
        }
        lastSequence = sequence;
      }
      onEvent(event);
    }
  }
}

function isAbort(caught: unknown): boolean {
  return caught instanceof DOMException && caught.name === "AbortError";
}
