<template>
  <div class="progress-bar" :class="`progress-${variant}`">
    <div 
      class="progress-fill" 
      :style="{ width: `${clampedValue}%` }"
    >
      <span class="progress-glow"></span>
    </div>
    <span class="progress-text" v-if="showText">
      {{ displayText }}
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: {
    type: Number,
    default: 0
  },
  max: {
    type: Number,
    default: 100
  },
  variant: {
    type: String,
    default: 'primary', // primary, success, warning, error
    validator: (v) => ['primary', 'success', 'warning', 'error'].includes(v)
  },
  showText: {
    type: Boolean,
    default: true
  },
  text: String, // 自定义文本
  size: {
    type: String,
    default: 'md' // sm, md, lg
  }
})

const clampedValue = computed(() => {
  const percentage = (props.value / props.max) * 100
  return Math.min(Math.max(percentage, 0), 100)
})

const displayText = computed(() => {
  if (props.text) return props.text
  return `${Math.round(clampedValue.value)}%`
})
</script>

<style scoped>
.progress-bar {
  position: relative;
  width: 100%;
  height: 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.progress-fill {
  position: relative;
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 0.3s ease;
  overflow: hidden;
}

/* Glow effect */
.progress-glow {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.3),
    transparent
  );
  animation: shimmer 2s infinite;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

/* Variants */
.progress-primary .progress-fill {
  background: linear-gradient(90deg, var(--color-primary), #818cf8);
}

.progress-success .progress-fill {
  background: linear-gradient(90deg, var(--color-success), #34d399);
}

.progress-warning .progress-fill {
  background: linear-gradient(90deg, var(--color-warning), #fbbf24);
}

.progress-error .progress-fill {
  background: linear-gradient(90deg, var(--color-error), #f87171);
}

/* Text */
.progress-text {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  padding-left: var(--spacing-sm);
}
</style>
