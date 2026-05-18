<template>
  <div class="card" :class="{ 'card-hoverable': hoverable, 'card-bordered': bordered }">
    <div class="card-header" v-if="title || $slots.header">
      <slot name="header">
        <h3 class="card-title">{{ title }}</h3>
        <p class="card-subtitle" v-if="subtitle">{{ subtitle }}</p>
      </slot>
      <div class="card-actions" v-if="$slots.actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="card-body" :class="{ 'no-padding': noPadding }">
      <slot />
    </div>
    <div class="card-footer" v-if="$slots.footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: String,
  subtitle: String,
  hoverable: Boolean,
  bordered: Boolean,
  noPadding: Boolean
})
</script>

<style scoped>
.card {
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.card-bordered {
  border: 1px solid var(--color-border);
}

.card-hoverable {
  transition: all var(--transition-fast);
}

.card-hoverable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

/* Header */
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: var(--spacing-md) var(--spacing-lg);
  border-bottom: 1px solid var(--color-border);
}

.card-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}

.card-subtitle {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin: var(--spacing-xs) 0 0;
}

.card-actions {
  display: flex;
  gap: var(--spacing-sm);
}

/* Body */
.card-body {
  padding: var(--spacing-lg);
}

.card-body.no-padding {
  padding: 0;
}

/* Footer */
.card-footer {
  padding: var(--spacing-md) var(--spacing-lg);
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-tertiary);
}
</style>
