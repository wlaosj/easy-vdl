<template>
  <div class="license-settings">
    <div class="setting-group">
      <div class="group-title">高级功能授权</div>
      
      <LicenseCardShell
        class="card license-card"
        :class="[systemStore.license.status, { 'loading': systemStore.license.isLoading }]"
        :is-licensed="systemStore.license.is_licensed"
        :remaining-days="systemStore.license.remaining_days"
        :loading="systemStore.license.isLoading"
      >
        <template v-if="systemStore.license.isLoading">
          <div class="setting-license-skeleton">
            <div class="skeleton-header">
              <div class="skeleton-circle"></div>
              <div class="skeleton-texts">
                <div class="skeleton-line title"></div>
                <div class="skeleton-line sub"></div>
              </div>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="license-header">
            <div class="header-main">
              <div class="license-crown" v-if="systemStore.license.is_licensed">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M5 16L3 5l5.5 5L12 4l3.5 6L21 5l-2 11H5z"/>
                  <path d="M5 19h14v2H5z" opacity="0.8"/>
                </svg>
              </div>
              <div class="status-icon" :class="{ 'is-licensed': systemStore.license.is_licensed }">
                <Icon :name="systemStore.license.is_licensed ? 'check' : 'x'" :size="14" />
              </div>
            </div>
            <div class="license-info">
              <h3>{{ systemStore.license.is_licensed ? '高级版已激活' : '未授权 / 基础版' }}</h3>
      <p v-if="systemStore.license.is_licensed">
        有效期剩余: 
        <strong v-if="systemStore.license.remaining_days === -1 || systemStore.license.remaining_days > 3650">永久</strong>
        <strong v-else>{{ systemStore.license.remaining_days }} 天</strong>
        <span v-if="envKey" class="key-inline">Key: <code>{{ envKey.substring(0, 12) }}****</code></span>
      </p>
      <p v-if="systemStore.license.error" class="error-text">
        {{ systemStore.license.error }}
        <span v-if="!envKey">请确认已在环境变量中配置 <code>SNIFFER_LICENSE_KEY</code> 并重启容器</span>
      </p>
      <p v-if="!systemStore.license.is_licensed">
        基础版支持 YouTube / B 站等基础下载功能，高级功能（直播录制、订阅系统、AI 高光等）需要授权后使用
        <span v-if="envKey" class="key-inline">Key: <code>{{ envKey.substring(0, 12) }}****</code></span>
      </p>
      <p v-if="containerTimeText" class="container-time">{{ containerTimeText }}</p>
      <p v-else class="container-time muted">容器时间：--</p>
            </div>
          </div>
        </template>

        <div class="license-actions">
          <button @click="refreshLicense" :disabled="refreshing" class="btn btn-primary">
            <Icon name="refresh" :size="16" />
            {{ refreshing ? '刷新中...' : '刷新状态' }}
          </button>
          <a href="https://c.fakamiao.top/shopDetail/6WNe26" target="_blank" class="btn btn-primary">
            <Icon name="heart" :size="16" />
            购买授权
          </a>
          <button class="btn btn-secondary" @click="handleEmailFeedback">
            <Icon name="mail" :size="16" />
            邮件反馈
          </button>
          <router-link to="/feedback-progress" class="btn btn-secondary">
            <Icon name="message-square" :size="16" />
            开发进度
          </router-link>
          <button
            v-if="systemStore.license.is_licensed"
            class="btn btn-secondary"
            @click="handleFeedbackClick"
            title="高级版用户专属优先反馈通道"
          >
            <Icon name="message-square" :size="16" />
            高级专享反馈
          </button>
        </div>

        <!-- 使用提示 -->
        <div class="license-notice">
          <Icon name="alert-triangle" :size="14" />
          <span>{{ licenseUsageNotice }}</span>
        </div>
      </LicenseCardShell>

      <!-- 帮助指引 -->
      <div class="help-section">
        <div class="help-title">
          <Icon name="info" :size="18" />
          如何配置授权密钥？
        </div>
        <div class="help-content">
          <p>购买授权后你将收到一串密钥，通过环境变量注入容器即可激活。</p>
          <p><strong>docker-compose 部署</strong>，在配置文件中添加：</p>
          <pre class="code-block">environment:
  - SNIFFER_LICENSE_KEY=你的授权密钥</pre>
          <p><strong>docker run 部署</strong>，添加 <code>-e SNIFFER_LICENSE_KEY=你的授权密钥</code> 参数。</p>
          <p class="help-note">添加后需重启容器生效：<code>docker-compose up -d</code> 或 <code>docker restart &lt;容器名&gt;</code></p>
        </div>
      </div>

    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useSystemStore } from '@/stores/system'
