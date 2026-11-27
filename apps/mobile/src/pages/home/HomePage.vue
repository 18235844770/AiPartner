<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import { assets } from "@/assets/slices";
import Avatar from "@/components/avatar/Avatar.vue";
import CompanionCharacter from "@/components/avatar/CompanionCharacter.vue";
import AppTabBar from "@/components/layout/AppTabBar.vue";
import ScreenFrame from "@/components/layout/ScreenFrame.vue";
import { useNow } from "@/composables/useNow";
import { useDialogueStore } from "@/stores/dialogue";
import { useWorkspaceStore } from "@/stores/workspace";

import { useThemeStore } from "@/stores/theme";
import { midnightAssets, midnightState, midnightStatus } from "@/themes/midnight";

const theme = useThemeStore();
const router = useRouter();
const workspace = useWorkspaceStore();
const dialogue = useDialogueStore();
const now = useNow();
const state = computed(() => midnightState(dialogue.emotion));
const statusLabel = computed(() => midnightStatus[state.value]);

const weekdays = ["日", "一", "二", "三", "四", "五", "六"];

const dateLabel = computed(() => {
  const current = now.value;
  return `${current.getMonth() + 1}月${current.getDate()}日 周${weekdays[current.getDay()]}`;
});

const timeLabel = computed(() => {
  const current = now.value;
  const hours = String(current.getHours()).padStart(2, "0");
  const minutes = String(current.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
});

function openChat(): void {
  void router.push("/chat");
}

function openSettings(): void {
  void router.push("/settings");
}
</script>

<template>
  <ScreenFrame page="home">
    <section class="home" :class="{ midnight: theme.midnight }">
      <template v-if="!theme.midnight">
        <img class="blob lavender" :src="assets.lavenderBlob" alt="" />
        <img class="blob yellow" :src="assets.yellowBlob" alt="" />
        <img class="blob pink" :src="assets.pinkBlob" alt="" />
        <img class="blob mint" :src="assets.mintBlob" alt="" />
        <img class="blob blue" :src="assets.blueBlob" alt="" />
        <img class="blob dot" :src="assets.skyDot" alt="" />
      </template>

      <header>
        <div class="date-row">
          <p class="date">{{ dateLabel }}</p>
          <button class="gear" type="button" aria-label="设置" @click="openSettings">
            <img :src="theme.midnight ? midnightAssets.icons['settings-inactive'] : assets.settings" alt="" />
          </button>
        </div>
        <p class="clock">{{ timeLabel }}</p>
        <p v-if="workspace.error" class="notice">{{ workspace.error }}</p>
      </header>

      <div class="stage">
        <template v-if="!theme.midnight">
          <img class="heart large" :src="assets.heartLarge" alt="" />
          <img class="heart small" :src="assets.heartSmall" alt="" />
          <img class="rays" :src="assets.raysPurple" alt="" />
          <img class="curve" :src="assets.curveBlue" alt="" />
        </template>
        <button class="companion" type="button" :aria-label="`和${workspace.companion?.name ?? '遇见'}聊天`" @click="openChat">
          <CompanionCharacter v-if="theme.midnight" :state="state" animate />
          <Avatar v-else :expression="dialogue.expression" :width="300" />
        </button>
      </div>

      <button class="mood-status" type="button" @click="openChat">
        <img :src="theme.midnight ? midnightAssets.decorations.crescent : assets.heartSmall" alt="" />
        <span>{{ statusLabel }}</span>
      </button>
      <AppTabBar />
    </section>
  </ScreenFrame>
</template>

<style scoped>
.home {
  --home-gutter: 28px;
  --companion-width: 300px;
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  padding: calc(env(safe-area-inset-top) + 18px) var(--home-gutter) calc(clamp(118px, 18dvh, 174px) + env(safe-area-inset-bottom));
  background: #fbfafe;
}

.blob,
.heart,
.rays,
.curve {
  position: absolute;
  height: auto;
  pointer-events: none;
  user-select: none;
}

.lavender {
  width: 340px;
  left: -70px;
  bottom: 20px;
}

.yellow {
  width: 210px;
  right: -70px;
  top: 34%;
}

.pink {
  width: 250px;
  right: -40px;
  bottom: -10px;
}

.mint {
  width: 150px;
  left: -30px;
  top: 42%;
}

.blue {
  width: 110px;
  right: 18px;
  bottom: 28%;
}

.dot {
  width: 42px;
  right: 22%;
  top: 30%;
}

header {
  position: relative;
  z-index: 1;
}

.date-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.date {
  font-size: 16px;
  font-weight: 700;
}

.gear {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
}

.gear img {
  width: 26px;
  height: 26px;
  object-fit: contain;
}

.clock {
  margin-top: 2px;
  font-size: 52px;
  line-height: 1;
  font-weight: 800;
  letter-spacing: -0.04em;
}

.notice {
  margin-top: 8px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.stage {
  position: relative;
  z-index: 1;
  flex: 1;
  display: grid;
  place-items: center;
  min-height: 0;
  container-type: size;
}

.companion {
  width: min(100%, var(--companion-width), 100cqh);
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  position: relative;
  z-index: 1;
}

.companion :deep(.avatar) { max-width: 100%; }

.heart.large {
  width: 42px;
  left: 18%;
  top: 28%;
}

.heart.small {
  width: 24px;
  left: 28%;
  top: 48%;
}

.rays {
  width: 54px;
  right: 18%;
  top: 18%;
}

.curve {
  width: 70px;
  right: 8%;
  bottom: 18%;
}

.mood-status {
  position: relative;
  z-index: 10;
  display: grid;
  justify-items: center;
  gap: 4px;
  flex: none;
  align-self: center;
  min-height: 44px;
  max-width: 100%;
  padding: 0 16px;
  text-align: center;
  font-size: 24px;
  line-height: 1.3;
}

.mood-status img {
  width: 22px;
  height: 22px;
  object-fit: contain;
}

.home.midnight {
  --companion-width: 440px;
  background: transparent;
}
.midnight header { z-index: 10; }
.midnight .stage {
  z-index: 2;
  margin-inline: calc(-1 * var(--home-gutter));
}
.midnight .mood-status {
  font-family: var(--theme-heading-font);
  letter-spacing: 0.08em;
  text-shadow: 0 0 16px var(--theme-glow);
}
</style>
