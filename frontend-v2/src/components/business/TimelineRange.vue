<template>
  <div class="timeline-range" ref="trackRef">
    <div class="timeline-label-row">
      <span class="timeline-label">{{ label }}</span>
      <div class="zoom-controls">
        <button class="zoom-btn" @click="zoomOut" title="缩小视野" :disabled="!canZoomOut">–</button>
        <span class="zoom-indicator">{{ zoomLabel }}</span>
        <button class="zoom-btn" @click="zoomIn" title="放大视野" :disabled="!canZoomIn">+</button>
      </div>
    </div>
    <div class="track-wrap" 
      @mousedown.prevent="onTrackMouseDown" 
      @touchstart.passive="onTrackMouseDown"
      @wheel.prevent="onWheel" 
      @mousemove="onTrackHover" 
      @mouseleave="onTrackHoverLeave"
    >
      <div class="track-bg">
        <div class="track-fill" :style="{ left: leftPct + '%', width: widthPct + '%' }"></div>
        <div class="track-tick" v-for="tick in ticks" :key="tick" :style="{ left: tick.pct + '%' }">
          <span class="tick-label">{{ tick.label }}</span>
        </div>
      </div>
      <div
        class="handle handle-left" :class="{ dragging: dragging === 'left', 'hover-side': hoverSide === 'left' }"
        :style="{ left: leftPct + '%' }"
        @mousedown.stop.prevent="startDrag($event, 'left')"
        @touchstart.stop.passive="startDrag($event, 'left')"
      >
        <div class="handle-knob"></div>
        <div class="handle-time left" :class="{ 'edge-left': leftPct < 8 }">{{ formatTime(startSec) }}</div>
      </div>
      <div
        v-if="currentSecVisible"
        class="playhead"
        :style="{ left: currentPct + '%' }"
      ></div>
      <div
        class="handle handle-right" :class="{ dragging: dragging === 'right', 'hover-side': hoverSide === 'right' }"
        :style="{ left: rightPct + '%' }"
        @mousedown.stop.prevent="startDrag($event, 'right')"
        @touchstart.stop.passive="startDrag($event, 'right')"
      >
        <div class="handle-knob"></div>
        <div class="handle-time right" :class="{ 'edge-right': rightPct > 92 }">{{ formatTime(endSec) }}</div>
      </div>
    </div>
    <div class="timeline-info">
      <span class="info-duration">总时长 {{ formatTime(totalDuration) }}</span>
      <span class="info-selected">选中 {{ formatTime(endSec - startSec) }}</span>
    </div>
    <div class="nudge-bar left">
      <div class="nudge-group">
        <span class="nudge-label">起点</span>
        <button
          class="nudge-btn nudge-btn-frame"
          @mousedown.prevent="startHold('start', -frameStepSec)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('start', -frameStepSec)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          :title="`起点向前 1 帧（${frameStepLabel}）`"
        >
          <span>-1帧</span>
          <span class="nudge-sub">{{ frameStepLabel }}</span>
        </button>
        <button
          class="nudge-btn nudge-btn-frame"
          @mousedown.prevent="startHold('start', frameStepSec)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('start', frameStepSec)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          :title="`起点向后 1 帧（${frameStepLabel}）`"
        >
          <span>+1帧</span>
          <span class="nudge-sub">{{ frameStepLabel }}</span>
        </button>
        <button
          class="nudge-btn"
          @mousedown.prevent="startHold('start', -1)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('start', -1)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          title="起点向前 1 秒"
        >-1秒</button>
        <button
          class="nudge-btn"
          @mousedown.prevent="startHold('start', 1)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('start', 1)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          title="起点向后 1 秒"
        >+1秒</button>
      </div>
      <div class="nudge-divider"></div>
      <div class="nudge-group">
        <span class="nudge-label">终点</span>
        <button
          class="nudge-btn nudge-btn-frame"
          @mousedown.prevent="startHold('end', -frameStepSec)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('end', -frameStepSec)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          :title="`终点向前 1 帧（${frameStepLabel}）`"
        >
          <span>-1帧</span>
          <span class="nudge-sub">{{ frameStepLabel }}</span>
        </button>
        <button
          class="nudge-btn nudge-btn-frame"
          @mousedown.prevent="startHold('end', frameStepSec)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('end', frameStepSec)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          :title="`终点向后 1 帧（${frameStepLabel}）`"
        >
          <span>+1帧</span>
          <span class="nudge-sub">{{ frameStepLabel }}</span>
        </button>
        <button
          class="nudge-btn"
          @mousedown.prevent="startHold('end', -1)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('end', -1)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          title="终点向前 1 秒"
        >-1秒</button>
        <button
          class="nudge-btn"
          @mousedown.prevent="startHold('end', 1)"
          @mouseup="stopHold"
          @mouseleave="stopHold"
          @touchstart.prevent="startHold('end', 1)"
          @touchend="stopHold"
          @touchcancel="stopHold"
          title="终点向后 1 秒"
        >+1秒</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  startSec: { type: Number, required: true },
  endSec: { type: Number, required: true },
  totalDuration: { type: Number, required: true },
  frameRate: { type: Number, default: 30 },
  label: { type: String, default: '' },
  initialWindowSec: { type: Number, default: 0 },
  currentSec: { type: Number, default: -1 }
})