import { licenseApi } from '@/api/license'
import { systemApi } from '@/api/system'
import { useToast } from '@/composables/useToast'
import Icon from '@/components/common/Icon.vue'
import LicenseCardShell from '@/components/common/LicenseCardShell.vue'

const systemStore = useSystemStore()
const toast = useToast()
const refreshing = ref(false)
const envKey = ref('')
const containerTimeText = ref('')
let containerTimeOffsetMs = 0
let timeTickTimer = null
let timeSyncTimer = null

const isLifetimeLicensed = computed(() => {
  return systemStore.license.is_licensed && (
    systemStore.license.remaining_days === -1 || systemStore.license.remaining_days > 3650
  )
})

const licenseUsageNotice = computed(() => {
  const instances = isLifetimeLicensed.value ? '2 个' : '1 个'
  return `每个授权密钥限用于 ${instances} Docker 实例。请勿公开分享密钥，违规使用将导致授权封禁。`
})


async function refreshLicense() {
  refreshing.value = true
  try {
    await licenseApi.refresh()
    await systemStore.fetchLicenseStatus()
    toast.success('授权状态已刷新')
  } catch (err) {
    console.error('Failed to refresh license:', err)
    toast.error('刷新失败')
  } finally {
    refreshing.value = false
  }
}

async function handleEmailFeedback() {
  const email = '918652593@qq.com'
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(email)
      toast.success('邮箱已复制，可直接粘贴发送')
    } else {
      const textArea = document.createElement('textarea')
      textArea.value = email
      textArea.style.position = 'fixed'
      textArea.style.left = '-999999px'
      textArea.style.top = '-999999px'
      document.body.appendChild(textArea)
      textArea.focus()
      textArea.select()
      const successful = document.execCommand('copy')
      document.body.removeChild(textArea)
      if (successful) {
        toast.success('邮箱已复制，可直接粘贴发送')
      } else {
        throw new Error('execCommand 复制失败')
      }
    }
  } catch (err) {
    console.error('Failed to copy email:', err)
    toast.error('复制失败，请手动记录邮箱地址')
  }

  // 尝试唤起本地邮件客户端（部分环境可能不支持）
  try {
    window.location.href = `mailto:${email}`
  } catch (err) {
    // 忽略唤起失败
  }
}

function handleFeedbackClick() {
  if (typeof window.showFeedbackForm === 'function') {
    window.showFeedbackForm()
  } else {
    window.alert('反馈表单正在初始化，请稍后再试一次～')
  }
}

function formatContainerTime(date) {
  const pad = (n) => String(n).padStart(2, '0')
  const y = date.getFullYear()
  const m = pad(date.getMonth() + 1)
  const d = pad(date.getDate())
  const hh = pad(date.getHours())
  const mm = pad(date.getMinutes())
  const ss = pad(date.getSeconds())
  return `容器时间：${y}-${m}-${d} ${hh}:${mm}:${ss}`
}

function updateContainerTimeText() {
  const now = new Date(Date.now() + containerTimeOffsetMs)
  containerTimeText.value = formatContainerTime(now)
}

