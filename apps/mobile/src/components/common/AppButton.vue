<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "danger";
    type?: "button" | "submit";
    loading?: boolean;
    disabled?: boolean;
    icon?: string;
  }>(),
  {
    variant: "primary",
    type: "button",
    loading: false,
    disabled: false,
  },
);
</script>

<template>
  <button
    class="button"
    :class="variant"
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
  >
    <img v-if="icon" class="icon" :src="icon" alt="" />
    <span class="label"><slot /></span>
    <span v-if="loading" class="spinner" aria-hidden="true" />
  </button>
</template>

<style scoped>
.button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 56px;
  padding: 0 20px;
  border-radius: var(--radius-round);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.button:active:not(:disabled) {
  transform: scale(0.985);
}

.button:disabled {
  opacity: 0.62;
}

.primary {
  color: #fff;
  background: linear-gradient(180deg, #8d68f8 0%, #7348f0 100%);
  box-shadow: 0 8px 18px rgba(123, 85, 245, 0.28);
}

.secondary {
  color: var(--color-text-primary);
  background: var(--color-surface);
  border: 1.5px solid #e4dfec;
  font-weight: 600;
  letter-spacing: 0;
}

.danger {
  color: #fff;
  background: var(--color-danger);
  letter-spacing: 0;
}

.icon {
  width: 22px;
  height: 22px;
  object-fit: contain;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

.primary .spinner {
  border-color: rgba(255, 255, 255, 0.45);
  border-right-color: transparent;
  border-top-color: #fff;
}
</style>
