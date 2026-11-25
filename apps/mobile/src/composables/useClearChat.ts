import { ref } from "vue";

import { clearMessages, listConversations } from "@/services/conversations";
import { errorText } from "@/services/http";
import { useDialogueStore } from "@/stores/dialogue";
import { useWorkspaceStore } from "@/stores/workspace";

export function useClearChat() {
  const workspace = useWorkspaceStore();
  const dialogue = useDialogueStore();
  const confirming = ref(false);
  const clearing = ref(false);
  const error = ref("");
  const notice = ref("");

  function ask(): void {
    confirming.value = true;
    error.value = "";
    notice.value = "";
  }

  function cancel(): void {
    confirming.value = false;
  }

  async function confirm(): Promise<void> {
    const scope = workspace.scope;
    if (!scope) {
      error.value = workspace.error || "还没有连上陪伴者";
      return;
    }
    clearing.value = true;
    error.value = "";
    try {
      const conversations = await listConversations(scope);
      const targets = conversations.filter((item) => item.status !== "archived");
      if (targets.length === 0) {
        notice.value = "还没有可以清空的对话";
        confirming.value = false;
        return;
      }
      let deleted = 0;
      for (const item of targets) {
        const result = await clearMessages(scope, item.id);
        deleted += result.deleted_count;
      }
      dialogue.refresh();
      notice.value = deleted > 0 ? `已清空 ${deleted} 条聊天记录` : "这段对话里没有记录";
      confirming.value = false;
    } catch (caught) {
      error.value = errorText(caught);
    } finally {
      clearing.value = false;
    }
  }

  return { confirming, clearing, error, notice, ask, cancel, confirm };
}
