<template>
  <div class="card live-monitor-card desktop-only">
    <div class="monitor-layout">
      <!-- 左侧：平台分布饼图 -->
      <div class="monitor-column pie-column">
        <div class="section-label">直播订阅</div>
        <PieChart
          :segments="segments"
          :total="total"
          label="监控中"
          :gradients="liveGradients"
          @segment-click="handleSegmentClick"
        />
      </div>

      <!-- 右侧：实时状态 (列表布局) -->
      <div class="monitor-column status-column">
        <div class="section-label">运行状态</div>

        <div class="live-status-list">
          <!-- 正在订阅 & 开启录播 (并列显示) -->
          <div class="live-row">
            <div class="live-list-item flex-1" @click="handleStatusClick('all', 'all')">
              <div class="live-list-left">
                <span class="status-dot primary"></span>
                <span class="live-list-label">正在订阅</span>
              </div>
              <div class="live-list-value text-primary font-bold">{{ stats.total_subscriptions }}</div>
            </div>
            <div class="live-list-item flex-1" @click="handleStatusClick('all', 'all')">
              <div class="live-list-left">
                <span class="status-dot success"></span>
                <span class="live-list-label">开启录播</span>
              </div>
              <div class="live-list-value text-success font-bold">{{ totalEnabled }}</div>
            </div>
          </div>

          <!-- 直播中 & 录制中 (并列显示) -->
          <div class="live-row">
            <div class="live-list-item flex-1" @click="handleStatusClick('live', 'all')">
              <div class="live-list-left">
                <span class="status-dot warning"></span>
                <span class="live-list-label">正在直播</span>
              </div>
              <div class="live-list-value text-warning font-bold">{{ stats.live_count }}</div>
            </div>
            <div class="live-list-item flex-1" @click="handleStatusClick('recording')">
              <div class="live-list-left">
                <span class="status-dot error"></span>
                <span class="live-list-label">正在录制</span>
              </div>
              <div class="live-list-value text-error font-bold">{{ stats.recording_count }}</div>
            </div>
          </div>

          <!-- 已录制 -->
          <div class="live-list-item" @click="handleHistoryClick">
            <div class="live-list-left">
              <span class="status-dot primary"></span>
              <span class="live-list-label">今日已录</span>
            </div>
            <div class="live-list-value text-primary font-bold">{{ stats.today_records }}</div>
          </div>
        </div>

        <!-- 存储空间行 -->
        <div class="live-storage-card" @click="handleStorageClick">
          <div class="storage-icon">
            <Icon name="hard-drive" :size="16" />
          </div>
          <span class="storage-label">直播订阅总占用</span>
          <span class="storage-value">{{ formatBytes(stats.total_size) }}</span>
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
  stats: {
    type: Object,
    required: true,
    default: () => ({
      total_subscriptions: 0,
      live_count: 0,
      recording_count: 0,
      today_records: 0,
      total_size: 0
    })
  },
  totalEnabled: {
    type: Number,
    default: 0
  }
})

const router = useRouter()

// 直播订阅的渐变配置
const liveGradients = [
  { id: 'douyin', startColor: '#25F4EE', endColor: '#FE2C55' },
  { id: 'tiktok', startColor: '#25F4EE', endColor: '#000000' },
  { id: 'bilibili', startColor: '#00A1D6', endColor: '#0082B3' },
  { id: 'youtube', startColor: '#FF6B6B', endColor: '#FF7F7F' },
  { id: 'redbook', startColor: '#FF2442', endColor: '#FF2442' },
  { id: 'xhs', startColor: '#FF2442', endColor: '#FF2442' },
  { id: 'huya', startColor: '#FFAA00', endColor: '#FF8800' },
  { id: 'cc', startColor: '#0D91E9', endColor: '#00B0FF' },
  { id: 'douyu', startColor: '#FF5500', endColor: '#FF4400' },
  { id: 'migu', startColor: '#1d8ef7', endColor: '#4aa7ff' },
  { id: 'kuaishou', startColor: '#FF5000', endColor: '#FF5000' },
  { id: 'weibo', startColor: '#EB0028', endColor: '#EB0028' },
  { id: 'other', startColor: '#999', endColor: '#666' }
]

function handleSegmentClick(segment) {
  router.push(`/live-record?platform=${segment.platform}`)
}

function handleStatusClick(status, platform = 'all') {
  router.push(`/live-record?status=${status}&platform=${platform}`)
}

function handleHistoryClick() {
  router.push({ path: '/live-record', query: { action: 'history' } })
}

function handleStorageClick() {
  router.push('/live-record')
}
</script>

<style scoped>
.live-monitor-card {
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
}

.monitor-column {
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

.pie-column {
  flex: 1.2;
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

.live-row {
  display: flex;
  gap: 12px;
}

.flex-1 {
  flex: 1;
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

.status-dot.primary {
  background: #3498db;
  box-shadow: 0 0 4px rgba(52, 152, 219, 0.5);
}

.status-dot.success {
  background: #27ae60;
  box-shadow: 0 0 4px rgba(39, 174, 96, 0.5);
}

.status-dot.warning {
  background: #f39c12;
  box-shadow: 0 0 4px rgba(243, 156, 18, 0.5);
}

.status-dot.error {
  background: #e74c3c;
  box-shadow: 0 0 4px rgba(231, 76, 60, 0.5);
}

.live-list-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.live-list-value {
  font-size: 18px;
  font-weight: bold;
}

.text-primary {
  color: #3498db !important;
}

.text-success {
  color: #27ae60 !important;
}

.text-warning {
  color: #f39c12 !important;
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
