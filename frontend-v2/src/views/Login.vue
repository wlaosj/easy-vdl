<template>
  <div class="login-page">
    <div class="login-card">
      <!-- Unraid 风格背景，保留 Easy-VDL Logo -->
      <div class="brand-header">
        <div class="logo-wrapper">
          <BrandLogo class="brand-logo" :class="{ 'logo-spinning': healthStatus.status === 'ok' }" />
          <span class="brand-name">Easy-VDL</span>
        </div>
      </div>
      
      <div class="login-body">
        <div class="login-main">
          <div class="welcome-text">
            <div class="welcome-header-row">
              <h2>{{ isRegisterMode ? '管理员注册' : '欢迎登录' }}</h2>
              
              <!-- 紧凑型健康状态徽章 -->
              <div v-if="healthStatus.status !== 'checking'" 
                   class="health-badge" 
                   :class="{'health-badge-success': healthStatus.status === 'ok', 'health-badge-error': healthStatus.status !== 'ok'}"
                   :title="healthStatus.message">
                <span class="health-text">{{ healthStatus.status === 'ok' ? '服务正常' : '服务异常' }}</span>
                
                <!-- 悬停/异常时显示的详细信息 -->
                <div class="health-popover">
                   <div v-for="(state, name) in healthStatus.services" :key="name" class="popover-item" :class="{ 'pop-down': state !== 'RUNNING' }">
                    <span>{{ getServiceName(name) }}</span>
                    <span>{{ state }}</span>
                  </div>
                </div>
              </div>
            </div>
            <p>{{ isRegisterMode ? '首次使用请创建管理员账号' : 'Easy-vdl管理系统' }}</p>
          </div>

          <form class="login-form" @submit.prevent="handleSubmit">
            <div class="form-group">
              <input type="text" v-model="username" class="unraid-input" placeholder="用户名" required />
            </div>
            
            <div class="form-group">
              <input type="password" v-model="password" class="unraid-input" :placeholder="isRegisterMode ? '设置密码' : '密码'" required />
            </div>

            <div v-if="isRegisterMode" class="form-group">
              <input type="password" v-model="confirmPassword" class="unraid-input" placeholder="确认密码" required />
            </div>

            <div class="form-actions">
              <button class="unraid-btn" :disabled="loading" type="submit">
                {{ loading ? '请 稍 候' : (isRegisterMode ? '注 册' : '登 录') }}
              </button>
            </div>

            <div class="form-footer">
              <a v-if="!isRegisterMode" href="#" class="forgot-link" @click.prevent="toast.info('请联系系统管理员重置密码')">找回密码</a>
              <span v-if="envOverrideEnabled" class="env-status-tip">
                <Icon name="shield" :size="14" />
                <span>已启用环境变量账户验证</span>
              </span>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import BrandLogo from '@/components/common/BrandLogo.vue'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const authStore = useAuthStore()
const toast = useToast()

const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const envOverrideEnabled = ref(false)
const isInitialized = ref(true) // 默认假设已初始化，通过 API 检查更新状态
const isRegisterMode = ref(false)
const healthStatus = ref({ status: 'checking', message: '', services: {} })
const isHealthChecking = ref(false)

const HEALTH_CHECK_INTERVAL_MS = 1000
const HEALTH_MAX_POLL_DURATION_MS = 60000
let healthPollTimer = null
let healthPollStartTs = 0

// 检查系统健康状态
async function checkHealth() {
  if (isHealthChecking.value) return
  isHealthChecking.value = true
  try {
    const res = await fetch('/api/system/health')
    if (res.ok) {
      const data = await res.json()
      healthStatus.value = data
    } else {
      healthStatus.value = { 
        status: 'error', 
        message: '无法连接到后端服务', 
        services: {}
      }
    }
  } catch (e) {
    healthStatus.value = { 
      status: 'error', 
      message: '网络连接失败',
      services: {}
    }
  } finally {
    isHealthChecking.value = false
  }
}

function clearHealthPolling() {
  if (healthPollTimer) {
    clearInterval(healthPollTimer)
    healthPollTimer = null
  }
}

