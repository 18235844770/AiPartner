import type { ConversationScope } from "./conversations";
import { ApiError, errorFromResponse, requestJson } from "./http";

export type AudioHealthResponse = {
  status: string;
  worker: {
    status: string;
    asr_backend: string;
    tts_backend: string;
    asr_loaded: boolean;
    tts_loaded: boolean;
    gpu_available: boolean;
    reachable: boolean;
    error?: string | null;
  };
};

export type AsrRecognizeResponse = {
  task_id: string;
  text: string;
  language: string | null;
  emotion: string | null;
  status: string;
  duration_ms: number;
};

export type VoicePreset = {
  id: string;
  name: string;
  provider: string;
  provider_label: string;
  model: string;
  language: string;
};

export type VoicePresetSelection = {
  preset_id: string | null;
  preset: VoicePreset | null;
};

export type TtsSynthesizeResponse = {
  task_id: string;
  status: string;
  message_id: string;
  audio_url: string | null;
  format: string | null;
  sample_rate: number | null;
};

export async function fetchAudioHealth(apiBaseUrl: string): Promise<AudioHealthResponse> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/audio/health`, {
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new ApiError("无法连接本地服务", 0, "network_error");
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  return (await response.json()) as AudioHealthResponse;
}

export async function recognizeSpeech(
  scope: ConversationScope,
  audio: Blob,
  options: {
    language?: string;
    conversationId?: string | null;
    signal?: AbortSignal;
  } = {},
): Promise<AsrRecognizeResponse> {
  const form = new FormData();
  form.append("audio", audio, "speech.wav");
  form.append("language", options.language ?? "auto");
  if (options.conversationId) {
    form.append("conversation_id", options.conversationId);
  }
  let response: Response;
  try {
    response = await fetch(
      `${scope.apiBaseUrl}/api/audio/users/${scope.userId}/companions/${scope.companionId}/asr`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
        body: form,
        signal: options.signal,
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
  return (await response.json()) as AsrRecognizeResponse;
}

export function fetchVoicePresets(apiBaseUrl: string): Promise<VoicePreset[]> {
  return requestJson<VoicePreset[]>(`${apiBaseUrl}/api/audio/voice-presets`);
}

export function fetchVoicePreset(scope: ConversationScope): Promise<VoicePresetSelection> {
  return requestJson<VoicePresetSelection>(
    `${scope.apiBaseUrl}/api/audio/users/${scope.userId}/companions/${scope.companionId}/voice-preset`,
  );
}

export function saveVoicePreset(scope: ConversationScope, presetId: string | null): Promise<VoicePresetSelection> {
  return requestJson<VoicePresetSelection>(
    `${scope.apiBaseUrl}/api/audio/users/${scope.userId}/companions/${scope.companionId}/voice-preset`,
    {
      method: "PUT",
      body: JSON.stringify({ preset_id: presetId }),
    },
  );
}

export async function synthesizeSpeech(
  scope: ConversationScope,
  messageId: string,
  options: { voiceProfileId?: string | null; signal?: AbortSignal } = {},
): Promise<TtsSynthesizeResponse> {
  let response: Response;
  try {
    response = await fetch(
      `${scope.apiBaseUrl}/api/audio/users/${scope.userId}/companions/${scope.companionId}/tts`,
      {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message_id: messageId,
          voice_profile_id: options.voiceProfileId ?? null,
        }),
        signal: options.signal,
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
  return (await response.json()) as TtsSynthesizeResponse;
}

export async function cancelAudioTask(
  scope: ConversationScope,
  taskId: string,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(
      `${scope.apiBaseUrl}/api/audio/users/${scope.userId}/companions/${scope.companionId}/tasks/${taskId}/cancel`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
      },
    );
  } catch {
    throw new ApiError("无法连接本地服务", 0, "network_error");
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
}

export function absoluteAudioUrl(apiBaseUrl: string, audioUrl: string): string {
  if (audioUrl.startsWith("http://") || audioUrl.startsWith("https://")) {
    return audioUrl;
  }
  return `${apiBaseUrl.replace(/\/$/, "")}${audioUrl.startsWith("/") ? "" : "/"}${audioUrl}`;
}
