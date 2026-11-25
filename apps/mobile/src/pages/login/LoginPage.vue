<script setup lang="ts">
import { computed, ref } from "vue";

import { assets } from "@/assets/slices";
import Avatar from "@/components/avatar/Avatar.vue";
import AppButton from "@/components/common/AppButton.vue";
import AppInput from "@/components/common/AppInput.vue";
import ScreenFrame from "@/components/layout/ScreenFrame.vue";
import { useKeyboardInset } from "@/composables/useKeyboardInset";
import { isEmailAddress } from "@/utils/email";

useKeyboardInset();

const languageOpen = ref(false);
const mode = ref<"password" | "code">("password");
const email = ref("");
const password = ref("");
const code = ref("");
const emailError = ref("");
const secretError = ref("");
const notice = ref("");
const submitting = ref(false);

const codeMode = computed(() => mode.value === "code");

function resetErrors(): void {
  emailError.value = "";
  secretError.value = "";
  notice.value = "";
}

function validateEmail(): boolean {
  if (!email.value.trim()) {
    emailError.value = "请输入邮箱地址";
    return false;
  }
  if (!isEmailAddress(email.value)) {
    emailError.value = "请输入有效的邮箱地址";
    return false;
  }
  return true;
}

function requestCode(): void {
  resetErrors();
  if (!validateEmail()) {
    return;
  }
  notice.value = "验证码发送将在账号服务接入后可用";
}

async function submit(): Promise<void> {
  resetErrors();
  if (!validateEmail()) {
    return;
  }
  if (mode.value === "password" && !password.value) {
    secretError.value = "请输入密码";
    return;
  }
  if (mode.value === "code" && !code.value.trim()) {
    secretError.value = "请输入验证码";
    return;
  }
  submitting.value = true;
  try {
    notice.value = "登录稍后接入";
  } finally {
    submitting.value = false;
  }
}

function showPasswordLogin(): void {
  mode.value = "password";
  resetErrors();
}

function showCodeLogin(): void {
  mode.value = "code";
  resetErrors();
}

function showLater(message: string): void {
  notice.value = message;
}
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

      <form class="form" @submit.prevent="submit">
        <AppInput
          v-model="email"
          type="email"
          name="email"
          autocomplete="username"
          inputmode="email"
          placeholder="邮箱地址"
          :icon="assets.email"
          :error="emailError"
          :disabled="submitting"
        />
        <AppInput
          v-if="!codeMode"
          v-model="password"
          type="password"
          name="password"
          autocomplete="current-password"
          placeholder="密码"
          revealable
          :icon="assets.lock"
          :error="secretError"
          :disabled="submitting"
        />
        <AppInput
          v-else
          v-model="code"
          name="code"
          inputmode="numeric"
          autocomplete="one-time-code"
          placeholder="验证码"
          :icon="assets.email"
          :error="secretError"
          :disabled="submitting"
        >
          <template #suffix>
            <button class="code-action" type="button" @click="requestCode">获取验证码</button>
          </template>
        </AppInput>

        <div v-if="!codeMode" class="forgot-row">
          <button class="forgot" type="button" @click="showLater('重置密码将在账号服务接入后可用')">
            忘记密码？
          </button>
          <img class="forgot-spark" :src="assets.starSmall" alt="" />
        </div>

        <AppButton type="submit" :loading="submitting">登录</AppButton>
        <p v-if="notice" class="notice">{{ notice }}</p>
      </form>

      <div class="divider" aria-hidden="true"><span>或</span></div>

      <AppButton v-if="!codeMode" variant="secondary" :icon="assets.email" @click="showCodeLogin">
        邮箱验证码登录
      </AppButton>
      <AppButton v-else variant="secondary" @click="showPasswordLogin">使用密码登录</AppButton>

      <p class="register">
        还没有账号？
        <button type="button" @click="showLater('注册将在账号服务接入后可用')">注册账号</button>
      </p>
      <p class="legal">
        <button type="button" @click="showLater('服务条款将在正式页面提供')">服务条款</button>
        <span>·</span>
        <button type="button" @click="showLater('隐私政策将在正式页面提供')">隐私政策</button>
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

.forgot-row {
  position: relative;
  display: flex;
  justify-content: flex-end;
  margin-top: -2px;
}

.forgot {
  min-height: 32px;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.forgot-spark {
  position: absolute;
  width: 18px;
  right: -8px;
  top: -10px;
  pointer-events: none;
}

.notice {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  text-align: center;
}

.code-action {
  min-height: 44px;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 600;
  white-space: nowrap;
}

.divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0;
  color: #b7b2c2;
  font-size: var(--font-size-sm);
}

.divider::before,
.divider::after {
  content: "";
  height: 1px;
  flex: 1;
  background: #e6e1ee;
}

.register {
  margin-top: 22px;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.register button,
.legal button {
  color: var(--color-primary);
  font-weight: 700;
}

.legal {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 28px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
}

.legal button {
  min-height: 32px;
  font-weight: 600;
}
</style>
