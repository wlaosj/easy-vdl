<template>
  <div v-if="show" class="clip-editor-overlay" @click.self="$emit('close')">
    <div class="clip-editor">
      <!-- 顶部栏 -->
      <div class="editor-header">
        <div class="editor-header-left">
          <h2 class="editor-title">切片编辑器</h2>
          <span class="editor-segment-label" :title="title">{{ title }}</span>
        </div>
        <div class="editor-header-actions">
          <button class="editor-btn close-btn" @click="$emit('close')" title="关闭">
            <Icon name="x" :size="20" />
          </button>
        </div>
      </div>

      <!-- 主体 -->
      <div class="editor-body">
        <!-- 左栏：视频 + 时间轴 -->
        <div class="editor-main">
          <div class="editor-player-wrap">
            <video
              v-if="videoUrl"
              ref="previewVideoRef"
              class="editor-video"
              :src="videoUrl"
              controls
              autoplay
              playsinline
              @error="handlePreviewError"
              @loadedmetadata="onPreviewLoaded"
              @timeupdate="onPreviewTimeUpdate"
            />
            <div v-else class="editor-empty">暂无可预览的视频源</div>
          </div>

          <div class="editor-actions-row">
            <button class="editor-btn" :disabled="exporting" @click="handleExport">
              <Icon name="check" :size="16" />
              <span>{{ exporting ? '导出中...' : '导出切片' }}</span>
            </button>
            <button class="editor-btn secondary" @click="resetRange">
              <Icon name="refresh" :size="16" />
              <span>重置</span>
            </button>
            <button
              class="editor-btn secondary loop-btn"
              :class="{ active: loopPlayback }"
              @click="toggleLoopPlayback"
              :title="loopPlayback ? '关闭区间循环播放' : '开启区间循环播放'"
            >
              <Icon name="repeat" :size="16" />
              <span>{{ loopPlayback ? '循环中' : '区间循环' }}</span>
            </button>
          </div>

          <div class="editor-timeline-wrap" v-if="originalDuration > 0">
            <TimelineRange
              :start-sec="adjustedStartSec"
              :end-sec="adjustedEndSec"
              :total-duration="originalDuration"
              :frame-rate="detectedFrameRate"
              :current-sec="currentPreviewSec"
              label="拖拽手柄调整切片范围"
              @update:start-sec="onStartSecAdjusted"
              @update:end-sec="onEndSecAdjusted"
              @seek="onTimelineSeek"
            />
          </div>
        </div>

        <!-- 右栏：时间信息 + 扩展插槽 -->
        <div class="editor-sidebar">
          <slot name="sidebar-extra" />
          <div class="sidebar-card">
            <div class="sidebar-card-head">
              <Icon name="clock" :size="13" />
              <span>时间</span>
            </div>
            <div class="sidebar-time-display">
              <div class="time-row">
                <span class="time-label">起始</span>
                <span class="time-value">{{ secToClock(adjustedStartSec) }}</span>
              </div>
              <div class="time-row">
                <span class="time-label">结束</span>
                <span class="time-value">{{ secToClock(adjustedEndSec) }}</span>
              </div>
              <div class="time-row">
                <span class="time-label">长度</span>
                <span class="time-value primary">{{ secToClock(adjustedEndSec - adjustedStartSec) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'
import Icon from '@/components/common/Icon.vue'
import TimelineRange from '@/components/business/TimelineRange.vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  videoUrl: { type: String, default: '' },
  title: { type: String, default: '手动切片' },
  /** 外部传入的初始时长，如果为 0 则从视频元素加载 */
  initialDuration: { type: Number, default: 0 },
  /** 初始起始秒数（AI 模式传入片段起止时间） */
  startSec: { type: Number, default: 0 },
  /** 初始结束秒数 */
  endSec: { type: Number, default: 30 },
  /** TS 流模式（浏览器无法 seek，需后端重建 URL） */
  tsMode: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'export', 'time-change', 'seek'])

