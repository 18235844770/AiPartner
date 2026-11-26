<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { assets } from "@/assets/slices";
import Avatar from "@/components/avatar/Avatar.vue";
import AppButton from "@/components/common/AppButton.vue";
import AppInput from "@/components/common/AppInput.vue";
import ScreenFrame from "@/components/layout/ScreenFrame.vue";
import { useKeyboardInset } from "@/composables/useKeyboardInset";
import { afterLogin } from "@/router";
import { errorText } from "@/services/http";
import { useWorkspaceStore } from "@/stores/workspace";

useKeyboardInset();

const languageOpen = ref(false);
const registering = ref(false);
const username = ref("");
const password = ref("");
const confirmation = ref("");
const confirmationError = ref("");
const usernameError = ref("");
const secretError = ref("");
const notice = ref("");
const submitting = ref(false);
const canRetrySetup = ref(false);
const setupAttempt = ref(0);
const workspace = useWorkspaceStore();
const router = useRouter();
const route = useRoute();

async function run(action: () => Promise<void>): Promise<void> {
  if (submitting.value) return;
  notice.value = "";
  submitting.value = true;
  try {
    await action();
  } catch (caught) {
    notice.value = errorText(caught);
  } finally {
    submitting.value = false;
  }
}

function submit(): void {
  const name = username.value.normalize("NFKC").trim();
  usernameError.value = /^[\p{L}\p{N}._-]{3,64}$/u.test(name) ? "" : "请输入 3–64 位用户名，可使用字母、数字、点、下划线和连字符";
  secretError.value = !password.value ? "请输入密码" : registering.value && password.value.length < 8 ? "密码至少 8 位" : "";
  confirmationError.value = registering.value && confirmation.value !== password.value ? "两次输入的密码不一致" : "";
  if (usernameError.value || secretError.value || confirmationError.value) return;
  void run(async () => {
    await workspace.signIn({ username: name, password: password.value }, registering.value ? confirmation.value : undefined);
    password.value = confirmation.value = "";
  });
}

function toggleMode(): void {
  registering.value = !registering.value;
  password.value = confirmation.value = confirmationError.value = usernameError.value = secretError.value = notice.value = "";
}

watch(() => workspace.phase, (phase) => {
  if (phase === "ready") void router.replace(afterLogin(route.query.redirect));
}, { immediate: true });

async function retrySetup(): Promise<void> {
  await workspace.retrySetup();
  setupAttempt.value += 1;
}

watch([() => workspace.companion?.initialization_status, setupAttempt], ([status], _, onCleanup) => {
  canRetrySetup.value = status === "failed";
  if (status !== "pending") return;
  let attempts = 0;
  let disposed = false;
  let timer: number;
  const poll = async () => {
    try { await workspace.checkCompanion(); } catch (caught) {
      if (!disposed) notice.value = errorText(caught);
    }
    if (disposed) return;
    if (++attempts < 5) timer = window.setTimeout(poll, 1200);
    else canRetrySetup.value = true;
  };
  timer = window.setTimeout(poll, 1200);
  onCleanup(() => { disposed = true; window.clearTimeout(timer); });
}, { immediate: true });
</script>