const emit = defineEmits(['update:startSec', 'update:endSec', 'seek'])

const trackRef = ref(null)
const dragging = ref(null)
const hoverSide = ref(null)
const minGapSec = 3
const frameStepSec = computed(() => {
  const fps = Number(props.frameRate || 0)
  const safeFps = fps > 0 ? fps : 30
  return 1 / safeFps
})
const frameStepLabel = computed(() => `${frameStepSec.value.toFixed(3)}秒`)
let holdDelayTimer = 0
let holdRepeatTimer = 0

const minWindowSec = computed(() => {
  if (props.totalDuration <= 12) return 3
  if (props.totalDuration <= 60) return 5
  return 10
})

const selectionDuration = computed(() => Math.max(minGapSec, props.endSec - props.startSec))
const minAllowedWindowSec = computed(() => Math.max(minWindowSec.value, selectionDuration.value))

function clampWindow(value) {
  const maxW = Math.max(minAllowedWindowSec.value, props.totalDuration || minAllowedWindowSec.value)
  return Math.max(minAllowedWindowSec.value, Math.min(value, maxW))
}

function getDefaultWindow() {
  if (props.initialWindowSec > 0) return clampWindow(props.initialWindowSec)
  if (props.totalDuration <= 0) return minWindowSec.value
  // 短视频默认直接全长显示，长视频给一个可操作的中等视野
  if (props.totalDuration <= 20) return props.totalDuration
  return clampWindow(Math.min(props.totalDuration, Math.max((props.endSec - props.startSec) * 2.5, 30)))
}

const windowSec = ref(getDefaultWindow())

const segCenter = computed(() => (props.startSec + props.endSec) / 2)
const windowStart = computed(() => {
  let ws = segCenter.value - windowSec.value / 2
  ws = Math.max(0, Math.min(ws, props.totalDuration - windowSec.value))
  return ws
})

const leftPct = computed(() => {
  if (windowSec.value <= 0) return 0
  const pct = ((props.startSec - windowStart.value) / windowSec.value) * 100
  return Math.max(0, Math.min(100, pct))
})
const rightPct = computed(() => {
  if (windowSec.value <= 0) return 100
  const pct = ((props.endSec - windowStart.value) / windowSec.value) * 100
  return Math.max(0, Math.min(100, pct))
})
const widthPct = computed(() => Math.max(0, rightPct.value - leftPct.value))

