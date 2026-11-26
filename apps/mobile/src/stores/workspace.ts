import { defineStore } from "pinia";
import { computed, ref } from "vue";

import {
  accountFetch, accountJson, authAction, bindAccount, restoreAccount,
  type AccountProfile, type Credentials, type ManagedCompanion,
} from "@/services/account";
import { ApiError, errorText } from "@/services/http";

export const useWorkspaceStore = defineStore("workspace", () => {
  const phase = ref<"loading" | "signed-out" | "setup" | "ready" | "unavailable">("loading");
  const user = ref<AccountProfile | null>(null);
  const companion = ref<ManagedCompanion | null>(null);
  const error = ref("");
  const customizeAfterRegistration = ref(false);
  let controller = new AbortController();
  let restoreTask: Promise<void> | undefined;

  const scope = computed(() => phase.value === "ready" && user.value && companion.value
    ? { userId: user.value.id, companionId: companion.value.id } : null);
  const presence = computed(() => phase.value === "ready" ? "在线" : "连接中");

  function reset(): void {
    controller.abort();
    controller = new AbortController();
    restoreTask = undefined;
    user.value = null;
    companion.value = null;
    customizeAfterRegistration.value = false;
    error.value = "";
    phase.value = "signed-out";
    try { localStorage.removeItem("ai-companion.mobile.workspace"); } catch { /* local storage may be disabled */ }
  }

  async function checkCompanion(): Promise<void> {
    const signal = controller.signal;
    const current = await accountJson<ManagedCompanion>("/companion/me");
    if (signal.aborted) return;
    error.value = "";
    companion.value = current;
    phase.value = current.initialization_status === "ready" ? "ready" : "setup";
  }

  async function loadSession(signal: AbortSignal, registered = false): Promise<void> {
    try {
      const profile = await restoreAccount(signal);
      if (signal.aborted) return;
      bindAccount(profile.id, signal, reset);
      user.value = profile;
      if (registered) sessionStorage.setItem("companion.registration-setup", profile.id);
      customizeAfterRegistration.value = sessionStorage.getItem("companion.registration-setup") === profile.id;
      await checkCompanion();
    } catch (caught) {
      if (signal.aborted) return;
      if (caught instanceof ApiError && caught.status === 401) reset();
      else {
        error.value = errorText(caught);
        phase.value = "unavailable";
      }
    }
  }

  function ensure(): Promise<void> {
    if (phase.value !== "loading") return Promise.resolve();
    restoreTask ??= loadSession(controller.signal);
    return restoreTask;
  }

  async function retryConnection(): Promise<void> {
    phase.value = "loading";
    error.value = "";
    restoreTask = undefined;
    await ensure();
  }

  async function signIn(credentials: Credentials, confirmation?: string): Promise<void> {
    const signal = controller.signal;
    if (confirmation !== undefined) {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      await authAction("register", signal, { ...credentials, confirm_password: confirmation, timezone });
    }
    await authAction("login", signal, credentials);
    await loadSession(signal, confirmation !== undefined);
  }

  function finishRegistrationSetup(): void {
    sessionStorage.removeItem("companion.registration-setup");
    customizeAfterRegistration.value = false;
  }

  async function signOut(): Promise<void> {
    await accountFetch("/auth/logout", { method: "POST" });
    reset();
  }

  async function retrySetup(): Promise<void> {
    await accountFetch("/companion/me/retry", { method: "POST" });
    await checkCompanion();
  }

  async function saveCompanion(body: { name: string; description?: string; mbti_type?: string }): Promise<void> {
    const signal = controller.signal;
    const updated = await accountJson<ManagedCompanion>("/companion/me", { method: "PATCH", body: JSON.stringify(body) });
    if (!signal.aborted) companion.value = updated;
  }

  async function deleteAccount(password: string): Promise<void> {
    await accountFetch("/user/me", { method: "DELETE", body: JSON.stringify({ password }) });
    reset();
  }

  return {
    phase, user, companion, error, presence, scope, ensure, signIn, signOut, checkCompanion,
    customizeAfterRegistration, finishRegistrationSetup,
    retryConnection, retrySetup, saveCompanion, deleteAccount,
  };
});
