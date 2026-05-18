<template>
  <div class="notification-detail">
    <div class="detail-header">
      <div class="header-title">Server酱³ 推送</div>
      <p class="header-desc">配置 Server酱³ (方糖) 的 UID 与 SendKey。</p>
    </div>

    <div class="setting-group">
      <div class="group-title">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo serverchan-logo">
          <circle cx="12" cy="12" r="10" fill="#FF6B35"/>
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z" fill="white"/>
          <path d="M9 12l2 2 4-4" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        </svg>
        Server酱³ 推送
      </div>
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用推送</span>
          <p class="desc">通过 Server酱³ (方糖) 发送微信通知</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.serverChan3Enabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>

      <template v-if="settingsStore.notificationSettings.serverChan3Enabled">
        <div class="setting-item">
          <div class="setting-label">
            <span class="title">UID</span>
            <p class="desc">Server酱³ 用户的 UID</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.serverChan3Uid"
              placeholder="方糖 UID"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">SendKey</span>
            <p class="desc">Server酱³ 的应用 SendKey</p>
          </div>
          <div class="setting-control vertical">
            <input
              type="password"
              v-model="settingsStore.notificationSettings.serverChan3Sendkey"
              placeholder="方糖 SendKey"
              class="form-input"
              autocomplete="off"
              autocapitalize="off"
              autocorrect="off"
              spellcheck="false"
            />
            <div class="control-actions">
              <button @click="testServerChan" :disabled="testingServer" class="btn btn-outline">
                <Icon :name="testingServer ? 'refresh' : 'check'" :size="16" :class="{ 'spin': testingServer }" />
                {{ testingServer ? '测试中...' : '测试发送' }}
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
const testingServer = ref(false)

async function saveSettings() {
  const result = await settingsStore.saveNotificationSettings()
  if (result.success) {
    toast.success('通知设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

async function testServerChan() {
  const { serverChan3Uid, serverChan3Sendkey } = settingsStore.notificationSettings
  if (!serverChan3Uid || !serverChan3Sendkey) {
    toast.warning('请先填写 UID 和 SendKey')
    return
  }
  testingServer.value = true
  try {
    const response = await notificationsApi.testServerChan3(serverChan3Uid, serverChan3Sendkey)
    if (response.success) {
      toast.success('测试消息已发出，请在 Server酱³ 中确认')
    } else {
      toast.error(response.message || '测试失败')
    }
  } catch (err) {
    toast.error(`测试异常: ${err.message}`)
  } finally {
    testingServer.value = false
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

.serverchan-logo {
  filter: drop-shadow(0 1px 2px rgba(255, 107, 53, 0.3));
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
