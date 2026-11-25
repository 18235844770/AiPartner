import type { AvatarExpression } from "@/assets/slices";

const HAPPY = new Set(["开心", "兴奋", "亲密", "joy", "happy", "affection", "excitement"]);
const SAD = new Set(["难过", "委屈", "想念", "sadness", "hurt", "longing"]);
const ANGRY = new Set(["愤怒", "嫉妒", "anger", "jealousy"]);
const SHY = new Set(["不安", "anxiety"]);
const THINKING = new Set(["好奇", "专注", "投入", "curious", "attentive", "engaged"]);

export function expressionForEmotion(primary: string): AvatarExpression {
  if (HAPPY.has(primary)) {
    return "happy";
  }
  if (SAD.has(primary)) {
    return "sad";
  }
  if (ANGRY.has(primary)) {
    return "angry";
  }
  if (SHY.has(primary)) {
    return "shy";
  }
  if (THINKING.has(primary)) {
    return "thinking";
  }
  return "idle";
}
