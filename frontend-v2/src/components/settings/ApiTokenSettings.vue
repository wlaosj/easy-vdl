<template>
  <div class="api-token-settings">
    <div class="setting-group">
      <div class="group-header">
        <div class="group-title">API Token 管理</div>
        <p class="group-desc">创建和管理 API Token，用于外部应用、脚本、机器人、iOS 快捷指令等调用 API</p>
      </div>

      <div class="top-entry-grid">
        <!-- 浏览器插件提示卡片 -->
        <div class="browser-extension-banner">
          <div class="banner-content">
            <div class="banner-icon">
              <Icon name="globe" :size="24" />
            </div>
            <div class="banner-text">
              <div class="banner-title">🚀 推荐使用浏览器插件</div>
              <div class="banner-desc">使用 easy-vdl 浏览器插件，无需手动复制链接，一键下载视频更便捷！</div>
            </div>
            <a
              href="https://github.com/wlaosj/easy-vdl/releases"
              target="_blank"
              rel="noopener noreferrer"
              class="banner-link"
            >
              <Icon name="external-link" :size="16" />
              下载插件
            </a>
          </div>
        </div>

        <div class="help-entry-card">
          <div class="help-entry-left">
            <Icon name="info" :size="18" />
            <div>
              <div class="help-entry-title">API Token 使用说明</div>
              <div class="help-entry-desc">完整文档已迁移到二级页面，包含调用示例、安全建议和快捷指令说明。</div>
            </div>
          </div>
          <button class="btn btn-outline" @click="goToUsageGuide">
            <Icon name="external-link" :size="14" />
            查看使用说明
          </button>
        </div>
      </div>

      <!-- 横向布局：创建表单和 Token 列表 -->
      <div class="settings-layout">
        <!-- 左侧列：创建 Token 表单 -->
        <div class="settings-column">
          <div class="card">
            <div class="card-header">
              <h3>创建新 Token</h3>
            </div>
            <div class="card-body">
              <div class="form-group">
                <label class="form-label">Token 名称</label>
                <input
                  v-model="newToken.name"
                  type="text"
                  class="form-input"
                  placeholder="例如：浏览器插件"
                  :disabled="creating"
                />
              </div>
              <div class="form-group">
                <label class="form-label">过期时间（可选）</label>
                <input
                  v-model.number="newToken.expires_in_days"
                  type="number"
                  class="form-input"
                  placeholder="天数，留空表示永不过期"
                  min="1"
                  :disabled="creating"
                />
                <p class="form-hint">留空表示永不过期</p>
              </div>
              <div class="form-actions">
                <button @click="createToken" :disabled="creating || !newToken.name" class="btn btn-primary">
                  <Icon name="plus" :size="16" />
                  {{ creating ? '创建中...' : '创建 Token' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 右侧列：Token 列表 -->
        <div class="settings-column">
          <div class="card">
            <div class="card-header">
              <h3>Token 列表</h3>
              <button @click="loadTokens" :disabled="loading" class="btn btn-sm btn-outline">
                <Icon name="refresh" :size="14" />
                刷新
              </button>
            </div>
            <div class="card-body">
              <div v-if="loading" class="loading-state">
                <Icon name="loader" :size="20" class="spinning" />
                <span>加载中...</span>
              </div>
              <div v-else-if="tokens.length === 0" class="empty-state">
                <Icon name="key" :size="32" />
                <p>暂无 Token</p>
                <p class="empty-hint">创建 Token 后，外部应用可以使用它来调用 API</p>
              </div>
              <div v-else class="token-list">
                <div v-for="token in tokens" :key="token.id" class="token-item">
                  <div class="token-info">
                    <div class="token-header">
                      <h4>{{ token.name }}</h4>
                      <div class="token-badges">
                        <span v-if="isExpired(token)" class="badge badge-danger">已过期</span>
                        <span v-else-if="token.is_active !== 'true'" class="badge badge-warning">已禁用</span>
                        <span v-else class="badge badge-success">活跃</span>
                      </div>
                    </div>
                    <div class="token-details">
                      <div class="detail-item">
                        <Icon name="calendar" :size="12" />
                        <span>创建时间：{{ formatDate(token.created_at) }}</span>
                      </div>
                      <div class="detail-item" v-if="token.expires_at">
                        <Icon name="clock" :size="12" />
                        <span>过期时间：{{ formatDate(token.expires_at) }}</span>
                      </div>
                      <div class="detail-item" v-else>
                        <Icon name="infinity" :size="12" />
                        <span>永不过期</span>
                      </div>
                      <div class="detail-item" v-if="token.last_used_at">
                        <Icon name="activity" :size="12" />
                        <span>最后使用：{{ formatDate(token.last_used_at) }}</span>
                      </div>
                      <div class="detail-item" v-else>
                        <Icon name="activity" :size="12" />
                        <span>从未使用</span>
                      </div>
                    </div>
                    <div class="token-value-row">
                      <div class="token-value" v-if="token.token">
                        <code>{{ token.token }}</code>
                        <button v-if="!token.token.startsWith('***')" @click="copyToken(token.token)" class="btn-icon" title="复制">
                          <Icon name="copy" :size="14" />
                        </button>
                      </div>
                    </div>
                    <div class="token-actions">
                      <button @click="showRegenerateDialog(token)" class="btn btn-sm btn-outline">
                        <Icon name="refresh-cw" :size="14" />
                        重新生成
                      </button>
                      <button @click="showEditDialog(token)" class="btn btn-sm btn-outline">
                        <Icon name="edit" :size="14" />
                        编辑
                      </button>
                      <button @click="showDeleteDialog(token.id)" class="btn btn-sm btn-danger">
                        <Icon name="trash" :size="14" />
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑对话框 -->
    <div v-if="editingToken" class="modal-overlay" @click="closeEditDialog">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3>编辑 Token</h3>
          <button @click="closeEditDialog" class="btn-icon">
            <Icon name="x" :size="20" />
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">Token 名称</label>
            <input v-model="editForm.name" type="text" class="form-input" />
          </div>
          <div class="form-group">
            <label class="form-label">过期时间（天）</label>
            <input v-model.number="editForm.expires_in_days" type="number" class="form-input" min="0" placeholder="留空或设为 0 表示永不过期" />
            <p class="form-hint">当前显示的是剩余天数，修改后将从当前时间重新计算过期时间</p>
            <div class="form-warning" style="margin-top: 8px; padding: 8px 12px; background: rgba(243, 156, 18, 0.1); border-left: 3px solid #f39c12; border-radius: 4px; font-size: 12px; color: #856404;">
              <Icon name="alert-triangle" :size="14" style="margin-right: 6px; vertical-align: middle;" />
              <span>⚠️ 重要提示：修改过期时间将从当前时间重新计算，而不是保持原过期时间。例如：如果剩余 30 天，您输入 30 天，实际会延长到 30 天后。</span>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">状态</label>
            <label class="checkbox-label">
              <input v-model="editForm.is_active" type="checkbox" />
              <span>激活</span>
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="closeEditDialog" class="btn btn-outline">取消</button>
          <button @click="updateToken" :disabled="updating" class="btn btn-primary">
            {{ updating ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 重新生成确认对话框 -->
    <div v-if="regeneratingToken" class="modal-overlay" @click="closeRegenerateDialog">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3>重新生成 Token</h3>
          <button @click="closeRegenerateDialog" class="btn-icon">
            <Icon name="x" :size="20" />
          </button>
        </div>
        <div class="modal-body">
          <p>重新生成后，旧的 Token 将立即失效，请确保已更新所有使用该 Token 的应用。</p>
          <p class="warning-text">此操作不可撤销！</p>
        </div>
        <div class="modal-footer">
          <button @click="closeRegenerateDialog" class="btn btn-outline">取消</button>
          <button @click="confirmRegenerate" :disabled="regenerating" class="btn btn-danger">
            {{ regenerating ? '生成中...' : '确认重新生成' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Token 创建成功模态框 -->
    <Modal
      v-model:show="showTokenModal"
      title="Token 创建成功"
      type="success"
      width="600px"
      :show-confirm="false"
    >
      <div class="token-success-content">
        <p style="margin-bottom: 16px; color: var(--color-text-primary);">
          Token 已成功创建，请妥善保管。此 Token 仅显示一次，关闭后将无法再次查看。
        </p>
        <div class="token-display-box">
          <label class="token-label">Token 值：</label>
          <div class="token-value-wrapper">
            <code class="token-code">{{ createdToken?.token || '' }}</code>
            <button @click="copyCreatedToken" class="btn-copy" title="复制 Token">
              <Icon name="copy" :size="16" />
              复制
            </button>
          </div>
        </div>
        <div class="token-info-box">
          <div class="info-item">
            <span class="info-label">名称：</span>
            <span class="info-value">{{ createdToken?.name || '' }}</span>
          </div>
          <div class="info-item" v-if="createdToken?.expires_at">
            <span class="info-label">过期时间：</span>
            <span class="info-value">{{ formatDate(createdToken.expires_at) }}</span>
          </div>
          <div class="info-item" v-else>
            <span class="info-label">过期时间：</span>
            <span class="info-value">永不过期</span>
          </div>
        </div>
        <div class="token-warning-box">
          <Icon name="alert-triangle" :size="16" />
          <span>请立即复制并保存 Token，关闭此对话框后将无法再次查看完整 Token。</span>
        </div>
      </div>
      <template #footer>
        <button @click="closeTokenModal" class="btn btn-primary">
          我已保存
        </button>
      </template>
    </Modal>

    <!-- 删除确认模态框 -->
    <Modal
      v-model:show="showDeleteConfirm"
      title="删除 Token"
      type="warning"
      width="500px"
      :show-confirm="false"
    >
      <div class="delete-confirm-content">
        <p style="margin-bottom: 12px; color: var(--color-text-primary);">
          确定要删除这个 Token 吗？
        </p>
        <p style="color: var(--color-text-secondary); font-size: 14px;">
          删除后该 Token 将立即失效，所有使用此 Token 的应用将无法继续调用 API。此操作不可撤销。
        </p>
      </div>
      <template #footer>
        <button @click="closeDeleteDialog" class="btn btn-outline">取消</button>
        <button @click="confirmDelete" class="btn btn-danger">
          确认删除
        </button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'
import { authApi } from '@/api/auth'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const router = useRouter()

const tokens = ref([])
const loading = ref(false)
const creating = ref(false)
const updating = ref(false)
const regenerating = ref(false)
const editingToken = ref(null)
const regeneratingToken = ref(null)
const showTokenModal = ref(false)
const createdToken = ref(null)
const showDeleteConfirm = ref(false)
const deletingToken = ref(null)

const newToken = ref({
  name: '',
  expires_in_days: null
})

const editForm = ref({
  name: '',
  expires_in_days: null,
  is_active: true
})

async function loadTokens() {
  loading.value = true
  try {
    const data = await authApi.listTokens()
    tokens.value = data || []
  } catch (err) {
    console.error('Failed to load tokens:', err)
    toast.error('加载 Token 列表失败')
  } finally {
    loading.value = false
  }
}

async function createToken() {
  if (!newToken.value.name.trim()) {
    toast.error('请输入 Token 名称')
    return
  }

  creating.value = true
  try {
    const tokenData = {
      name: newToken.value.name.trim(),
      expires_in_days: newToken.value.expires_in_days || null
    }
    const data = await authApi.createToken(tokenData)
    
    // 保存创建的 Token 并显示模态框
    createdToken.value = data
    showTokenModal.value = true
    
    // 重置表单
    newToken.value = { name: '', expires_in_days: null }
    
    // 重新加载列表
    await loadTokens()
  } catch (err) {
    console.error('Failed to create token:', err)
    toast.error(err.response?.data?.detail || '创建 Token 失败')
  } finally {
    creating.value = false
  }
}

function showDeleteDialog(tokenId) {
  deletingToken.value = tokenId
  showDeleteConfirm.value = true
}

function closeDeleteDialog() {
  showDeleteConfirm.value = false
  deletingToken.value = null
}

async function confirmDelete() {
  if (!deletingToken.value) return

  try {
    await authApi.deleteToken(deletingToken.value)
    toast.success('Token 已删除')
    closeDeleteDialog()
    await loadTokens()
  } catch (err) {
    console.error('Failed to delete token:', err)
    toast.error('删除失败')
  }
}

function showEditDialog(token) {
  editingToken.value = token
  // 计算剩余天数（仅用于显示，实际更新时会从当前时间重新计算）
  const remainingDays = token.expires_at ? calculateDaysUntilExpiry(token.expires_at) : null
  editForm.value = {
    name: token.name,
    expires_in_days: remainingDays, // 显示剩余天数，但更新时会从当前时间重新计算
    is_active: token.is_active === 'true'
  }
}

function closeEditDialog() {
  editingToken.value = null
  editForm.value = { name: '', expires_in_days: null, is_active: true }
}

async function updateToken() {
  updating.value = true
  try {
    // 如果用户输入了过期天数，需要明确处理：0 或 null 表示永不过期
    let expires_in_days = editForm.value.expires_in_days
    if (expires_in_days === '' || expires_in_days === null || expires_in_days === undefined) {
      expires_in_days = null // 永不过期
    } else if (expires_in_days <= 0) {
      expires_in_days = null // 0 或负数也视为永不过期
    }
    
    const tokenData = {
      name: editForm.value.name,
      expires_in_days: expires_in_days,
      is_active: editForm.value.is_active
    }
    await authApi.updateToken(editingToken.value.id, tokenData)
    toast.success('Token 已更新')
    closeEditDialog()
    await loadTokens()
  } catch (err) {
    console.error('Failed to update token:', err)
    toast.error('更新失败')
  } finally {
    updating.value = false
  }
}

function showRegenerateDialog(token) {
  regeneratingToken.value = token
}

function closeRegenerateDialog() {
  regeneratingToken.value = null
}

async function confirmRegenerate() {
  regenerating.value = true
  try {
    const data = await authApi.regenerateToken(regeneratingToken.value.id)
    toast.success('Token 已重新生成')
    
    // 显示新 Token 模态框
    createdToken.value = data
    showTokenModal.value = true
    
    closeRegenerateDialog()
    await loadTokens()
  } catch (err) {
    console.error('Failed to regenerate token:', err)
    toast.error('重新生成失败')
  } finally {
    regenerating.value = false
  }
}

function closeTokenModal() {
  showTokenModal.value = false
  createdToken.value = null
}

async function copyCreatedToken() {
  if (createdToken.value?.token) {
    await copyToken(createdToken.value.token)
  }
}

async function copyToken(token) {
  try {
    // 优先使用现代 Clipboard API
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(token)
      toast.success('Token 已复制到剪贴板')
      return
    }
    
    // 降级方案：使用传统的 execCommand 方法
    const textArea = document.createElement('textarea')
    textArea.value = token
    textArea.style.position = 'fixed'
    textArea.style.left = '-999999px'
    textArea.style.top = '-999999px'
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()
    
    try {
      const successful = document.execCommand('copy')
      document.body.removeChild(textArea)
      
      if (successful) {
        toast.success('Token 已复制到剪贴板')
      } else {
        throw new Error('execCommand 复制失败')
      }
    } catch (execErr) {
      document.body.removeChild(textArea)
      throw execErr
    }
  } catch (err) {
    console.error('Failed to copy token:', err)
    
    // 如果所有方法都失败，提供手动复制提示
    if (err.name === 'NotAllowedError' || err.message?.includes('permission')) {
      toast.error('复制失败：需要 HTTPS 环境或用户授权。请手动选择并复制 Token。')
    } else {
      toast.error('复制失败，请手动选择并复制 Token')
    }
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function isExpired(token) {
  if (!token.expires_at) return false
  return new Date(token.expires_at) < new Date()
}

function calculateDaysUntilExpiry(expiresAt) {
  if (!expiresAt) return null
  const now = new Date()
  const expiry = new Date(expiresAt)
  const diffTime = expiry - now
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
  return diffDays > 0 ? diffDays : null
}

function goToUsageGuide() {
  router.push('/settings/api-token-guide')
}

onMounted(() => {
  loadTokens()
})
</script>

<style scoped>
.api-token-settings,
.api-token-settings *,
.api-token-settings *::before,
.api-token-settings *::after {
  box-sizing: border-box;
}

.api-token-settings {
  max-width: 1400px;
  width: 100%;
}

.setting-group {
  margin-bottom: 32px;
}

.top-entry-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 16px;
  align-items: stretch;
  margin-bottom: 24px;
}

.settings-layout {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
  gap: 24px;
  align-items: stretch;
  margin-bottom: 32px;
}

@media (max-width: 1280px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
}

.settings-column {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.help-entry-card {
  padding: 16px 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-secondary);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.help-entry-left {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  color: var(--color-text-primary);
}

.help-entry-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 4px;
}

.help-entry-desc {
  font-size: 13px;
  color: var(--color-text-secondary);
}

/* 响应式布局：小屏幕时改为单列 */
@media (max-width: 1100px) {
  .top-entry-grid {
    grid-template-columns: 1fr;
  }
  
  .token-inline-row {
    flex-direction: column;
    align-items: stretch;
  }
  
  .token-actions {
    justify-content: flex-start;
    width: 100%;
  }
  
  .token-actions .btn {
    flex: 1;
  }
}

/* 浏览器插件横幅响应式 */
@media (max-width: 768px) {
  .top-entry-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .settings-layout {
    grid-template-columns: 1fr;
    gap: 16px;
    width: 100%;
  }

  .token-list {
    max-height: 280px;
  }

  .help-entry-card {
    flex-direction: column;
    align-items: stretch;
  }

  .help-entry-card .btn {
    width: 100%;
    justify-content: center;
  }

  .banner-content {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .banner-icon {
    width: 40px;
    height: 40px;
  }

  .banner-link {
    width: 100%;
    justify-content: center;
  }

  /* 核心修复：内边距自适应 */
  .card-header {
    padding: 12px 16px;
    flex-wrap: wrap; /* 允许标题和按钮换列 */
    gap: 8px;
  }

  .card-body {
    padding: 16px;
  }

  .form-actions {
    flex-direction: column;
  }

  .form-actions .btn {
    width: 100%;
    justify-content: center;
  }

  /* Token 列表自适应 */
  .token-item {
    padding: 16px;
    width: 100%;
  }

  .token-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .token-value-row {
    margin: 10px 0;
  }

  .token-value {
    padding: 10px;
  }

  .token-actions .btn {
    flex: 1;
    min-width: 100px;
    justify-content: center;
  }
}

.group-header {
  margin-bottom: 24px;
}

.group-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: 8px;
}

.group-desc {
  font-size: 14px;
  color: var(--color-text-tertiary);
  line-height: 1.6;
}

.card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  margin-bottom: 24px;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.card-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}

.card-body {
  padding: 24px;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* Token 列表卡片：当内容过多时允许滚动 */
.settings-column:last-child .card {
  min-height: 320px;
}

.settings-column:last-child .card-body {
  overflow: hidden;
  max-height: none;
}

.form-group {
  margin-bottom: 20px;
}

.form-label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-primary);
  margin-bottom: 8px;
}

.form-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  font-size: 14px;
  transition: all 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-hint {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin-top: 4px;
}

.form-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
}

.btn-primary {
  background: var(--color-primary);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--color-primary-dark);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-outline {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text-primary);
}

.btn-outline:hover {
  background: var(--color-bg-hover);
}

.btn-danger {
  background: #e74c3c;
  color: white;
}

.btn-danger:hover {
  background: #c0392b;
}

.btn-sm {
  padding: 6px 12px;
  font-size: 12px;
}

.btn-icon {
  background: transparent;
  border: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.btn-icon:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--color-text-tertiary);
  gap: 12px;
}

.empty-hint {
  font-size: 13px;
  color: var(--color-text-muted);
  margin-top: 4px;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.token-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-height: 325px;
  overflow-y: auto;
  padding-right: 6px;
}

.token-list::-webkit-scrollbar {
  width: 8px;
}

.token-list::-webkit-scrollbar-track {
  background: var(--color-bg-secondary);
  border-radius: 4px;
}

.token-list::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 4px;
}

