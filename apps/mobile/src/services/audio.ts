import { accountJson } from "./account";

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

export function fetchAudioHealth(): Promise<AudioHealth> {
  return accountJson("/companion/voice/health");
}

export function listVoicePresets(): Promise<VoicePreset[]> {
  return accountJson("/companion/voice/presets");
}

export function getVoicePreset(): Promise<VoicePresetSelection> {
  return accountJson("/companion/voice/preset");
}

export function setVoicePreset(presetId: string): Promise<VoicePresetSelection> {
  return accountJson("/companion/voice/preset", {
    method: "PUT",
    body: JSON.stringify({ preset_id: presetId }),
  });
}
