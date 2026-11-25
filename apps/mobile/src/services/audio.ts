import { apiBaseUrl } from "./api";
import type { ConversationScope } from "./conversations";
import { requestJson } from "./http";

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

export type AudioHealth = {
  status: string;
  worker: {
    status: string;
    reachable: boolean;
    asr_backend: string;
    tts_backend: string;
  };
};

function audioUrl(path: string): string {
  return `${apiBaseUrl()}/api/audio${path}`;
}

export function fetchAudioHealth(): Promise<AudioHealth> {
  return requestJson<AudioHealth>(audioUrl("/health"));
}

export function listVoicePresets(): Promise<VoicePreset[]> {
  return requestJson<VoicePreset[]>(audioUrl("/voice-presets"));
}

export function getVoicePreset(scope: ConversationScope): Promise<VoicePresetSelection> {
  return requestJson<VoicePresetSelection>(audioUrl(`/users/${scope.userId}/companions/${scope.companionId}/voice-preset`));
}

export function setVoicePreset(scope: ConversationScope, presetId: string): Promise<VoicePresetSelection> {
  return requestJson<VoicePresetSelection>(audioUrl(`/users/${scope.userId}/companions/${scope.companionId}/voice-preset`), {
    method: "PUT",
    body: JSON.stringify({ preset_id: presetId }),
  });
}
