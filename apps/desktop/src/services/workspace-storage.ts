const STORAGE_KEY = "ai-companion.workspace";

export type StoredWorkspace = {
  userId: string;
  companionId: string | null;
};

function isStoredWorkspace(value: unknown): value is StoredWorkspace {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.userId === "string" &&
    (record.companionId === null || typeof record.companionId === "string")
  );
}

export function readWorkspace(): StoredWorkspace | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return isStoredWorkspace(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeWorkspace(value: StoredWorkspace): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

export function clearWorkspace(): void {
  localStorage.removeItem(STORAGE_KEY);
}
