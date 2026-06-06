<template>
  <div class="notification-settings">
    <!-- WeChat Bot Overview -->
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
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">详细配置</span>
          <p class="desc">Webhook 地址、测试发送等</p>
        </div>
        <div class="setting-control horizontal">
          <router-link class="btn btn-outline" to="/settings/notifications/wechat">进入配置</router-link>
        </div>
      </div>
    </div>

    <!-- ServerChan Overview -->
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
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">详细配置</span>
          <p class="desc">UID、SendKey、测试发送</p>
        </div>
        <div class="setting-control horizontal">
          <router-link class="btn btn-outline" to="/settings/notifications/serverchan">进入配置</router-link>
        </div>
      </div>
    </div>

    <!-- Bark Overview -->
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
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">详细配置</span>
          <p class="desc">服务器、设备 Key、声音、分组等</p>
        </div>
        <div class="setting-control horizontal">
          <router-link class="btn btn-outline" to="/settings/notifications/bark">进入配置</router-link>
        </div>
      </div>
    </div>

    <!-- Telegram Overview -->
    <div class="setting-group">
      <div class="group-title">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo telegram-logo">
          <circle cx="12" cy="12" r="10" fill="#2AABEE"/>
          <path d="M17.3 7.85l-2.07 9.8c-.15.68-.5.85-.92.53l-2.73-1.87-1.32 1.34c-.15.15-.27.27-.56.27l.2-2.78 4.98-4.5c.22-.2-.05-.31-.33-.11l-6.16 3.88-2.69-.87c-.58-.18-.59-.58.12-.86l10.5-4.05c.49-.18.91.11.78.69z" fill="white"/>
        </svg>
        Telegram 机器人 (高级)
        <span class="lifetime-badge">LIFETIME</span>
      </div>
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用全能管家</span>
          <p class="desc">支持远程下载指令、状态查询和实时推送</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.telegramBotEnabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">详细配置</span>
          <p class="desc">Token、Chat ID、代理与高级功能（媒体转存为 LIFETIME 专属）</p>
        </div>
        <div class="setting-control horizontal">
          <router-link class="btn btn-outline" to="/settings/notifications/telegram">进入配置</router-link>
        </div>
      </div>
    </div>

    <!-- 企业微信应用Bot Overview -->
    <div class="setting-group">
      <div class="group-title">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo wecom-logo">
          <rect width="24" height="24" rx="6" fill="#07C160"/>
          <path d="M12 5C8.13 5 5 7.69 5 11c0 1.84 1.08 3.47 2.76 4.57L7 18l3.08-1.54c.88.22 1.81.34 2.77.34 3.58 0 6.5-2.46 6.5-5.5S15.43 5 12 5z" fill="white"/>
        </svg>
        企业微信应用Bot
      </div>
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用应用Bot</span>
          <p class="desc">支持消息推送、菜单交互和指令查询</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.wecomBotEnabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">详细配置</span>
          <p class="desc">企业ID、AgentId、Secret、回调设置</p>
        </div>
        <div class="setting-control horizontal">
          <router-link class="btn btn-outline" to="/settings/notifications/wecom">进入配置</router-link>
        </div>
      </div>
    </div>

    <!-- Notification Types (Left) -->
    <div class="setting-group combined-group combined-left">
      <div class="group-title">
        <Icon name="notifications" :size="20" style="color: var(--color-primary)" />
        选择通知场景
      </div>
      
      <div class="checkbox-grid">
        <label class="checkbox-item">
          <input type="checkbox" v-model="settingsStore.notificationSettings.downloadCompleted" />
          <span class="checkbox-label">下载完成时</span>
        </label>
        <label class="checkbox-item">
          <input type="checkbox" v-model="settingsStore.notificationSettings.downloadError" />
          <span class="checkbox-label">下载发生错误时</span>
        </label>
        <label class="checkbox-item">
          <input type="checkbox" v-model="settingsStore.notificationSettings.subscriptionCheckFailed" />
          <span class="checkbox-label">订阅检查失败时</span>
        </label>
        <label class="checkbox-item">
          <input type="checkbox" v-model="settingsStore.notificationSettings.subscriptionCheckNewVideos" />
          <span class="checkbox-label">订阅发现新视频时</span>
        </label>
        <label class="checkbox-item">
          <input type="checkbox" v-model="settingsStore.notificationSettings.subscriptionCheckNoNewVideos" />
          <span class="checkbox-label">订阅未发现新视频时</span>
        </label>
        <label class="checkbox-item">
          <input type="checkbox" v-model="settingsStore.notificationSettings.systemStatusEnabled" />
          <span class="checkbox-label">系统公告/状态更新时</span>
        </label>
      </div>
    </div>

    <!-- Quiet Hours (Right) -->
    <div class="setting-group combined-group combined-right">
      <div class="group-title">
        <Icon name="clock" :size="20" style="color: #2f3542" />
        静音时间 (勿扰模式)
      </div>
      
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用勿扰</span>
          <p class="desc">在指定时间段内不发送任何推送消息</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.quietHoursEnabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>

      <template v-if="settingsStore.notificationSettings.quietHoursEnabled">
        <div class="setting-item border-top-none">
          <div class="setting-label">
            <span class="title">时间范围</span>
            <p class="desc">设置开始和结束的时间</p>
          </div>
          <div class="setting-control horizontal">
             <div class="time-inputs">
               <input type="time" v-model="settingsStore.notificationSettings.quietHoursStart" class="form-input" />
               <span class="divider">至</span>
               <input type="time" v-model="settingsStore.notificationSettings.quietHoursEnd" class="form-input" />
             </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 全局保存按钮容器 -->
    <div class="settings-actions">
      <div class="action-card">
        <div class="action-info">
          <span class="info-title">保存全部配置</span>
          <p class="info-desc">以上所有推送平台和场景的修改需点击此按钮方可生效</p>
        </div>
        <button @click="saveSettings" :disabled="settingsStore.saving" class="btn btn-primary btn-lg">
          <Icon :name="settingsStore.saving ? 'refresh' : 'check'" :size="18" :class="{ 'spin': settingsStore.saving }" />
          {{ settingsStore.saving ? '保存中...' : '保存全部通知设置' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import Icon from '@/components/common/Icon.vue'

const settingsStore = useSettingsStore()
const toast = useToast()

async function saveSettings() {
  const result = await settingsStore.saveNotificationSettings()
  if (result.success) {
    toast.success('通知设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

onMounted(() => {
  settingsStore.loadNotificationSettings()
})
</script>

<style scoped>
.notification-settings {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.setting-group {
  background: var(--color-bg-secondary);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
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

.lifetime-badge {
  margin-left: 2px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  line-height: 1.3;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: #7a4a00;
  background: linear-gradient(135deg, #ffe29a, #ffc04d);
  border: 1px solid rgba(255, 183, 60, 0.7);
  box-shadow: 0 2px 6px rgba(255, 183, 60, 0.25);
}

.platform-logo {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
}

.wechat-logo {
  filter: drop-shadow(0 1px 2px rgba(7, 193, 96, 0.3));
}

.serverchan-logo {
  filter: drop-shadow(0 1px 2px rgba(255, 107, 53, 0.3));
}

.bark-logo {
  filter: drop-shadow(0 1px 2px rgba(255, 159, 26, 0.35));
}

.telegram-logo {
  filter: drop-shadow(0 1px 2px rgba(42, 171, 238, 0.3));
}

.checkbox-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  padding: 8px 0;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  padding: 12px 16px;
  border-radius: 12px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  transition: all 0.2s ease;
}

.checkbox-item:hover {
  border-color: var(--color-primary);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.checkbox-label {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--color-text-primary);
  user-select: none;
}

.checkbox-item input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-border);
  border-radius: 6px;
  background-color: white;
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s;
}

.checkbox-item input[type="checkbox"]:focus {
  box-shadow: 0 0 0 3px var(--color-primary-light);
  border-color: var(--color-primary);
}

.checkbox-item input[type="checkbox"]:checked {
  background-color: var(--color-primary);
  border-color: var(--color-primary);
}

.checkbox-item input[type="checkbox"]:checked::after {
  content: '';
  position: absolute;
  left: 6px;
  top: 2px;
  width: 5px;
  height: 10px;
  border: solid white;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
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
  min-width: 0;
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
  flex: 1;
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.setting-control.horizontal {
  align-items: center;
  justify-content: space-between;
}

.time-inputs {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
}

.time-inputs .form-input {
  min-width: 120px;
}

.time-inputs .divider {
  color: var(--color-text-tertiary);
  font-size: 0.9rem;
}

.combined-group {
  display: flex;
  flex-direction: column;
}

.combined-left {
  grid-column: span 1;
}

.combined-right {
  grid-column: span 1;
}

.border-top-none {
  border-top: none !important;
  padding-top: 0 !important;
}

.settings-actions {
  grid-column: span 2;
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

.action-info .info-title {
  display: block;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.action-info .info-desc {
  font-size: 0.9rem;
  color: var(--color-text-tertiary);
}

.btn-lg {
  padding: 12px 32px;
  font-size: 1rem;
  font-weight: 600;
  min-width: 200px;
}

@media (max-width: 1280px) {
  .notification-settings {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  
  .settings-actions {
    grid-column: span 1;
  }

  .setting-group {
    padding: 20px;
  }
}

@media (max-width: 768px) {
  .notification-settings {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .setting-group {
    padding: 16px;
    border-radius: 12px;
  }

  .group-title {
    margin-bottom: 16px;
    font-size: 1rem;
  }

  .action-card {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
    padding: 16px;
    gap: 16px;
  }

  .btn-lg {
    width: 100%;
    padding: 10px 0;
  }

  .setting-item {
    flex-direction: column;
    gap: 12px;
    padding: 16px 0;
  }

  .checkbox-grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .checkbox-item {
    padding: 10px 12px;
  }
}
</style>