const currentPct = computed(() => {
  if (windowSec.value <= 0 || props.currentSec < 0) return -100
  return ((props.currentSec - windowStart.value) / windowSec.value) * 100
})
const currentSecVisible = computed(() => {
  return props.currentSec >= 0 &&
    currentPct.value >= (leftPct.value - 2) &&
    currentPct.value <= (rightPct.value + 2)
})

const ticks = computed(() => {
  const labels = []
  if (windowSec.value <= 0) return labels
  const start = windowStart.value
  const end = windowStart.value + windowSec.value
  const step = getTickStep(windowSec.value)
  const firstTick = Math.ceil(start / step) * step

  for (let sec = firstTick; sec <= end + 0.001; sec += step) {
    const pct = ((sec - start) / windowSec.value) * 100
    labels.push({ pct, label: formatTimeShort(sec) })
  }

  if (!labels.length || labels[0].pct > 1) labels.unshift({ pct: 0, label: formatTimeShort(start) })
  const last = labels[labels.length - 1]
  if (!last || last.pct < 99) labels.push({ pct: 100, label: formatTimeShort(end) })
  return labels
})

const zoomLabel = computed(() => {
  if (windowSec.value >= 3600) return `${(windowSec.value / 3600).toFixed(1)}h`
  if (windowSec.value >= 60) return `${Math.round(windowSec.value / 60)}m`
  return `${Math.round(windowSec.value)}s`
})

const canZoomIn = computed(() => windowSec.value > minAllowedWindowSec.value + 0.01)
const canZoomOut = computed(() => windowSec.value < props.totalDuration - 0.01)

function zoomIn() {
  if (!canZoomIn.value) return
  windowSec.value = clampWindow(windowSec.value / 2)
}

function zoomOut() {
  if (!canZoomOut.value) return
  windowSec.value = clampWindow(windowSec.value * 2)
}

function onWheel(e) {
  // 根据鼠标在轨道上的左右位置，决定微调起点还是终点
  const mouseSec = posToSec(e.clientX)
  const mid = (props.startSec + props.endSec) / 2
  if (mouseSec < mid) {
    if (e.deltaY < 0) nudgeStart(1)
    else nudgeStart(-1)
  } else {
    if (e.deltaY < 0) nudgeEnd(1)
    else nudgeEnd(-1)
  }
}

watch(() => props.totalDuration, () => {
  windowSec.value = getDefaultWindow()
})

watch(selectionDuration, () => {
  if (windowSec.value < minAllowedWindowSec.value) {
    windowSec.value = clampWindow(windowSec.value)
  }
})

