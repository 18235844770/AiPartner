import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { fetchHealth } from "@/services/api";
import { ApiError, errorText } from "@/services/http";
import {
  createCompanion,
  createUser,
  getUser,
  initializeCompanionBasics,
  listCompanions,
  updateCompanion,
} from "@/services/identity";
import type { CompanionResponse, UpdateCompanionRequest, UserResponse } from "@/types/api";
import {
  clearWorkspace,
  readEnvWorkspaceOverride,
  readWorkspace,
  writeWorkspace,
} from "@/services/workspace-storage";

export type WorkspacePhase = "loading" | "ready" | "unavailable";

const DEFAULT_COMPANION_NAME = "遇见";

let ensureTask: Promise<void> | null = null;

export const useWorkspaceStore = defineStore("workspace", () => {
  const phase = ref<WorkspacePhase>("loading");
  const user = ref<UserResponse | null>(null);
  const companion = ref<CompanionResponse | null>(null);
  const error = ref("");

  const scope = computed(() => {
    if (!user.value || !companion.value) {
      return null;
    }
    return { userId: user.value.id, companionId: companion.value.id };
  });

  const presence = computed(() => {
    if (phase.value === "loading") {
      return "连接中";
    }
    if (phase.value === "unavailable" || companion.value?.status === "paused") {
      return "未连接";
    }
    return "在线";
  });

  function remember(userId: string, companionId: string | null): void {
    writeWorkspace({ userId, companionId });
  }

  function chooseCompanion(items: CompanionResponse[], preferredId: string | null): CompanionResponse | null {
    const active = items.filter((item) => item.status !== "archived");
    const pool = active.length > 0 ? active : items;
    return (
      pool.find((item) => item.id === preferredId) ??
      pool.find((item) => item.is_default) ??
      pool[0] ??
      null
    );
  }

  async function createDefault(): Promise<void> {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
    const createdUser = await createUser({
      display_name: "我",
      timezone,
      locale: "zh-CN",
    });
    user.value = createdUser;
    remember(createdUser.id, null);
    const items = await listCompanions(createdUser.id);
    const existing = chooseCompanion(items, null);
    const created =
      existing ??
      (await createCompanion(createdUser.id, {
        name: DEFAULT_COMPANION_NAME,
        description: null,
        is_default: true,
      }));
    await initializeCompanionBasics(createdUser.id, created.id);
    companion.value = created;
    remember(createdUser.id, created.id);
  }

  async function ensure(): Promise<void> {
    if (phase.value === "ready" && user.value && companion.value) {
      return;
    }
    ensureTask ??= runEnsure().finally(() => {
      ensureTask = null;
    });
    return ensureTask;
  }

  async function runEnsure(): Promise<void> {
    phase.value = "loading";
    error.value = "";
    try {
      await fetchHealth();
    } catch (caught) {
      error.value = errorText(caught);
      phase.value = "unavailable";
      return;
    }

    const stored = readWorkspace();
    const override = readEnvWorkspaceOverride();
    try {
      if (stored) {
        try {
          user.value = await getUser(stored.userId);
          const items = await listCompanions(stored.userId);
          const selected = chooseCompanion(items, stored.companionId);
          if (selected) {
            await initializeCompanionBasics(stored.userId, selected.id);
            companion.value = selected;
            remember(stored.userId, selected.id);
            phase.value = "ready";
            return;
          }
          const created = await createCompanion(stored.userId, {
            name: DEFAULT_COMPANION_NAME,
            description: null,
            is_default: true,
          });
          await initializeCompanionBasics(stored.userId, created.id);
          companion.value = created;
          remember(stored.userId, created.id);
          phase.value = "ready";
          return;
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status !== 404) {
            throw caught;
          }
          if (override) {
            error.value = "指定的用户不存在";
            phase.value = "unavailable";
            return;
          }
          clearWorkspace();
          user.value = null;
          companion.value = null;
        }
      }
      await createDefault();
      phase.value = "ready";
    } catch (caught) {
      error.value = errorText(caught);
      phase.value = "unavailable";
    }
  }

  async function saveCompanion(body: UpdateCompanionRequest): Promise<CompanionResponse> {
    const currentUser = user.value;
    const currentCompanion = companion.value;
    if (!currentUser || !currentCompanion) {
      throw new ApiError("还没有连上陪伴者", 0, "workspace_missing");
    }
    const updated = await updateCompanion(currentUser.id, currentCompanion.id, body);
    companion.value = updated;
    return updated;
  }

  return { phase, user, companion, error, presence, scope, ensure, saveCompanion };
});
