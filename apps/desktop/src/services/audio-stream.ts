import type { ConversationScope } from "./conversations";
import { ApiError, errorFromResponse } from "./http";

export type AudioStreamEventName =
  | "audio.started"
  | "audio.chunk"
  | "audio.completed"
  | "audio.failed"
  | "audio.cancelled";

export type AudioStreamEvent = {
  event: AudioStreamEventName;
  data: Record<string, unknown>;
};

const EVENT_NAMES = new Set<AudioStreamEventName>([
  "audio.started",
  "audio.chunk",
  "audio.completed",
  "audio.failed",
  "audio.cancelled",
]);

function isEventName(value: string): value is AudioStreamEventName {
  return EVENT_NAMES.has(value as AudioStreamEventName);
}

export function parseAudioSseBlock(block: string): AudioStreamEvent | null {
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
    throw new ApiError("音频事件无法识别", 0, "invalid_event");
  }
  return { event: eventName, data: parsed as Record<string, unknown> };
}

export async function streamSpeech(
  scope: ConversationScope,
  messageId: string,
  signal: AbortSignal,
  onEvent: (event: AudioStreamEvent) => void,
  options: { voiceProfileId?: string | null } = {},
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(
      `${scope.apiBaseUrl}/api/audio/users/${scope.userId}/companions/${scope.companionId}/tts/stream`,
      {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message_id: messageId,
          voice_profile_id: options.voiceProfileId ?? null,
        }),
        signal,
      },
    );
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw caught;
    }
    throw new ApiError("无法连接本地服务", 0, "network_error");
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  if (!response.body) {
    throw new ApiError("没有收到音频事件", response.status, "empty_stream");
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
      const event = parseAudioSseBlock(block);
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

export function base64ToBlob(dataBase64: string, mime = "audio/wav"): Blob {
  const binary = atob(dataBase64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: mime });
}