function formatTime(sec) {
  const s = Math.max(0, Math.round(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const secs = s % 60
  if (h > 0) return h + ":" + String(m).padStart(2, "0") + ":" + String(secs).padStart(2, "0")
  return m + ":" + String(secs).padStart(2, "0")
}

function formatTimeShort(sec) {
  const s = Math.max(0, Math.round(sec))
  const m = Math.floor(s / 60)
  const secs = s % 60
  return m + ":" + String(secs).padStart(2, "0")
}

function getTickStep(windowSeconds) {
  if (windowSeconds <= 12) return 1
  if (windowSeconds <= 30) return 2
  if (windowSeconds <= 90) return 5
  if (windowSeconds <= 300) return 10
  if (windowSeconds <= 900) return 30
  if (windowSeconds <= 1800) return 60
  if (windowSeconds <= 3600) return 120
  return 300
}

function posToSec(clientX) {
  if (!trackRef.value) return 0
  const rect = trackRef.value.querySelector(".track-bg").getBoundingClientRect()
  let ratio = (clientX - rect.left) / rect.width
  ratio = Math.max(0, Math.min(1, ratio))
  return windowStart.value + ratio * windowSec.value
}

function onTrackMouseDown(e) {
  if (!trackRef.value || dragging.value) return
  const clientX = e.type.startsWith('touch') ? (e.touches[0]?.clientX || e.changedTouches[0]?.clientX) : e.clientX
  const clickSec = posToSec(clientX)
  emit("seek", clickSec)
}

function onTrackHover(e) {
  if (!trackRef.value || dragging.value) return
  const mouseSec = posToSec(e.clientX)
  hoverSide.value = mouseSec < (props.startSec + props.endSec) / 2 ? 'left' : 'right'
}

function onTrackHoverLeave() {
  hoverSide.value = null
}

function startDrag(e, side) {
  dragging.value = side
  document.addEventListener("mousemove", onDrag)
  document.addEventListener("mouseup", stopDrag)
  document.addEventListener("touchmove", onDrag, { passive: false })
  document.addEventListener("touchend", stopDrag)
}

function onDrag(e) {
  if (!dragging.value || !trackRef.value) return
  // 如果是触屏事件且正在拖拽，阻止默认行为（如页面滚动）
  if (e.type === 'touchmove') e.preventDefault()
  
  const clientX = e.type.startsWith('touch') ? (e.touches[0]?.clientX || e.changedTouches[0]?.clientX) : e.clientX
  const sec = posToSec(clientX)
  const winStart = windowStart.value
  const winEnd = winStart + windowSec.value
  if (dragging.value === "left") {
    emit("update:startSec", Math.max(winStart, Math.min(sec, props.endSec - minGapSec)))
  } else {
    emit("update:endSec", Math.min(winEnd, Math.max(sec, props.startSec + minGapSec)))
  }
}

function stopDrag() {
  if (!dragging.value) return
  dragging.value = null
  document.removeEventListener("mousemove", onDrag)
  document.removeEventListener("mouseup", stopDrag)
  document.removeEventListener("touchmove", onDrag)
  document.removeEventListener("touchend", stopDrag)
}

onUnmounted(() => {
  stopHold()
  document.removeEventListener("mousemove", onDrag)
  document.removeEventListener("mouseup", stopDrag)
  document.removeEventListener("touchmove", onDrag)
  document.removeEventListener("touchend", stopDrag)
})

function clampStart(sec) {
  return Math.max(0, Math.min(sec, props.endSec - minGapSec))
}

function clampEnd(sec) {
  return Math.min(props.totalDuration, Math.max(sec, props.startSec + minGapSec))
}

function nudgeStart(delta) {
  emit("update:startSec", clampStart(props.startSec + delta))
}

function nudgeEnd(delta) {
  emit("update:endSec", clampEnd(props.endSec + delta))
}

function applyNudge(target, delta) {
  if (target === 'start') nudgeStart(delta)
  else nudgeEnd(delta)
}

function startHold(target, delta) {
  stopHold()
  applyNudge(target, delta)
  holdDelayTimer = window.setTimeout(() => {
    holdRepeatTimer = window.setInterval(() => {
      applyNudge(target, delta)
    }, 70)
  }, 260)
}

function stopHold() {
  if (holdDelayTimer) {
    clearTimeout(holdDelayTimer)
    holdDelayTimer = 0
  }
  if (holdRepeatTimer) {
    clearInterval(holdRepeatTimer)
    holdRepeatTimer = 0
  }
}
</script>

<style scoped>
.timeline-range {
  padding: 12px 0 6px;
  user-select: none;
}

.timeline-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.timeline-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.zoom-controls {
  display: flex;
  align-items: center;
  gap: 4px;
}

.zoom-btn {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  line-height: 1;
  padding: 0;
  transition: all 0.12s ease;
}

.zoom-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
  border-color: var(--color-text-secondary);
}

.zoom-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.zoom-indicator {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-tertiary);
  min-width: 28px;
  text-align: center;
}

.track-wrap {
  position: relative;
  height: 48px;
  cursor: pointer;
  touch-action: none;
}

.track-bg {
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 8px;
  transform: translateY(-50%);
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  cursor: pointer;
  transition: height 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}

.track-wrap:hover .track-bg {
  height: 16px;
  box-shadow: 0 0 0 2px var(--color-primary);
  background: var(--color-bg-secondary);
}

