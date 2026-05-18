<template>
  <div class="stat-card gpu-monitor-card">
    <div class="gpu-header">
      <div class="gpu-title-stack" v-if="primaryGpu">
        <span class="gpu-title-main">{{ gpuHeaderTitle }}</span>
        <span class="gpu-title-sub">负载 {{ formatPercent(primaryGpu.util_percent) }}</span>
      </div>
      <div class="gpu-title-stack" v-else>
        <span class="gpu-title-main">GPU</span>
        <span class="gpu-title-sub">负载 N/A</span>
      </div>
      <div class="gpu-header-right">
        <button class="gpu-debug-btn" @click.stop="openDebugModal">调试</button>
        <span class="gpu-badge" :class="monitorStatusClass">{{ monitorStatusText }}</span>
        <span class="gpu-badge" :class="transcodeStatusClass">{{ transcodeStatusText }}</span>
      </div>
    </div>

    <div v-if="isLoading" class="gpu-empty">加载中...</div>
    <div v-else-if="!hasGpu" class="gpu-empty">未检测到可用 GPU</div>
    <div v-else-if="primaryGpu">
      <!-- 移动端精简视图：顶部核心信息 -->
      <div class="gpu-mobile-view mobile-only">
        <div class="gpu-mobile-header">
          <div class="gpu-title-stack">
            <span class="gpu-title-main">{{ gpuHeaderTitle }}</span>
          </div>
        </div>
      </div>

      <!-- 桌面端摘要行 -->
      <div class="gpu-summary-row desktop-only">
        <span v-if="extraGpuCount > 0" class="gpu-extra-count">+{{ extraGpuCount }} 张</span>
        <span class="metric-chip metric-temp" v-if="primaryGpu.temperature_c !== undefined && primaryGpu.temperature_c !== null">
          温度 {{ Number(primaryGpu.temperature_c).toFixed(0) }}°C
        </span>
        <span class="metric-chip metric-mem" v-if="primaryGpu.memory_used_mb !== undefined && primaryGpu.memory_total_mb !== undefined && primaryGpu.memory_total_mb > 0">
          显存 {{ formatMem(primaryGpu.memory_used_mb) }}/{{ formatMem(primaryGpu.memory_total_mb) }}
        </span>
        <span v-if="nvidiaRuntimeHint" class="metric-chip metric-hint">{{ nvidiaRuntimeHint }}</span>
      </div>

      <!-- 公用图表区域：移动端现在也显示 -->
      <div class="gpu-chart">
        <div class="chart-label-max">{{ gpuChartMaxLabel }}%</div>
        <svg viewBox="0 0 200 60" preserveAspectRatio="none" class="gpu-chart-svg">
          <defs>
            <pattern id="gpu-grid" :x="gridScrollX" width="16.949" height="60" patternUnits="userSpaceOnUse">
              <line x1="16.949" y1="0" x2="16.949" y2="60" stroke="rgba(0,0,0,0.2)" stroke-width="1" />
            </pattern>
            <pattern id="gpu-grid-static" width="200" height="15" patternUnits="userSpaceOnUse">
              <line x1="0" y1="15" x2="200" y2="15" stroke="rgba(0,0,0,0.2)" stroke-width="1" />
            </pattern>
          </defs>
          <rect width="200" height="60" fill="url(#gpu-grid)" class="chart-grid-rect" />
          <rect width="200" height="60" fill="url(#gpu-grid-static)" class="chart-grid-rect" />
          <path
            :d="gpuChartPoints"
            fill="none"
            stroke="#8e44ad"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <div class="chart-label-min">0%</div>
      </div>

      <!-- 移动端底部：单行展示核心硬件与转码信息 -->
      <div class="gpu-mobile-metrics mobile-only">
        <span class="metric-chip metric-hw">{{ mobileHwLabel }}</span>
        <span class="metric-chip metric-load">{{ formatPercent(primaryGpu.util_percent) }}</span>
        <span class="metric-chip metric-temp" v-if="primaryGpu.temperature_c !== undefined && primaryGpu.temperature_c !== null">
          {{ Number(primaryGpu.temperature_c).toFixed(0) }}°C
        </span>
        <span class="metric-chip metric-backend" v-if="formatBackends(primaryGpu.transcode_backends)">
          {{ formatBackends(primaryGpu.transcode_backends) }}
        </span>
      </div>
    </div>
    <div v-else class="gpu-empty">
      GPU 数据暂不可用
    </div>
  </div>

  <div v-if="showDebugModal" class="gpu-debug-modal-overlay" @click="closeDebugModal">
    <div class="gpu-debug-modal" @click.stop>
      <div class="gpu-debug-modal-header">
        <div class="gpu-debug-modal-title">GPU 调试信息</div>
        <button class="gpu-debug-close-btn" @click="closeDebugModal">关闭</button>
      </div>

      <div class="gpu-debug-toolbar">
        <button class="gpu-debug-action" @click="refreshDebugReport" :disabled="debugLoading">
          {{ debugLoading ? '刷新中...' : '刷新' }}
        </button>
        <button class="gpu-debug-action" @click="copyDebugReport" :disabled="!debugReportText">
          复制
        </button>
        <button class="gpu-debug-action" @click="downloadDebugReport" :disabled="!debugReportText">
          下载
        </button>
      </div>

      <div v-if="debugError" class="gpu-debug-error">{{ debugError }}</div>
      <pre class="gpu-debug-content">{{ debugReportText || '暂无数据' }}</pre>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { systemApi } from '@/api/system'

