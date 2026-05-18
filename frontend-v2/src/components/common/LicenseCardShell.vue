<template>
  <div class="license-shell" :class="{ 'is-loading': loading, 'is-lifetime': isLifetime }">
    <span v-if="showLifetimeBadge && isLifetime" class="lifetime-badge">LIFETIME</span>
    <slot :is-lifetime="isLifetime"></slot>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  isLicensed: {
    type: Boolean,
    default: false
  },
  remainingDays: {
    type: Number,
    default: 0
  },
  loading: {
    type: Boolean,
    default: false
  },
  showLifetimeBadge: {
    type: Boolean,
    default: true
  }
})

const isLifetime = computed(() => {
  return props.isLicensed && (props.remainingDays === -1 || props.remainingDays > 3650)
})
</script>

<style scoped>
.license-shell {
  position: relative;
  overflow: hidden;
}

:deep(.license-header-compact) {
  display: flex;
  align-items: center;
  gap: 12px;
}

:deep(.license-crown) {
  color: #e67e22;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.license-crown svg) {
  filter: drop-shadow(0 2px 4px rgba(230, 126, 34, 0.25));
  transition: transform 0.3s ease;
}

:deep(.license-main) {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

:deep(.license-label) {
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.2;
}

:deep(.license-usage) {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

:deep(.usage-text) {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

:deep(.usage-bar) {
  height: 6px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
}

:deep(.usage-fill) {
  height: 100%;
  background: linear-gradient(90deg, #e74c3c, #f39c12);
  border-radius: var(--radius-full);
  transition: width 0.3s ease;
}

.license-shell.valid:not(.is-lifetime) {
  border-color: var(--color-success);
  background: rgba(39, 174, 96, 0.05);
}

.license-shell.invalid:not(.is-lifetime),
.license-shell.expired:not(.is-lifetime) {
  border-color: var(--color-error);
  background: rgba(231, 76, 60, 0.05);
}

.license-shell.is-lifetime {
  border-color: rgba(230, 126, 34, 0.3);
  background:
    radial-gradient(140% 120% at 100% 0%, rgba(230, 126, 34, 0.1) 0%, rgba(230, 126, 34, 0) 50%),
    radial-gradient(100% 90% at 0% 100%, rgba(211, 84, 0, 0.08) 0%, rgba(211, 84, 0, 0) 55%),
    linear-gradient(135deg, var(--color-bg-card) 0%, rgba(230, 126, 34, 0.05) 45%, rgba(211, 84, 0, 0.07) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.35),
    0 6px 18px rgba(230, 126, 34, 0.1);
}

.license-shell.is-lifetime :deep(.license-crown) {
  color: var(--color-primary);
}

.license-shell.is-lifetime :deep(.license-label) {
  color: var(--color-text-primary);
}

.license-shell.is-lifetime :deep(.usage-text) {
  color: var(--color-text-secondary);
}

.license-shell.is-lifetime :deep(.usage-fill) {
  background: linear-gradient(90deg, var(--color-primary), var(--color-primary-hover));
}

.license-shell.is-lifetime :deep(.license-header-compact) {
  padding-right: 68px;
}

.license-shell.inactive-license :deep(.license-crown) {
  color: #bdc3c7;
  opacity: 0.8;
}

.license-shell.inactive-license :deep(.license-label) {
  color: var(--color-text-secondary);
}

.license-shell.inactive-license :deep(.usage-fill) {
  background: linear-gradient(90deg, #bdc3c7, #95a5a6);
  opacity: 0.5;
}

.license-shell.is-lifetime::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  border: 1px solid rgba(230, 126, 34, 0.2);
  pointer-events: none;
}

.lifetime-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 10;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.8px;
  color: #fff;
  background: linear-gradient(90deg, var(--color-primary) 0%, var(--color-primary-hover) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 4px 10px rgba(211, 84, 0, 0.24);
}

[data-theme="dark"] .license-shell.is-lifetime {
  border-color: rgba(230, 126, 34, 0.35);
  background:
    radial-gradient(130% 120% at 100% 0%, rgba(230, 126, 34, 0.12) 0%, rgba(230, 126, 34, 0) 55%),
    radial-gradient(100% 90% at 0% 100%, rgba(211, 84, 0, 0.11) 0%, rgba(211, 84, 0, 0) 60%),
    linear-gradient(135deg, rgba(37, 37, 37, 0.98) 0%, rgba(54, 41, 26, 0.82) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 10px 24px rgba(0, 0, 0, 0.36),
    0 4px 14px rgba(230, 126, 34, 0.12);
}

[data-theme="dark"] .license-shell.is-lifetime::before {
  border-color: rgba(230, 126, 34, 0.24);
}

[data-theme="dark"] .lifetime-badge {
  color: #fff;
}

@media (max-width: 768px) {
  .lifetime-badge {
    top: 8px;
    right: 8px;
    padding: 2px 7px;
    font-size: 9px;
    letter-spacing: 0.6px;
  }
}
</style>