.track-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary), var(--color-primary-dark, var(--color-primary)));
  border-radius: 4px;
  opacity: 0.5;
  pointer-events: none;
  min-width: 4px;
}

.track-tick {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255, 255, 255, 0.15);
  pointer-events: none;
}

.tick-label {
  position: absolute;
  top: calc(100% + 2px);
  left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  font-weight: 500;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  font-family: var(--font-mono, monospace);
}

.handle {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  cursor: ew-resize;
  z-index: 2;
  pointer-events: none;
}

.playhead {
  position: absolute;
  top: 50%;
  left: 0;
  width: 2px;
  height: 34px;
  background: #ef4444;
  transform: translate(-50%, -50%);
  z-index: 3;
  pointer-events: none;
  border-radius: 1px;
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);
  transition: left 0.15s linear;
}

.playhead::before {
  content: '';
  position: absolute;
  top: -4px;
  left: 50%;
  transform: translateX(-50%);
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.7);
}

.playhead::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #ef4444;
}

.handle-knob {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--color-primary);
  border: 3px solid var(--color-bg-card);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(0, 0, 0, 0.2);
  transition: transform 0.12s ease, box-shadow 0.12s ease;
  cursor: ew-resize;
  pointer-events: auto;
  position: relative;
  z-index: 2;
}

/* 增加触摸热区 */
.handle-knob::after {
  content: '';
  position: absolute;
  top: -12px;
  left: -12px;
  right: -12px;
  bottom: -12px;
}

.handle:hover .handle-knob,
.handle.dragging .handle-knob,
.handle.hover-side .handle-knob {
  transform: scale(1.35);
  box-shadow: 0 0 0 2px var(--color-primary), 0 0 18px var(--color-primary);
}

.handle.hover-side .handle-knob {
  animation: knob-pulse 1s ease-in-out infinite;
}

@keyframes knob-pulse {
  0%, 100% { box-shadow: 0 0 0 2px var(--color-primary), 0 0 18px var(--color-primary); }
  50% { box-shadow: 0 0 0 3px var(--color-primary), 0 0 28px var(--color-primary); }
}

.handle-time {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-primary);
  background: var(--color-bg-card);
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
  pointer-events: none;
  font-family: var(--font-mono, monospace);
  z-index: 1;
}

.handle-time.left {
  right: calc(100% + 6px);
}

.handle-time.right {
  left: calc(100% + 6px);
}

.handle-time.left.edge-left {
  right: auto;
  left: calc(100% + 6px);
}

.handle-time.right.edge-right {
  left: auto;
  right: calc(100% + 6px);
}

.timeline-info {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-top: 6px;
}

.info-selected {
  font-weight: 600;
  color: var(--color-primary);
}

.nudge-bar {
  display: flex;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
}

.nudge-divider {
  width: 1px;
  background: var(--color-border);
  margin: 0 4px;
}

.nudge-group {
  display: flex;
  align-items: center;
  gap: 3px;
}

.nudge-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-tertiary);
  margin-right: 4px;
  min-width: 24px;
}

.nudge-btn {
  min-width: 44px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  padding: 2px 6px;
  line-height: 1;
  font-family: var(--font-mono, monospace);
  transition: all 0.12s ease;
}

.nudge-btn-frame {
  min-width: 54px;
}

.nudge-sub {
  font-size: 9px;
  font-weight: 600;
  color: var(--color-text-tertiary);
  margin-top: 2px;
}

.nudge-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-primary);
  border-color: var(--color-primary);
}

.nudge-btn:active {
  transform: scale(0.92);
}
/* 适配移动端：按钮分行显示 */
@media (max-width: 768px) {
  .nudge-bar {
    flex-direction: column;
    gap: 12px;
    padding-bottom: 8px;
  }

  .nudge-divider {
    display: none;
  }

  .nudge-group {
    width: 100%;
    justify-content: center;
  }
}
</style>
