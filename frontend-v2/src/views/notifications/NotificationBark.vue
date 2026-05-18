<template>
  <div class="notification-detail">
    <div class="detail-header">
      <div class="header-title">Bark 推送 (iOS)</div>
      <p class="header-desc">配置 Bark 设备 Key 与推送参数。</p>
    </div>

    <div class="setting-group">
      <div class="group-title">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo bark-logo">
          <rect width="24" height="24" rx="6" fill="#FF9F1A"/>
          <path d="M8.2 17.4V6.6h4.6c2.2 0 3.8 1.2 3.8 3.1 0 1.3-.7 2.2-1.8 2.7 1.3.4 2.2 1.5 2.2 3 0 2.1-1.7 3.5-4.1 3.5H8.2zm2.2-6.5h2.2c1.1 0 1.8-.6 1.8-1.5 0-.9-.7-1.5-1.8-1.5h-2.2v3zm0 4.8h2.5c1.2 0 2-.6 2-1.6 0-1-.8-1.6-2-1.6h-2.5v3.2z" fill="white"/>
        </svg>
        Bark 推送 (iOS)
      </div>
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用推送</span>
          <p class="desc">通过 Bark App 推送到 iPhone/iPad</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.barkEnabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>

      <template v-if="settingsStore.notificationSettings.barkEnabled">
        <div class="setting-item">
          <div class="setting-label">
            <span class="title">服务器地址</span>
            <p class="desc">默认官方服务器，可填写自建 Bark 服务</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.barkServerUrl"
              placeholder="https://api.day.app"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">设备 Key</span>
            <p class="desc">Bark App 中生成的设备 Key</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.barkDeviceKey"
              placeholder="你的设备 Key"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">通知声音 (可选)</span>
            <p class="desc">如: default / alarm / bell / chime</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.barkSound"
              placeholder="default"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">分组 (可选)</span>
            <p class="desc">同组通知可在 Bark 内聚合</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.barkGroup"
              placeholder="easy-vdl"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">图标 (可选)</span>
            <p class="desc">通知图标 URL</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.barkIcon"
              placeholder="https://example.com/icon.png"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">点击跳转 (可选)</span>
            <p class="desc">通知点击后打开的链接</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.barkUrl"
              placeholder="https://example.com"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">自动复制内容</span>
            <p class="desc">通知到达时自动复制消息文本</p>
          </div>
          <div class="setting-control horizontal">
            <label class="switch">
              <input type="checkbox" v-model="settingsStore.notificationSettings.barkAutomaticallyCopy" />
              <span class="switch-slider"></span>
            </label>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">发送测试</span>
            <p class="desc">验证 Bark 配置是否正确</p>
          </div>
          <div class="setting-control vertical">
            <div class="control-actions">
              <button @click="testBark" :disabled="testingBark" class="btn btn-outline">
                <Icon :name="testingBark ? 'refresh' : 'check'" :size="16" :class="{ 'spin': testingBark }" />
                {{ testingBark ? '测试中...' : '测试发送' }}
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
const testingBark = ref(false)

async function saveSettings() {
  const result = await settingsStore.saveNotificationSettings()
  if (result.success) {
    toast.success('通知设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

async function testBark() {
  const {
    barkServerUrl,
    barkDeviceKey,
    barkSound,
    barkGroup,
    barkIcon,
    barkUrl,
    barkAutomaticallyCopy
  } = settingsStore.notificationSettings

  if (!barkDeviceKey) {
    toast.warning('请先填写设备 Key')
    return
  }

  testingBark.value = true
  try {
    const response = await notificationsApi.testBark({
      device_key: barkDeviceKey,
      server_url: barkServerUrl,
      sound: barkSound || null,
      group: barkGroup || null,
      icon: barkIcon || null,
      url: barkUrl || null,
      automatically_copy: barkAutomaticallyCopy ? 'true' : 'false',
      title: '🧪 Bark 测试消息',
      message: 'Easy-VDL: 这是一条测试通知'
    })
    if (response.success) {
      toast.success('测试消息已发出，请在 Bark 中确认')
    } else {
      toast.error(response.message || '测试失败')
    }
  } catch (err) {
    toast.error(`测试异常: ${err.message}`)
  } finally {
    testingBark.value = false
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

.bark-logo {
  filter: drop-shadow(0 1px 2px rgba(255, 159, 26, 0.35));
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
