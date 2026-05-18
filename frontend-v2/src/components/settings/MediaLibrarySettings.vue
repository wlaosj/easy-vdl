<template>
  <div class="media-library-settings">
    <div class="setting-group">
      <div class="group-title">
        <Icon name="monitor" :size="20" style="color: #6c5ce7" />
        媒体库同步设置
      </div>

      <!-- Brief Explanation -->
      <div class="sync-tip">
        <div class="tip-icon">
          <Icon name="info" :size="18" />
        </div>
        <div class="tip-content">
          <div class="tip-title">简要说明</div>
          <div class="tip-desc">
            <p class="tip-p">
              这里的“同步”指的是：当下载完成后，通知 Jellyfin/Emby 执行媒体库刷新（触发其扫描媒体目录），<b>不会</b>上传/搬运你的媒体文件。
            </p>
            <ul class="tip-list">
              <li><b>性能</b>：刷新可能带来磁盘 IO 峰值。系统已做节流：同一服务器默认 <b>90 秒</b> 内合并为一次刷新，避免频繁全库扫描。</li>
              <li><b>前提</b>：Jellyfin/Emby 必须已正确挂载/监控下载目录，否则刷新也不会入库。</li>
              <li><b>安全</b>：API Key 等同于高权限凭证，请勿泄露；建议仅内网访问或在反代层做鉴权/白名单。</li>
            </ul>
          </div>
        </div>
      </div>
      
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">媒体服务器同步</span>
          <p class="desc">下载任务完成后自动通知 Jellyfin/Emby 刷新媒体库</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.mediaServerEnabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>

      <template v-if="settingsStore.notificationSettings.mediaServerEnabled">
        <div class="setting-item">
          <div class="setting-label">
            <span class="title">服务器类型</span>
            <p class="desc">选择您的媒体服务器类型</p>
          </div>
          <div class="setting-control">
            <select v-model="settingsStore.notificationSettings.mediaServerType" class="form-select">
              <option value="jellyfin">Jellyfin</option>
              <option value="emby">Emby</option>
              <option value="auto">自动检测</option>
            </select>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">服务器地址</span>
            <p class="desc">媒体服务器的完整 URL，例如 https://jellyfin.local</p>
          </div>
          <div class="setting-control">
            <input 
              type="url" 
              v-model="settingsStore.notificationSettings.mediaServerUrl" 
              placeholder="https://your-server.com"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">API 密钥</span>
            <p class="desc">在服务器后台生成的有效 API Key</p>
          </div>
          <div class="setting-control">
            <input 
              type="password" 
              v-model="settingsStore.notificationSettings.mediaServerApiKey" 
              placeholder="输入 API 密钥"
              class="form-input"
              autocomplete="off"
              autocapitalize="off"
              autocorrect="off"
              spellcheck="false"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">连接测试</span>
            <p class="desc">验证服务器地址和 API 密钥是否有效</p>
          </div>
          <div class="setting-control horizontal">
            <button @click="testConnection" :disabled="testing" class="btn btn-outline">
              <Icon :name="testing ? 'refresh' : 'check'" :size="16" :class="{ 'spin': testing }" />
              {{ testing ? '测试中...' : '测试连接' }}
            </button>
            <button @click="saveSettings" :disabled="settingsStore.saving" class="btn btn-primary">
              <Icon name="check" :size="16" />
              {{ settingsStore.saving ? '保存中...' : '保存更改' }}
            </button>
          </div>
        </div>
      </template>

      <div class="setting-item" v-else>
        <div class="setting-label">
          <span class="title">保存设置</span>
        </div>
        <div class="setting-control">
          <button @click="saveSettings" :disabled="settingsStore.saving" class="btn btn-primary">
            <Icon name="check" :size="16" />
            {{ settingsStore.saving ? '保存中...' : '保存更改' }}
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
const testing = ref(false)

async function saveSettings() {
  const result = await settingsStore.saveNotificationSettings()
  if (result.success) {
    toast.success('媒体库同步设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

async function testConnection() {
  const { mediaServerUrl, mediaServerApiKey, mediaServerType } = settingsStore.notificationSettings
  
  if (!mediaServerUrl || !mediaServerApiKey) {
    toast.warning('请填写完整的服务器地址和 API 密钥')
    return
  }

  testing.value = true
  try {
    const response = await notificationsApi.testMediaServer(mediaServerUrl, mediaServerApiKey, mediaServerType)
    // client.js 拦截器已经解包了 response.data
    if (response.success) {
      toast.success(response.message || '连接测试成功')
    } else {
      toast.error(response.message || '连接测试失败')
    }
  } catch (err) {
    toast.error(`测试失败: ${err.message}`)
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  settingsStore.loadNotificationSettings()
})
</script>

<style scoped>

.media-library-settings {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.setting-group {
  background: var(--color-bg-secondary);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
}

.sync-tip {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 16px;
  margin: 4px 0 18px 0;
  border-radius: 12px;
  background: rgba(37, 99, 235, 0.08);
  border: 1px solid rgba(37, 99, 235, 0.22);
}

[data-theme="dark"] .sync-tip {
  background: rgba(37, 99, 235, 0.05);
  border-color: rgba(37, 99, 235, 0.18);
}

.tip-icon {
  color: var(--color-primary);
  padding-top: 2px;
}

.tip-content {
  flex: 1;
  min-width: 0;
}

.tip-title {
  font-weight: 700;
  font-size: 0.95rem;
  color: var(--color-primary);
  margin-bottom: 6px;
}

.tip-desc {
  color: var(--color-text-secondary);
  font-size: 0.85rem;
  line-height: 1.6;
}

.tip-p {
  margin: 0 0 8px 0;
}

.tip-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 6px;
}

.group-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-primary);
}

.setting-item {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 20px 0;
  border-top: 1px solid var(--color-border);
}

.setting-label {
  flex: 1;
  max-width: 300px;
}

.setting-label .title {
  display: block;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
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

.setting-control.horizontal {
  justify-content: space-between;
  align-items: center;
}

@media (max-width: 768px) {
  .setting-item {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
