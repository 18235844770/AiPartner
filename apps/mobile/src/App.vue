<script setup lang="ts">
import { watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";

import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();
const route = useRoute();
const router = useRouter();

watch(() => workspace.phase, (phase) => {
  if (phase === "signed-out" && route.name !== "login") void router.replace({ name: "login" });
});
</script>

<template>
  <RouterView />
</template>