const previewVideoRef = ref(null)
const adjustedStartSec = ref(0)
const adjustedEndSec = ref(30)
const originalDuration = ref(0)
const currentPreviewSec = ref(-1)
const exporting = ref(false)
const detectedFrameRate = ref(30)
const loopPlayback = ref(false)
let frameProbeHandle = 0
let frameProbeLastMediaTime = 0
let frameProbeCounter = 0
let frameProbeAccum = 0

watch(() => props.show, (v) => {
  if (v) {
    const dur = props.initialDuration || 0
    const start = props.startSec
    const end = props.endSec > start ? props.endSec : start + 30
    adjustedStartSec.value = start
    adjustedEndSec.value = Math.min(end, dur > 0 ? dur : end)
    originalDuration.value = dur
    currentPreviewSec.value = -1
    detectedFrameRate.value = 30
    stopFrameRateProbe()
  } else {
    stopFrameRateProbe()
  }
})

function secToClock(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const x = s % 60
  if (h > 0) return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`
  return `${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`
}

function onPreviewLoaded() {
  if (previewVideoRef.value) {
    const vidDur = previewVideoRef.value.duration
    if (vidDur > 0 && (originalDuration.value <= 0 || Math.abs(vidDur - originalDuration.value) > 1)) {
      originalDuration.value = vidDur
      if (adjustedEndSec.value > vidDur) adjustedEndSec.value = vidDur
    }
  }
  if (adjustedStartSec.value > 0) {
    seekTo(adjustedStartSec.value)
  }
  startFrameRateProbe()
}

function onPreviewTimeUpdate() {
  const vid = previewVideoRef.value
  if (!vid) return
  currentPreviewSec.value = Number(vid.currentTime || 0)
  if (!vid.paused && !vid.ended && adjustedEndSec.value > 0 &&
      Number(vid.currentTime || 0) >= adjustedEndSec.value) {
    if (loopPlayback.value) {
      if (props.tsMode) {
        seekTo(adjustedStartSec.value)
      } else {
        vid.currentTime = adjustedStartSec.value
        vid.play().catch(() => {})
      }
    } else {
      vid.pause()
    }
  }
}

function seekTo(sec) {
  if (props.tsMode) {
    emit('seek', sec)
  } else if (previewVideoRef.value) {
    previewVideoRef.value.currentTime = sec
  }
}

function onStartSecAdjusted(sec) {
  adjustedStartSec.value = sec
  seekTo(sec)
  emit('time-change', { startSec: sec, endSec: adjustedEndSec.value })
}

function onEndSecAdjusted(sec) {
  adjustedEndSec.value = sec
  emit('time-change', { startSec: adjustedStartSec.value, endSec: sec })
}

function onTimelineSeek(sec) {
  currentPreviewSec.value = sec
  seekTo(sec)
}

function toggleLoopPlayback() {
  loopPlayback.value = !loopPlayback.value
}

function resetRange() {
  adjustedStartSec.value = 0
  adjustedEndSec.value = Math.min(30, originalDuration.value || 30)
  seekTo(0)
}

async function handleExport() {
  exporting.value = true
  try {
    await emit('export', {
      startSec: adjustedStartSec.value,
      endSec: adjustedEndSec.value,
    })
  } finally {
    exporting.value = false
  }
}

function handlePreviewError() {
  console.warn('ClipEditor: video playback error')
}

function startFrameRateProbe() {
  stopFrameRateProbe()
  const video = previewVideoRef.value
  if (!video || typeof video.requestVideoFrameCallback !== 'function') return

  frameProbeLastMediaTime = 0
  frameProbeCounter = 0
  frameProbeAccum = 0

  const onFrame = (_, metadata) => {
    if (!props.show) return
    const mediaTime = Number(metadata?.mediaTime || 0)
    if (frameProbeLastMediaTime > 0 && mediaTime > frameProbeLastMediaTime) {
      const delta = mediaTime - frameProbeLastMediaTime
      const fps = 1 / delta
      if (Number.isFinite(fps) && fps > 1 && fps < 240) {
        frameProbeAccum += fps
        frameProbeCounter += 1
        if (frameProbeCounter >= 8) {
          detectedFrameRate.value = Math.round((frameProbeAccum / frameProbeCounter) * 100) / 100
        }
      }
    }
    frameProbeLastMediaTime = mediaTime
    frameProbeHandle = video.requestVideoFrameCallback(onFrame)
  }

  frameProbeHandle = video.requestVideoFrameCallback(onFrame)
}

function stopFrameRateProbe() {
  const video = previewVideoRef.value
  if (video && frameProbeHandle && typeof video.cancelVideoFrameCallback === 'function') {
    video.cancelVideoFrameCallback(frameProbeHandle)
  }
  frameProbeHandle = 0
}

onUnmounted(() => {
  stopFrameRateProbe()
})
</script>

<style scoped>
.clip-editor-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: editorFadeIn 0.2s ease;
}
@keyframes editorFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
.clip-editor {
  width: 95vw;
  height: 92vh;
  background: var(--color-bg-card);
  border-radius: 14px;
  box-shadow: 0 12px 60px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: editorSlideIn 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes editorSlideIn {
  from { transform: translateY(20px) scale(0.97); opacity: 0; }
  to { transform: translateY(0) scale(1); opacity: 1; }
}
.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}
.editor-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.editor-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text-primary);
  margin: 0;
  white-space: nowrap;
}
.editor-segment-label {
  font-size: 13px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.editor-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.editor-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 8px;
  border: none;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  background: var(--color-primary);
  color: #fff;
  transition: all 0.15s ease;
}
.editor-btn:hover { opacity: 0.9; transform: translateY(-1px); }
.editor-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.editor-btn.secondary {
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
}
.editor-btn.secondary:hover {
  background: var(--color-bg-hover);
}
.editor-btn.close-btn {
  background: transparent;
  color: var(--color-text-secondary);
  padding: 6px;
}
.editor-btn.close-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
  transform: none;
}
.editor-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 0;
  min-height: 0;
  overflow: hidden;
}
.editor-main {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #000;
}
.editor-player-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
  background: #000;
  position: relative;
}
.editor-video {
  max-width: 100%;
  max-height: 100%;
  display: block;
  outline: none;
}
.editor-empty {
  color: var(--color-text-secondary);
  font-size: 14px;
}
.editor-actions-row {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
  background: var(--color-bg-tertiary, #1a1a1a);
  flex-shrink: 0;
}
.editor-timeline-wrap {
  padding: 8px 16px 12px;
  background: var(--color-bg-tertiary, #1a1a1a);
  flex-shrink: 0;
}
.loop-btn.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-bg-secondary));
}
.editor-sidebar {
  padding: 16px;
  overflow-y: auto;
  background: var(--color-bg-card);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sidebar-card {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 14px;
}
.sidebar-card-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 10px;
}
.sidebar-time-display {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.time-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.time-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}
.time-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.time-value.primary {
  color: var(--color-primary);
}

/* 适配移动端 */
@media (max-width: 768px) {
  .clip-editor {
    width: 100vw;
    height: 100vh;
    height: 100dvh;
    border-radius: 0;
  }
  .editor-body {
    grid-template-columns: 1fr;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }
  .editor-main {
    flex: none;
    height: auto;
    background: var(--color-bg-primary);
  }
  .editor-player-wrap {
    aspect-ratio: 16 / 9;
    width: 100%;
    height: auto;
    flex: none;
    position: sticky;
    top: 0;
    z-index: 10;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  }
  .editor-video {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .editor-actions-row {
    padding: 12px 16px;
    background: var(--color-bg-secondary);
    border-bottom: 1px solid var(--color-border);
  }
  .editor-timeline-wrap {
    padding: 16px;
    padding-bottom: calc(30px + env(safe-area-inset-bottom));
    background: var(--color-bg-secondary);
  }
  .editor-sidebar {
    display: none;
  }
}
</style>