const props = defineProps({
  gpuStats: {
    type: Object,
    default: () => ({ summary: { has_gpu: false, transcode_enabled: false }, gpus: [] })
  },
  isLoading: {
    type: Boolean,
    default: false
  },
  gpuHistory: {
    type: Array,
    default: () => []
  },
  gpuChartPoints: {
    type: String,
    default: ''
  },
  gpuMaxPercent: {
    type: Number,
    default: 100
  },
  gridScrollX: {
    type: Number,
    default: 0
  }
})

const hasGpu = computed(() => Boolean(props.gpuStats?.summary?.has_gpu))
const gpus = computed(() => Array.isArray(props.gpuStats?.gpus) ? props.gpuStats.gpus : [])
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

const activeSelector = computed(() => {
  const summary = props.gpuStats?.summary || {}
  const activeTranscoder = summary.active_transcoder || {}
  const activeVendor = normalizeVendor(summary.active_vendor || activeTranscoder.vendor)
  const activeHwaccel = String(summary.active_hwaccel || activeTranscoder.hardware || '').trim().toLowerCase()
  const activeGpuIndex = parseGpuIndex(summary.active_gpu_index ?? activeTranscoder.gpu_index)
  return { activeVendor, activeHwaccel, activeGpuIndex }
})

const primaryGpu = computed(() => {
  const gpuList = gpus.value || []
  if (!gpuList.length) return null
  const pickPreferred = (list) => {
    if (!Array.isArray(list) || list.length === 0) return null
    const ok = list.find((gpu) => String(gpu?.status || '').toLowerCase() === 'ok')
    if (ok) return ok
    const degradedUsable = list.find((gpu) => {
      const status = String(gpu?.status || '').toLowerCase()
      return status === 'degraded' && Boolean(gpu?.transcode_enabled)
    })
    if (degradedUsable) return degradedUsable
    const nonError = list.find((gpu) => String(gpu?.status || '').toLowerCase() !== 'error')
    return nonError || list[0] || null
  }

  const explicitActive = gpuList.find((gpu) => Boolean(gpu?.is_active))
  if (explicitActive) return explicitActive

  const { activeVendor, activeHwaccel, activeGpuIndex } = activeSelector.value
  if (activeVendor) {
    const sameVendor = gpuList.filter((gpu) => normalizeVendor(gpu?.vendor) === activeVendor)
    if (sameVendor.length > 0) {
      if (activeVendor === 'nvidia' && activeGpuIndex !== null) {
        const exact = sameVendor.find((gpu) => parseGpuIndex(gpu?.index) === activeGpuIndex)
        if (exact) return exact
      }
      return pickPreferred(sameVendor)
    }
  }

  if (activeHwaccel === 'vaapi') {
    const vaapiCapable = gpuList.filter((gpu) => {
      const backends = Array.isArray(gpu?.transcode_backends) ? gpu.transcode_backends : []
      return backends.map((item) => String(item || '').toLowerCase()).includes('vaapi')
    })
    if (vaapiCapable.length > 0) return pickPreferred(vaapiCapable)
  }

  return pickPreferred(gpuList)
})
const primaryGpuName = computed(() => primaryGpu.value?.name || primaryGpu.value?.vendor?.toUpperCase() || 'GPU')
const mobileHwLabel = computed(() => {
  const rawVendor = String(primaryGpu.value?.vendor || '').trim().toLowerCase()
  if (!rawVendor) return 'CPU'
  if (rawVendor.includes('intel')) return 'Intel'
  if (rawVendor.includes('nvidia')) return 'NVIDIA'
  if (rawVendor.includes('amd')) return 'AMD'
  return rawVendor.toUpperCase()
})
const gpuHeaderTitle = computed(() => {
  const rawVendor = String(primaryGpu.value?.vendor || '').trim().toLowerCase()
  if (!rawVendor) return 'GPU'
  if (rawVendor.includes('intel')) return 'Intel GPU'
  if (rawVendor.includes('nvidia')) return 'NVIDIA GPU'
  if (rawVendor.includes('amd')) return 'AMD GPU'
  return `${rawVendor.toUpperCase()} GPU`
})
const extraGpuCount = computed(() => Math.max(0, gpus.value.length - 1))
const hasIssue = computed(() => gpus.value.some((gpu) => gpu?.status === 'degraded' || gpu?.status === 'error'))
const gpuChartMaxLabel = computed(() => {
  const max = Number(props.gpuMaxPercent || 100)
  if (!Number.isFinite(max) || max <= 0) return 100
  return Math.round(max)
})
const transcodeEnabled = computed(() => {
  const summaryEnabled = props.gpuStats?.summary?.transcode_enabled
  if (typeof summaryEnabled === 'boolean') return summaryEnabled
  return gpus.value.some((gpu) => {
    if (typeof gpu?.transcode_enabled === 'boolean') return gpu.transcode_enabled
    return Array.isArray(gpu?.transcode_backends) && gpu.transcode_backends.length > 0
  })
})
const showDebugModal = ref(false)
const debugLoading = ref(false)
const debugError = ref('')
const debugReport = ref(null)

