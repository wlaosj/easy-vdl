<template>
  <Teleport to="body">
    <Transition name="vnc-modal">
      <div v-if="show" class="vnc-modal-overlay" @click.self="handleClose">
        <div class="vnc-modal-container">
          <!-- 头部 -->
          <div class="vnc-modal-header">
            <h3 class="vnc-modal-title">{{ title }}</h3>
            <button class="vnc-save-btn" @click="handleSave">
              <Icon name="check" :size="16" />
              <span class="btn-text">保存登录</span>
            </button>
          </div>

          <!-- VNC iframe 容器 -->
          <div class="vnc-frame-container">
            <iframe
              ref="vncFrame"
              class="vnc-frame"
              :src="vncUrl"
              @load="handleFrameLoad"
            ></iframe>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import Icon from '@/components/common/Icon.vue'
import { subscriptionsApi } from '@/api/subscriptions'

const props = defineProps({
  show: Boolean,
  platform: {
    type: String,
    required: true,
    validator: (value) => ['douyin', 'youtube', 'bilibili', 'xiaohongshu'].includes(value)
  }
})

const emit = defineEmits(['update:show', 'close'])

const vncFrame = ref(null)
const browserRunning = ref(false)
const isClosing = ref(false)
const frameWatchTimer = ref(null)
const heartbeatTimer = ref(null)
const heartbeatInFlight = ref(false)
const HEARTBEAT_INTERVAL_MS = 10000

// 平台标题映射
const platformTitles = {
  douyin: '抖音登录',
  youtube: 'YouTube登录',
  bilibili: 'B站登录',
  xiaohongshu: '小红书登录'
}

// 平台关闭API映射
const platformCloseApis = {
  douyin: '/api/subscribe/douyin/close',
  youtube: '/api/subscribe/youtube/close',
  bilibili: '/api/subscribe/bilibili/close',
  xiaohongshu: '/api/subscribe/xiaohongshu/close'
}

const title = computed(() => platformTitles[props.platform] || '账号登录')

// VNC URL配置
const vncUrl = computed(() => {
  if (!props.show) return ''
  const token = localStorage.getItem('token')
  const wsPath = token ? `websockify?token=${encodeURIComponent(token)}` : 'websockify'
  return '/novnc/vnc_lite.html?path=' + encodeURIComponent(wsPath) +
    '&autoconnect=true&resize=remote&scale=true&quality=9&compression=0&show_dot=true&reconnect=true'
})

// iframe加载完成
function handleFrameLoad() {
  // 设置浏览器运行标记
  browserRunning.value = true
  
  // 监听iframe关闭
  stopFrameWatch()
  frameWatchTimer.value = setInterval(() => {
    try {
      if (!vncFrame.value?.contentWindow || vncFrame.value.contentWindow.closed) {
        stopFrameWatch()
        handleClose()
      }
    } catch (e) {
      // 跨域访问限制，忽略错误
    }
  }, 1000)
}

function stopFrameWatch() {
  if (frameWatchTimer.value) {
    clearInterval(frameWatchTimer.value)
    frameWatchTimer.value = null
  }
}

async function sendHeartbeat() {
  if (heartbeatInFlight.value || !props.show) return
  heartbeatInFlight.value = true
  try {
    await subscriptionsApi.browserHeartbeat(props.platform)
  } catch (error) {
    console.warn('VNC心跳发送失败:', error)
  } finally {
    heartbeatInFlight.value = false
  }
}

function startHeartbeat() {
  if (heartbeatTimer.value) return
  sendHeartbeat()
  heartbeatTimer.value = setInterval(() => {
    sendHeartbeat()
  }, HEARTBEAT_INTERVAL_MS)
}

function stopHeartbeat() {
  if (heartbeatTimer.value) {
    clearInterval(heartbeatTimer.value)
    heartbeatTimer.value = null
  }
  heartbeatInFlight.value = false
}

// 保存登录并关闭
async function handleSave() {
  await handleClose()
}

