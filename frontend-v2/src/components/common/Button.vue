<template>
  <button 
    class="btn" 
    :class="[
      `btn-${variant}`,
      `btn-${size}`,
      { 'btn-loading': loading, 'btn-block': block }
    ]"
    :disabled="disabled || loading"
    @click="$emit('click', $event)"
  >
    <span class="btn-spinner" v-if="loading"></span>
    <span class="btn-icon" v-if="icon && !loading">{{ icon }}</span>
    <span class="btn-text"><slot /></span>
  </button>
</template>

<script setup>
defineProps({
  variant: {
    type: String,
    default: 'primary', // primary, secondary, ghost, danger
    validator: (v) => ['primary', 'secondary', 'ghost', 'danger'].includes(v)
  },
  size: {
    type: String,
    default: 'md', // sm, md, lg
    validator: (v) => ['sm', 'md', 'lg'].includes(v)
  },
  icon: String,
  loading: Boolean,
  disabled: Boolean,
  block: Boolean
})

defineEmits(['click'])
</script>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-sm);
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Sizes */
.btn-sm {
  height: 32px;
  padding: 0 var(--spacing-md);
  font-size: var(--font-size-sm);
}

.btn-md {
  height: 40px;
  padding: 0 var(--spacing-lg);
  font-size: var(--font-size-sm);
}

.btn-lg {
  height: 48px;
  padding: 0 var(--spacing-xl);
  font-size: var(--font-size-md);
}

/* Variants - Unraid Style (aligned with global.css design system) */

/* Primary: Filled orange gradient button */
.btn-primary {
  background: var(--gradient-header);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 6px rgba(230, 126, 34, 0.2);
}

.btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #d35400 0%, #e67e22 100%);
  color: #ffffff;
  box-shadow: 0 6px 12px rgba(230, 126, 34, 0.3);
}

.btn-primary:active:not(:disabled) {
  box-shadow: 0 2px 4px rgba(230, 126, 34, 0.2);
  filter: brightness(0.95);
}

/* Secondary: Gray button */
.btn-secondary {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--color-bg-hover);
  border-color: var(--color-border-light);
}

/* Ghost: Minimal transparent button */
.btn-ghost {
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.btn-ghost:hover:not(:disabled) {
  background: var(--color-bg-hover);
  border-color: var(--color-border-light);
  color: var(--color-text-primary);
}

/* Danger: Light red background */
.btn-danger {
  background: #fff1f0;
  color: #ff4d4f;
  border: 1px solid #ffa39e;
}

.btn-danger:hover:not(:disabled) {
  background: #fff1f0;
  border-color: #ff4d4f;
}


/* Block */
.btn-block {
  width: 100%;
}

/* Loading */
.btn-loading {
  pointer-events: none;
}

.btn-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Icon */
.btn-icon {
  font-size: 16px;
}
</style>
