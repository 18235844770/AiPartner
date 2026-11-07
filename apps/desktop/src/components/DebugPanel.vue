<script setup lang="ts">
import { computed, toRef, watch } from "vue";

import { useInspection, type DebugSection } from "../composables/useInspection";
import { formatRecord, formatTimestamp, labelOf } from "../domain/presentation";
import type { ConversationScope } from "../services/conversations";

const props = defineProps<{
  apiBaseUrl: string;
  userId: string;
  companionId: string;
  section: DebugSection;
}>();

const section = toRef(props, "section");

function currentScope(): ConversationScope | null {
  if (!props.apiBaseUrl || !props.userId || !props.companionId) {
    return null;
  }
  return {
    apiBaseUrl: props.apiBaseUrl,
    userId: props.userId,
    companionId: props.companionId,
  };
}

const {
  loading,
  error,
  missing,
  persona,
  memories,
  topics,
  conversations,
  workingConversationId,
  working,
  workingMissing,
  state,
  events,
  decisions,
  calls,
  tasks,
  reload,
  selectWorking,
} = useInspection(section, currentScope);

const title = computed(() => {
  if (props.section === "persona") {
    return "人格";
  }
  if (props.section === "memory") {
    return "记忆";
  }
  if (props.section === "state") {
    return "状态";
  }
  if (props.section === "decisions") {
    return "决策";
  }
  return "模型调用";
});

watch(
  () => [props.section, props.apiBaseUrl, props.userId, props.companionId] as const,
  () => {
    void reload();
  },
  { immediate: true },
);

function onWorkingChange(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLSelectElement) {
    void selectWorking(target.value);
  }
}

function tokenText(input: number | null, output: number | null): string {
  const left = input === null ? "—" : String(input);
  const right = output === null ? "—" : String(output);
  return `${left} / ${right}`;
}
</script>

