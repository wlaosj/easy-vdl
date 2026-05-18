<template>
  <div class="gpu-runtime-inline" :class="[rootStateClass, { 'has-info': !!info }]">
    <div class="gpu-runtime-bottom">
      <span class="gpu-load">GPU {{ utilText }}</span>
      <svg v-if="showCurve" class="gpu-sparkline" viewBox="0 0 96 30" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <pattern :id="gridPatternId" :x="gridScrollX" :width="gridPatternWidth" height="30" patternUnits="userSpaceOnUse">
            <line :x1="gridPatternWidth" y1="0" :x2="gridPatternWidth" y2="30" class="gpu-sparkline-vgrid" />
          </pattern>
        </defs>
        <rect width="96" height="30" :fill="`url(#${gridPatternId})`" class="gpu-sparkline-grid-bg" />
        <path class="gpu-sparkline-grid" d="M0 15H96" />
        <path class="gpu-sparkline-area" :d="sparkAreaPath" />
        <path class="gpu-sparkline-line" :d="sparkLinePath" />
      </svg>
      <span v-else class="gpu-disabled-hint">GPU转码未启用</span>
    </div>
    <div v-if="info" class="gpu-info-text" ref="infoContainerRef">
      <div
        class="gpu-info-inner"
        ref="infoInnerRef"
        :class="{ 'is-scrolling': isOverflowing }"
        :style="marqueeStyle"
      >
        <span class="info-content">{{ info }}</span>
        <span v-if="isOverflowing" class="info-content">&nbsp;&nbsp;&nbsp;&nbsp;{{ info }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  gpuStats: {
    type: Object,
    default: () => ({ summary: { has_gpu: false, transcode_enabled: false }, gpus: [] })
  },
  isLoading: {
    type: Boolean,
    default: false
  },
  errorText: {
    type: String,
    default: ''
  },
  info: {
    type: String,
    default: ''
  }
})

const CHART_WIDTH = 96
const CHART_HEIGHT = 30
const HISTORY_LIMIT = 28
const UPDATE_INTERVAL = 1000
const chartGap = CHART_WIDTH / (HISTORY_LIMIT - 1)
const gridStepPoints = 5
const gridPatternWidth = chartGap * gridStepPoints

const history = ref(new Array(HISTORY_LIMIT).fill(0))
const targetValue = ref(0)
const sparkLinePath = ref('')
const sparkAreaPath = ref('')
const gridScrollX = ref(0)
const gridPatternId = `gpu-spark-grid-${Math.random().toString(36).slice(2, 10)}`

const lastUpdateTs = ref(Date.now())
const gridTickCount = ref(0)
let animationFrameId = null
let initialized = false

const gpuList = computed(() => (
  Array.isArray(props.gpuStats?.gpus) ? props.gpuStats.gpus : []
))

const normalizeVendor = (value) => {
  const text = String(value || '').trim().toLowerCase()
  if (!text) return ''
  if (text.includes('intel')) return 'intel'
  if (text.includes('nvidia')) return 'nvidia'
  if (text.includes('amd')) return 'amd'
  return text
}

const parseGpuIndex = (value) => {
  if (value === undefined || value === null || value === '') return null
  const parsed = Number.parseInt(String(value).trim(), 10)
  return Number.isFinite(parsed) ? parsed : null
}

const primaryGpu = computed(() => {
  const list = gpuList.value || []
  if (!list.length) return null
  const pickPreferred = (items) => {
    if (!Array.isArray(items) || items.length === 0) return null
    const ok = items.find((gpu) => String(gpu?.status || '').toLowerCase() === 'ok')
    if (ok) return ok
    const degradedUsable = items.find((gpu) => {
      const status = String(gpu?.status || '').toLowerCase()
      return status === 'degraded' && Boolean(gpu?.transcode_enabled)
    })
    if (degradedUsable) return degradedUsable
    const nonError = items.find((gpu) => String(gpu?.status || '').toLowerCase() !== 'error')
    return nonError || items[0] || null
  }

  const explicitActive = list.find((gpu) => Boolean(gpu?.is_active))
  if (explicitActive) return explicitActive

  const summary = props.gpuStats?.summary || {}
  const activeTranscoder = summary.active_transcoder || {}
  const activeVendor = normalizeVendor(summary.active_vendor || activeTranscoder.vendor)
  const activeHwaccel = String(summary.active_hwaccel || activeTranscoder.hardware || '').trim().toLowerCase()
  const activeGpuIndex = parseGpuIndex(summary.active_gpu_index ?? activeTranscoder.gpu_index)

  if (activeVendor) {
    const sameVendor = list.filter((gpu) => normalizeVendor(gpu?.vendor) === activeVendor)
    if (sameVendor.length > 0) {
      if (activeVendor === 'nvidia' && activeGpuIndex !== null) {
        const exact = sameVendor.find((gpu) => parseGpuIndex(gpu?.index) === activeGpuIndex)
        if (exact) return exact
      }
      return pickPreferred(sameVendor)
    }
  }

  if (activeHwaccel === 'vaapi') {
    const vaapiCapable = list.filter((gpu) => {
      const backends = Array.isArray(gpu?.transcode_backends) ? gpu.transcode_backends : []
      return backends.map((item) => String(item || '').toLowerCase()).includes('vaapi')
    })
    if (vaapiCapable.length > 0) return pickPreferred(vaapiCapable)
  }

  return pickPreferred(list)
})

