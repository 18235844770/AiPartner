export type MessageRole = "user" | "companion";

export interface ChatMessageItem {
  id: string;
  role: MessageRole;
  text: string;
  status: string;
  retryTurnId?: string;
}