async function syncContainerTime() {
  try {
    const t0 = Date.now()
    const res = await systemApi.getContainerTime()
    const t1 = Date.now()
    const data = res?.data || {}
    const serverMs = data.timestamp_ms || (data.timestamp ? Math.round(data.timestamp * 1000) : 0)
    if (!serverMs) {
      throw new Error('invalid server time')
    }
    containerTimeOffsetMs = serverMs - Math.round((t0 + t1) / 2)
    updateContainerTimeText()
  } catch (err) {
    console.error('Failed to sync container time:', err)
    containerTimeText.value = ''
  }
}

onMounted(async () => {
  await systemStore.fetchLicenseStatus()
  
  // 获取高级功能密钥
  try {
    const data = await licenseApi.getEnvKey()
    // 后端已返回脱敏值，前端直接展示
    envKey.value = data.key_code || ''
  } catch (err) {
    console.error('Failed to fetch env key:', err)
  }

  await syncContainerTime()
  updateContainerTimeText()
  timeTickTimer = setInterval(updateContainerTimeText, 1000)
  timeSyncTimer = setInterval(syncContainerTime, 60 * 1000)
})

onBeforeUnmount(() => {
  if (timeTickTimer) {
    clearInterval(timeTickTimer)
    timeTickTimer = null
  }
  if (timeSyncTimer) {
    clearInterval(timeSyncTimer)
    timeSyncTimer = null
  }
})
</script>

