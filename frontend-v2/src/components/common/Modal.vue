<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="show" class="modal-overlay" :style="overlayStyle" @click.self="persistent ? null : handleClose()" v-bind="$attrs">
        <div class="modal-container" :style="[containerStyle, playerContainerStyle]">
          <!-- 头部 -->
          <div class="modal-header" :style="playerHeaderStyle">
            <div class="header-content">
              <div v-if="type" :class="['type-icon', `icon-${type}`]">
                <Icon :name="getIcon" :size="20" />
              </div>
              <h3 :class="{ 'modal-title-single-line': titleSingleLine }" :style="playerTitleStyle">{{ title }}</h3>
            </div>
            <div class="header-actions">
              <button v-if="closeText" class="btn btn-primary btn-sm" @click="handleClose">{{ closeText }}</button>
              <button v-if="showConfirm && confirmTopRight" class="btn btn-primary btn-sm" @click="handleClose">确定</button>
              <button v-if="!hideClose" class="close-btn" :style="playerCloseStyle" @click="handleClose">
                <Icon name="x" :size="20" />
              </button>
            </div>
          </div>

          <!-- 内容区 -->
          <div class="modal-body" :class="{ 'modal-body-fill': bodyFill }" :style="bodyStyle">
            <slot></slot>
          </div>

          <!-- 底部按钮区 (可选) -->
          <div v-if="$slots.footer" class="modal-footer" :style="playerFooterStyle">
            <slot name="footer"></slot>
          </div>
          <div v-else-if="showConfirm && !confirmTopRight" class="modal-footer" :style="playerFooterStyle">
            <button class="btn btn-primary" @click="handleClose">确定</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, useAttrs } from 'vue'
import Icon from './Icon.vue'

// 禁用属性继承警告，因为我们手动绑定了$attrs
defineOptions({
  inheritAttrs: false
})

const props = defineProps({
  show: Boolean,
  title: {
    type: String,
    default: '提示'
  },
  type: {
    type: String, // success, error, warning, info
    default: ''
  },
  width: {
    type: String,
    default: '500px'
  },
  titleSingleLine: {
    type: Boolean,
    default: false
  },
  containerHeight: {
    type: String,
    default: ''
  },
  showConfirm: {
    type: Boolean,
    default: true
  },
  confirmTopRight: {
    type: Boolean,
    default: false
  },
  persistent: {
    type: Boolean,
    default: false
  },
  hideClose: {
    type: Boolean,
    default: false
  },
  closeText: {
    type: String,
    default: ''
  },
  overlayPadding: {
    type: String,
    default: ''
  },
  overlayAlign: {
    type: String,
    default: ''
  },
  bodyFill: {
    type: Boolean,
    default: false
  },
  bodyPadding: {
    type: String,
    default: ''
  },
  zIndex: {
    type: [Number, String],
    default: 30000
  }
})

const emit = defineEmits(['update:show', 'close'])
const attrs = useAttrs()

const theme = ref('')
let themeObserver = null

const normalizeClass = (value) => {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join(' ')
  if (typeof value === 'object') return Object.keys(value).filter(key => value[key]).join(' ')
  return String(value)
}

const isPlayerLight = computed(() => normalizeClass(attrs.class).includes('player-modal-light'))
const isDarkTheme = computed(() => theme.value === 'dark')

const playerHeaderStyle = computed(() => {
  if (!isPlayerLight.value) return {}
  return isDarkTheme.value
    ? { background: '#0b0f16', borderBottom: '1px solid #1f2937', color: '#f8fafc' }
    : { background: '#ffffff', borderBottom: '1px solid #e5e7eb', color: '#1f2937' }
})

const playerTitleStyle = computed(() => {
  if (!isPlayerLight.value) return {}
  return isDarkTheme.value ? { color: '#f8fafc' } : { color: '#1f2937' }
})

const playerCloseStyle = computed(() => {
  if (!isPlayerLight.value) return {}
  return isDarkTheme.value ? { color: '#94a3b8' } : { color: '#6b7280' }
})

const playerFooterStyle = computed(() => {
  if (!isPlayerLight.value) return {}
  return isDarkTheme.value
    ? { background: '#0b0f16', borderTop: '1px solid #1f2937' }
    : { background: '#f8fafc', borderTop: '1px solid #e5e7eb' }
})

