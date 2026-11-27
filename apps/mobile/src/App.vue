<script setup lang="ts">
import { watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";

import { useThemeStore } from "@/stores/theme";
import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();
const theme = useThemeStore();

watch(() => theme.id, (id) => { document.documentElement.dataset.theme = id; }, { immediate: true, flush: "sync" });
const route = useRoute();
const router = useRouter();

watch(() => workspace.phase, (phase) => {
  if (phase === "signed-out" && route.name !== "login") void router.replace({ name: "login" });
});
</script>

<template>
  <RouterView />
</template>
