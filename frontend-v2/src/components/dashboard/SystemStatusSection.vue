<template>
  <div class="dashboard-right">
    <div class="system-status-section">
      <!-- 系统/内存卡片 -->
      <div class="status-card" :style="{ '--usage-percent': getMemoryUsagePercent(metrics.memory_mb, metrics.memory_limit_mb) + '%' }">
        <div class="status-header">
          <div class="status-icon memory battery-fill">
            <Icon name="chip-dip" :size="30" />
          </div>
          <div class="status-title">
            <h4>系统</h4>
            <span class="status-subtitle">运行时长: {{ formatUptime(metrics.uptime_seconds) }}</span>
          </div>
          <div class="status-badge memory-badge">
            <span class="badge-title">内存使用率</span>
            <span class="badge-value">{{ getMemoryUsagePercent(metrics.memory_mb, metrics.memory_limit_mb) }}%</span>
            <span class="badge-total" v-if="metrics.memory_limit_mb">共 {{ (metrics.memory_limit_mb / 1024).toFixed(1) }}GB</span>
          </div>
        </div>
        <div class="system-stats-row">
          <div class="system-stat-item">
            <span class="system-stat-label">内存使用</span>
            <span class="system-stat-value">{{ formatBytes(metrics.memory_mb * 1024 * 1024, 1) }}</span>
          </div>
          <div class="system-stat-item">
            <span class="system-stat-label">浏览器页面</span>
            <span class="system-stat-value">{{ metrics.browsers?.total_pages || 0 }}</span>
          </div>
          <div class="system-stat-item">
            <span class="system-stat-label">GC 清理</span>
            <span class="system-stat-value">{{ metrics.watchdog?.cleanup_count || 0 }}</span>
          </div>
        </div>
        <div class="system-info-group">
          <a href="https://hub.docker.com/r/qq918652593/easy-vdl" target="_blank" class="info-badge version-badge" title="查看 Docker 镜像">
            <Icon name="zap" :size="10" />
            <span>版本: {{ appVersion }}</span>
          </a>
          <div
            class="info-badge core-badge"
            :class="{ 'checking': isCheckingCore, 'has-update': coreHasUpdate }"
            @click="handleCoreUpdate"
            :title="getCoreTitle()"
          >
            <Icon :name="isCheckingCore ? 'refresh' : 'cpu'" :size="10" :class="[{ 'spin': isCheckingCore }, 'flex-shrink-0']" />
            <span class="core-text">核心: {{ getCoreDisplayText() }}</span>
            <span v-if="coreHasUpdate" class="update-dot"></span>
          </div>
        </div>
      </div>

      <!-- CPU 卡片 -->
      <div class="status-card" :style="{ '--usage-percent': (metrics.cpu_percent || 0).toFixed(1) + '%' }">
        <div class="status-header">
          <div class="status-icon cpu battery-fill">
            <Icon name="cpu-socket" :size="30" />
          </div>
          <div class="status-title">
            <h4>处理器</h4>
            <span class="status-subtitle">处理器使用率</span>
          </div>
          <div class="status-badge">{{ metrics.cpu_percent?.toFixed(1) }}%</div>
        </div>
        <!-- CPU 使用率折线图 -->
        <div class="cpu-chart">
          <div class="chart-label-max">{{ Math.round(cpuMaxPercent) }}%</div>
          <svg viewBox="0 0 200 60" preserveAspectRatio="none" class="cpu-chart-svg">
            <defs>
              <pattern id="cpu-grid" :x="gridScrollX" width="16.949" height="60" patternUnits="userSpaceOnUse">
                 <!-- 竖线 (跟随滚动) -->
                 <line x1="16.949" y1="0" x2="16.949" y2="60" stroke="rgba(0,0,0,0.2)" stroke-width="1" />
              </pattern>
              <pattern id="cpu-grid-static" width="200" height="15" patternUnits="userSpaceOnUse">
                 <!-- 横线 (固定) -->
                 <line x1="0" y1="15" x2="200" y2="15" stroke="rgba(0,0,0,0.2)" stroke-width="1" />
              </pattern>
            </defs>
            <!-- 两个图层：滚动的竖线 + 固定的横线 -->
            <rect width="200" height="60" fill="url(#cpu-grid)" class="chart-grid-rect"/>
            <rect width="200" height="60" fill="url(#cpu-grid-static)" class="chart-grid-rect"/>
            
            <path
              :d="cpuChartPoints"
              fill="none"
              stroke="#e74c3c"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <div class="chart-label-min">0%</div>
        </div>
      </div>

      <!-- 数据库卡片 -->
      <div class="status-card" :style="{ '--usage-percent': (metrics.database?.pool_usage || 0) + '%' }">
        <div class="status-header">
          <div class="status-icon database battery-fill">
            <Icon name="database" :size="30" />
          </div>
          <div class="status-title">
            <h4>数据库</h4>
            <span class="status-subtitle">连接池状态</span>
          </div>
          <div class="status-badge">{{ getPoolCapacity(metrics.database) }}</div>
        </div>
        <div class="db-stats-row">
          <div class="db-stat-item">
            <span class="db-stat-label">使用率</span>
            <span class="db-stat-value" :class="getUsageClass(metrics.database?.pool_usage || 0)">
              {{ (metrics.database?.pool_usage || 0).toFixed(1) }}%
            </span>
          </div>
          <div class="db-stat-item">
            <span class="db-stat-label">已用连接</span>
            <span class="db-stat-value">{{ metrics.database?.checked_out || 0 }}</span>
          </div>
          <div class="db-stat-item">
            <span class="db-stat-label">空闲连接</span>
            <span class="db-stat-value">{{ metrics.database?.checked_in || 0 }}</span>
          </div>
        </div>
        <div class="db-info-text">
          {{ getPoolInfoText(metrics.database) }}
        </div>
      </div>

      <!-- 网络卡片 -->
      <div class="status-card" :style="{ '--usage-percent': Math.min(100, (metrics.net?.rx_bps + metrics.net?.tx_bps) / 1000000) + '%' }">
        <div class="status-header">
          <div class="status-icon network battery-fill">
            <Icon name="ethernet-port" :size="30" />
          </div>
          <div class="status-title">
            <h4>网络</h4>
            <span class="status-subtitle">实时网络速率</span>
          </div>
          <div class="network-speed-badge">
            <div class="speed-item download">
              <span class="speed-icon">↓</span>
              <span>{{ formatSpeed(metrics.net?.rx_bps || 0) }}</span>
            </div>
            <div class="speed-item upload">
              <span class="speed-icon">↑</span>
              <span>{{ formatSpeed(metrics.net?.tx_bps || 0) }}</span>
            </div>
          </div>
        </div>
        <!-- 网络速度折线图 -->
        <div class="network-chart">
          <div class="chart-label-max">{{ formatSpeed(networkMaxSpeed) }}</div>
          <svg viewBox="0 0 200 60" preserveAspectRatio="none" class="network-chart-svg">
            <defs>
              <pattern id="net-grid" :x="gridScrollX" width="16.949" height="60" patternUnits="userSpaceOnUse">
                 <!-- 竖线 (跟随滚动) -->
                 <line x1="16.949" y1="0" x2="16.949" y2="60" stroke="rgba(0,0,0,0.2)" stroke-width="1" />
              </pattern>
              <pattern id="net-grid-static" width="200" height="15" patternUnits="userSpaceOnUse">
                 <!-- 横线 (固定) -->
                 <line x1="0" y1="15" x2="200" y2="15" stroke="rgba(0,0,0,0.2)" stroke-width="1" />
              </pattern>
            </defs>
            <rect width="200" height="60" fill="url(#net-grid)" class="chart-grid-rect"/>
            <rect width="200" height="60" fill="url(#net-grid-static)" class="chart-grid-rect"/>
            <path
              :d="networkChartPoints.download"
              fill="none"
              stroke="#f39c12"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <path
              :d="networkChartPoints.upload"
              fill="none"
              stroke="#e67e22"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              opacity="0.6"
            />
          </svg>
          <div class="chart-label-min">0 B/s</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import Icon from '../common/Icon.vue'