const playerContainerStyle = computed(() => {
  if (!isPlayerLight.value) return {}
  return isDarkTheme.value ? { background: '#0b0f16' } : { background: '#ffffff' }
})

onMounted(() => {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  theme.value = root.getAttribute('data-theme') || ''
  themeObserver = new MutationObserver(() => {
    theme.value = root.getAttribute('data-theme') || ''
  })
  themeObserver.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
})

onUnmounted(() => {
  if (themeObserver) themeObserver.disconnect()
  themeObserver = null
})

const getIcon = computed(() => {
  const icons = {
    success: 'check',
    error: 'x',
    warning: 'alert-triangle',
    info: 'bell'
  }
  return icons[props.type] || 'bell'
})

const overlayStyle = computed(() => {
  const style = { zIndex: props.zIndex }
  if (props.overlayPadding) style.padding = props.overlayPadding
  if (props.overlayAlign) style.alignItems = props.overlayAlign
  return style
})

const containerStyle = computed(() => {
  const style = { maxWidth: props.width }
  if (props.containerHeight) {
    style.height = props.containerHeight
    style.maxHeight = props.containerHeight
  }
  return style
})

const bodyStyle = computed(() => {
  const style = {}
  if (props.bodyPadding) style.padding = props.bodyPadding
  return style
})

const handleClose = () => {
  emit('update:show', false)
  emit('close')
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 30000;
  padding: 20px;
  overflow-y: auto; /* 允许内容超出视口时滚动 */
  -webkit-overflow-scrolling: touch;
}

