<template>
  <div class="feedback-progress-page">
    <div class="top-row">
      <div class="page-header card">
        <div class="header-left">
          <h1>开发进度反馈</h1>
          <p>展示所有已受理问题的处理进展。</p>
          <p class="feedback-tip">问题反馈可通过仪表盘中高级专享反馈专用通道，或 TG 群进行提交。</p>
        </div>
        <div class="header-actions">
          <select v-model="statusFilter" class="status-filter" @change="handleFilterChange">
            <option value="active">待跟进（已受理+处理中）</option>
            <option value="">全部状态</option>
            <option value="accepted">已受理</option>
            <option value="processing">处理中</option>
            <option value="resolved_next_release">已处理（下版本发布）</option>
            <option value="resolved">已处理（已上线）</option>
          </select>
          <button class="btn btn-primary" :disabled="loading" @click="loadProgress">
            {{ loading ? '刷新中...' : '刷新' }}
          </button>
        </div>
      </div>

      <div class="summary-grid">
        <div class="summary-card card">
          <span class="summary-label">已受理</span>
          <span class="summary-value">{{ summary.accepted }}</span>
        </div>
        <div class="summary-card card">
          <span class="summary-label">处理中</span>
          <span class="summary-value">{{ summary.processing }}</span>
        </div>
        <div class="summary-card card">
          <span class="summary-label">已处理（下版本发布）</span>
          <span class="summary-value">{{ summary.resolved_next_release }}</span>
        </div>
        <div class="summary-card card">
          <span class="summary-label">已处理（已上线）</span>
          <span class="summary-value">{{ summary.resolved }}</span>
        </div>
      </div>
    </div>

    <div class="list-wrap card">
      <div class="list-meta">
        <span>共 {{ total }} 条</span>
        <span>最后更新：{{ lastUpdatedText }}</span>
      </div>

      <div v-if="loading && filteredItems.length === 0" class="progress-loading">
        <div class="progress-loading-head">
          <span class="loading-spinner" aria-hidden="true"></span>
          <span>正在加载开发进度...</span>
        </div>
        <div class="progress-skeleton-list">
          <div v-for="n in 4" :key="`skeleton-${n}`" class="progress-skeleton-item">
            <div class="skeleton-title-row">
              <span class="skeleton-line skeleton-title"></span>
              <span class="skeleton-pill"></span>
            </div>
            <span class="skeleton-line skeleton-content"></span>
            <span class="skeleton-line skeleton-content short"></span>
            <div class="skeleton-meta-row">
              <span class="skeleton-line skeleton-meta"></span>
              <span class="skeleton-line skeleton-meta"></span>
              <span class="skeleton-line skeleton-meta"></span>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="filteredItems.length === 0" class="empty-state">暂无开发进度数据</div>

      <div v-else class="progress-list">
        <article v-for="item in visibleItems" :key="item.id" class="progress-item">
          <div class="item-main">
            <div class="item-title-row">
              <span class="status-pill" :class="`status-${item.status}`">{{ getStatusText(item.status) }}</span>
              <h3>{{ item.title }}</h3>
            </div>
            <p class="item-content" :class="{ collapsed: !isExpanded(item.id) }">{{ item.content || '已记录该问题，详情将持续更新。' }}</p>
            <button
              v-if="(item.content || '').length > 80"
              class="text-toggle-btn"
              @click="toggleExpand(item.id)"
            >
              {{ isExpanded(item.id) ? '收起' : '展开' }}
            </button>
          </div>
          <div class="item-meta">
            <span>ID: {{ item.id }}</span>
            <span>来源: {{ item.source || '用户反馈' }}</span>
            <span v-if="item.eta_version">目标版本: {{ item.eta_version }}</span>
            <span>更新时间: {{ formatTime(item.updated_at) }}</span>
          </div>
        </article>
        <div class="list-load-more" v-if="visibleCount < filteredItems.length">
          <button class="btn btn-secondary" @click="loadMore">加载更多（{{ filteredItems.length - visibleCount }}）</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { systemApi } from '@/api/system'

const loading = ref(false)
const statusFilter = ref('')
const items = ref([])
const total = ref(0)
const lastUpdatedText = ref('-')
const visibleCount = ref(20)
const expandedIds = ref(new Set())
const summary = ref({
  accepted: 0,
  processing: 0,
  resolved_next_release: 0,
  resolved: 0
})

const getStatusText = (status) => {
  if (status === 'accepted') return '已受理'
  if (status === 'processing') return '处理中'
  if (status === 'resolved_next_release') return '已处理（下版本发布）'
  if (status === 'resolved') return '已处理（已上线）'
  return '已受理'
}