const hasGpu = computed(() => {
  const summary = props.gpuStats?.summary?.has_gpu
  if (typeof summary === 'boolean') return summary
  return gpuList.value.length > 0
})

const transcodeEnabled = computed(() => {
  const summaryEnabled = props.gpuStats?.summary?.transcode_enabled
  if (typeof summaryEnabled === 'boolean') return summaryEnabled
  return gpuList.value.some((gpu) => {
    if (typeof gpu?.transcode_enabled === 'boolean') return gpu.transcode_enabled
    return Array.isArray(gpu?.transcode_backends) && gpu.transcode_backends.length > 0
  })
})

const hasIssue = computed(() => gpuList.value.some((gpu) => {
  const status = String(gpu?.status || '').toLowerCase()
  return status === 'error' || status === 'degraded'
}))

const showCurve = computed(() => hasGpu.value && transcodeEnabled.value)

const utilPercent = computed(() => {
  if (!showCurve.value) return null
  const raw = primaryGpu.value?.util_percent
  if (raw === undefined || raw === null || Number.isNaN(Number(raw))) return null
  return Math.max(0, Math.min(100, Number(raw)))
})

const utilText = computed(() => {
  if (utilPercent.value === null) return 'N/A'
  return `${utilPercent.value.toFixed(1)}%`
})

const rootStateClass = computed(() => {
  if (!showCurve.value) return 'is-disabled'
  if (hasIssue.value || props.errorText) return 'is-warning'
  return 'is-ok'
})

const initSeries = (value) => {
  const safe = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
  history.value = new Array(HISTORY_LIMIT).fill(safe)
  targetValue.value = safe
  initialized = true
  lastUpdateTs.value = Date.now()
}

watch(utilPercent, (value) => {
  if (value === null) return
  const safe = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
  if (!initialized) {
    initSeries(safe)
    return
  }
  targetValue.value = safe
}, { immediate: true })

