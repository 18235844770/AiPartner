import { computed, ref } from "vue";

import { ApiError, errorText } from "../services/http";
import {
  createCompanion,
  createUser,
  getUser,
  initializeCompanionBasics,
  listCompanions,
  type CompanionResponse,
  type UserResponse,
} from "../services/identity";
import { clearWorkspace, readWorkspace, writeWorkspace } from "../services/workspace-storage";

export type WorkspacePhase = "loading" | "setup" | "ready" | "unavailable";

export type IdentityDraft = {
  displayName: string;
  timezone: string;
  locale: string;
  companionName: string;
  companionDescription: string;
  companionIsDefault: boolean;
};

export type CompanionDraft = {
  name: string;
  description: string;
  isDefault: boolean;
};

function requiredText(value: string, label: string, maxLength: number): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new ApiError(`${label}不能为空`, 0, "validation_error");
  }
  if (trimmed.length > maxLength) {
    throw new ApiError(`${label}不能超过 ${maxLength} 个字符`, 0, "validation_error");
  }
  return trimmed;
}

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function useWorkspace() {
  const phase = ref<WorkspacePhase>("loading");
  const user = ref<UserResponse | null>(null);
  const companions = ref<CompanionResponse[]>([]);
  const companionId = ref<string | null>(null);
  const error = ref("");
  const busy = ref(false);

  const companion = computed(
    () => companions.value.find((item) => item.id === companionId.value) ?? null,
  );

  function remember(userId: string, nextCompanionId: string | null): void {
    writeWorkspace({ userId, companionId: nextCompanionId });
  }

  function applyCompanions(items: CompanionResponse[], preferredId: string | null): void {
    companions.value = items;
    const active = items.filter((item) => item.status !== "archived");
    const pool = active.length > 0 ? active : items;
    const next =
      pool.find((item) => item.id === preferredId) ??
      pool.find((item) => item.is_default) ??
      pool[0] ??
      null;
    companionId.value = next?.id ?? null;
    if (user.value) {
      remember(user.value.id, companionId.value);
    }
    phase.value = next ? "ready" : "setup";
  }

  async function restore(apiBaseUrl: string): Promise<void> {
    const stored = readWorkspace();
    if (!stored) {
      user.value = null;
      companions.value = [];
      companionId.value = null;
      phase.value = "setup";
      return;
    }

    phase.value = "loading";
    error.value = "";
    try {
      user.value = await getUser(apiBaseUrl, stored.userId);
      const items = await listCompanions(apiBaseUrl, stored.userId);
      applyCompanions(items, stored.companionId);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        clearWorkspace();
        user.value = null;
        companions.value = [];
        companionId.value = null;
        error.value = "本地记录的用户不存在，请重新建立身份。";
        phase.value = "setup";
        return;
      }
      error.value = errorText(caught);
      phase.value = "unavailable";
    }
  }

  async function createIdentity(apiBaseUrl: string, draft: IdentityDraft): Promise<void> {
    busy.value = true;
    error.value = "";
    try {
      const current = user.value;
      const nextUser =
        current ??
        (await createUser(apiBaseUrl, {
          display_name: requiredText(draft.displayName, "显示名称", 64),
          timezone: requiredText(draft.timezone, "时区", 64),
          locale: requiredText(draft.locale, "语言", 16),
        }));
      user.value = nextUser;
      remember(nextUser.id, companionId.value);
      const created = await createCompanion(apiBaseUrl, nextUser.id, {
        name: requiredText(draft.companionName, "陪伴者名称", 64),
        description: optionalText(draft.companionDescription),
        is_default: draft.companionIsDefault,
      });
      await initializeCompanionBasics(apiBaseUrl, nextUser.id, created.id);
      const items = await listCompanions(apiBaseUrl, nextUser.id);
      applyCompanions(items, created.id);
    } catch (caught) {
      error.value = errorText(caught);
    } finally {
      busy.value = false;
    }
  }

  async function addCompanion(apiBaseUrl: string, draft: CompanionDraft): Promise<void> {
    const current = user.value;
    if (!current) {
      return;
    }
    busy.value = true;
    error.value = "";
    try {
      const created = await createCompanion(apiBaseUrl, current.id, {
        name: requiredText(draft.name, "陪伴者名称", 64),
        description: optionalText(draft.description),
        is_default: draft.isDefault,
      });
      await initializeCompanionBasics(apiBaseUrl, current.id, created.id);
      const items = await listCompanions(apiBaseUrl, current.id);
      applyCompanions(items, created.id);
    } catch (caught) {
      error.value = errorText(caught);
    } finally {
      busy.value = false;
    }
  }

  function selectCompanion(id: string): void {
    if (!user.value || !companions.value.some((item) => item.id === id)) {
      return;
    }
    companionId.value = id;
    remember(user.value.id, id);
  }

  function forget(): void {
    clearWorkspace();
    user.value = null;
    companions.value = [];
    companionId.value = null;
    error.value = "";
    phase.value = "setup";
  }

  return {
    phase,
    user,
    companion,
    companions,
    error,
    busy,
    restore,
    createIdentity,
    addCompanion,
    selectCompanion,
    forget,
  };
}
