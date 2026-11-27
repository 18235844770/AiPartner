<script setup lang="ts">
import { assets, avatarSource, type AvatarExpression } from "@/assets/slices";
import Avatar from "@/components/avatar/Avatar.vue";
import SettingsDetail from "@/components/layout/SettingsDetail.vue";
import { useDialogueStore } from "@/stores/dialogue";
import { useThemeStore } from "@/stores/theme";
import { midnightAssets, midnightState } from "@/themes/midnight";

const dialogue = useDialogueStore();
const theme = useThemeStore();
const nightFaces = {
  idle: "平常", happy: "开心", shy: "害羞", curious: "好奇",
  angry: "生气", sad: "低落", sleeping: "睡眠", affectionate: "亲昵",
};

const faces: { id: AvatarExpression; label: string }[] = [
  { id: "idle", label: "平常" },
  { id: "happy", label: "开心" },
  { id: "shy", label: "害羞" },
  { id: "thinking", label: "在想" },
  { id: "wink", label: "眨眼" },
  { id: "surprised", label: "惊讶" },
  { id: "sad", label: "难过" },
  { id: "angry", label: "生气" },
];
</script>

<template>
  <SettingsDetail title="外观偏好">
    <section class="panel panel-body current">
      <img v-if="!theme.midnight" class="rays" :src="assets.raysPurple" alt="" />
      <Avatar :expression="dialogue.expression" :width="120" :motion="false" :midnight-state="theme.midnight ? midnightState(dialogue.emotion) : undefined" />
      <p class="hint">表情跟着陪伴者此刻的感受变化，聊天和首页用的是同一张脸。</p>
    </section>
    <section class="panel faces">
      <h2 class="kicker">表情</h2>
      <ul v-if="theme.midnight">
        <li v-for="(label, id) in nightFaces" :key="id" :class="{ current: midnightState(dialogue.emotion) === id }">
          <img :src="midnightAssets.avatars[id]" alt="" />
          <span>{{ label }}</span>
        </li>
      </ul>
      <ul v-else>
        <li v-for="face in faces" :key="face.id" :class="{ current: dialogue.expression === face.id }">
          <img :src="avatarSource(face.id)" alt="" />
          <span>{{ face.label }}</span>
        </li>
      </ul>
    </section>
  </SettingsDetail>
</template>

<style scoped>
.current {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-align: center;
}

.rays {
  position: absolute;
  width: 42px;
  margin-left: 78px;
  margin-top: -8px;
  pointer-events: none;
}

.faces {
  padding: 16px 16px 8px;
}

ul {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

li {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 4px 10px;
  border-radius: 16px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}

li.current {
  background: var(--color-primary-soft);
  color: var(--color-primary-deep);
  font-weight: 700;
}

img {
  width: 56px;
  height: 56px;
  object-fit: contain;
}
</style>
