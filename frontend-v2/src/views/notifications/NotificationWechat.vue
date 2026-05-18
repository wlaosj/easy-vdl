<template>
  <div class="notification-detail">
    <div class="detail-header">
      <div class="header-title">微信机器人通知</div>
      <p class="header-desc">配置企业微信群机器人 Webhook，实现任务通知推送。</p>
    </div>

    <div class="setting-group">
      <div class="group-title">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo wechat-logo">
          <rect width="24" height="24" rx="5" fill="#07C160"/>
          <path d="M7.5 8.5c-.83 0-1.5.67-1.5 1.5s.67 1.5 1.5 1.5 1.5-.67 1.5-1.5-.67-1.5-1.5-1.5zm9 0c-.83 0-1.5.67-1.5 1.5s.67 1.5 1.5 1.5 1.5-.67 1.5-1.5-.67-1.5-1.5-1.5z" fill="white"/>
          <path d="M12 2C6.48 2 2 6.48 2 12c0 1.54.36 2.98.97 4.29L1 23l6.71-1.97C9.02 21.64 10.46 22 12 22c5.52 0 10-4.48 10-10S17.52 2 12 2zm0 18c-1.33 0-2.57-.35-3.65-.96l-.42-.21-2.75.81.81-2.75-.21-.42C5.35 14.57 5 13.33 5 12c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7z" fill="white" opacity="0.95"/>
        </svg>
        微信机器人通知
      </div>
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用推送</span>
          <p class="desc">通过企业微信群机器人发送任务状态通知</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.wechatBotEnabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>

      <template v-if="settingsStore.notificationSettings.wechatBotEnabled">
        <div class="setting-item">
          <div class="setting-label">
            <span class="title">Webhook URL</span>
            <p class="desc">机器人的 Webhook 地址 (包含 key)</p>
          </div>
          <div class="setting-control vertical">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.wechatWebhookUrl"
              placeholder="https://qyapi.weixin.qq.com/..."
              class="form-input"
            />
            <div class="control-actions">
              <button @click="testWechatBot" :disabled="testingWechat" class="btn btn-outline">
                <Icon :name="testingWechat ? 'refresh' : 'check'" :size="16" :class="{ 'spin': testingWechat }" />
                {{ testingWechat ? '测试中...' : '测试发送' }}
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <div class="settings-actions">
      <div class="action-card">
        <div class="action-info">
          <span class="info-title">保存配置</span>
          <p class="info-desc">修改完成后请保存以生效</p>
        </div>
        <div class="action-buttons">
          <router-link class="btn btn-outline btn-lg" to="/settings?tab=notifications">
            <Icon name="chevron-left" :size="18" />
            返回通知设置
          </router-link>
          <button @click="saveSettings" :disabled="settingsStore.saving" class="btn btn-primary btn-lg">
            <Icon :name="settingsStore.saving ? 'refresh' : 'check'" :size="18" :class="{ 'spin': settingsStore.saving }" />
            {{ settingsStore.saving ? '保存中...' : '保存设置' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { notificationsApi } from '@/api/settings'
import Icon from '@/components/common/Icon.vue'

const settingsStore = useSettingsStore()
const toast = useToast()
const testingWechat = ref(false)

async function saveSettings() {
  const result = await settingsStore.saveNotificationSettings()
  if (result.success) {
    toast.success('通知设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

async function testWechatBot() {
  const { wechatWebhookUrl } = settingsStore.notificationSettings
  if (!wechatWebhookUrl) {
    toast.warning('请先填写 Webhook URL')
    return
  }
  testingWechat.value = true
  try {
    const response = await notificationsApi.testWechatBot(wechatWebhookUrl)
    if (response.success) {
      toast.success('测试消息已发出，请在微信群中确认')
    } else {
      toast.error(response.message || '测试失败')
    }
  } catch (err) {
    toast.error(`测试异常: ${err.message}`)
  } finally {
    testingWechat.value = false
  }
}

onMounted(() => {
  settingsStore.loadNotificationSettings()
})
</script>

<style scoped>
.notification-detail {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.header-title {
  font-size: 1.2rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.header-desc {
  color: var(--color-text-tertiary);
  font-size: 0.9rem;
}

.setting-group {
  background: var(--color-bg-secondary);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
}

.group-title {
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-primary);
}

.platform-logo {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
}

.wechat-logo {
  filter: drop-shadow(0 1px 2px rgba(7, 193, 96, 0.3));
}

.setting-item {
  display: flex;
  align-items: flex-start;
  gap: 24px;
  padding: 20px 0;
  border-top: 1px solid var(--color-border);
}

.setting-label {
  flex: 1;
  max-width: 280px;
}

.setting-label .title {
  display: block;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
  font-size: 0.95rem;
}

.setting-label .desc {
  font-size: 0.85rem;
  color: var(--color-text-tertiary);
  line-height: 1.4;
}

.setting-control {
  flex: 2;
  display: flex;
  gap: 12px;
}

.setting-control.vertical {
  flex-direction: column;
}

.setting-control.horizontal {
  align-items: center;
  justify-content: space-between;
}

.settings-actions {
  margin-top: 12px;
}

.action-card {
  background: var(--color-bg-secondary);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  align-items: center;
}

.action-info .info-title {
  display: block;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.action-info .info-desc {
  font-size: 0.9rem;
  color: var(--color-text-tertiary);
}

.btn-lg {
  padding: 12px 28px;
  font-size: 1rem;
  font-weight: 600;
  min-width: 160px;
}

@media (max-width: 768px) {
  .setting-group {
    padding: 16px;
    border-radius: 12px;
  }

  .setting-item {
    flex-direction: column;
    gap: 12px;
    padding: 16px 0;
  }

  .action-card {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
    padding: 16px;
    gap: 16px;
  }

  .action-buttons {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
    gap: 10px;
  }

  .btn-lg {
    width: 100%;
    padding: 10px 0;
  }
}
</style>