<style scoped>
.license-settings {
  display: block;
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

.license-card {
  padding: 32px;
  border-radius: 16px;
  margin-bottom: 32px;
}

/* 骨架屏样式 */
.setting-license-skeleton {
  width: 100%;
  min-height: 84px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.skeleton-header {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 24px;
}

.skeleton-circle {
  width: 48px;
  height: 48px;
  background: var(--color-bg-tertiary);
  border-radius: 50%;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

.skeleton-texts {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-line {
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

.skeleton-line.title {
  width: 150px;
  height: 20px;
  margin-bottom: 8px;
}

.skeleton-line.sub {
  width: 200px; /* 缩短长度，更像真实 Key 的长度 */
  height: 12px;
}

.skeleton-footer {
  display: flex;
  gap: 12px;
}

.skeleton-button {
  width: 100px;
  height: 36px;
  background: var(--color-bg-tertiary);
  border-radius: 8px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

@keyframes skeleton-pulse {
  0% { opacity: 0.6; }
  50% { opacity: 0.3; }
  100% { opacity: 0.6; }
}

.license-header {
  display: flex;
  gap: 24px;
  align-items: center;
  margin-bottom: 24px;
  min-height: 84px; /* 精确锁定高度 */
}

.header-main {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-icon {
  position: absolute;
  bottom: 2px;
  right: 2px;
  width: 22px;
  height: 22px;
  background: var(--color-bg-secondary);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2.5px solid var(--color-border);
  color: var(--color-error);
  box-shadow: 0 2px 4px rgba(0,0,0,0.15);
}

.status-icon.is-licensed {
  color: var(--color-success);
  border-color: var(--color-success);
}

.license-info {
  flex: 1;
  min-height: 52px; /* 预留两行文字的高度，防止单行与双行切换时跳变 */
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.license-info h3 {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 4px; /* 稍微外边距，收紧布局 */
  color: var(--color-text-primary);
}

.license-info p {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}

.license-info strong {
  color: var(--color-text-primary);
  font-weight: 600;
}

.license-card.is-lifetime .license-info h3 {
  color: var(--color-text-primary);
  text-shadow: none;
}

.license-card.is-lifetime .license-info p {
  color: var(--color-text-secondary);
}

.license-card.is-lifetime .license-info strong {
  color: var(--color-primary-hover);
}

.license-card.is-lifetime .status-icon {
  background: var(--color-bg-secondary);
  border-color: rgba(230, 126, 34, 0.3);
}

.key-inline {
  color: var(--color-text-tertiary);
  font-size: 13px;
  margin-left: 8px;
}

.key-inline code {
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 12px;
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
  padding: 2px 6px;
  border-radius: 4px;
}

@media (max-width: 640px) {
  .key-inline {
    display: block;
    margin-left: 0;
    margin-top: 6px;
  }

  .key-inline code {
    display: inline-block;
    margin-top: 4px;
  }
}

.license-card.is-lifetime .key-inline {
  color: var(--color-text-secondary);
}

.license-card.is-lifetime .key-inline code {
  color: var(--color-text-primary);
  background: rgba(230, 126, 34, 0.12);
  border: 1px solid rgba(230, 126, 34, 0.24);
}

.container-time {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin-top: 6px;
}

.container-time.muted {
  color: var(--color-text-tertiary);
}

.error-text {
  color: var(--color-error);
}

.license-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.license-actions .btn-secondary {
  background: transparent;
  color: var(--color-primary);
  border: 1px solid rgba(230, 126, 34, 0.35);
}

.license-actions .btn-secondary:hover:not(:disabled) {
  background: #fff5eb;
  border-color: rgba(230, 126, 34, 0.6);
  color: #d35400;
}

@media (min-width: 768px) {
  .license-actions {
    justify-content: flex-start;
  }
}

.license-notice {
  margin-top: 16px;
  padding: 10px 12px;
  background: rgba(243, 156, 18, 0.08);
  border: 1px solid rgba(243, 156, 18, 0.2);
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.license-notice svg {
  color: var(--color-warning);
  flex-shrink: 0;
}

.license-card.is-lifetime .license-notice {
  background: rgba(230, 126, 34, 0.08);
  border-color: rgba(230, 126, 34, 0.22);
  color: var(--color-text-secondary);
}

.license-card.is-lifetime .license-notice svg {
  color: var(--color-primary);
}

/* License Key 区域 */
.license-key-section {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid var(--color-border);
}

.key-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.key-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.key-source {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

/* 购买区域 */
.purchase-section {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid var(--color-border);
}


.setting-item {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 48px;
  padding: 24px 0;
  border-bottom: 1px solid var(--color-border);
  align-items: flex-start;
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

.setting-control {
  padding-top: 4px;
}

.key-preview {
  padding: 12px 16px;
  background: var(--color-bg-tertiary);
  border-radius: 8px;
  max-width: 400px;
}

.key-preview.key-missing {
  background: rgba(231, 76, 60, 0.08);
  border: 1px dashed var(--color-error);
}

.key-preview code {
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 13px;
  color: var(--color-text-primary);
}

.key-placeholder {
  color: var(--color-text-tertiary);
  font-style: italic;
}

/* 帮助指引区域 */
.help-section {
  margin-top: 24px;
  padding: 20px 24px;
  background: rgba(230, 126, 34, 0.06);
  border: 1px solid rgba(230, 126, 34, 0.18);
  border-radius: 12px;
}

.help-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-primary);
  margin-bottom: 16px;
}

.help-content p {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0 0 12px 0;
  line-height: 1.6;
}

.help-content code {
  background: var(--color-bg-tertiary);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 12px;
}

.code-block {
  background: var(--color-bg-tertiary);
  padding: 16px;
  border-radius: 8px;
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-primary);
  overflow-x: auto;
  margin: 12px 0;
  white-space: pre;
}

.help-note {
  font-size: 13px !important;
  color: var(--color-text-tertiary) !important;
  margin-top: 8px !important;
}

.btn-purchase {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  color: white;
  background: linear-gradient(135deg, #ff9ff3, #f368e0);
  text-decoration: none;
  transition: all 0.2s;
  box-shadow: 0 4px 12px rgba(243, 104, 224, 0.3);
}

.btn-purchase:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(243, 104, 224, 0.4);
}

@media (max-width: 640px) {
  .license-settings {
    display: block;
  }
}
</style>
