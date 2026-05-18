<template>
  <LicenseCardShell
    class="card license-card compact-dashboard"
    :class="{
      'inactive-license': !hasLicense,
      'loading': isLoading
    }"
    :is-licensed="hasLicense"
    :remaining-days="remainingDays"
    :loading="isLoading"
    @click="handleClick"
  >
    <template v-if="isLoading">
      <div class="license-skeleton">
        <div class="skeleton-icon"></div>
        <div class="skeleton-content">
          <div class="skeleton-line-title"></div>
          <div class="skeleton-line-sub"></div>
        </div>
      </div>
    </template>
    <template v-else>
      <div class="license-header-compact">
        <div class="license-crown">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
            <path d="M5 16L3 5l5.5 5L12 4l3.5 6L21 5l-2 11H5z"/>
            <path d="M5 19h14v2H5z" opacity="0.8"/>
          </svg>
        </div>
        <div class="license-main">
          <span class="license-label">{{ hasLicense ? '高级版' : '基础版' }}</span>
        </div>
      </div>
      
      <div class="license-usage">
        <div class="usage-info-row">
          <span class="usage-text">
            {{ hasLicense ? (remainingDays === -1 || remainingDays > 3650 ? '永久有效' : `有效期剩余 ${remainingDays} 天`) : '' }}
          </span>
          <span v-if="hasLicense" class="license-feedback-btn" @click.stop="handleFeedbackClick" title="高级版用户专属优先反馈通道">
            <Icon name="message-square" :size="14" />
            高级专享反馈
          </span>
        </div>
        <div class="usage-bar">
          <div class="usage-fill" :style="{ width: usagePercent + '%' }"></div>
        </div>
      </div>
    </template>
  </LicenseCardShell>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '../common/Icon.vue'
import LicenseCardShell from '../common/LicenseCardShell.vue'

const props = defineProps({
  hasLicense: {
    type: Boolean,
    default: false
  },
  isLoading: {
    type: Boolean,
    default: false
  },
  remainingDays: {
    type: Number,
    default: 0
  }
})

const router = useRouter()

const usagePercent = computed(() => {
  const days = props.remainingDays || 0
  if (days === -1 || days > 365) return 100
  return Math.max(0, Math.min(100, (days / 365) * 100))
})

function handleClick() {
  router.push('/settings?tab=license')
}

function handleFeedbackClick() {
  if (typeof window.showFeedbackForm === 'function') {
    window.showFeedbackForm()
  } else {
    window.alert('反馈表单正在初始化，请稍后再试一次～')
  }
}
</script>

<style scoped>
.license-card.compact-dashboard {
  flex: 1;
  min-width: 0;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  min-height: 110px;
  height: 110px;
}

.license-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.skeleton-icon {
  width: 40px;
  height: 40px;
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

.skeleton-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skeleton-line-title {
  width: 80px;
  height: 20px;
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

.skeleton-line-sub {
  width: 100%;
  height: 6px;
  background: var(--color-bg-tertiary);
  border-radius: 3px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

@keyframes skeleton-pulse {
  0% { opacity: 0.6; }
  50% { opacity: 0.3; }
  100% { opacity: 0.6; }
}

[data-theme="dark"] .license-card.compact-dashboard {
  background: linear-gradient(to bottom right, var(--color-bg-card), rgba(230, 126, 34, 0.05));
  border-color: rgba(230, 126, 34, 0.2);
}

.license-card.compact-dashboard:hover:not(.is-lifetime) {
  box-shadow: 0 4px 12px rgba(230, 126, 34, 0.15);
  border-color: rgba(230, 126, 34, 0.6);
  background: var(--color-bg-hover);
}

.license-card.compact-dashboard:hover:not(.is-lifetime) .license-crown svg {
  transform: scale(1.2);
}

.license-card .license-label {
  font-size: 20px;
  font-weight: 800;
  white-space: nowrap;
  line-height: 1.1;
  display: block;
}

.license-card .license-usage {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.license-card .usage-text {
  font-size: 11px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.license-card .usage-info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.license-feedback-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.license-feedback-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.license-card .usage-bar {
  width: 100%;
  height: 4px;
  background: var(--color-bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
}

.license-card .usage-fill {
  height: 100%;
  background: linear-gradient(90deg, #e67e22, #d35400);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.license-card.compact-dashboard.is-lifetime .license-feedback-btn {
  background: rgba(230, 126, 34, 0.12);
  color: var(--color-text-primary);
  border: 1px solid rgba(230, 126, 34, 0.35);
  backdrop-filter: blur(2px);
  transition: transform 0.2s ease;
}

.license-card.compact-dashboard.is-lifetime .license-feedback-btn:hover {
  background: rgba(230, 126, 34, 0.18);
  color: var(--color-text-primary);
  border-color: rgba(230, 126, 34, 0.5);
  box-shadow: none;
  transform: translateY(-1px);
}

  /* 移动端适配 */
@media (max-width: 768px) {
  .license-card.compact-dashboard {
    height: auto !important;
    min-height: 100px !important;
    padding: 12px !important;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .license-card .license-header-compact {
    gap: 10px;
  }

  .license-card.compact-dashboard.is-lifetime .license-header-compact {
    padding-right: 0;
    align-items: flex-start;
  }

  .license-card.compact-dashboard.is-lifetime .license-main {
    padding-top: 20px;
  }

  .license-card.compact-dashboard.is-lifetime .license-label {
    white-space: nowrap;
    word-break: keep-all;
    line-height: 1.05;
  }

  .license-card .license-crown svg {
    width: 36px;
    height: 36px;
  }

  .license-card .license-label {
    font-size: 18px !important;
  }

  .license-card .license-usage {
    gap: 8px;
  }

  .license-card .usage-info-row {
    flex-direction: row;
    justify-content: space-between;
    align-items: flex-end;
    gap: 4px;
  }

  .license-card .usage-text {
    font-size: 10px;
    line-height: 1;
    margin-bottom: 2px;
  }

  .license-card .license-feedback-btn {
    font-size: 10px;
    padding: 3px 8px;
    white-space: nowrap;
    margin-bottom: -1px; /* 稍微下移一点，与文字对齐 */
  }

  .license-card .usage-bar {
    height: 4px;
    margin-top: 2px;
  }
  
  /* 寿命卡片在移动端的特殊处理 */
  .license-card.compact-dashboard.is-lifetime .license-label {
    font-size: 18px !important;
  }
}
</style>
