import type { ConversationResponse } from "../services/conversations";

export function conversationTitle(conversation: ConversationResponse): string {
  const title = conversation.title?.trim();
  return title ? title : "未命名会话";
}

export function messageStateLabel(status: string): string {
  if (status === "failed") {
    return "未完成";
  }
  if (status === "interrupted") {
    return "已停止";
  }
  if (status === "generating") {
    return "生成中";
  }
  return "";
}

export function senderLabel(senderType: string): string {
  if (senderType === "user") {
    return "用户";
  }
  if (senderType === "companion") {
    return "陪伴者";
  }
  if (senderType === "system") {
    return "系统";
  }
  return senderType;
}

export function conversationStatusLabel(status: string): string {
  if (status === "active") {
    return "进行中";
  }
  if (status === "archived") {
    return "已归档";
  }
  return status;
}

export function formatTimestamp(value: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function compareConversations(left: ConversationResponse, right: ConversationResponse): number {
  const leftTime = left.last_message_at ?? left.created_at;
  const rightTime = right.last_message_at ?? right.created_at;
  return rightTime.localeCompare(leftTime);
}

const LABELS: Record<string, string> = {
  respond: "回应",
  share: "分享",
  ask: "询问",
  react: "反应",
  continue: "延续",
  close: "结束",
  quiet: "安静",
  pending: "待处理",
  approved: "已通过",
  executing: "执行中",
  completed: "已完成",
  rejected: "已拒绝",
  failed: "失败",
  cancelled: "已取消",
  queued: "已入队",
  running: "运行中",
  retrying: "重试中",
  success: "成功",
  timeout: "超时",
  user_message: "用户消息",
  proactive: "主动",
  system_event: "系统事件",
  background: "后台",
  companion_action: "陪伴者行为",
  dialogue_decision: "交流决策",
  background_task: "后台任务",
  system: "系统",
  candidate: "候选",
  active: "有效",
  archived: "已归档",
  semantic: "语义记忆",
  episodic: "情景记忆",
  working: "工作记忆",
  user_explicit: "用户明确表达",
  user_behavior: "行为观察",
  ai_inference: "归纳认知",
  ai_interest: "自主关注",
  system_generated: "系统生成",
  conversation: "对话",
  decision: "决策",
  memory: "记忆",
  embedding: "向量",
  deepseek: "DeepSeek",
  local: "本地",
  memory_extract: "记忆提取",
  memory_evaluate: "记忆评估",
  memory_embedding: "记忆向量",
  memory_relation: "记忆关联",
  memory_summarize: "工作记忆摘要",
  state_maintenance: "状态维护",
  proactive_check: "主动检查",
  available: "可交流",
  waiting: "等待",
  paused: "暂停",
  emotion_changed: "情绪变化",
  relationship_changed: "关系变化",
  interaction_changed: "交互变化",
  motivation_changed: "动机变化",
  multiple_changed: "多项变化",
  state_initialized: "状态初始化",
  state_recovered: "状态恢复",
  user_message_source: "用户消息",
  connect: "连接",
  listen: "倾听",
  comfort: "安慰",
  understand: "理解",
  play: "玩闹",
  resolve_conflict: "化解张力",
  rest: "休息",
};

export function labelOf(value: string): string {
  return LABELS[value] ?? value;
}

export function formatRecord(value: Record<string, unknown> | unknown[] | null): string {
  if (value === null) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}
