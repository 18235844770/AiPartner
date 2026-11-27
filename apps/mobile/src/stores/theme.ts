import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

import { useWorkspaceStore } from "./workspace";

export const themes = {
  cloud: { name: "云朵", description: "柔和的淡紫与薄荷色", colors: ["#f7f6fb", "#7b55f5", "#91dccb"] },
  midnight: { name: "Midnight · 夜猫", description: "月光下的黑红与酒红", colors: ["#090408", "#a81942", "#f04a7c"] },
} as const;

type ThemeId = keyof typeof themes;
const storageKey = "ai-companion.mobile.theme";

function preference(key: string): ThemeId | null {
  try {
    const value = localStorage.getItem(key);
    return value === "cloud" || value === "midnight" ? value : null;
  } catch {
    return null;
  }
}

function persist(key: string, value: ThemeId): void {
  try { localStorage.setItem(key, value); } catch { /* Keep the in-memory preference. */ }
}

export const useThemeStore = defineStore("theme", () => {
  const workspace = useWorkspaceStore();
  const guest = ref(preference(storageKey));
  const id = ref<ThemeId>(guest.value ?? "cloud");
  const midnight = computed(() => id.value === "midnight");

  watch(() => workspace.user?.id, (userId) => {
    id.value = guest.value ?? "cloud";
    if (!userId) return;
    const key = `${storageKey}.${userId}`;
    const saved = preference(key);
    if (saved) id.value = saved;
    else if (guest.value) persist(key, guest.value);
  }, { immediate: true, flush: "sync" });

  function select(value: ThemeId): void {
    id.value = value;
    const userId = workspace.user?.id;
    if (userId) {
      persist(`${storageKey}.${userId}`, value);
    } else {
      guest.value = value;
      persist(storageKey, value);
    }
  }

  return { id, midnight, select };
});
