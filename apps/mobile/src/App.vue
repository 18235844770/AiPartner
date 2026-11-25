<script setup lang="ts">
import { RouterView } from "vue-router";

import { useWorkspaceStore } from "@/stores/workspace";

const workspace = useWorkspaceStore();
void workspace.ensure();
</script>

<template>
  <RouterView />
</template>
