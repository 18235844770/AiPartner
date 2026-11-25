<script setup lang="ts">
import { useRouter } from "vue-router";

import { assets } from "@/assets/slices";
import SettingsDetail from "@/components/layout/SettingsDetail.vue";

const router = useRouter();

const topics = [
  {
    title: "怎么聊天",
    body: "在首页点角色，或打开聊天页，把想说的话发出去。回复会逐段出现。",
    to: "/chat",
    action: "去聊天",
  },
  {
    title: "安静也算回应",
    body: "陪伴者可以先听着，不说话。这种时候不会留下一条空白消息。",
    to: "/settings/notifications",
    action: "看看最近回复",
  },
  {
    title: "换一种声音",
    body: "语音页可以选择正在使用的音色。选中后，之后的语音会用这一个。",
    to: "/voice",
    action: "打开语音",
  },
  {
    title: "聊天记录",
    body: "聊天记录可以清空。清空不会改掉陪伴者自己的记忆。",
    to: "/settings/privacy",
    action: "数据与隐私",
  },
];
</script>

<template>
  <SettingsDetail title="帮助与支持">
    <section v-for="topic in topics" :key="topic.title" class="panel panel-body">
      <h2>{{ topic.title }}</h2>
      <p class="hint">{{ topic.body }}</p>
      <button type="button" @click="router.push(topic.to)">
        {{ topic.action }}
        <img :src="assets.chevron" alt="" />
      </button>
    </section>
  </SettingsDetail>
</template>

<style scoped>
h2 {
  font-size: 16px;
  font-weight: 700;
}

.hint {
  margin: 6px 0 10px;
}

button {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--color-primary-deep);
  font-weight: 700;
}

button img {
  width: 16px;
  height: 16px;
  object-fit: contain;
}
</style>
