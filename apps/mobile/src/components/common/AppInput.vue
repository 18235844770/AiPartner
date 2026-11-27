<script setup lang="ts">
import { computed, ref, useId } from "vue";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    type?: "text" | "email" | "password";
    placeholder?: string;
    icon?: string;
    error?: string;
    autocomplete?: string;
    inputmode?: "text" | "email" | "numeric";
    name?: string;
    revealable?: boolean;
    disabled?: boolean;
  }>(),
  {
    type: "text",
    placeholder: "",
    error: "",
    autocomplete: "off",
    revealable: false,
    disabled: false,
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const revealed = ref(false);
const errorId = useId();

const inputType = computed(() => {
  if (props.type === "password" && props.revealable && revealed.value) {
    return "text";
  }
  return props.type;
});

function onInput(event: Event): void {
  const target = event.target;
  if (target instanceof HTMLInputElement) {
    emit("update:modelValue", target.value);
  }
}

function onFocus(event: FocusEvent): void {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  window.setTimeout(() => {
    target.scrollIntoView({ block: "center", behavior: "smooth" });
  }, 280);
}
</script>

<template>
  <div class="field">
    <div class="control" :class="{ invalid: Boolean(error) }">
      <img v-if="icon" class="icon" :src="icon" alt="" />
      <input
        :value="modelValue"
        :type="inputType"
        :placeholder="placeholder"
        :aria-label="placeholder"
        :autocomplete="autocomplete"
        :inputmode="inputmode"
        :name="name"
        :disabled="disabled"
        :aria-invalid="Boolean(error) || undefined"
        :aria-describedby="error ? errorId : undefined"
        @input="onInput"
        @focus="onFocus"
      />
      <button
        v-if="revealable"
        class="suffix"
        type="button"
        :aria-pressed="revealed"
        @click="revealed = !revealed"
      >
        {{ revealed ? "隐藏" : "显示" }}
      </button>
      <span v-else class="suffix-slot">
        <slot name="suffix" />
      </span>
    </div>
    <p v-if="error" :id="errorId" class="error">{{ error }}</p>
  </div>
</template>

<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.control {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 56px;
  padding: 0 16px;
  border-radius: 18px;
  background: var(--color-input);
  border: 1.5px solid var(--input-border, transparent);
}

.control:focus-within {
  border-color: var(--color-primary-light);
  background: var(--input-focus-background, #fff);
}

.invalid {
  border-color: var(--color-danger);
  background: var(--input-error-background, #fff7f8);
}

.icon {
  width: 22px;
  height: 22px;
  object-fit: contain;
  flex: none;
}

input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: var(--color-text-primary);
}

input::placeholder {
  color: var(--color-text-disabled);
}

.suffix,
.suffix-slot {
  flex: none;
}

.suffix {
  min-width: 44px;
  min-height: 44px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.error {
  padding-left: 8px;
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

</style>
