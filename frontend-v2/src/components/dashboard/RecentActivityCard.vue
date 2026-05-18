<template>
  <div class="card activity-card mobile-hidden">
    <div class="activity-list">
      <div class="activity-item" v-for="item in activities" :key="item.id">
        <div class="activity-icon" :class="item.type">
          <Icon :name="getActivityIcon(item.type)" :size="16" />
        </div>
        <div class="activity-content">
          <div class="activity-main-info">
            <img v-if="getThumbnail(item)" :src="getThumbnail(item)" class="activity-thumb" />
            <div class="activity-text">
              <span class="activity-filename">{{ item.filename }}</span>
              <span class="activity-user" v-if="item.user">{{ item.action }} by user: {{ item.user }}</span>
              <span class="activity-user" v-else>{{ item.action }}</span>
            </div>
          </div>
        </div>
        <span class="activity-time">{{ item.time }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import Icon from '../common/Icon.vue'

const props = defineProps({
  activities: {
    type: Array,
    default: () => []
  },
  thumbnailCache: {
    type: Object,
    default: () => ({})
  }
})

function getActivityIcon(type) {
  const map = {
    download: 'download',
    subscription: 'refresh',
    system: 'settings',
    delete: 'trash'
  }
  return map[type] || 'activity'
}

function getThumbnail(item) {
  return props.thumbnailCache[item.id] || null
}
</script>

<style scoped>
.activity-card {
  padding: 16px;
}

.activity-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 5px;
}

.activity-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px;
  border-radius: var(--radius-md);
  transition: background-color 0.2s;
}

.activity-item:hover {
  background: var(--color-bg-hover);
}

.activity-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--color-bg-tertiary);
}

.activity-icon.download {
  color: #3498db;
}

.activity-icon.subscription {
  color: #27ae60;
}

.activity-icon.system {
  color: #e67e22;
}

.activity-icon.delete {
  color: #e74c3c;
}

.activity-content {
  flex: 1;
  min-width: 0;
}

.activity-main-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.activity-thumb {
  width: 40px;
  height: 40px;
  border-radius: 4px;
  object-fit: cover;
  flex-shrink: 0;
}

.activity-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.activity-filename {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-user {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.activity-time {
  font-size: 11px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  flex-shrink: 0;
}

.mobile-hidden {
  display: block;
}

@media (max-width: 768px) {
  .mobile-hidden {
    display: none;
  }
}
</style>