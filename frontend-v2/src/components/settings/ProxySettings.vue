<template>
  <div class="proxy-settings">
    <div class="setting-group">
      <div class="group-title">全局代理配置</div>
      
      <!-- 显眼的重启提示 -->
      <div class="restart-notice">
        <div class="notice-icon">
          <Icon name="alert-triangle" :size="20" />
        </div>
        <div class="notice-content">
          <span class="notice-title">配置提示</span>
          <p class="notice-desc">全局代理配置涉及容器环境，修改并保存该配置后，您需要<strong>通过 SSH 或管理界面重启 Docker 容器</strong>方可使所有设置完全生效。</p>
        </div>
      </div>
      
      <div class="setting-item">
        <div class="setting-label">
          <span class="title">启用全局代理</span>
          <p class="desc">为整个系统启用网络代理,支持所有网络请求</p>
        </div>
        <div class="setting-control">
          <label class="switch">
            <input type="checkbox" v-model="settingsStore.proxySettings.enabled" />
            <span class="switch-slider"></span>
          </label>
        </div>
      </div>

      <template v-if="settingsStore.proxySettings.enabled">
        <div class="setting-item">
          <div class="setting-label">
            <span class="title">代理类型</span>
            <p class="desc">选择代理协议类型 (支持 HTTP/HTTPS/SOCKS5)</p>
          </div>
          <div class="setting-control">
            <select v-model="settingsStore.proxySettings.type" class="form-select">
              <option value="http">HTTP</option>
              <option value="https">HTTPS</option>
              <option value="socks5">SOCKS5</option>
            </select>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">代理服务器</span>
            <p class="desc">代理服务器的地址或域名</p>
          </div>
          <div class="setting-control">
            <input 
              type="text" 
              v-model="settingsStore.proxySettings.host" 
              placeholder="例如: 127.0.0.1 或 proxy.example.com"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">端口</span>
            <p class="desc">代理服务器的端口号 (1-65535)</p>
          </div>
          <div class="setting-control">
            <input 
              type="number" 
              v-model.number="settingsStore.proxySettings.port" 
              placeholder="8080"
              class="form-input"
              min="1"
              max="65535"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">不使用代理的地址</span>
            <p class="desc">这些地址将绕过代理直接连接,多个地址用逗号分隔</p>
          </div>
          <div class="setting-control">
            <input 
              type="text" 
              v-model="settingsStore.proxySettings.noProxy" 
              placeholder="localhost,127.0.0.1,*.local"
              class="form-input"
            />
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-label">
            <span class="title">操作与保存</span>
            <p class="desc">提交配置至服务器，或测试连接有效性</p>
          </div>
          <div class="setting-control action-buttons">
            <button @click="saveProxy" :disabled="settingsStore.saving" class="btn btn-primary">
              <Icon name="check" :size="16" />
              {{ settingsStore.saving ? '保存中...' : '提交保存' }}
            </button>
            <button @click="clearProxy" class="btn btn-outline text-danger">
              <Icon name="trash" :size="16" />
              清除配置
            </button>
            <button @click="testProxy" :disabled="testing" class="btn btn-outline">
              <Icon name="zap" :size="16" />
              {{ testing ? '测试中...' : '立即测试' }}
            </button>
          </div>
        </div>
      </template>

      <div class="setting-item" v-if="!settingsStore.proxySettings.enabled">
        <div class="setting-label">
          <span class="title">持久化保存</span>
          <p class="desc">将当前关闭代理的状态保存到服务器</p>
        </div>
        <div class="setting-control action-buttons">
          <button @click="saveProxy" :disabled="settingsStore.saving" class="btn btn-primary">
            <Icon name="check" :size="16" />
            {{ settingsStore.saving ? '保存中...' : '提交保存' }}
          </button>
          <button @click="clearProxy" class="btn btn-outline text-danger">
            <Icon name="trash" :size="16" />
            清除配置
          </button>
        </div>
      </div>
    </div>

    <!-- 测试结果弹窗 -->
    <Modal 
      v-model:show="showTestModal" 
      :title="testResult?.success ? '代理测试成功' : '代理测试失败'"
      :type="testResult?.success ? 'success' : 'error'"
    >
      <p v-if="testResult?.success">{{ testResult.message }}</p>
      <p v-else class="error-text">{{ testResult?.error }}</p>
    </Modal>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'

const settingsStore = useSettingsStore()
const toast = useToast()
const testing = ref(false)
const testResult = ref(null)
const showTestModal = ref(false)

// 保存代理设置
async function saveProxy() {
  const result = await settingsStore.saveProxySettings()
  if (result.success) {
    toast.success('代理设置已保存')
  } else {
    toast.error(`保存失败: ${result.error}`)
  }
}

// 测试代理
async function testProxy() {
  testing.value = true
  testResult.value = null
  
  try {
    const result = await settingsStore.testProxyConnection()
    testResult.value = result
    showTestModal.value = true
  } catch (err) {
    testResult.value = {
      success: false,
      error: err.message || '测试失败'
    }
    showTestModal.value = true
  } finally {
    testing.value = false
  }
}

// 清除代理配置
async function clearProxy() {
  if (!confirm('确定要清除代理配置吗?')) return
  
  const result = await settingsStore.clearProxySettings()
  if (result.success) {
    toast.success('代理配置已清除')
  } else {
    toast.error(`清除失败: ${result.error}`)
  }
}

// 加载代理设置
settingsStore.loadProxySettings()
</script>

<style scoped>
.proxy-settings {
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
  grid-template-columns: minmax(200px, 280px) 1fr;
  gap: 32px;
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

.setting-control {
  display: flex;
  gap: 12px;
  justify-content: flex-start;
  padding-top: 4px;
}

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.action-buttons .btn {
  flex: 0 0 auto;
}

.btn {
  white-space: nowrap;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-text {
  color: var(--color-error);
}

.restart-notice {
  display: flex;
  gap: 16px;
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 32px;
  align-items: flex-start;
}

[data-theme="dark"] .restart-notice {
  background: rgba(234, 179, 8, 0.05);
  border-color: rgba(234, 179, 8, 0.2);
}

.notice-icon {
  color: #eab308;
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
  color: #eab308;
  margin-bottom: 4px;
}

.notice-desc {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin: 0;
}

@media (max-width: 1200px) {
  .setting-item {
    gap: 24px;
    grid-template-columns: 220px 1fr;
  }
}

@media (max-width: 900px) {
  .setting-item {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .setting-control {
    width: 100%;
  }
}

@media (max-width: 768px) {
  .setting-group {
    margin-bottom: 24px;
  }

  .group-title {
    margin-bottom: 16px;
  }

  .restart-notice {
    padding: 12px 16px;
    gap: 12px;
    margin-bottom: 20px;
  }

  .setting-item {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px 0;
  }

  .setting-control {
    width: 100%;
    padding-top: 0;
  }

  .action-buttons {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
    width: 100%;
  }

  .action-buttons .btn {
    width: 100%;
    justify-content: center;
  }
}
</style>
