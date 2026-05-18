<template>
  <div class="stat-card gradient-dark storage-card battery-card-style">
    <div class="battery-bg-fill" :class="storageClass" :style="{ width: freePercent + '%' }"></div>
    <div class="stat-content relative-z">
      <div class="label-row">
        <span class="stat-label">磁盘总存储空间</span>
        <button class="unit-toggle-btn" type="button" @click="emit('toggle-unit')">
          {{ isBinaryUnit ? 'GiB' : 'GB' }}
        </button>
      </div>
      <div class="stat-value-group">
        <span class="stat-value">{{ formatUnitValue(usedBytes) }}{{ unitLabel }}</span>
        <span class="stat-suffix">/ {{ formatUnitValue(totalBytes) }}{{ unitLabel }}</span>
      </div>
      <div class="stat-footer-row">
        <p class="text-xs text-gray-400">剩余空间</p>
        <span class="stat-percent-large" :class="storageClass">{{ freePercent.toFixed(1) }}%</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  totalBytes: {
    type: Number,
    default: 0
  },
  usedBytes: {
    type: Number,
    default: 0
  },
  freeBytes: {
    type: Number,
    default: 0
  },
  unitMode: {
    type: String,
    default: 'decimal'
  }
})

const emit = defineEmits(['toggle-unit'])
const isBinaryUnit = computed(() => props.unitMode === 'binary')
const unitDivisor = computed(() => (isBinaryUnit.value ? 1024 ** 3 : 1000 ** 3))
const unitLabel = computed(() => (isBinaryUnit.value ? 'GiB' : 'GB'))

const formatUnitValue = (bytes) => {
  const value = (bytes || 0) / unitDivisor.value
  return value.toFixed(2)
}

const freePercent = computed(() => {
  const total = props.totalBytes || 0
  const free = props.freeBytes || 0
  if (total <= 0) return 0
  return (free / total) * 100
})

const storageClass = computed(() => {
  const free = freePercent.value
  if (free <= 10) return 'critical'
  if (free <= 25) return 'warning'
  if (free <= 40) return 'caution'
  return 'normal'
})
</script>

<style scoped>
.stat-card.storage-card.battery-card-style {
  position: relative;
  border: 2px solid var(--color-border);
  border-radius: 12px;
  overflow: hidden;
  background: var(--color-bg-card);
  padding: 0;
  transition: all 0.3s ease;
  min-height: 110px;
}

.stat-card.storage-card.battery-card-style::after {
  content: '';
  position: absolute;
  top: 50%;
  right: -7px;
  transform: translateY(-50%);
  width: 5px;
  height: 24px;
  background: var(--color-border);
  border-radius: 0 4px 4px 0;
  transition: background-color 0.3s ease;
}

.stat-card.storage-card.battery-card-style:hover {
  border-color: var(--color-text-secondary);
}

.stat-card.storage-card.battery-card-style:hover::after {
  background: var(--color-text-secondary);
}

.battery-bg-fill {
  position: absolute;
  top: 4px;
  left: 4px;
  bottom: 4px;
  border-radius: 8px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 0;
  max-width: calc(100% - 8px);
  opacity: 0.18;
  backdrop-filter: blur(4px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.battery-bg-fill.normal {
  background: rgba(39, 174, 96, 0.15);
}

.battery-bg-fill.caution {
  background: rgba(241, 196, 15, 0.15);
}

.battery-bg-fill.warning {
  background: rgba(230, 126, 34, 0.15);
}

.battery-bg-fill.critical {
  background: rgba(231, 76, 60, 0.15);
}

.stat-content.relative-z {
  position: relative;
  z-index: 1;
  padding: 12px 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-sizing: border-box;
}

.stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  line-height: 1;
}

.unit-toggle-btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-tertiary);
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  padding: 2px 6px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
  opacity: 0.8;
}

.unit-toggle-btn:hover {
  color: var(--color-text-primary);
  border-color: var(--color-text-secondary);
}

.stat-value-group {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  margin-top: 4px;
  min-width: 0;
}

.stat-value {
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1.1;
  white-space: nowrap;
}

.stat-suffix {
  font-size: 12px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  line-height: 1.1;
}

.stat-footer-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-top: auto;
  padding-bottom: 0;
}

.text-xs {
  font-size: 12px;
}

.text-gray-400 {
  color: var(--color-text-tertiary);
}

.stat-percent-large {
  font-weight: 800;
  font-size: 15px;
  letter-spacing: -0.5px;
}

.stat-percent-large.normal {
  color: #27ae60;
}

.stat-percent-large.caution {
  color: #f1c40f;
}

.stat-percent-large.warning {
  color: #e67e22;
}

.stat-percent-large.critical {
  color: #e74c3c;
}

/* 移动端优化 */
@media (max-width: 768px) {
  .stat-card.storage-card.battery-card-style {
    min-height: 100px !important;
    overflow: hidden;
    padding: 0 !important; /* Reset padding to use stat-content padding */
  }

  .stat-content.relative-z {
    padding: 12px !important;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .stat-label {
    font-size: 11px;
    line-height: 1.2;
    margin-bottom: 4px;
  }

  .stat-value-group {
    display: flex;
    align-items: baseline;
    gap: 4px;
    margin-top: 2px;
    flex-wrap: nowrap; /* Keep on one line if possible */
  }

  .stat-value {
    font-size: 18px !important;
    font-weight: 700;
    line-height: 1;
    white-space: nowrap;
  }

  .stat-suffix {
    font-size: 11px;
    line-height: 1;
    opacity: 0.8;
    white-space: nowrap;
  }

  .stat-footer-row {
    margin-top: 8px !important;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }

  .stat-footer-row p {
    font-size: 10px;
    margin: 0;
    line-height: 1;
    color: var(--color-text-tertiary);
  }

  .stat-percent-large {
    font-size: 14px !important;
    font-weight: 800;
    line-height: 1;
  }
}

/* 超小屏幕优化 */
@media (max-width: 480px) {
  .stat-card.storage-card.battery-card-style {
    min-height: 90px !important;
  }

  .stat-content.relative-z {
    padding: 10px !important;
  }

  .stat-value {
    font-size: 16px !important;
  }

  .stat-suffix {
    font-size: 10px;
  }

  .stat-label {
    font-size: 10px;
  }
}
</style>