const formatTime = (raw) => {
  if (!raw) return '-'
  const dt = new Date(raw)
  if (Number.isNaN(dt.getTime())) return raw
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const d = String(dt.getDate()).padStart(2, '0')
  const hh = String(dt.getHours()).padStart(2, '0')
  const mm = String(dt.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${d} ${hh}:${mm}`
}

const loadProgress = async () => {
  loading.value = true
  try {
    const apiStatus = ['accepted', 'processing', 'resolved_next_release', 'resolved'].includes(statusFilter.value)
      ? statusFilter.value
      : ''
    const [listData, summaryData] = await Promise.all([
      systemApi.getFeedbackProgress(500, apiStatus),
      apiStatus ? systemApi.getFeedbackProgress(1, '') : Promise.resolve(null)
    ])

    const data = listData || {}
    const globalSummaryData = summaryData || data

    items.value = Array.isArray(data?.items) ? data.items : []
    total.value = Number(data?.total || 0)
    summary.value = {
      accepted: Number(globalSummaryData?.summary?.accepted || 0),
      processing: Number(globalSummaryData?.summary?.processing || 0),
      resolved_next_release: Number(globalSummaryData?.summary?.resolved_next_release || 0),
      resolved: Number(globalSummaryData?.summary?.resolved || 0)
    }
    lastUpdatedText.value = formatTime(data?.timestamp)
  } catch (err) {
    console.error('获取开发进度失败:', err)
  } finally {
    loading.value = false
  }
}

const filteredItems = computed(() => {
  if (statusFilter.value === 'active') {
    return items.value.filter((it) => it.status === 'accepted' || it.status === 'processing')
  }
  return items.value
})

const sortedItems = computed(() => {
  const priority = {
    accepted: 0,
    processing: 1,
    resolved_next_release: 2,
    resolved: 3
  }

  return [...filteredItems.value].sort((a, b) => {
    const pa = priority[a?.status] ?? 99
    const pb = priority[b?.status] ?? 99
    if (pa !== pb) return pa - pb

    const ta = new Date(a?.updated_at || 0).getTime()
    const tb = new Date(b?.updated_at || 0).getTime()
    return tb - ta
  })
})

const visibleItems = computed(() => sortedItems.value.slice(0, visibleCount.value))

const handleFilterChange = () => {
  visibleCount.value = 20
  expandedIds.value = new Set()
  loadProgress()
}

const loadMore = () => {
  visibleCount.value += 20
}

const toggleExpand = (id) => {
  const next = new Set(expandedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  expandedIds.value = next
}

const isExpanded = (id) => expandedIds.value.has(id)

onMounted(() => {
  loadProgress()
})
</script>

<style scoped>
.feedback-progress-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.top-row {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.header-left h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.3;
}

.header-left p {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
}

.feedback-tip {
  font-size: 13px;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.status-filter {
  min-width: 180px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  border-radius: 8px;
  height: 36px;
  padding: 0 10px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-label {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.summary-value {
  font-size: 24px;
  font-weight: 700;
}

.list-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.list-meta {
  display: flex;
  justify-content: space-between;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.progress-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.progress-item {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px;
  background: var(--color-bg-card);
}

.item-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-start;
}

.item-title-row h3 {
  margin: 0;
  font-size: 16px;
  min-width: 0;
}

.item-content {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.item-content.collapsed {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.text-toggle-btn {
  margin-top: 6px;
  border: none;
  background: transparent;
  color: var(--color-primary);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}

.item-meta {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--color-text-tertiary);
  font-size: 12px;
}

.list-load-more {
  display: flex;
  justify-content: center;
  margin-top: 8px;
}

.status-pill {
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  white-space: nowrap;
}

.status-accepted {
  background: rgba(52, 152, 219, 0.12);
  color: #2980b9;
}

.status-processing {
  background: rgba(243, 156, 18, 0.14);
  color: #b9770e;
}

.status-resolved_next_release {
  background: rgba(155, 89, 182, 0.14);
  color: #7d3c98;
}

.status-resolved {
  background: rgba(39, 174, 96, 0.14);
  color: #1e8449;
}

.empty-state {
  text-align: center;
  color: var(--color-text-secondary);
  padding: 28px 12px;
}

.progress-loading {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.progress-loading-head {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--color-text-secondary);
  min-height: 56px;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: progress-loading-spin 1s linear infinite;
}

.progress-skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.progress-skeleton-item {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 12px;
}

.skeleton-title-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.skeleton-line,
.skeleton-pill {
  position: relative;
  overflow: hidden;
  background: var(--color-bg-hover);
}

.skeleton-line::after,
.skeleton-pill::after {
  content: '';
  position: absolute;
  top: 0;
  left: -150%;
  width: 120%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.55), transparent);
  animation: progress-skeleton-shimmer 1.3s ease-in-out infinite;
}

[data-theme="dark"] .skeleton-line::after,
[data-theme="dark"] .skeleton-pill::after {
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
}

.skeleton-title {
  display: block;
  width: 42%;
  height: 16px;
  border-radius: 6px;
}

.skeleton-pill {
  width: 74px;
  height: 22px;
  border-radius: 999px;
}

.skeleton-content {
  display: block;
  width: 100%;
  height: 13px;
  margin-top: 10px;
  border-radius: 6px;
}

.skeleton-content.short {
  width: 75%;
}

.skeleton-meta-row {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.skeleton-meta {
  display: block;
  width: 96px;
  height: 12px;
  border-radius: 6px;
}

@keyframes progress-loading-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

@keyframes progress-skeleton-shimmer {
  0% {
    left: -150%;
  }
  100% {
    left: 130%;
  }
}

@media (max-width: 1024px) {
  .top-row {
    grid-template-columns: 1fr;
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: 10px;
  }

  .header-left h1 {
    font-size: 34px;
  }

  .header-left p {
    margin-top: 6px;
    font-size: 14px;
    line-height: 1.45;
  }

  .feedback-tip {
    font-size: 12px;
    line-height: 1.45;
  }

  .header-actions {
    width: 100%;
    gap: 6px;
  }

  .status-filter {
    flex: 1;
    min-width: 0;
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .summary-card {
    gap: 4px;
    padding: 10px 12px;
    min-height: 86px;
  }

  .summary-label {
    font-size: 12px;
    line-height: 1.35;
  }

  .summary-value {
    font-size: 20px;
  }

  .list-meta {
    flex-direction: column;
    gap: 4px;
  }
}

@media (max-width: 420px) {
  .summary-card {
    min-height: 78px;
    padding: 9px 10px;
  }

  .summary-value {
    font-size: 18px;
  }
}
</style>