.modal-container {
  background: var(--color-bg-secondary);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.header-content h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.modal-title-single-line {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.type-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-success { background: var(--color-success-light); color: var(--color-success); }
.icon-error { background: var(--color-error-light); color: var(--color-error); }
.icon-warning { background: var(--color-warning-light); color: var(--color-warning); }
.icon-info { background: var(--color-primary-light); color: var(--color-primary); }

.close-btn {
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast);
  padding: 4px;
  border-radius: var(--radius-md);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.close-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

/* Force light theme variables inside player modal */
:global(.player-modal-light) {
  --color-bg-primary: #f5f5f5;
  --color-bg-secondary: #ffffff;
  --color-bg-tertiary: #f2f2f2;
  --color-bg-hover: #eeeeee;
  --color-bg-card: #ffffff;
  --color-primary-rgb: 230, 126, 34;
  --color-text-primary: #1f2937;
  --color-text-secondary: #4b5563;
  --color-text-tertiary: #6b7280;
  --color-text-muted: #9ca3af;
  --color-border: #e5e7eb;
  --color-border-light: #d1d5db;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
  --shadow-md: 0 2px 6px rgba(0, 0, 0, 0.08);
  --shadow-lg: 0 8px 20px rgba(15, 23, 42, 0.12);
}

:global(.player-modal-light) .modal-body {
  background: var(--color-bg-primary) !important;
}

:global(.modal-overlay.player-modal-light) .modal-container {
  background: #ffffff !important;
}

:global(.modal-overlay.player-modal-light) .modal-header {
  background: #ffffff !important;
  border-bottom: 1px solid #e5e7eb !important;
}

:global(.modal-overlay.player-modal-light) .modal-footer {
  background: #f8fafc !important;
  border-top: 1px solid #e5e7eb !important;
}

:global(.modal-overlay.player-modal-light) .header-content h3 {
  color: #1f2937 !important;
}

:global(.modal-overlay.player-modal-light) .close-btn {
  color: #6b7280 !important;
}

:global(.modal-overlay.player-modal-light) .close-btn:hover {
  color: #111827 !important;
  background: #f1f5f9 !important;
}

[data-theme="dark"] :global(.player-modal-light) {
  --color-bg-primary: #1a1a1a;
  --color-bg-secondary: #252525;
  --color-bg-tertiary: #2d2d2d;
  --color-bg-hover: #353535;
  --color-bg-card: #252525;
  --color-text-primary: #d0d0d0;
  --color-text-secondary: #a0a0a0;
  --color-text-tertiary: #7a7a7a;
  --color-text-muted: #5a5a5a;
  --color-border: #3a3a3a;
  --color-border-light: #4a4a4a;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-md: 0 2px 4px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 4px 8px rgba(0, 0, 0, 0.5);
}

[data-theme="dark"] :global(.modal-overlay.player-modal-light) .modal-container {
  background: #0b0f16 !important;
}

[data-theme="dark"] :global(.modal-overlay.player-modal-light) .modal-header {
  background: #0b0f16 !important;
  border-bottom: 1px solid #1f2937 !important;
}

[data-theme="dark"] :global(.modal-overlay.player-modal-light) .modal-footer {
  background: #0b0f16 !important;
  border-top: 1px solid #1f2937 !important;
}

[data-theme="dark"] :global(.player-modal-light) .modal-body {
  background: #000 !important;
}

[data-theme="dark"] :global(.modal-overlay.player-modal-light) .header-content h3 {
  color: #f8fafc !important;
}

[data-theme="dark"] :global(.modal-overlay.player-modal-light) .close-btn {
  color: #94a3b8 !important;
}

[data-theme="dark"] :global(.modal-overlay.player-modal-light) .close-btn:hover {
  color: #f8fafc !important;
  background: rgba(148, 163, 184, 0.12) !important;
}

/* Player Modal Light Theme Overrides (Teleport-safe) */
:global(.player-modal) .modal-container {
  background: var(--color-bg-card) !important;
}

:global(.player-modal) .modal-header {
  background: var(--color-bg-card) !important;
  border-bottom: 1px solid var(--color-border) !important;
}

:global(.player-modal) .modal-body {
  background: var(--color-bg-card) !important;
}

:global(.player-modal) .modal-footer {
  background: var(--color-bg-secondary) !important;
  border-top: 1px solid var(--color-border) !important;
}

:global(.player-modal) .header-content h3 {
  color: var(--color-text-primary) !important;
}

:global(.player-modal) .close-btn {
  color: var(--color-text-tertiary) !important;
}

:global(.player-modal) .close-btn:hover {
  color: var(--color-text-primary) !important;
  background: var(--color-bg-hover) !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-container {
  background: #000 !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-header {
  background: #0b0f16 !important;
  border-bottom: 1px solid #1f2937 !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-body {
  background: #000 !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .modal-footer {
  background: #0b0f16 !important;
  border-top: 1px solid #1f2937 !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .header-content h3 {
  color: #f8fafc !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .close-btn {
  color: #94a3b8 !important;
}

[data-theme="dark"] :global(.player-modal:not(.player-modal-light)) .close-btn:hover {
  color: #f8fafc !important;
  background: rgba(148, 163, 184, 0.12) !important;
}

.modal-body {
  padding: 24px;
  font-size: 15px;
  line-height: 1.6;
  color: var(--color-text-secondary);
  max-height: 70vh;
  overflow-y: auto;
}

.modal-body-fill {
  flex: 1 1 auto;
  max-height: none;
  overflow: hidden;
  display: flex;
}

.modal-footer {
  padding: 1.5rem;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: var(--spacing-md);
  border-top: 1px solid var(--border-color);
}

/* 移除对全局按钮样式的干扰，确保按钮高度一致且对齐 */
.modal-footer :deep(.btn) {
  min-width: 90px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0; /* 消除可能的边距干扰 */
  cursor: pointer;
}

/* 动画优化 */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.4s cubic-bezier(0.25, 0.1, 0.25, 1);
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  opacity: 0;
  transform: scale(0.92) translateY(30px);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .modal-overlay {
    padding: 8px; /* 严格对齐 8px 边距 */
    padding-top: max(12px, env(safe-area-inset-top)); /* 适配刘海屏 */
    padding-bottom: max(12px, env(safe-area-inset-bottom));
    align-items: flex-start; /* 移动端顶部对齐，防止内容过长导致头部被切掉 */
  }

  .modal-container {
    max-width: calc(100vw - 16px) !important;
    max-height: calc(100vh - 24px - env(safe-area-inset-top) - env(safe-area-inset-bottom)) !important;
    margin: 0; /* 移除 margin，靠 overlay 的 padding 提供边距 */
    border-radius: var(--radius-lg);
  }

  .modal-header {
    padding: 16px 20px;
  }

  .modal-body {
    padding: 20px;
    font-size: 14px;
  }

  .modal-footer {
    padding: 16px 20px;
    gap: 10px;
  }

  .modal-footer :deep(.btn) {
    flex: 1;
    padding: 0.75rem 0; /* 移动端增加高度方便点击 */
  }
}

</style>
