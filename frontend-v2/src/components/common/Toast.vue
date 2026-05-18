<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div 
          v-for="toast in toasts" 
          :key="toast.id"
          :class="['toast', `toast-${toast.type}`]"
        >
          <div class="toast-icon">
            <Icon :name="getIcon(toast.type)" :size="20" />
          </div>
          <div class="toast-content">
            <div class="toast-title" v-if="toast.title">{{ toast.title }}</div>
            <div class="toast-message">{{ toast.message }}</div>
          </div>
          <button class="toast-close" @click="removeToast(toast.id)">
            <Icon name="x" :size="16" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
import Icon from './Icon.vue'

const toasts = ref([])
let nextId = 0

function getIcon(type) {
  const icons = {
    success: 'check',
    error: 'x',
    warning: 'alert-triangle',
    info: 'bell'
  }
  return icons[type] || 'bell'
}

function addToast(message, type = 'info', title = '', duration = 3000) {
  const id = nextId++
  const toast = { id, message, type, title }
  
  toasts.value.push(toast)
  
  if (duration > 0) {
    setTimeout(() => {
      removeToast(id)
    }, duration)
  }
  
  return id
}

function removeToast(id) {
  const index = toasts.value.findIndex(t => t.id === id)
  if (index > -1) {
    toasts.value.splice(index, 1)
  }
}

function clearAll() {
  toasts.value = []
}

// 暴露方法供外部调用
defineExpose({
  success: (message, title = '', duration = 3000) => addToast(message, 'success', title, duration),
  error: (message, title = '', duration = 5000) => addToast(message, 'error', title, duration),
  warning: (message, title = '', duration = 4000) => addToast(message, 'warning', title, duration),
  info: (message, title = '', duration = 3000) => addToast(message, 'info', title, duration),
  clear: clearAll
})
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: calc(var(--header-height) + 20px);
  right: 20px;
  z-index: 40000;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 400px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  border-left: 3px solid;
  pointer-events: auto;
  min-width: 300px;
  max-width: 400px;
  transition: all var(--transition-normal);
}

.toast-success {
  border-left-color: var(--color-success);
  background: var(--color-bg-secondary);
}

.toast-error {
  border-left-color: var(--color-error);
  background: var(--color-bg-secondary);
}

.toast-warning {
  border-left-color: var(--color-warning);
  background: var(--color-bg-secondary);
}

.toast-info {
  border-left-color: var(--color-primary);
  background: var(--color-bg-secondary);
}

.toast-icon {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  margin-top: 2px;
}

.toast-success .toast-icon {
  background: var(--color-success-light);
  color: var(--color-success);
}

.toast-error .toast-icon {
  background: var(--color-error-light);
  color: var(--color-error);
}

.toast-warning .toast-icon {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.toast-info .toast-icon {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.toast-content {
  flex: 1;
  min-width: 0;
}

.toast-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.toast-message {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: 1.5;
  word-wrap: break-word;
}

.toast-close {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: var(--color-text-tertiary);
  transition: all var(--transition-fast);
  cursor: pointer;
}

.toast-close:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

/* 动画效果 */
.toast-enter-active,
.toast-leave-active {
  transition: all var(--transition-normal);
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%) scale(0.95);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(100%) scale(0.95);
}

.toast-move {
  transition: transform var(--transition-normal);
}
</style>
