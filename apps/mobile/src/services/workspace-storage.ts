const STORAGE_KEY = "ai-companion.mobile.workspace";

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

export function readEnvWorkspaceOverride(): StoredWorkspace | null {
  const userId = import.meta.env.VITE_WORKSPACE_USER_ID;
  if (typeof userId !== "string" || !userId.trim()) {
    return null;
  }
  const companionId = import.meta.env.VITE_WORKSPACE_COMPANION_ID;
  return {
    userId: userId.trim(),
    companionId: typeof companionId === "string" && companionId.trim() ? companionId.trim() : null,
  };
}

export function readWorkspace(): StoredWorkspace | null {
  const override = readEnvWorkspaceOverride();
  if (override) {
    return override;
  }
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
