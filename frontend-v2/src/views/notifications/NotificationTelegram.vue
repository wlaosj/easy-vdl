<template>
  <div class="notification-detail">
    <div class="detail-header">
      <div class="header-title">Telegram 机器人 (高级) <span class="lifetime-badge">LIFETIME</span></div>
      <p class="header-desc">配置 Bot Token、Chat ID 白名单与代理设置。</p>
    </div>

    <div class="setting-group">
      <div class="group-title group-title-with-action">
        <div class="group-title-main">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo telegram-logo">
            <circle cx="12" cy="12" r="10" fill="#2AABEE"/>
            <path d="M17.3 7.85l-2.07 9.8c-.15.68-.5.85-.92.53l-2.73-1.87-1.32 1.34c-.15.15-.27.27-.56.27l.2-2.78 4.98-4.5c.22-.2-.05-.31-.33-.11l-6.16 3.88-2.69-.87c-.58-.18-.59-.58.12-.86l10.5-4.05c.49-.18.91.11.78.69z" fill="white"/>
          </svg>
          Telegram 机器人 (高级)
          <span class="lifetime-badge">LIFETIME</span>
        </div>
        <router-link class="btn btn-outline btn-sm" to="/settings/telegram-bot-guide">
          功能介绍
        </router-link>
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

      <template v-if="settingsStore.notificationSettings.telegramBotEnabled">
        <div class="setting-item">
          <div class="setting-label">
            <span class="title">Bot Token</span>
            <p class="desc">从 @BotFather 获取的令牌</p>
          </div>
          <div class="setting-control">
            <input
              type="password"
              v-model="settingsStore.notificationSettings.telegramBotToken"
              placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
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
            <span class="title">允许的 Chat ID</span>
            <p class="desc">白名单 ID，多个用逗号分隔</p>
            <p class="desc">获取方式：向当前 Bot 发送 <code>/id</code></p>
          </div>
          <div class="setting-control">
             <input
              type="text"
              v-model="settingsStore.notificationSettings.telegramChatId"
              placeholder="12345678, 87654321"
              class="form-input"
            />
            <p class="field-hint">提示：请先在 Telegram 私聊一次 Bot，否则部分通知可能无法送达。</p>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">转存并发数</span>
            <p class="desc">同时进行的 Bot 媒体转存任务数（1-10，默认 5）</p>
          </div>
          <div class="setting-control">
            <input
              type="number"
              min="1"
              max="10"
              step="1"
              v-model.number="settingsStore.notificationSettings.telegramMediaMaxConcurrent"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item date-subdir-item">
          <div class="setting-label">
            <span class="title">按日期分目录</span>
            <p class="desc">开启后路径为 /app/downloads/telegram-inbox/&lt;chat_id&gt;/YYYYMMDD/</p>
            <p class="desc">关闭后路径为 /app/downloads/telegram-inbox/&lt;chat_id&gt;/</p>
          </div>
          <div class="setting-control horizontal">
            <label class="switch">
              <input type="checkbox" v-model="settingsStore.notificationSettings.telegramMediaUseDateSubdir" />
              <span class="switch-slider"></span>
            </label>
          </div>
        </div>

        <div class="setting-item media-transfer-item">
          <div class="setting-label">
            <span class="title">媒体转存说明（LIFETIME）</span>
            <p class="desc">仅【LIFETIME（永久高级授权）】且白名单 Chat ID 可用。</p>
            <p class="desc">向 Bot 发送视频/图片即可转存本地（不进入下载列表）。</p>
            <p class="desc">路径：/app/downloads/telegram-inbox/&lt;chat_id&gt;/(可选日期子目录) · 单个文件上限约（2GB）。</p>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">HTTP 代理 (可选)</span>
            <p class="desc">国内环境需要配置代理 (如 http://10.0.0.5:7890)</p>
          </div>
          <div class="setting-control vertical">
             <input
              type="text"
              v-model="settingsStore.notificationSettings.telegramProxy"
              placeholder="http://127.0.0.1:7890"
              class="form-input"
            />
            <div class="control-actions">
              <button @click="testTelegramBot" :disabled="testingTelegram" class="btn btn-outline">
                <Icon :name="testingTelegram ? 'refresh' : 'check'" :size="16" :class="{ 'spin': testingTelegram }" />
                {{ testingTelegram ? '测试中...' : '测试连接' }}
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
const testingTelegram = ref(false)

async function saveSettings() {
  const result = await settingsStore.saveNotificationSettings()
  if (result.success) {
    toast.success('通知设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

async function testTelegramBot() {
  const { telegramBotToken, telegramChatId, telegramProxy } = settingsStore.notificationSettings
  if (!telegramBotToken || !telegramChatId) {
    toast.warning('请先填写 Token 和 Chat ID')
    return
  }
  testingTelegram.value = true
  try {
    const response = await notificationsApi.testTelegramBot(telegramBotToken, telegramChatId, telegramProxy)
    if (response.success) {
      toast.success('测试消息已发出，请在 TG 确认')
    } else {
      toast.error(response.message || '测试失败')
    }
  } catch (err) {
    toast.error(`测试异常: ${err.message}`)
  } finally {
    testingTelegram.value = false
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
  display: flex;
  align-items: center;
  gap: 8px;
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

.group-title-with-action {
  justify-content: space-between;
}

.group-title-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.lifetime-badge {
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

.telegram-logo {
  filter: drop-shadow(0 1px 2px rgba(42, 171, 238, 0.3));
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
  max-width: 320px;
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

.field-hint {
  margin: 6px 0 0;
  font-size: 0.82rem;
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

.media-transfer-item {
  display: block;
}

.media-transfer-item .setting-label {
  max-width: none;
}

.date-subdir-item .setting-label {
  max-width: 560px;
}

@media (min-width: 769px) {
  .date-subdir-item .setting-label .desc {
    white-space: nowrap;
  }
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