// 关闭模态框
async function handleClose() {
  if (isClosing.value) return
  isClosing.value = true

  stopHeartbeat()
  stopFrameWatch()

  // 清空iframe源
  if (vncFrame.value) {
    vncFrame.value.src = 'about:blank'
  }
  
  // 发送关闭浏览器请求
  if (browserRunning.value) {
    try {
      const closeUrl = platformCloseApis[props.platform]
      await fetch(closeUrl, { method: 'POST' })
    } catch (error) {
      console.error('关闭浏览器失败:', error)
    }
  }
  
  browserRunning.value = false
  emit('update:show', false)
  emit('close')
  isClosing.value = false
}

// 页面关闭/刷新提示
function handlePageClose(event) {
  if (props.show && browserRunning.value) {
    event.preventDefault()
    event.returnValue = '浏览器窗口正在运行，关闭页面将中断登录过程。确定要离开吗？'
    return event.returnValue
  }
}

// 监听显示状态
watch(() => props.show, (newVal) => {
  if (newVal) {
    startHeartbeat()
    // 添加页面关闭监听
    window.addEventListener('beforeunload', handlePageClose)
    // 禁止body滚动
    document.body.style.overflow = 'hidden'
  } else {
    stopHeartbeat()
    stopFrameWatch()
    // 移除页面关闭监听
    window.removeEventListener('beforeunload', handlePageClose)
    // 恢复body滚动
    document.body.style.overflow = ''
  }
})

// 组件卸载时清理
onBeforeUnmount(() => {
  stopHeartbeat()
  stopFrameWatch()
  window.removeEventListener('beforeunload', handlePageClose)
  document.body.style.overflow = ''
})
</script>

<style scoped>
.vnc-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20000;
  padding: 20px;
  overflow: auto;
}

.vnc-modal-container {
  background: white;
  border-radius: 12px;
  width: min(1000px, 95vw);
  max-height: 95vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
}

.vnc-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid var(--color-border);
}

.vnc-modal-title {
  font-size: 1.2rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}

.vnc-save-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.vnc-save-btn:hover {
  background: #d35400;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(230, 126, 34, 0.3);
}

.vnc-save-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(230, 126, 34, 0.2);
}

.vnc-frame-container {
  width: 100%;
  height: min(1024px, calc(95vh - 100px));
  background: #f5f5f5;
  border-radius: 0 0 12px 12px;
  overflow: hidden;
  position: relative;
}

.vnc-frame {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}

/* 动画 */
.vnc-modal-enter-active,
.vnc-modal-leave-active {
  transition: opacity 0.3s ease;
}

.vnc-modal-enter-active .vnc-modal-container,
.vnc-modal-leave-active .vnc-modal-container {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.vnc-modal-enter-from,
.vnc-modal-leave-to {
  opacity: 0;
}

.vnc-modal-enter-from .vnc-modal-container,
.vnc-modal-leave-to .vnc-modal-container {
  opacity: 0;
  transform: scale(0.95) translateY(20px);
}

/* 响应式 */
@media (max-width: 768px) {
  .vnc-modal-overlay {
    padding: 0;
    align-items: flex-start; /* 从顶部开始 */
  }

  .vnc-modal-container {
    width: 100%;
    max-width: 100%;
    height: auto; /* 自适应高度 */
    max-height: 100vh; /* 最大不超过屏幕 */
    border-radius: 0;
  }

  .vnc-modal-header {
    padding: var(--spacing-sm) var(--spacing-md);
    flex-wrap: wrap;
    gap: var(--spacing-xs);
  }

  .vnc-modal-title {
    font-size: 1rem;
    flex: 1;
    min-width: 0;
  }

  .vnc-save-btn {
    padding: 6px 12px;
    font-size: 0.85rem;
    white-space: nowrap;
  }

  .vnc-frame-container {
    height: 70vh; /* 使用视口高度的70% */
    max-height: 600px; /* 限制最大高度 */
    border-radius: 0;
  }
}

/* 超窄屏优化 */
@media (max-width: 400px) {
  .vnc-modal-header {
    padding: var(--spacing-xs) var(--spacing-sm);
  }

  .vnc-modal-title {
    font-size: 0.9rem;
  }

  .vnc-save-btn {
    padding: 5px 10px;
    font-size: 0.8rem;
  }

  .vnc-save-btn .btn-text {
    display: none; /* 超窄屏只显示图标 */
  }
}
</style>