function startHealthPolling() {
  clearHealthPolling()
  healthPollStartTs = Date.now()

  healthPollTimer = setInterval(async () => {
    if (healthStatus.value.status === 'ok') {
      clearHealthPolling()
      return
    }

    if (Date.now() - healthPollStartTs >= HEALTH_MAX_POLL_DURATION_MS) {
      clearHealthPolling()
      return
    }

    await checkHealth()
    if (healthStatus.value.status === 'ok') {
      clearHealthPolling()
    }
  }, HEALTH_CHECK_INTERVAL_MS)
}

function getServiceName(name) {
  const map = {
    'easy-vdl-unified-service': '主程序',
    'postgresql': '数据库'
  }
  return map[name] || name
}

// 检查系统状态（环境变量覆盖和初始化状态）
async function checkSystemStatus() {
  try {
    // 1. 检查初始化状态
    const initStatus = await authStore.getInitStatus()
    isInitialized.value = initStatus
    if (!initStatus) {
      isRegisterMode.value = true // 未初始化则进入注册模式
      // 如果未初始化，同时也应该检查一下 ENV 覆盖，虽然可能不太常见
    }

    // 2. 检查环境变量覆盖（仅在登录模式或已初始化时有意义，或者作为额外信息）
    const res = await fetch('/api/auth/env-override-status')
    if (res.ok) {
        const data = await res.json()
        envOverrideEnabled.value = data.env_override_enabled
    }
  } catch (e) {
    console.warn('Check system status failed', e)
  }
}

// 页面加载时检查
onMounted(async () => {
    checkSystemStatus()
    await checkHealth()
    if (healthStatus.value.status !== 'ok') {
      startHealthPolling()
    }
})

onUnmounted(() => {
  clearHealthPolling()
})

async function handleSubmit() {
    if (isRegisterMode.value) {
        await handleRegister()
    } else {
        await handleLogin()
    }
}

async function handleRegister() {
    if (!username.value || !password.value || !confirmPassword.value) {
        toast.warning('请填写完整信息')
        return
    }

    if (password.value !== confirmPassword.value) {
        toast.warning('两次输入的密码不一致')
        return
    }

    loading.value = true
    try {
        await authStore.register(username.value, password.value)
        toast.success('管理员账户注册成功，已自动登录！')
        router.push('/')
    } catch (e) {
        console.error('注册失败:', e)
        const errorMsg = e.response?.data?.detail || '注册失败，请重试'
        toast.error(errorMsg)
    } finally {
        loading.value = false
    }
}

async function handleLogin() {
  if (!username.value || !password.value) {
    toast.warning('请输入用户名和密码')
    return
  }
  
  loading.value = true
  try {
    await authStore.login(username.value, password.value)
    clearHealthPolling()
    toast.success('登录成功，欢迎回来！')
    router.push('/')
  } catch (e) {
    console.error('登录失败:', e)
    const errorMsg = e.response?.data?.detail || '登录失败，请检查用户名或密码'
    toast.error(errorMsg)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-primary);
  overflow: hidden;
  z-index: 9999;
  font-family: Arial, sans-serif;
}

.login-card {
  width: 100%;
  max-width: 600px;
  background: var(--color-bg-card);
  border-radius: 8px;
  box-shadow: var(--shadow-md);
  overflow: hidden;
  position: relative;
  z-index: 1;
}

/* 品牌头部：Unraid 风格斜向切边 + Easy-VDL 品牌 */
.brand-header {
  height: 160px;
  background: linear-gradient(135deg, #d9230f 0%, #ff8c40 100%);
  position: relative;
  display: flex;
  align-items: center;
  padding: 0 40px;
  clip-path: polygon(0 0, 100% 0, 100% 75%, 0 100%);
  margin-bottom: -40px;
}

.logo-wrapper {
  display: flex;
  align-items: center;
  gap: 15px;
}

.brand-logo {
  width: 45px;
  height: 45px;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
}

.brand-logo.logo-spinning {
  animation: logo-spin 2.4s linear infinite;
  transform-origin: center;
}

@keyframes logo-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.brand-name {
  color: white;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: 1px;
}

.login-body {
  padding: 60px 40px 40px;
}

.welcome-text {
  margin-bottom: 30px;
}

.welcome-text h2 {
  font-size: 28px;
  margin: 0;
  color: var(--color-text-primary);
  font-weight: bold;
  line-height: 1.2;
}

.welcome-header-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 紧凑型徽章样式 */
.health-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: normal;
  cursor: help;
  position: relative;
  transition: all 0.2s;
}

