<script setup lang="ts">
import { useRouter } from "vue-router";

import { assets } from "@/assets/slices";

import AppTabBar from "./AppTabBar.vue";
import ScreenFrame from "./ScreenFrame.vue";

const props = withDefaults(
  defineProps<{
    title: string;
    backTo?: string;
    showBack?: boolean;
    tab?: boolean;
  }>(),
  {
    backTo: "/settings",
    showBack: true,
    tab: false,
  },
);

const router = useRouter();

function back(): void {
  void router.push(props.backTo);
}
</script>

<template>
  <ScreenFrame>
    <section class="detail" :class="{ tab }">
      <img class="mint" :src="assets.mintBlob" alt="" />
      <header>
        <button v-if="showBack" class="back" type="button" aria-label="返回" @click="back">
          <img :src="assets.back" alt="" />
        </button>
        <h1>{{ title }}</h1>
      </header>
      <div class="body">
        <slot />
      </div>
      <AppTabBar v-if="tab" />
    </section>
  </ScreenFrame>
</template>

<style scoped>
.detail {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f6f4fb;
}

.mint {
  position: absolute;
  width: 140px;
  right: -40px;
  top: 0;
  height: auto;
  pointer-events: none;
}

header {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 52px;
  padding: calc(env(safe-area-inset-top) + 12px) 16px 8px 12px;
}

.back {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex: none;
}

.back img {
  width: 28px;
  height: 28px;
  object-fit: contain;
}

h1 {
  font-size: 22px;
  font-weight: 800;
}

.body {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 8px 20px calc(24px + env(safe-area-inset-bottom));
}

.tab .body {
  padding-bottom: calc(136px + env(safe-area-inset-bottom));
}
</style>