<template>
  <ScreenFrame scroll>
    <div class="login">
      <div class="lang">
        <button type="button" :aria-expanded="languageOpen" @click="languageOpen = !languageOpen">
          简体中文
          <img class="chevron" :src="assets.chevron" alt="" />
        </button>
        <ul v-if="languageOpen" class="lang-menu">
          <li>
            <button type="button" @click="languageOpen = false">简体中文</button>
          </li>
        </ul>
      </div>

      <div class="hero" aria-hidden="true">
        <img class="art yellow" :src="assets.yellowBlob" alt="" />
        <img class="art pink" :src="assets.pinkBlob" alt="" />
        <img class="art mint" :src="assets.mintBlob" alt="" />
        <img class="art blue" :src="assets.blueBlob" alt="" />
        <img class="art star" :src="assets.starLarge" alt="" />
        <img class="art star-small" :src="assets.starSmall" alt="" />
        <div class="figure">
          <Avatar expression="wink" :width="250" />
        </div>
      </div>

      <div class="title-block">
        <h1>遇见</h1>
        <img class="title-star" :src="assets.starSmall" alt="" />
        <img class="swoosh" :src="assets.curvePurple" alt="" />
      </div>
      <p class="slogan">让陪伴，自然而然地发生</p>

      <div v-if="workspace.phase === 'setup'" class="form">
        <p class="notice" role="status">
          {{ workspace.companion?.initialization_status === 'failed' ? '伴侣初始化失败' : '正在为你准备专属伴侣' }}
        </p>
        <AppButton v-if="canRetrySetup" :loading="submitting" @click="run(retrySetup)">重试初始化</AppButton>
        <AppButton variant="secondary" :disabled="submitting" @click="run(workspace.signOut)">退出登录</AppButton>
      </div>
      <div v-else-if="workspace.phase === 'loading' || workspace.phase === 'unavailable'" class="form">
        <p class="notice" role="status">{{ workspace.error || '正在恢复登录' }}</p>
        <AppButton v-if="workspace.phase === 'unavailable'" @click="run(workspace.retryConnection)">重试连接</AppButton>
      </div>
      <form v-else class="form" @submit.prevent="submit">
        <AppInput
          v-model="username"
          name="username"
          autocomplete="username"
          placeholder="用户名"
          :icon="assets.profile"
          :error="usernameError"
          :disabled="submitting"
        />
        <AppInput
          v-model="password"
          type="password"
          name="password"
          :autocomplete="registering ? 'new-password' : 'current-password'"
          placeholder="密码"
          revealable
          :icon="assets.lock"
          :error="secretError"
          :disabled="submitting"
        />
        <AppInput
          v-if="registering"
          v-model="confirmation"
          type="password"
          name="confirm-password"
          autocomplete="new-password"
          placeholder="确认密码"
          :icon="assets.lock"
          :error="confirmationError"
          :disabled="submitting"
        />
        <AppButton type="submit" :loading="submitting">{{ registering ? '注册并登录' : '登录' }}</AppButton>
      </form>
      <p v-if="notice" class="notice feedback" role="alert">{{ notice }}</p>
      <p v-if="workspace.phase === 'signed-out'" class="register">
        {{ registering ? '已有账号？' : '还没有账号？' }}
        <button type="button" :disabled="submitting" @click="toggleMode">{{ registering ? '返回登录' : '注册账号' }}</button>
      </p>
    </div>
  </ScreenFrame>
</template>

<style scoped>
.login {
  position: relative;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  padding: calc(env(safe-area-inset-top) + 18px) 32px calc(env(safe-area-inset-bottom) + 16px);
  overflow: hidden;
  background:
    radial-gradient(120px 90px at 8% 18%, rgba(255, 214, 120, 0.35), transparent 70%),
    radial-gradient(160px 140px at 100% 22%, rgba(166, 230, 214, 0.45), transparent 70%),
    var(--color-background);
}

.lang {
  position: relative;
  z-index: 2;
  align-self: flex-end;
}

.lang > button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 36px;
  color: #5f5872;
  font-size: var(--font-size-sm);
}

.chevron {
  width: 14px;
  height: 14px;
  transform: rotate(90deg);
  object-fit: contain;
}

.lang-menu {
  position: absolute;
  top: 36px;
  right: 0;
  min-width: 120px;
  padding: 6px;
  border-radius: 12px;
  background: #fff;
  box-shadow: var(--shadow-float);
}

.lang-menu button {
  width: 100%;
  min-height: 36px;
  border-radius: 8px;
  text-align: left;
  padding: 0 10px;
  font-size: var(--font-size-sm);
}

.hero {
  position: relative;
  height: 268px;
  margin-top: 4px;
}

.art {
  position: absolute;
  height: auto;
  pointer-events: none;
  user-select: none;
}

.yellow {
  width: 150px;
  left: -36px;
  top: 78px;
  transform: rotate(-18deg);
}

.pink {
  width: 150px;
  left: -48px;
  bottom: 8px;
}

.mint {
  width: 132px;
  right: -28px;
  top: 36px;
}

.blue {
  width: 92px;
  right: 8px;
  bottom: 18px;
}

.star {
  width: 58px;
  left: 54px;
  top: 6px;
  z-index: 2;
}

.star-small {
  width: 28px;
  right: 78px;
  top: 28px;
  z-index: 2;
}

.figure {
  position: absolute;
  left: 50%;
  top: 54%;
  z-index: 1;
  transform: translate(-50%, -50%);
}

.title-block {
  position: relative;
  width: fit-content;
  margin-top: 4px;
}

h1 {
  font-size: 40px;
  line-height: 1.1;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.title-star {
  position: absolute;
  width: 22px;
  right: -26px;
  top: 2px;
}

.swoosh {
  position: absolute;
  width: 118px;
  right: -78px;
  bottom: -18px;
}

.slogan {
  margin-top: 10px;
  color: #6f6a7d;
  font-size: 15px;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 28px;
}

.notice {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  text-align: center;
}

.feedback {
  margin-top: 12px;
}

.register {
  margin-top: 22px;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.register button {
  color: var(--color-primary);
  font-weight: 700;
}
</style>
