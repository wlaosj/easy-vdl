<template>
  <div class="files-page">
    <div class="browser-container">
      <!-- 加载态 -->
      <div v-if="loading" class="files-loading">
        <div class="files-loading-spinner"></div>
        <span>加载文件管理器...</span>
      </div>

      <!-- 错误态 -->
      <div v-if="loadError" class="files-error">
        <div class="files-error-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>
        <span class="files-error-text">文件管理器加载失败</span>
        <span class="files-error-hint">请检查后端服务是否正常运行</span>
        <button class="file-retry-btn" @click="retryLoad">重试</button>
      </div>

      <iframe
        ref="iframeRef"
        src="/files/"
        class="file-browser-frame"
        title="File Browser"
        sandbox="allow-scripts allow-same-origin"
        :class="{ 'is-loaded': !loading && !loadError }"
        @load="onLoad"
      ></iframe>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const iframeRef = ref(null)
const loading = ref(true)
const loadError = ref(false)
let loadTimer = null

function onLoad() {
  loading.value = false
  loadError.value = false
  clearTimeout(loadTimer)
}

function retryLoad() {
  loading.value = true
  loadError.value = false
  if (iframeRef.value) {
    iframeRef.value.src = '/files/'
  }
  startLoadTimer()
}

function startLoadTimer() {
  clearTimeout(loadTimer)
  loadTimer = setTimeout(() => {
    if (loading.value) {
      loading.value = false
      loadError.value = true
    }
  }, 15000)
}

onMounted(() => {
  startLoadTimer()
})

onUnmounted(() => {
  clearTimeout(loadTimer)
})
</script>

<style scoped>
.files-page {
  height: calc(100vh - var(--header-height) - 40px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
}

.browser-container {
  flex: 1;
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
}

.file-browser-frame {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
  opacity: 0;
  transition: opacity var(--transition-normal);
}

.file-browser-frame.is-loaded {
  opacity: 1;
}

/* 加载态 */
.files-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-md);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
  background: var(--color-bg-card);
  z-index: 1;
}

.files-loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: files-spin 0.8s linear infinite;
}

@keyframes files-spin {
  to { transform: rotate(360deg); }
}

/* 错误态 */
.files-error {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-sm);
  background: var(--color-bg-card);
  z-index: 1;
  padding: var(--spacing-xl);
}

.files-error-icon {
  color: var(--color-error);
  margin-bottom: var(--spacing-sm);
}

.files-error-text {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.files-error-hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--spacing-md);
}

.file-retry-btn {
  padding: var(--spacing-sm) var(--spacing-xl);
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.file-retry-btn:hover {
  background: var(--color-primary-hover);
}
</style>