.token-list::-webkit-scrollbar-thumb:hover {
  background: var(--color-text-tertiary);
}

.token-item {
  padding: 20px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
}

.token-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.token-header h4 {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}

.token-badges {
  display: flex;
  gap: 8px;
}

.badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.badge-success {
  background: rgba(39, 174, 96, 0.1);
  color: #27ae60;
}

.badge-warning {
  background: rgba(243, 156, 18, 0.1);
  color: #f39c12;
}

.badge-danger {
  background: rgba(231, 76, 60, 0.1);
  color: #e74c3c;
}

.token-details {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 12px;
}

.detail-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.token-value-row {
  margin: 12px 0;
  width: 100%;
}

.token-value {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  font-family: 'Courier New', monospace;
  font-size: 13px;
  width: 100%;
}

.token-value code {
  flex: 1;
  word-break: break-all;
  color: var(--color-text-primary);
  letter-spacing: 0.5px;
}

.token-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

/* 浏览器插件横幅 */
.browser-extension-banner {
  background: linear-gradient(135deg, rgba(52, 152, 219, 0.1) 0%, rgba(155, 89, 182, 0.1) 100%);
  border: 2px solid rgba(52, 152, 219, 0.3);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  transition: all 0.3s ease;
}

.browser-extension-banner:hover {
  border-color: rgba(52, 152, 219, 0.5);
  box-shadow: 0 4px 12px rgba(52, 152, 219, 0.15);
}