<template>
  <section class="debug-page">
    <header class="debug-toolbar">
      <div>
        <p class="eyebrow">调试</p>
        <h2>{{ title }}</h2>
      </div>
      <button class="secondary" type="button" :disabled="loading" @click="reload">刷新</button>
    </header>

    <p v-if="loading" class="muted">正在读取</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="missing" class="notice">{{ missing }}</p>

    <template v-else-if="!loading && section === 'persona' && persona">
      <p class="meta-row">
        <span>{{ persona.current_version.mbti_type }}</span>
        <span>版本 {{ persona.current_version.version_number }}</span>
        <span>{{ formatTimestamp(persona.current_version.created_at) }}</span>
      </p>
      <p>{{ persona.current_version.change_reason }}</p>
      <div class="record-list">
        <article class="record">
          <h3>核心特质</h3>
          <pre>{{ formatRecord(persona.current_version.core_traits) }}</pre>
        </article>
        <article class="record">
          <h3>行为特质</h3>
          <pre>{{ formatRecord(persona.current_version.behavior_traits) }}</pre>
        </article>
        <article class="record">
          <h3>表达偏好</h3>
          <pre>{{ formatRecord(persona.current_version.communication_preferences) }}</pre>
        </article>
        <article class="record">
          <h3>人格档案</h3>
          <pre>{{ formatRecord(persona.current_version.archive) }}</pre>
        </article>
      </div>
    </template>

    <template v-else-if="!loading && section === 'memory'">
      <h3 class="section-label">正式记忆</h3>
      <p v-if="memories.length === 0" class="notice">还没有正式记忆</p>
      <ul v-else class="record-list">
        <li v-for="memory in memories" :key="memory.id" class="record">
          <h3>{{ memory.current_version.summary || memory.current_version.content }}</h3>
          <p class="meta-row">
            <span>{{ labelOf(memory.memory_type) }}</span>
            <span>{{ labelOf(memory.status) }}</span>
            <span>{{ labelOf(memory.memory_origin) }}</span>
            <span v-if="memory.is_inference">推断</span>
            <span>置信度 {{ memory.confidence }}</span>
            <span>{{ formatTimestamp(memory.updated_at) }}</span>
          </p>
          <p v-if="memory.current_version.summary" class="memory-body">{{ memory.current_version.content }}</p>
        </li>
      </ul>

      <h3 class="section-label">长期关注</h3>
      <p v-if="topics.length === 0" class="notice">还没有关注主题</p>
      <ul v-else class="record-list">
        <li v-for="topic in topics" :key="topic.id" class="record">
          <h3>{{ topic.title }}</h3>
          <p class="meta-row">
            <span>{{ labelOf(topic.status) }}</span>
            <span>{{ labelOf(topic.origin_type) }}</span>
            <span>关注 {{ topic.interest_score }}</span>
          </p>
          <p v-if="topic.description">{{ topic.description }}</p>
        </li>
      </ul>

      <h3 class="section-label">工作记忆</h3>
      <p v-if="conversations.length === 0" class="notice">还没有会话</p>
      <template v-else>
        <label>
          会话
          <select :value="workingConversationId" @change="onWorkingChange">
            <option v-for="conversation in conversations" :key="conversation.id" :value="conversation.id">
              {{ conversation.title?.trim() || "未命名会话" }}
            </option>
          </select>
        </label>
        <p v-if="workingMissing" class="notice">这个会话还没有工作记忆</p>
        <article v-else-if="working" class="record">
          <p class="meta-row">
            <span v-if="working.current_topic">话题 {{ working.current_topic }}</span>
            <span>版本 {{ working.version }}</span>
          </p>
          <p>{{ working.summary || "还没有摘要" }}</p>
          <ul v-if="working.open_threads.length > 0" class="thread-items">
            <li v-for="(thread, index) in working.open_threads" :key="index">
              {{ formatRecord(thread) }}
            </li>
          </ul>
        </article>
      </template>
    </template>

    <template v-else-if="!loading && section === 'state' && state">
      <div class="grid">
        <article>
          <h3>情绪</h3>
          <p class="value">{{ state.emotion.primary }}</p>
          <p class="muted">强度 {{ state.emotion.intensity }} · {{ state.emotion.cause_summary }}</p>
        </article>
        <article>
          <h3>内部关系</h3>
          <p class="muted">亲近 {{ state.relationship.closeness }} · 信任 {{ state.relationship.trust }}</p>
          <p class="muted">在意 {{ state.relationship.care }} · 张力 {{ state.relationship.current_tension }}</p>
          <p>{{ state.relationship.summary }}</p>
        </article>
        <article>
          <h3>交互</h3>
          <p class="value">{{ labelOf(state.interaction.mode) }}</p>
          <p class="muted">主动交流 {{ state.interaction.proactive_allowed ? "允许" : "不允许" }}</p>
        </article>
        <article>
          <h3>动机</h3>
          <p class="value">{{ labelOf(state.motivation.primary) }}</p>
          <p class="muted">{{ state.motivation.reason }}</p>
        </article>
      </div>
      <h3 class="section-label">变更记录</h3>
      <p v-if="events.length === 0" class="notice">还没有状态变更</p>
      <ul v-else class="record-list">
        <li v-for="event in events" :key="event.id" class="record">
          <h3>{{ labelOf(event.event_type) }}</h3>
          <p class="meta-row">
            <span>{{ labelOf(event.source_type) }}</span>
            <span>版本 {{ event.version_after ?? "—" }}</span>
            <span>{{ formatTimestamp(event.created_at) }}</span>
          </p>
          <p>{{ event.reason }}</p>
        </li>
      </ul>
    </template>

    <template v-else-if="!loading && section === 'decisions'">
      <p v-if="decisions.length === 0" class="notice">还没有决策</p>
      <ul v-else class="record-list">
        <li v-for="decision in decisions" :key="decision.id" class="record">
          <h3>{{ labelOf(decision.primary_action) }}</h3>
          <p class="meta-row">
            <span>{{ labelOf(decision.trigger_type) }}</span>
            <span>{{ labelOf(decision.status) }}</span>
            <span>置信度 {{ decision.confidence }}</span>
            <span>{{ formatTimestamp(decision.created_at) }}</span>
          </p>
          <p>{{ decision.reasoning_summary }}</p>
        </li>
      </ul>
    </template>

    <template v-else-if="!loading && section === 'models'">
      <h3 class="section-label">调用记录</h3>
      <p v-if="calls.length === 0" class="notice">还没有模型调用</p>
      <ul v-else class="record-list">
        <li v-for="call in calls" :key="call.id" class="record">
          <h3>{{ labelOf(call.task_type) }} · {{ call.model_name }}</h3>
          <p class="meta-row">
            <span>{{ labelOf(call.provider) }}</span>
            <span>{{ labelOf(call.status) }}</span>
            <span>{{ call.latency_ms }} ms</span>
            <span>Token {{ tokenText(call.input_tokens, call.output_tokens) }}</span>
            <span>{{ formatTimestamp(call.created_at) }}</span>
          </p>
          <p v-if="call.error_message" class="error">{{ call.error_message }}</p>
        </li>
      </ul>
      <h3 class="section-label">后台任务</h3>
      <p v-if="tasks.length === 0" class="notice">还没有后台任务</p>
      <ul v-else class="record-list">
        <li v-for="task in tasks" :key="task.id" class="record">
          <h3>{{ labelOf(task.task_type) }}</h3>
          <p class="meta-row">
            <span>{{ labelOf(task.status) }}</span>
            <span>重试 {{ task.retry_count }}/{{ task.max_retries }}</span>
            <span>{{ formatTimestamp(task.updated_at) }}</span>
          </p>
          <p class="task-key">{{ task.task_key }}</p>
          <p v-if="task.error_message" class="error">{{ task.error_message }}</p>
        </li>
      </ul>
    </template>
  </section>
</template>