.health-badge-success {
  background: #f0fff4;
  color: #2f855a;
  border: 1px solid #c6f6d5;
}

.health-badge-error {
  background: #fff5f5;
  color: #c53030;
  border: 1px solid #fed7d7;
  animation: pulse-red 2s infinite;
}

@keyframes pulse-red {
  0% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0.4); }
  70% { box-shadow: 0 0 0 6px rgba(229, 62, 62, 0); }
  100% { box-shadow: 0 0 0 0 rgba(229, 62, 62, 0); }
}

/* 详情悬浮框 */
.health-popover {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 8px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-lg);
  padding: 8px;
  border-radius: 6px;
  min-width: 160px;
  z-index: 10;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-5px);
  transition: all 0.2s;
  pointer-events: none;
}

.health-badge:hover .health-popover {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
  pointer-events: auto;
}

.popover-item {
  display: flex;
  justify-content: space-between;
  gap: 15px;
  padding: 4px 0;
  font-size: 12px;
  white-space: nowrap;
  color: var(--color-text-tertiary);
}

.popover-item.pop-down {
  color: #e53e3e;
  font-weight: bold;
}

.welcome-text p {
  font-size: 14px;
  color: var(--color-text-tertiary);
  margin: 4px 0 0;
}

/* 删除旧的 health-alert 样式 */

.login-form {
  display: flex;
  flex-direction: column;
  gap: 15px;
  max-width: 380px;
}

.form-group {
  width: 100%;
}

.password-group {
  display: flex;
  align-items: center;
  gap: 20px;
}

.unraid-input {
  width: 100%;
  padding: 12px 15px;
  border: 2px solid var(--color-border);
  background: var(--color-bg-secondary);
  font-size: 18px;
  color: var(--color-text-primary);
  transition: border-color 0.2s;
  outline: none;
}

.unraid-input:focus {
  border-color: var(--color-text-tertiary);
}

.server-icon-wrapper {
  color: var(--color-text-primary);
  flex-shrink: 0;
  opacity: 0.9;
}

.form-actions {
  margin-top: 20px;
  display: flex;
  align-items: center;
  gap: 15px;
  flex-wrap: nowrap;
}

.unraid-btn {
  flex-shrink: 0;
  padding: 10px 40px;
  font-size: 18px;
  background: var(--color-bg-card);
  color: var(--color-primary);
  border: 2px solid;
  border-image: linear-gradient(to bottom, #d9230f, #ff8c40) 1;
  cursor: pointer;
  font-weight: bold;
  transition: opacity 0.2s;
}

.form-footer {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 16px;
  margin-top: 15px;
  flex-wrap: wrap;
}

.unraid-btn:hover {
  opacity: 0.8;
}

.unraid-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.forgot-link {
  display: inline-block;
  color: var(--color-primary);
  text-decoration: none;
  font-weight: bold;
  font-size: 15px;
}

.forgot-link:hover {
  text-decoration: underline;
}

.env-status-tip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-error);
  font-size: 13px;
  font-weight: bold;
  white-space: nowrap;
}

.env-text {
  display: flex;
  flex-direction: column;
  font-size: 12px;
  color: var(--color-error);
}

@media (max-width: 640px) {
  .login-page {
    background: var(--color-bg-card);
  }
  .login-card {
    margin: 0;
    border-radius: 0;
    max-width: 100%;
    width: 100%;
    height: 100vh;
    box-shadow: none;
  }
  .brand-header {
    padding: 0 20px;
  }
  .login-body {
    padding: 40px 20px;
  }
  .password-group {
    flex-direction: column;
    align-items: flex-start;
  }
  .server-icon-wrapper {
    display: none;
  }
  .form-actions {
    flex-wrap: wrap;
  }
  .env-status-tip {
    white-space: normal;
    word-break: break-word;
  }
}

</style>
