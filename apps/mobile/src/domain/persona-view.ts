import type { PersonaResponse } from "@/types/api";

export type PersonaView = {
  mbti: string;
  summary: string;
  interests: string[];
};

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

export function readPersonaView(persona: PersonaResponse): PersonaView {
  const archive = record(persona.current_version.archive);
  const identity = record(archive?.identity);
  const summary = identity && typeof identity.identity_summary === "string" ? identity.identity_summary : "";
  return {
    mbti: persona.current_version.mbti_type,
    summary,
    interests: textList(archive?.interests),
  };
}
