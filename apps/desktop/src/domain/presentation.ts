import type { ConversationResponse } from "../services/conversations";

export function conversationTitle(conversation: ConversationResponse): string {
  const title = conversation.title?.trim();
  return title ? title : "未命名会话";
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
