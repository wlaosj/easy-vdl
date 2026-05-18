<template>
  <div class="card combined-stats-card">
    <div class="stat-values-row compact">
      <div class="stat-value-item" @click="handleClick('completed')">
        <span class="stat-label-inline">已下载</span>
        <span class="stat-value">{{ totalCompleted }}</span>
        <span class="stat-value-label">已完成</span>
      </div>
      <div class="stat-divider-vertical"></div>
      <div class="stat-value-item" @click="handleClick('active')">
        <span class="stat-label-inline">正在下载</span>
        <span class="stat-value">{{ downloading }}</span>
        <span class="stat-value-label">进行中</span>
      </div>
      <div class="stat-divider-vertical"></div>
      <div class="stat-value-item" @click="handleClick('active')">
        <span class="stat-label-inline">等待队列</span>
        <span class="stat-value">{{ queued }}</span>
        <span class="stat-value-label">待处理</span>
      </div>
      <div class="stat-divider-vertical"></div>
      <div class="stat-value-item" @click="handleClick('error')">
        <span class="stat-label-inline">下载失败</span>
        <span class="stat-value" :class="{ 'text-error': totalFailed > 0, 'has-failed-animation': totalFailed > 0 }">{{ totalFailed }}</span>
        <span class="stat-value-label">异常项</span>
      </div>
    </div>

    <!-- 移动端在此合并直播订阅统计 -->
    <div class="mobile-only">
      <slot name="mobile-stats"></slot>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const props = defineProps({
  downloading: {
    type: Number,
    default: 0
  },
  totalCompleted: {
    type: Number,
    default: 0
  },
  queued: {
    type: Number,
    default: 0
  },
  totalFailed: {
    type: Number,
    default: 0
  }
})

const router = useRouter()

function handleClick(status) {
  router.push({ path: '/downloads', query: { status } })
}
</script>

<style scoped>
.combined-stats-card {
  padding: 16px;
}

.stat-values-row {
  display: flex;
  align-items: center;
  gap: 0;
  flex-wrap: nowrap;
}

.stat-values-row.compact {
  gap: 0;
}

.stat-value-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  transition: background-color 0.2s;
}

.stat-value-item:hover {
  background-color: var(--color-bg-tertiary);
}

.stat-label-inline {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.stat-value {
  font-size: 24px;
  font-weight: bold;
  color: var(--color-text-primary);
  line-height: 1;
}

.stat-value-label {
  font-size: 11px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.stat-divider-vertical {
  width: 1px;
  height: 40px;
  background: var(--color-border);
  margin: 0 8px;
}

.text-error {
  color: #e74c3c !important;
}

.has-failed-animation {
  animation: failed-pulse 1.5s infinite cubic-bezier(0.4, 0, 0.6, 1);
  text-shadow: 0 0 10px rgba(231, 76, 60, 0.6);
  filter: drop-shadow(0 0 5px rgba(231, 76, 60, 0.3));
}

@keyframes failed-pulse {
  0% { 
    opacity: 1;
    transform: scale(1);
    color: #e74c3c;
    text-shadow: 0 0 10px rgba(231, 76, 60, 0.4);
    filter: drop-shadow(0 0 2px rgba(231, 76, 60, 0.2));
  }
  50% { 
    opacity: 0.9;
    transform: scale(1.1);
    color: #ff3e2a;
    text-shadow: 0 0 20px rgba(231, 76, 60, 0.9), 0 0 30px rgba(231, 76, 60, 0.4);
    filter: drop-shadow(0 0 8px rgba(231, 76, 60, 0.6));
  }
  100% { 
    opacity: 1;
    transform: scale(1);
    color: #e74c3c;
    text-shadow: 0 0 10px rgba(231, 76, 60, 0.4);
    filter: drop-shadow(0 0 2px rgba(231, 76, 60, 0.2));
  }
}

.mobile-only {
  display: none;
}

@media (max-width: 1550px) {
  .stat-values-row {
    flex-wrap: wrap;
    gap: 8px;
    justify-content: space-between;
  }

  .stat-value-item {
    flex: 1 1 calc(50% - 8px);
    min-width: 120px;
    padding: 8px 4px;
    background: var(--color-bg-tertiary);
  }

  .stat-divider-vertical {
    display: none;
  }

  .stat-value {
    font-size: 20px;
  }
}

@media (max-width: 768px) {
  .combined-stats-card {
    padding: 10px !important;
  }

  .stat-value-item {
    padding: 4px 2px;
    gap: 2px;
  }

  .stat-label-inline {
    font-size: 11px;
    white-space: nowrap;
  }

  .stat-value {
    font-size: 18px;
  }

  .stat-value-label {
    display: none !important;
  }

  .stat-divider-vertical {
    height: 24px;
    margin: 0 4px;
  }

  .mobile-only {
    display: block;
  }
}
</style>
