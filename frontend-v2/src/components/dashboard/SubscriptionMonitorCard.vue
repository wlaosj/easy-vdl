<template>
  <div class="card subscription-monitor-card desktop-only">
    <div class="monitor-layout">
      <!-- 左侧：平台分布饼图 -->
      <div class="monitor-column pie-column">
        <div class="section-label">视频订阅</div>
        <PieChart
          :segments="segments"
          :total="total"
          label="总订阅"
          :gradients="subscriptionGradients"
          @segment-click="handleSegmentClick"
        />
      </div>

      <!-- 右侧：运行状态 (列表布局) -->
      <div class="monitor-column status-column">
        <div class="section-label-row">
          <div class="section-label">运行状态</div>
          <button
            v-if="activeDownloadCount > 0"
            class="download-badge"
            @click="handleDownloadClick"
            title="查看订阅系统批量下载任务"
          >
            批量任务下载中 {{ activeDownloadCount }}
          </button>
        </div>

        <div class="live-status-list">
          <div class="status-row">
            <!-- 正常运行 -->
            <div class="live-list-item status-half" @click="handleStatusClick('', 'active')">
              <div class="live-list-left">
                <span class="status-dot success"></span>
                <span class="live-list-label">正在订阅</span>
              </div>
              <div class="live-list-value text-success font-bold">{{ statusStats.active }}</div>
            </div>

            <!-- 暂停 -->
            <div class="live-list-item status-half" @click="handleStatusClick('', 'paused')">
              <div class="live-list-left">
                <span class="status-dot warning"></span>
                <span class="live-list-label">暂停订阅</span>
              </div>
              <div class="live-list-value font-bold" style="color:var(--color-text-primary)">{{ statusStats.paused }}</div>
            </div>
          </div>

          <div class="status-row">
            <!-- 异常 -->
            <div class="live-list-item status-half" @click="handleStatusClick('', 'error')">
              <div class="live-list-left">
                <span class="status-dot error"></span>
                <span class="live-list-label">异常订阅</span>
              </div>
              <div class="live-list-value text-error font-bold">{{ statusStats.error }}</div>
            </div>

            <div class="live-list-item status-half" @click="handleStatusClick('', 'invalid')">
              <div class="live-list-left">
                <span class="status-dot invalid"></span>
                <span class="live-list-label">失效订阅</span>
              </div>
              <div class="live-list-value text-error font-bold">{{ statusStats.invalid }}</div>
            </div>
          </div>

          <div class="live-list-item" @click="handleStatusClick('', '')">
            <div class="live-list-left">
              <span class="status-dot primary"></span>
              <span class="live-list-label">自动下载开启</span>
            </div>
            <div class="live-list-value text-primary font-bold">{{ autoDownloadEnabledCount }}</div>
          </div>
        </div>

        <!-- 存储空间行 -->
        <div class="live-storage-card" @click="handleStorageClick">
          <div class="storage-icon">
            <Icon name="hard-drive" :size="16" />
          </div>
          <span class="storage-label">视频订阅总占用</span>
          <span class="storage-value">{{ formatBytes(storageSize) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import PieChart from './PieChart.vue'
import Icon from '../common/Icon.vue'
import { formatBytes } from '@/utils/dashboard'

const props = defineProps({
  segments: {
    type: Array,
    required: true,
    default: () => []
  },
  total: {
    type: Number,
    default: 0
  },
  platformDistribution: {
    type: Object,
    required: true,
    default: () => ({})
  },
  statusStats: {
    type: Object,
    required: true,
    default: () => ({
      active: 0,
      paused: 0,
      error: 0,
      invalid: 0
    })
  },
  storageSize: {
    type: Number,
    default: 0
  },
  activeDownloadCount: {
    type: Number,
    default: 0
  },
  autoDownloadEnabledCount: {
    type: Number,
    default: 0
  }
})

const router = useRouter()

// 视频订阅的渐变配置（使用柔和颜色）
const subscriptionGradients = [
  { id: 'youtube', startColor: '#FF6B6B', endColor: '#FF7F7F' }, // 柔和的珊瑚红
  { id: 'bilibili', startColor: '#00A1D6', endColor: '#0082B3' },
  { id: 'douyin', startColor: '#25F4EE', endColor: '#FE2C55' }, // 抖音品牌色渐变
  { id: 'tiktok', startColor: '#25F4EE', endColor: '#000000' },
  { id: 'netease', startColor: '#E53E3E', endColor: '#C53030' }, // 网易云红
  { id: 'redbook', startColor: '#ff2442', endColor: '#ff2442' }, // 小红书红色
  { id: 'x', startColor: '#111827', endColor: '#4b5563' }, // X 深色渐变
  { id: 'instagram', startColor: '#F58529', endColor: '#DD2A7B' } // Instagram 橙粉渐变
]

function handleSegmentClick(segment) {
  handlePlatformClick(segment.platform)
}

function handlePlatformClick(platform) {
  const query = {}
  if (platform) {
    query.platform = platform
  }
  router.push({ path: '/subscriptions', query })
}

function handleStatusClick(platform = '', status = '') {
  const query = {}
  if (platform) {
    query.platform = platform
  }
  if (status) {
    query.status = status
  }
  router.push({ path: '/subscriptions', query })
}

function handleStorageClick() {
  router.push('/downloads')
}

function handleDownloadClick() {
  router.push({ path: '/batch-download-tasks' })
}
</script>

<style scoped>
.subscription-monitor-card {
  flex: 1;
  margin: 0;
  height: auto !important;
  min-height: auto !important;
  padding: 16px 20px !important;
  margin-bottom: var(--spacing-md);
  display: flex;
  flex-direction: column;
  justify-content: center;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
}

.monitor-layout {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-top: 0;
}

.monitor-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.status-column {
  flex: 1.8;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.section-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.download-badge {
  border: 0;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #1d4ed8;
  background: rgba(37, 99, 235, 0.12);
  cursor: pointer;
  transition: all 0.2s ease;
}

.download-badge:hover {
  background: rgba(37, 99, 235, 0.2);
}

.pie-column {
  flex: 1;
  align-items: center;
  justify-content: center;
}

.pie-column .section-label {
  width: 100%;
  text-align: center;
}

.status-column {
  flex: 1.8;
  justify-content: center;
}

.live-status-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-row {
  display: flex;
  gap: 10px;
}

.status-half {
  flex: 1;
}

.live-list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.live-list-item:hover {
  background: var(--color-bg-hover);
  transform: translateX(2px);
}

.live-list-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.success {
  background: #27ae60;
  box-shadow: 0 0 4px rgba(39, 174, 96, 0.5);
}

.status-dot.primary {
  background: #3498db;
  box-shadow: 0 0 4px rgba(52, 152, 219, 0.5);
}

.status-dot.warning {
  background: #f39c12;
  box-shadow: 0 0 4px rgba(243, 156, 18, 0.5);
}

.status-dot.error {
  background: #e74c3c;
  box-shadow: 0 0 4px rgba(231, 76, 60, 0.5);
}

.status-dot.invalid {
  background: #7f8c8d;
  box-shadow: 0 0 4px rgba(127, 140, 141, 0.5);
}

.status-dot.downloading-dot {
  background: #3498db;
  box-shadow: 0 0 4px rgba(52, 152, 219, 0.5);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { transform: scale(0.95); opacity: 0.8; }
  50% { transform: scale(1.1); opacity: 1; }
  100% { transform: scale(0.95); opacity: 0.8; }
}

.live-list-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.live-list-value {
  font-size: 18px;
  font-weight: bold;
}

.text-success {
  color: #27ae60 !important;
}

.text-primary {
  color: #3498db !important;
}

.text-error {
  color: #e74c3c !important;
}

.font-bold {
  font-weight: bold;
}

.live-storage-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.live-storage-card:hover {
  background: var(--color-bg-hover);
  transform: translateX(2px);
}

.storage-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
}

.storage-label {
  flex: 1;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.storage-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.desktop-only {
  display: block;
}

@media (max-width: 1550px) {
  .monitor-layout {
    flex-direction: column;
    align-items: stretch;
  }
  .pie-column, .status-column {
    flex: none;
    width: 100%;
  }
}

@media (max-width: 768px) {
  .desktop-only {
    display: none;
  }
}
</style>
