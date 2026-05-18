<template>
  <div class="download-settings">
    <div class="setting-group">
      <div class="group-title">下载设置</div>
      
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">系统全局并发上限</span>
          <p class="desc">控制整个系统同时运行的下载任务总数（范围：1-15）。所有播主的下载任务都共享此限制，建议根据网络带宽和服务器性能调整</p>
        </div>
        <div class="setting-control">
          <input 
            v-if="!isLoading"
            type="number" 
            v-model.number="settingsStore.downloadSettings.maxConcurrentDownloads" 
            placeholder="10"
            class="form-input"
            min="1"
            max="15"
            @blur="validateConcurrentDownloads"
          />
          <div v-else class="form-input loading-placeholder">
            <span class="loading-text">加载中...</span>
          </div>
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">当前设置</span>
          <p class="desc">当前系统全局并发上限：<strong v-if="!isLoading">{{ settingsStore.downloadSettings.maxConcurrentDownloads }}</strong><span v-else class="loading-text">加载中...</span></p>
        </div>
        <div class="setting-control action-buttons">
          <button @click="saveSettings" :disabled="settingsStore.saving" class="btn btn-primary">
            <Icon name="check" :size="16" />
            {{ settingsStore.saving ? '保存中...' : '保存设置' }}
          </button>
          <button @click="resetToDefault" class="btn btn-outline">
            <Icon name="refresh-cw" :size="16" />
            恢复默认值
          </button>
        </div>
      </div>

      <!-- 提示信息 -->
      <div class="info-notice">
        <div class="notice-icon">
          <Icon name="info" :size="20" />
        </div>
        <div class="notice-content">
          <span class="notice-title">配置说明</span>
          <ul class="notice-desc">
            <li><strong>全局并发上限</strong>：控制整个系统同时运行的下载任务总数，所有播主的任务都受此限制</li>
            <li><strong>与批次设置的区别</strong>：视频列表页面的"并发"设置（1-5）是批次大小，用于控制单个播主的批次处理节奏；本设置是系统级全局上限（1-15）</li>
            <li><strong>建议值</strong>：普通网络 3-5，高速网络 5-10，最高不建议超过 15</li>
            <li><strong>风控警告</strong>：⚠️ 高并发可能会触发平台的风控机制，导致IP被封禁或账号受限，建议根据实际情况谨慎调整</li>
            <li><strong>注意事项</strong>：并发数过高可能导致网络拥塞或服务器资源不足；过低会降低下载效率</li>
            <li>修改后立即生效，无需重启服务</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- 恢复默认值确认弹窗 -->
    <Modal 
      v-model:show="showResetModal"
      title="恢复默认值"
      type="warning"
      width="450px"
      :show-confirm="false"
    >
      <div style="font-size: 15px; padding: 10px 0;">
        确定要恢复默认值（<strong>10</strong>）吗？
      </div>
      <template #footer>
        <button class="btn btn-secondary" @click="showResetModal = false">取消</button>
        <button class="btn btn-primary" @click="handleResetConfirm" style="margin-left: 12px;">确定</button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'

const settingsStore = useSettingsStore()
const toast = useToast()
const showResetModal = ref(false)
const isLoading = ref(true)

// 验证并发数范围
function validateConcurrentDownloads() {
  const value = settingsStore.downloadSettings.maxConcurrentDownloads
  // 如果值为空、NaN或无效，设置为默认值10
  if (value === null || value === undefined || isNaN(value) || value === '') {
    settingsStore.downloadSettings.maxConcurrentDownloads = 10
  } else if (value < 1) {
    settingsStore.downloadSettings.maxConcurrentDownloads = 1
  } else if (value > 15) {
    settingsStore.downloadSettings.maxConcurrentDownloads = 15
  }
}

// 保存设置
async function saveSettings() {
  const value = settingsStore.downloadSettings.maxConcurrentDownloads
  // 验证值是否有效
  if (value === null || value === undefined || isNaN(value) || value === '') {
    toast.error('请输入有效的并发数')
    settingsStore.downloadSettings.maxConcurrentDownloads = 10
    return
  }
  if (value < 1 || value > 15) {
    toast.error('系统全局并发上限必须在1-15之间')
    return
  }
  
  const result = await settingsStore.saveDownloadSettings()
  if (result.success) {
    toast.success(`系统全局并发上限已设置为 ${value}`)
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 恢复默认值
function resetToDefault() {
  showResetModal.value = true
}

// 确认恢复默认值
async function handleResetConfirm() {
  showResetModal.value = false
  settingsStore.downloadSettings.maxConcurrentDownloads = 10
  await saveSettings()
}

// 加载设置
onMounted(async () => {
  isLoading.value = true
  await settingsStore.loadDownloadSettings()
  isLoading.value = false
})
</script>

<style scoped>
.download-settings {
  width: 100%;
}

.setting-group {
  margin-bottom: 32px;
}

.group-title {
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--color-primary);
  margin-bottom: 24px;
}

.setting-item {
  display: grid;
  grid-template-columns: minmax(240px, 320px) 1fr;
  gap: 48px;
  padding: 24px 0;
  border-bottom: 1px solid var(--color-border);
  align-items: flex-start;
}

.setting-item:last-child {
  border-bottom: none;
}

.setting-label .title {
  display: block;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 6px;
}

.setting-label .desc {
  font-size: 13px;
  color: var(--color-text-tertiary);
  line-height: 1.6;
}

.setting-label .desc strong {
  color: var(--color-text-primary);
  font-weight: 600;
}

.setting-control {
  display: flex;
  gap: 12px;
  justify-content: flex-start;
  padding-top: 4px;
}

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.btn {
  white-space: nowrap;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-input {
  width: 120px;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 14px;
  background: var(--color-bg);
  color: var(--color-text-primary);
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.1);
}

.info-notice {
  display: flex;
  gap: 16px;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 12px;
  padding: 16px 20px;
  margin-top: 32px;
  align-items: flex-start;
}

[data-theme="dark"] .info-notice {
  background: rgba(59, 130, 246, 0.05);
  border-color: rgba(59, 130, 246, 0.2);
}

.notice-icon {
  color: #3b82f6;
  display: flex;
  padding-top: 2px;
}

.notice-content {
  flex: 1;
}

.notice-title {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #3b82f6;
  margin-bottom: 8px;
}

.notice-desc {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.8;
  margin: 0;
  padding-left: 20px;
}

.notice-desc li {
  margin-bottom: 4px;
}

.notice-desc li:last-child {
  margin-bottom: 0;
}

.loading-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  background: var(--color-bg);
  color: var(--color-text-tertiary);
}

.loading-text {
  font-size: 14px;
  color: var(--color-text-tertiary);
  font-style: italic;
}
</style>
