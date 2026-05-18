<template>
  <div
    class="card announcements-card compact"
    :class="{
      'has-update': hasAppUpdate,
      'matrix-mode': hasAppUpdate,
      'unread-mode': hasUnreadNotice && !hasAppUpdate
    }"
    @click="handleClick"
    @mouseenter="pauseMatrixAnimation"
    @mouseleave="resumeMatrixAnimation"
    style="cursor: pointer;"
  >
    <canvas v-if="hasAppUpdate" ref="matrixCanvas" class="matrix-bg"></canvas>
    <div class="announcements-status">
      <div class="ann-status-content">
        <div class="ann-status-text">
          <div class="ann-status-title-wrapper">
            <div class="ann-status-title">
              <span v-if="hasUnreadNotice && !hasAppUpdate" class="unread-dot" aria-hidden="true"></span>
              <span v-if="hasUnreadNotice" class="text-xl">有新消息</span>
              <span v-else-if="hasAppUpdate" class="text-xl">发现新版本</span>
              <span v-else>暂无新公告</span>
            </div>
            <!-- 版本状态：仅在无新公告且无新版本时显示 -->
            <span v-if="!hasUnreadNotice && !hasAppUpdate" class="version-status-text version-status-mobile">
              <svg class="version-check-icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5" fill="none"/>
                <path d="M5 8L7 10L11 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
              </svg>
              已是最新版
            </span>
          </div>
          <!-- 电脑端分行显示的版本状态 -->
          <div v-if="!hasUnreadNotice && !hasAppUpdate" class="version-status-desktop">
            <span class="version-status-text">
              <svg class="version-check-icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5" fill="none"/>
                <path d="M5 8L7 10L11 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
              </svg>
              已是最新版
            </span>
          </div>
          <button
            v-if="hasAppUpdate"
            class="changelog-link"
            type="button"
            @click.stop="handleClick"
          >
            点击查看更新日志
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  hasAppUpdate: {
    type: Boolean,
    default: false
  },
  hasUnreadNotice: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['click'])

const matrixCanvas = ref(null)
let matrixAnimationId = null
let matrixDrops = []
let matrixCtx = null
let matrixConfig = null
let matrixSpeedFactor = 1.0
let matrixLastFrameTime = 0
let matrixTargetSpeed = 1.0
const MATRIX_BASE_INTERVAL = 33

function drawMatrix() {
  if (!matrixCtx || !matrixConfig) return
  
  matrixCtx.fillStyle = 'rgba(0, 0, 0, 0.05)'
  matrixCtx.fillRect(0, 0, matrixConfig.canvas.width, matrixConfig.canvas.height)
  
  matrixCtx.fillStyle = '#0F0'
  matrixCtx.font = matrixConfig.fontSize + 'px monospace'
  
  for (let i = 0; i < matrixDrops.length; i++) {
    const text = matrixConfig.letters.charAt(Math.floor(Math.random() * matrixConfig.letters.length))
    
    const x = i * matrixConfig.fontSize
    const y = matrixDrops[i] * matrixConfig.fontSize
    
    const centerX = matrixConfig.canvas.width / 2
    const centerY = matrixConfig.canvas.height / 2
    const avoidWidth = 160
    const avoidHeight = 50

    const inSafeZone = Math.abs(x - centerX) < avoidWidth / 2 && 
                       Math.abs(y - centerY) < avoidHeight / 2

    if (!inSafeZone) {
      matrixCtx.fillText(text, x, y)
    }
    
    if (matrixDrops[i] * matrixConfig.fontSize > matrixConfig.canvas.height && Math.random() > 0.975) {
      matrixDrops[i] = 0
    }
    matrixDrops[i] += matrixSpeedFactor
  }
}

function matrixAnimationLoop(currentTime) {
  if (!matrixCtx || !matrixConfig) return
  
  const speedTransitionRate = 0.05
  matrixSpeedFactor += (matrixTargetSpeed - matrixSpeedFactor) * speedTransitionRate
  matrixSpeedFactor = Math.max(matrixSpeedFactor, 0.1)
  
  const actualInterval = MATRIX_BASE_INTERVAL / matrixSpeedFactor
  
  if (currentTime - matrixLastFrameTime >= actualInterval) {
    drawMatrix()
    matrixLastFrameTime = currentTime
  }
  
  matrixAnimationId = requestAnimationFrame(matrixAnimationLoop)
}

function startMatrixAnimation() {
  const canvas = matrixCanvas.value
  if (!canvas) return
  
  const ctx = canvas.getContext('2d')
  canvas.width = canvas.offsetWidth
  canvas.height = canvas.offsetHeight
  
  const letters = 'EASYVDL'
  const fontSize = 14
  const columns = canvas.width / fontSize
  
  if (matrixDrops.length === 0) {
    for (let i = 0; i < columns; i++) {
      matrixDrops[i] = 1
    }
  }
  
  matrixCtx = ctx
  matrixConfig = { letters, fontSize, columns, canvas }
  matrixSpeedFactor = 1.0
  matrixTargetSpeed = 1.0
  matrixLastFrameTime = performance.now()
  
  if (matrixAnimationId) {
    cancelAnimationFrame(matrixAnimationId)
  }
  
  matrixAnimationId = requestAnimationFrame(matrixAnimationLoop)
}