const monitorStatusText = computed(() => {
  if (props.isLoading) return '监控...'
  if (!hasGpu.value) return '监控×'
  if (hasIssue.value) return '监控!'
  return '监控√'
})

const monitorStatusClass = computed(() => {
  if (props.isLoading) return 'loading'
  if (!hasGpu.value) return 'empty'
  if (hasIssue.value) return 'warning'
  return 'ok'
})

const transcodeStatusText = computed(() => {
  if (props.isLoading) return '转码...'
  if (!hasGpu.value) return '转码×'
  if (!transcodeEnabled.value) return '转码×'
  return '转码√'
})

const transcodeStatusClass = computed(() => {
  if (props.isLoading) return 'loading'
  if (!hasGpu.value) return 'empty'
  if (!transcodeEnabled.value) return 'disabled'
  return 'ok'
})

const isUnmappedNvidiaGpu = (gpu) => {
  const vendor = String(gpu?.vendor || '').toLowerCase()
  if (!vendor.includes('nvidia')) return false
  const errorText = String(gpu?.error || '').toLowerCase()
  return errorText.includes('nvidia-smi') || errorText.includes('--gpus all')
}

const nvidiaRuntimeHint = computed(() => {
  if (!isUnmappedNvidiaGpu(primaryGpu.value)) return ''
  return 'NVIDIA 未映射（--gpus all）'
})

const formatPercent = (value) => {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return 'N/A'
  return `${Number(value).toFixed(1)}%`
}

const formatMem = (mb) => {
  if (mb === undefined || mb === null || Number.isNaN(Number(mb))) return 'N/A'
  if (Number(mb) >= 1024) return `${(Number(mb) / 1024).toFixed(1)}GB`
  return `${Number(mb).toFixed(0)}MB`
}

const formatBackends = (backends) => {
  if (!Array.isArray(backends) || backends.length === 0) return ''
  const normalized = backends
    .map((b) => String(b || '').trim().toUpperCase())
    .filter((b) => b.length > 0)
  if (!normalized.length) return ''
  return normalized.join('/')
}

const debugReportText = computed(() => {
  if (!debugReport.value) return ''
  try {
    return JSON.stringify(debugReport.value, null, 2)
  } catch {
    return ''
  }
})

const refreshDebugReport = async () => {
  debugLoading.value = true
  debugError.value = ''
  try {
    const data = await systemApi.getGpuDebugReport()
    debugReport.value = data
  } catch (error) {
    debugError.value = error?.message || '获取调试信息失败'
  } finally {
    debugLoading.value = false
  }
}

const openDebugModal = async () => {
  showDebugModal.value = true
  if (!debugReport.value) {
    await refreshDebugReport()
  }
}

const closeDebugModal = () => {
  showDebugModal.value = false
}

const copyDebugReport = async () => {
  if (!debugReportText.value) return
  try {
    await navigator.clipboard.writeText(debugReportText.value)
  } catch {
    debugError.value = '复制失败，请手动选择文本复制'
  }
}