const buildSmoothPath = (points) => {
  if (!points.length) return ''
  if (points.length === 1) return `M${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`

  let path = `M${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1]
    const curr = points[i]
    const cx = (prev.x + curr.x) / 2
    path += ` Q ${cx.toFixed(2)} ${prev.y.toFixed(2)} ${curr.x.toFixed(2)} ${curr.y.toFixed(2)}`
  }
  return path
}

const renderSparkline = () => {
  if (!initialized) return

  const now = Date.now()
  let elapsed = now - lastUpdateTs.value

  if (elapsed >= UPDATE_INTERVAL) {
    const steps = Math.floor(elapsed / UPDATE_INTERVAL)
    for (let i = 0; i < steps; i += 1) {
      history.value.push(targetValue.value)
      if (history.value.length > HISTORY_LIMIT) history.value.shift()
    }
    gridTickCount.value += steps
    lastUpdateTs.value += steps * UPDATE_INTERVAL
    elapsed = now - lastUpdateTs.value
  }

  let progress = elapsed / UPDATE_INTERVAL
  if (progress > 1.2) progress = 1.2
  if (progress < 0) progress = 0

  const points = []
  const series = history.value

  if (series.length) {
    const lastPoint = series[series.length - 1]
    const currentVal = lastPoint + (targetValue.value - lastPoint) * Math.min(progress, 1)

    series.forEach((val, index) => {
      const x = CHART_WIDTH - ((series.length - index) * chartGap) - (progress * chartGap) + chartGap
      const y = CHART_HEIGHT - (val / 100) * (CHART_HEIGHT - 4) - 2
      points.push({ x, y })
    })

    points.push({
      x: CHART_WIDTH,
      y: CHART_HEIGHT - (currentVal / 100) * (CHART_HEIGHT - 4) - 2
    })

    sparkLinePath.value = buildSmoothPath(points)
    sparkAreaPath.value = `${sparkLinePath.value} L${CHART_WIDTH} ${CHART_HEIGHT} L0 ${CHART_HEIGHT} Z`
  } else {
    sparkLinePath.value = ''
    sparkAreaPath.value = ''
  }

  const totalShift = (gridTickCount.value + progress) * chartGap
  gridScrollX.value = -(totalShift % gridPatternWidth)
}

const animate = () => {
  renderSparkline()
  animationFrameId = requestAnimationFrame(animate)
}

const infoContainerRef = ref(null)
const infoInnerRef = ref(null)
const isOverflowing = ref(false)
const scrollDist = ref(0)

const updateOverflow = () => {
  if (infoContainerRef.value && infoInnerRef.value) {
    const containerWidth = infoContainerRef.value.clientWidth
    const contentEl = infoInnerRef.value.querySelector('.info-content')
    if (contentEl) {
      const contentWidth = contentEl.offsetWidth
      const newIsOverflowing = contentWidth > containerWidth
      
      // 只有在状态改变或宽度变化超过一定阈值时才更新，防止频繁重置动画
      if (newIsOverflowing !== isOverflowing.value) {
        isOverflowing.value = newIsOverflowing
      }
      
      const newScrollDist = contentWidth + 24
      if (Math.abs(newScrollDist - scrollDist.value) > 10 || (newIsOverflowing && scrollDist.value === 0)) {
        scrollDist.value = newScrollDist
      }
    }
  }
}

const marqueeStyle = computed(() => {
  if (!isOverflowing.value) return {}
  return {
    '--scroll-dist': `-${scrollDist.value}px`,
    '--scroll-duration': `${scrollDist.value / 40}s` 
  }
})

watch(() => props.info, () => {
  nextTick(updateOverflow)
})

onMounted(() => {
  renderSparkline()
  animationFrameId = requestAnimationFrame(animate)
  updateOverflow()
  window.addEventListener('resize', updateOverflow)
})

onBeforeUnmount(() => {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
    animationFrameId = null
  }
  window.removeEventListener('resize', updateOverflow)
})
</script>

<style scoped>
.gpu-runtime-inline {
  min-width: 0;
  border: 1px solid var(--color-border, var(--border-color, #dcdfe6));
  border-radius: 10px;
  padding: 4px 8px;
  background: var(--color-bg-card, var(--bg-card, #fff));
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
}

.gpu-info-text {
  font-size: 11px;
  color: var(--color-text-secondary, var(--text-secondary, #606266));
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  margin-top: 4px;
  padding-top: 4px;
  overflow: hidden;
  position: relative;
  opacity: 0.85;
}

.gpu-info-inner {
  white-space: nowrap;
  display: inline-block;
  font-family: var(--font-family-mono, monospace);
  width: auto;
}

.gpu-info-inner.is-scrolling {
  animation: marquee var(--scroll-duration, 8s) linear infinite;
}

@keyframes marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(var(--scroll-dist, -100%)); }
}

.info-content {
  display: inline-block;
  white-space: nowrap;
}

.gpu-runtime-bottom {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  width: 100%;
}

.gpu-load {
  font-size: 11px;
  color: var(--color-text-secondary, var(--text-secondary, #606266));
  white-space: nowrap;
  flex-shrink: 0;
}

.gpu-sparkline {
  width: 100%;
  min-width: 96px;
  height: 24px;
  flex: 1 1 auto;
}

.gpu-disabled-hint {
  font-size: 11px;
  color: var(--color-text-tertiary, #909399);
  white-space: nowrap;
}

.gpu-sparkline-grid-bg {
  opacity: 0.9;
}

.gpu-sparkline-vgrid {
  stroke: rgba(0, 0, 0, 0.12);
  stroke-width: 1;
}

.gpu-sparkline-grid {
  stroke: rgba(0, 0, 0, 0.15);
  stroke-width: 1;
  fill: none;
}

.gpu-sparkline-area {
  fill: rgba(30, 154, 90, 0.12);
}

.gpu-sparkline-line {
  stroke: #1e9a5a;
  stroke-width: 1.4;
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.gpu-runtime-inline.is-warning .gpu-sparkline-line {
  stroke: #e67e22;
}

.gpu-runtime-inline.is-warning .gpu-sparkline-area {
  fill: rgba(230, 126, 34, 0.12);
}

.gpu-runtime-inline.is-disabled .gpu-load {
  color: var(--color-text-tertiary, #909399);
}

@media (max-width: 768px) {
  .gpu-runtime-inline {
    padding: 3px 7px;
  }

  .gpu-load {
    font-size: 10px;
  }

  .gpu-sparkline {
    min-width: 72px;
    height: 20px;
  }

  .gpu-disabled-hint {
    font-size: 10px;
  }
}
</style>
