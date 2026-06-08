<template>
  <div class="notification-detail">
    <div class="detail-header">
      <div class="header-title">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo wecom-logo">
          <rect width="24" height="24" rx="6" fill="#07C160"/>
          <path d="M12 5C8.13 5 5 7.69 5 11c0 1.84 1.08 3.47 2.76 4.57L7 18l3.08-1.54c.88.22 1.81.34 2.77.34 3.58 0 6.5-2.46 6.5-5.5S15.43 5 12 5z" fill="white"/>
        </svg>
        企业微信应用Bot
      </div>
      <p class="header-desc">配置企业微信自建应用，支持消息推送、菜单交互和指令查询。</p>
    </div>

    <div class="setting-group">
      <div class="group-title">
        <div class="group-title-main">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="platform-logo wecom-logo">
            <rect width="24" height="24" rx="6" fill="#07C160"/>
            <path d="M12 5C8.13 5 5 7.69 5 11c0 1.84 1.08 3.47 2.76 4.57L7 18l3.08-1.54c.88.22 1.81.34 2.77.34 3.58 0 6.5-2.46 6.5-5.5S15.43 5 12 5z" fill="white"/>
          </svg>
          企业微信应用Bot
        </div>
      </div>

      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用企业微信Bot</span>
          <p class="desc">开启后支持消息推送和交互指令</p>
        </div>
        <div class="setting-control horizontal">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.notificationSettings.wecomBotEnabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>

      <template v-if="settingsStore.notificationSettings.wecomBotEnabled">
        <div class="setting-item">
          <div class="setting-label">
            <span class="title">企业ID (Corp ID)</span>
            <p class="desc">企业微信管理后台 → 我的企业 → 企业信息</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.wecomCorpId"
              placeholder="ww1234567890abcdef"
              class="form-input"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">AgentId</span>
            <p class="desc">自建应用的 AgentId</p>
          </div>
          <div class="setting-control">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.wecomAgentId"
              placeholder="1000002"
              class="form-input"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">应用 Secret</span>
            <p class="desc">自建应用的 Secret</p>
          </div>
          <div class="setting-control">
            <input
              type="password"
              v-model="settingsStore.notificationSettings.wecomSecret"
              placeholder="应用Secret"
              class="form-input"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">回调 Token</span>
            <p class="desc">接收消息 API 设置中获取的 Token</p>
          </div>
          <div class="setting-control">
            <input
              type="password"
              v-model="settingsStore.notificationSettings.wecomCallbackToken"
              placeholder="回调Token"
              class="form-input"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">回调 EncodingAESKey</span>
            <p class="desc">接收消息 API 设置中获取的 AES Key</p>
          </div>
          <div class="setting-control">
            <input
              type="password"
              v-model="settingsStore.notificationSettings.wecomCallbackAesKey"
              placeholder="回调AESKey"
              class="form-input"
              autocomplete="off"
              spellcheck="false"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">回调 URL</span>
            <p class="desc">填入企业微信后台「接收消息」的 URL</p>
            <p class="desc">EDL 回调端口默认为 <code>8001</code></p>
          </div>
          <div class="setting-control vertical">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.wecomCallbackUrl"
              placeholder="http://你的公网IP:8001/api/wecom/callback"
              class="form-input"
            />
            <div class="callback-help">
              <p class="field-hint"><strong>有公网 IP：</strong><code>http://你的公网IP:8001/api/wecom/callback</code></p>
              <p class="field-hint"><strong>无公网 IP（frp 穿透）：</strong><code>http://VPS的IP或域名:8001/api/wecom/callback</code></p>
              <p class="field-hint">填写后到企业微信后台「接收消息」→ 填入此 URL → 点击保存验证。</p>
            </div>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">API 代理地址（可选）</span>
            <p class="desc">企业微信 API 出口代理，解决本地 IP 不在白名单的问题</p>
          </div>
          <div class="setting-control vertical">
            <input
              type="text"
              v-model="settingsStore.notificationSettings.wecomApiProxy"
              placeholder="http://user:pass@your-vps-ip:3128"
              class="form-input"
            />
            <div class="callback-help">
              <p class="field-hint"><strong>有公网 IP：</strong>不填，直接把公网 IP 加到企业微信可信 IP 白名单即可。</p>
              <p class="field-hint"><strong>无公网 IP：</strong>在 VPS 上开一个 HTTP 代理（如 Squid，务必设置用户名密码认证防扫描），填 <code>http://用户名:密码@VPS_IP:代理端口</code>，然后把 VPS IP 加到白名单。</p>
              <p class="field-hint">不填则 EDL 直连企业微信 API，需要 EDL 出口 IP 在白名单中。</p>
            </div>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">测试连接</span>
            <p class="desc">验证企业ID/AgentId/Secret 是否正确</p>
          </div>
          <div class="setting-control vertical">
            <div class="control-actions">
              <button @click="testWecomBot" :disabled="testingWecom" class="btn btn-outline">
                <Icon :name="testingWecom ? 'refresh' : 'check'" :size="16" :class="{ 'spin': testingWecom }" />
                {{ testingWecom ? '测试中...' : '测试连接' }}
              </button>
            </div>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">无公网 IP？</span>
            <p class="desc">使用 frp + Squid（带密码认证）搭建 VPS 中继</p>
          </div>
          <div class="setting-control">
            <router-link class="btn btn-outline" to="/settings/notifications/wecom/tutorial">
              查看搭建教程 →
            </router-link>
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
const testingWecom = ref(false)

async function saveSettings() {
  const result = await settingsStore.saveNotificationSettings()
  if (result.success) {
    toast.success('通知设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

async function testWecomBot() {
  const { wecomCorpId, wecomAgentId, wecomSecret, wecomApiProxy } = settingsStore.notificationSettings
  if (!wecomCorpId || !wecomAgentId || !wecomSecret) {
    toast.warning('请先填写企业ID、AgentId 和 Secret')
    return
  }
  testingWecom.value = true
  try {
    const response = await notificationsApi.testWecomBot(wecomCorpId, wecomAgentId, wecomSecret, wecomApiProxy)
    if (response.success) {
      toast.success('测试消息已发出，请在企业微信确认')
    } else {
      toast.error(response.message || '测试失败')
    }
  } catch (err) {
    toast.error(`测试异常: ${err.message}`)
  } finally {
    testingWecom.value = false
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

.group-title-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.platform-logo {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
}

.wecom-logo {
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

.field-hint code {
  background: var(--color-bg-tertiary, rgba(128,128,128,0.15));
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.8rem;
  word-break: break-all;
}

.callback-help {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--color-bg-tertiary, rgba(128,128,128,0.08));
  border-radius: 8px;
  border: 1px solid var(--color-border);
}

.callback-help .field-hint {
  margin: 4px 0;
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