const downloadDebugReport = () => {
  if (!debugReportText.value) return
  const blob = new Blob([debugReportText.value], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `easy-vdl-gpu-debug-${Date.now()}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.stat-card.gpu-monitor-card {
  border: 2px solid var(--color-border);
  border-radius: 12px;
  min-height: 110px;
  height: 110px;
  width: 100%;
  max-width: none;
  box-sizing: border-box;
  padding: 12px 14px;
  background: var(--color-bg-card);
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: hidden;
  position: relative;
}

.gpu-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  position: relative;
  z-index: 3;
  pointer-events: auto;
}

.gpu-header-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  position: relative;
  z-index: 4;
  pointer-events: auto;
}

.gpu-debug-btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  cursor: pointer;
  position: relative;
  z-index: 5;
  pointer-events: auto;
  white-space: nowrap;
}

.gpu-debug-btn.mobile {
  padding: 1px 6px;
}

.gpu-title-stack {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.1;
}

.gpu-title-main {
  font-size: 12px;
  color: var(--color-text-primary);
  font-weight: 700;
  white-space: nowrap;
}

.gpu-title-sub {
  margin-top: 1px;
  font-size: 11px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.gpu-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  white-space: nowrap;
}

.gpu-badge.ok {
  color: #1e9a5a;
  border-color: rgba(30, 154, 90, 0.3);
}

.gpu-badge.warning {
  color: #e67e22;
  border-color: rgba(230, 126, 34, 0.3);
}

.gpu-badge.loading {
  color: #e67e22;
}

.gpu-badge.empty {
  color: var(--color-text-tertiary);
}

.gpu-badge.disabled {
  color: var(--color-text-tertiary);
}

.gpu-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-tertiary);
  font-size: 12px;
}

.gpu-inline-mobile {
  display: none;
}

.gpu-chart-desktop {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
}

.gpu-summary-row {
  display: flex;
  gap: 6px;
  align-items: center;
  min-height: 0;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}

.gpu-summary-row::-webkit-scrollbar {
  display: none;
}

.gpu-extra-count {
  font-size: 10px;
  color: var(--color-text-tertiary);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 1px 6px;
  flex-shrink: 0;
}

.gpu-chart {
  position: relative;
  height: 52px;
}

.gpu-chart-svg {
  width: 100%;
  height: 100%;
}

.chart-grid-rect {
  opacity: 0.72;
}

.chart-label-max,
.chart-label-min {
  position: absolute;
  right: 0;
  font-size: 10px;
  color: var(--color-text-tertiary);
  line-height: 1;
}

.chart-label-max {
  top: -2px;
}

.chart-label-min {
  bottom: -2px;
}

.metric-chip {
  font-size: 11px;
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  padding: 2px 6px;
  white-space: nowrap;
  flex-shrink: 0;
}

.metric-hw {
  font-weight: 600;
}

.metric-hint {
  color: #e67e22;
  border: 1px solid rgba(230, 126, 34, 0.25);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gpu-debug-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.gpu-debug-modal {
  width: min(900px, 96vw);
  max-height: 85vh;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.gpu-debug-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border);
}

.gpu-debug-modal-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.gpu-debug-close-btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
}

.gpu-debug-toolbar {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border);
}

.gpu-debug-action {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
}

.gpu-debug-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.gpu-debug-error {
  padding: 8px 14px;
  color: #e74c3c;
  font-size: 12px;
  border-bottom: 1px solid var(--color-border);
}

.gpu-debug-content {
  margin: 0;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--color-text-primary);
  background: var(--color-bg-card);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.mobile-only {
  display: none !important;
}

@media (max-width: 768px) {
  .mobile-only {
    display: block !important;
  }
  
  .desktop-only {
    display: none !important;
  }

  .stat-card.gpu-monitor-card {
    min-height: 90px;
    height: auto;
    width: 100% !important;
    max-width: none !important;
    padding: 8px 10px;
    gap: 2px;
    justify-content: flex-start;
  }

  .gpu-header {
    display: none;
  }

  .gpu-mobile-view {
    width: 100%;
  }

  .gpu-mobile-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    margin-bottom: 0px;
  }

  .gpu-mobile-header .gpu-title-stack {
    flex: 1;
    min-width: 0;
  }

  .gpu-mobile-header .gpu-title-main {
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 600;
  }

  .gpu-mobile-header .gpu-header-right {
    gap: 4px;
  }

  .gpu-chart {
    height: 36px;
    margin: 2px 0;
    width: 100%;
  }

  .chart-label-max,
  .chart-label-min {
    font-size: 8px;
  }

  .gpu-mobile-metrics {
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
    padding-top: 0px;
  }

  .gpu-mobile-metrics::-webkit-scrollbar {
    display: none;
  }

  .metric-chip {
    font-size: 9px;
    padding: 1px 4px;
    flex-shrink: 0;
  }

  .metric-load {
    font-weight: 600;
    color: var(--color-primary);
    background: var(--color-primary-light);
    opacity: 0.9;
  }
}

@media (max-width: 430px) {
  .gpu-mobile-header .gpu-title-main {
    max-width: 80px;
  }
  
  .metric-backend {
    display: none;
  }
}
</style>
