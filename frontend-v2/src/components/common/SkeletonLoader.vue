<template>
  <div v-if="loading" class="skeleton-loader-container" :class="[type, { 'is-overlay': overlay }]">
    <div class="skeleton-content">
      <span class="skeleton-spinner"></span>
      <span class="skeleton-text">{{ text }}</span>
    </div>
    
    <div :class="['skeleton-layout', type]" :style="layoutStyle">
      <div 
        v-for="i in count" 
        :key="i" 
        class="skeleton-item" 
        :style="{ height: itemHeight }"
      >
        <div class="skeleton-shimmer"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  loading: {
    type: Boolean,
    default: false
  },
  text: {
    type: String,
    default: '加载中...'
  },
  type: {
    type: String,
    default: 'grid' // 'grid' | 'list'
  },
  count: {
    type: Number,
    default: 8
  },
  itemHeight: {
    type: String,
    default: '160px'
  },
  itemMinWidth: {
    type: String,
    default: '280px'
  },
  overlay: {
    type: Boolean,
    default: true
  },
  gap: {
    type: String,
    default: '20px'
  },
  maxWidth: {
    type: String,
    default: '100%'
  }
})

const layoutStyle = computed(() => ({
  gap: props.gap,
  maxWidth: props.maxWidth
}))
</script>

<style scoped>
.skeleton-loader-container {
  position: relative;
  width: 100%;
  min-height: 200px;
  overflow: hidden;
  z-index: 10;
}

.skeleton-loader-container.is-overlay {
  min-height: 400px;
}

.skeleton-content {
  position: absolute;
  top: 120px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 25;
  background: var(--color-bg-card, #fff);
  padding: 12px 24px;
  border-radius: 100px;
  /* backdrop-filter: blur(8px);  -- 移除以优化 GPU 性能 */
  border: 1px solid var(--color-border, rgba(0,0,0,0.1));
  box-shadow: 0 10px 30px rgba(0,0,0,0.15);
  color: var(--color-text-primary, #333);
}

[data-theme="dark"] .skeleton-content {
  background: rgba(40, 40, 40, 0.9);
  border-color: rgba(255, 255, 255, 0.1);
  color: #eee;
}

.skeleton-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(var(--color-primary-rgb, 255, 100, 0), 0.1);
  border-top-color: var(--color-primary, #ff6400);
  border-radius: 50%;
  animation: skeleton-spin-unique 0.8s linear infinite !important;
}

.skeleton-text {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.skeleton-layout {
  display: grid;
  padding: 10px;
  width: 100%;
}

.skeleton-layout.grid {
  grid-template-columns: repeat(auto-fill, minmax(v-bind(itemMinWidth), 1fr));
}

.skeleton-layout.list {
  grid-template-columns: 1fr;
}

.skeleton-item {
  background: var(--color-bg-card, #ffffff);
  border: 1px solid var(--color-border, rgba(0, 0, 0, 0.08));
  border-radius: 12px;
  position: relative;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
  opacity: 0.6;
}

[data-theme="dark"] .skeleton-item {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
}

.skeleton-shimmer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(128, 128, 128, 0.15) 50%,
    transparent 100%
  );
  animation: skeleton-shimmer-run-unique 1.5s infinite linear !important;
  will-change: transform;
}

[data-theme="dark"] .skeleton-shimmer {
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.08) 50%,
    transparent 100%
  );
}

@keyframes skeleton-shimmer-run-unique {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

@keyframes skeleton-spin-unique {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.4s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