.banner-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.banner-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #3498db 0%, #9b59b6 100%);
  border-radius: var(--radius-md);
  color: white;
  flex-shrink: 0;
}

.banner-text {
  flex: 1;
}

.banner-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.banner-desc {
  font-size: 14px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.banner-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: linear-gradient(135deg, #3498db 0%, #9b59b6 100%);
  color: white;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: all 0.2s ease;
  flex-shrink: 0;
  white-space: nowrap;
}

.banner-link:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(52, 152, 219, 0.4);
  color: white;
  text-decoration: none;
}

.banner-link:active {
  transform: translateY(0);
}

.help-section {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 24px;
}

.help-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 16px;
}

.help-content {
  color: var(--color-text-secondary);
  line-height: 1.8;
}

.help-content p {
  margin-bottom: 12px;
}

.help-content ul {
  margin-left: 20px;
  margin-bottom: 12px;
}

.help-content li {
  margin-bottom: 6px;
}

.code-block {
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  overflow-x: auto;
  margin: 12px 0;
}

.api-examples {
  margin: 16px 0;
}

.api-example {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.api-example p {
  margin-bottom: 8px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.api-example .code-block {
  margin: 8px 0;
  font-size: 11px;
  line-height: 1.6;
}

.api-note {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(52, 152, 219, 0.1);
  border-left: 3px solid #3498db;
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.use-cases {
  margin: 16px 0;
}

.use-case {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.use-case p {
  margin-bottom: 8px;
  color: var(--color-text-primary);
}

.use-case p strong {
  font-weight: 600;
  color: var(--color-text-primary);
}

.use-case ol {
  margin: 8px 0;
  padding-left: 20px;
  color: var(--color-text-secondary);
}

.use-case ol li {
  margin-bottom: 4px;
  line-height: 1.6;
}

.use-case code {
  background: var(--color-bg-tertiary);
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: var(--color-text-primary);
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
}

.modal-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}

.modal-body {
  padding: 24px;
}

.modal-footer {
  padding: 20px 24px;
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.warning-text {
  color: #e74c3c;
  font-weight: 600;
  margin-top: 12px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
}

/* Token 成功模态框样式 */
.token-success-content {
  color: var(--color-text-primary);
}

.token-display-box {
  margin: 20px 0;
  padding: 16px;
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.token-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 10px;
}

.token-value-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.token-code {
  flex: 1;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: var(--color-text-primary);
  word-break: break-all;
  user-select: all;
}

.btn-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--color-primary);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.btn-copy:hover {
  background: var(--color-primary-dark);
}

.token-info-box {
  margin: 20px 0;
  padding: 16px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.info-item {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
  font-size: 14px;
}

.info-item:last-child {
  margin-bottom: 0;
}

.info-label {
  font-weight: 600;
  color: var(--color-text-secondary);
  min-width: 80px;
}

.info-value {
  color: var(--color-text-primary);
}

.token-warning-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  background: rgba(243, 156, 18, 0.1);
  border: 1px solid rgba(243, 156, 18, 0.3);
  border-radius: var(--radius-md);
  color: #f39c12;
  font-size: 13px;
  line-height: 1.6;
  margin-top: 16px;
}

.token-warning-box :deep(.icon) {
  flex-shrink: 0;
  margin-top: 2px;
}
</style>