import { formatBytes, formatSpeed, formatUptime, getMemoryUsagePercent, getPoolCapacity, getPoolInfoText, getUsageClass } from '@/utils/dashboard'

const props = defineProps({
  metrics: {
    type: Object,
    required: true,
    default: () => ({})
  },
  appVersion: {
    type: String,
    default: 'Unknown'
  },
  coreVersion: {
    type: String,
    default: ''
  },
  coreLatestVersion: {
    type: String,
    default: ''
  },
  coreHasUpdate: {
    type: Boolean,
    default: false
  },
  isCheckingCore: {
    type: Boolean,
    default: false
  },
  cpuHistory: {
    type: Array,
    default: () => []
  },
  cpuChartPoints: {
    type: String,
    default: ''
  },
  cpuMaxPercent: {
    type: Number,
    default: 100
  },
  networkHistory: {
    type: Object,
    default: () => ({ rx: [], tx: [] })
  },
  networkChartPoints: {
    type: Object,
    default: () => ({ download: '', upload: '' })
  },
  networkMaxSpeed: {
    type: Number,
    default: 100 * 1024
  },
  gridScrollX: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['core-update'])

function getCoreDisplayText() {
  if (props.isCheckingCore) return '检测中...'
  if (props.coreHasUpdate && props.coreLatestVersion) {
    return `${props.coreLatestVersion} (新)`
  }
  return props.coreVersion || '检查中...'
}

function getCoreTitle() {
  if (props.isCheckingCore) return '正在与服务器通信...'
  if (props.coreHasUpdate) return '发现新版本，请更新镜像'
  return '点击检测更新'
}

function handleCoreUpdate() {
  emit('core-update')
}
</script>

<style scoped>
.dashboard-right {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  order: -1;
  overflow-x: hidden;
}

.system-status-section {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  flex: 1;
}

.status-card {
  padding: var(--spacing-md);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

/* 数据库卡片高度微调 */
.status-card:has(.db-stats-row) {
  min-height: 220px;
}

.status-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.status-icon {
  width: 46px;
  height: 46px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.status-icon.battery-fill {
  background: var(--color-bg-tertiary) !important;
  overflow: hidden;
  position: relative;
  box-shadow: inset 0 0 6px rgba(0,0,0,0.1);
  color: var(--color-text-primary);
}

.status-icon.battery-fill::before {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: var(--usage-percent, 0%);
  background: linear-gradient(to top, #27ae60, #2ecc71);
  transition: height 0.5s cubic-bezier(0.4, 0, 0.2, 1), background 0.3s;
  z-index: 0;
}

/* 动态颜色变化 — 使用 color-mix 根据使用率渐变 */
.status-icon::before {
  background: linear-gradient(to top,
    color-mix(in srgb, #27ae60 calc((100 - var(--usage-percent, 0)) * 1%), #e74c3c)
  ) !important;
}

.status-icon :deep(svg) {
  position: relative;
  z-index: 1;
  filter: drop-shadow(0 0 2px rgba(0,0,0,0.2));
}

.status-title {
  flex: 1;
  min-width: 0;
}

.status-title h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.status-subtitle {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

.status-badge {
  padding: 4px 8px;
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
}

.memory-badge {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.badge-title {
  font-size: 10px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.badge-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.badge-total {
  font-size: 10px;
  color: var(--color-text-tertiary);
}

.system-stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 8px;
}

.system-stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  background: var(--color-bg-tertiary);
  border-radius: 6px;
}

.system-stat-label {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.system-stat-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.system-info-group {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.flex-shrink-0 {
  flex-shrink: 0;
}

.core-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.info-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  font-size: 11px;
  color: var(--color-text-secondary);
  text-decoration: none;
  transition: all 0.2s;
  cursor: pointer;
  flex: 1;
  min-width: 0;
  white-space: nowrap;
}

.info-badge:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.core-badge.has-update {
  color: #f39c12;
}

.core-badge.checking {
  opacity: 0.7;
  cursor: wait;
}

.core-badge {
  position: relative;
  flex-shrink: 0;
}

.core-badge span {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.update-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f39c12;
  margin-left: 4px;
  flex-shrink: 0;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.db-stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 8px;
}

.db-stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  background: var(--color-bg-tertiary);
  border-radius: 6px;
}

.db-stat-label {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.db-stat-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.db-stat-value.usage-normal {
  color: #27ae60;
}

.db-stat-value.usage-caution {
  color: #f1c40f;
}

.db-stat-value.usage-warning {
  color: #f39c12;
}

.db-stat-value.usage-critical {
  color: #e74c3c;
}

.db-info-text {
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
}

.cpu-chart,
.network-chart {
  margin-top: 12px;
  position: relative;
}

.chart-label-max {
  position: absolute;
  top: 0;
  right: 0;
  font-size: 10px;
  color: var(--color-text-tertiary);
}

.chart-label-min {
  position: absolute;
  bottom: 0;
  right: 0;
  font-size: 10px;
  color: var(--color-text-tertiary);
}

.cpu-chart-svg,
.network-chart-svg {
  width: 100%;
  height: 60px;
  display: block;
}

.chart-grid-rect {
  opacity: 0.3;
}

.network-speed-badge {
  display: flex;
  gap: 12px;
}

.speed-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--color-text-secondary);
}

.speed-icon {
  font-size: 14px;
  font-weight: bold;
}

.speed-item.download .speed-icon {
  color: #f39c12;
}

.speed-item.upload .speed-icon {
  color: #e67e22;
}

@media (max-width: 768px) {
  .dashboard-right {
    gap: 10px;
    padding: 0;
  }

  .system-status-section {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    margin-top: 4px;
  }

  /* 强迫卡片在 2x2 网格中自适应 */
  .system-status-section .status-card:last-child {
    margin-top: 0;
  }

  .status-card {
    padding: 10px;
    gap: 4px;
    min-height: 0;
  }

  .status-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    margin-bottom: 4px;
    position: relative;
  }

  .status-icon {
    width: 28px;
    height: 28px;
    border-radius: 6px;
  }
  
  .status-icon :deep(svg) {
    width: 18px !important;
    height: 18px !important;
    position: relative;
    z-index: 1;
    filter: drop-shadow(0 0 2px rgba(0,0,0,0.2));
  }

  .status-title h4 {
    font-size: 13px;
  }

  .status-subtitle {
    font-size: 10px;
    display: none; /* 移动端隐藏较长的运行时长等副标题 */
  }

  .status-badge {
    position: absolute;
    top: 0;
    right: 0;
    padding: 2px 6px;
    font-size: 10px;
    background: transparent;
    color: var(--color-text-secondary);
  }

  .memory-badge {
    align-items: flex-end;
  }

  .badge-title {
    display: none;
  }

  .badge-value {
    font-size: 12px;
  }

  .badge-total {
    font-size: 9px;
  }

  /* 移动端重新开启部分关键统计行，但使用更精简的布局 */
  .system-stats-row,
  .db-stats-row {
    display: flex !important;
    gap: 4px;
    margin-top: 4px;
    flex-wrap: wrap;
  }

  .system-stat-item,
  .db-stat-item {
    background: var(--color-bg-tertiary);
    padding: 2px 6px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    gap: 4px;
    flex: 1;
    min-width: 0;
  }

  .system-stat-label,
  .db-stat-label {
    font-size: 9px;
    white-space: nowrap;
    opacity: 0.7;
    display: block; /* 移动端显示标签 */
  }

  .system-stat-value,
  .db-stat-value {
    font-size: 10px;
    font-weight: 700;
  }

  /* 隐藏非核心行 */
  .system-info-group,
  .db-info-text {
    display: none !important;
  }

  .cpu-chart,
  .network-chart {
    margin-top: 4px;
  }

  .cpu-chart-svg,
  .network-chart-svg {
    height: 36px;
  }

  .chart-label-max,
  .chart-label-min {
    font-size: 8px;
  }

  .network-speed-badge {
    position: absolute;
    top: 0;
    right: 0;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
    margin-top: 0;
  }

  .speed-item {
    font-size: 10px;
    gap: 2px;
    line-height: 1.1;
  }

  .speed-icon {
    font-size: 10px;
  }
}
</style>