function pauseMatrixAnimation() {
  matrixTargetSpeed = 0.2
}

function resumeMatrixAnimation() {
  if (matrixCtx && matrixConfig) {
    matrixTargetSpeed = 1.0
    matrixLastFrameTime = performance.now()
    
    if (!matrixAnimationId) {
      matrixAnimationId = requestAnimationFrame(matrixAnimationLoop)
    }
  }
}

function handleClick() {
  emit('click')
}

watch(() => props.hasAppUpdate, (newVal) => {
  if (newVal) {
    nextTick(() => {
      if (matrixAnimationId) {
        cancelAnimationFrame(matrixAnimationId)
        matrixAnimationId = null
      }
      matrixDrops = []
      matrixCtx = null
      matrixConfig = null
      startMatrixAnimation()
    })
  } else {
    if (matrixAnimationId) {
      cancelAnimationFrame(matrixAnimationId)
      matrixAnimationId = null
    }
    matrixDrops = []
    matrixCtx = null
    matrixConfig = null
    matrixSpeedFactor = 1.0
    matrixTargetSpeed = 1.0
  }
}, { immediate: true })

onMounted(() => {
  if (props.hasAppUpdate) {
    nextTick(() => {
      startMatrixAnimation()
    })
  }
})

onUnmounted(() => {
  if (matrixAnimationId) {
    cancelAnimationFrame(matrixAnimationId)
    matrixAnimationId = null
  }
  matrixDrops = []
  matrixCtx = null
  matrixConfig = null
  matrixSpeedFactor = 1.0
  matrixTargetSpeed = 1.0
})
</script>

<style scoped>
.announcements-card.compact {
  flex: 1.2;
  min-width: 0;
}

.announcements-card.compact,
.announcements-card.compact.stat-card {
  min-height: 110px;
  height: 110px;
}

.card.announcements-card.matrix-mode {
  position: relative;
  overflow: hidden;
  background: black !important;
  border: 1px solid #333;
}

.card.announcements-card.unread-mode {
  border-color: #f59e0b;
  background: linear-gradient(180deg, rgba(255, 248, 230, 0.9) 0%, rgba(255, 243, 217, 0.85) 100%);
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.14), 0 8px 18px rgba(245, 158, 11, 0.12);
}

.card.announcements-card.matrix-mode canvas.matrix-bg {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 1;
  z-index: 0;
  pointer-events: none;
}

.card.announcements-card.matrix-mode .announcements-status {
  position: relative;
  z-index: 1;
}

.card.announcements-card.matrix-mode .ann-status-title span {
  color: #0F0;
  text-shadow: 0 0 5px #0F0;
  font-family: 'Monaco', 'Menlo', monospace;
  font-weight: bold;
  letter-spacing: 1px;
}

.announcements-status {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.ann-status-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.ann-status-text {
  text-align: center;
}

.ann-status-title-wrapper {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-wrap: wrap;
}

.ann-status-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  text-align: center;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.unread-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7);
  animation: unreadPulse 1.8s infinite;
}

.text-xl {
  font-size: 18px;
}

.version-status-text {
  font-size: 12px;
  color: var(--color-text-secondary, #666);
  opacity: 0.8;
  font-weight: 400;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.version-check-icon {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  color: #10b981;
  opacity: 0.9;
}

/* 移动端：同一行显示 */
.version-status-mobile {
  display: inline;
}

.version-status-desktop {
  display: none;
}

.changelog-link {
  margin-top: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.2;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
  opacity: 0.9;
}

@keyframes unreadPulse {
  0% {
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7);
  }
  70% {
    box-shadow: 0 0 0 10px rgba(239, 68, 68, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);
  }
}

.changelog-link:hover {
  opacity: 1;
  color: var(--color-text-primary);
}

.card.announcements-card.matrix-mode .changelog-link {
  color: rgba(143, 255, 143, 0.95);
  text-shadow: 0 0 4px rgba(15, 255, 15, 0.45);
}

/* 电脑端：分行显示 */
@media (min-width: 768px) {
  .ann-status-title-wrapper {
    flex-direction: column;
    gap: 0;
  }
  
  .ann-status-title {
    width: 100%;
    font-size: 18px;
  }
  
  .text-xl {
    font-size: 20px;
  }
  
  .version-status-text {
    font-size: 14px;
  }
  
  .version-check-icon {
    width: 14px;
    height: 14px;
  }
  
  .version-status-mobile {
    display: none;
  }
  
  .version-status-desktop {
    display: block;
    margin-top: 6px;
    text-align: center;
  }

  .changelog-link {
    font-size: 13px;
    margin-top: 8px;
  }
}
</style>
