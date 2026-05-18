<template>
  <div class="content-view">
    <div class="content-container">
      
      <!-- 授权检测提示 -->
      <div v-if="!licenseValid" class="license-alert">
        <div class="license-icon">🔒</div>
        <h2>{{ checkingLicense ? '正在验证...' : '需要授权' }}</h2>
        <p v-if="!checkingLicense">该功能为高级功能，请前往发卡平台购买授权</p>
        
        <div class="license-features" v-if="!checkingLicense">
          <div class="feature-item">
            <Icon name="check" :size="16" />
            <span>支持国内外主流视频平台解析下载</span>
          </div>
          <div class="feature-item">
            <Icon name="check" :size="16" />
            <span>支持 4K / 1080P 等多种分辨率下载</span>
          </div>
          <div class="feature-item">
            <Icon name="check" :size="16" />
            <span>支持 Cookie 配置，解析登录可见内容</span>
          </div>
          <div class="feature-item">
            <Icon name="check" :size="16" />
            <span>极致的解析速度与下载稳定性</span>
          </div>
        </div>

        <p v-else>正在连接服务器验证授权状态...</p>
        <div class="license-actions" v-if="!checkingLicense">
          <a href="https://c.fakamiao.top/shopDetail/6WNe26" target="_blank" class="btn btn-primary">购买授权</a>
          <button @click="checkLicense(true)" class="btn btn-secondary">刷新状态</button>
        </div>
        <div class="license-actions" v-else>
            <span class="spinner" style="border-color: var(--color-primary); border-top-color: transparent;"></span>
        </div>
      </div>

      <!-- 主内容区域 (已授权) -->
      <div v-else class="content-wrapper">
        <!-- 头部区域 (仅在授权后显示) -->
        <header class="header-section">
          <div class="icon-glow theme-gradient">
            <Icon name="link" :size="40" />
          </div>
          <h1>通用解析</h1>
        </header>

        <div class="input-section">
          <div class="input-tools-top">
            <button type="button" class="btn btn-xs btn-secondary" @click="handlePaste" title="粘贴">
              <Icon name="file-text" :size="14" /> 粘贴
            </button>
            <button type="button" class="btn btn-xs btn-danger" @click="clearInput" title="清空">
              <Icon name="trash" :size="14" /> 清空
            </button>
          </div>
          <div class="input-wrapper">
            <input 
              v-model="url" 
              type="url" 
              placeholder="请粘贴视频链接到这里..." 
              @keyup.enter="handleParse"
              :disabled="loading"
            />
          </div>
        </div>

        <!-- Cookie 设置与操作 -->
        <div class="action-section">

          <!-- Cookie 设置 -->
          <div class="cookie-section">
             <button type="button" @click="showCookie = !showCookie" class="cookie-toggle">
                <span class="toggle-label">
                  <span class="label-text">Cookie 设置 <span class="optional">(可选)</span></span>
                  <span class="tip">用于访问会员或登录可见内容</span>
                </span>
                <svg 
                  xmlns="http://www.w3.org/2000/svg" 
                  width="20" height="20" 
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                  class="arrow-icon"
                  :class="{ 'rotate': showCookie }"
                >
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
             </button>
             
             <div v-show="showCookie" class="cookie-content">
               <textarea 
                  v-model="cookie"
                  rows="3"
                  placeholder="格式: key=value; key2=value2"
                  class="cookie-input"
               ></textarea>
               <div class="cookie-actions">
                 <button type="button" @click="saveCookie" class="btn btn-xs btn-success">
                    <Icon name="check" :size="14" /> 保存
                 </button>
                 <button type="button" @click="clearCookie" class="btn btn-xs btn-danger">
                    <Icon name="trash" :size="14" /> 清除
                 </button>
               </div>
             </div>
          </div>

          <!-- 解析按钮 -->
          <button @click="handleParse" :disabled="loading || !url" class="btn btn-primary btn-lg w-full">
            <span v-if="loading" class="spinner"></span>
            <span v-else class="btn-content">
              <Icon name="search" :size="20" />
              开始解析
            </span>
          </button>
        </div>

        <!-- 错误提示 -->
        <div v-if="error" class="alert alert-error">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
          <div class="alert-content">
            <h3>解析失败</h3>
            <p>{{ error }}</p>
          </div>
        </div>

        <!-- 解析结果展示 -->
        <ParserResultCard
          v-if="result"
          :title="result.title"
          :author="result.channel"
          :thumbnail="result.thumbnail"
          :duration="result.duration"
          :time="formatDate(result.upload_date)"
          platform="universal"
        >
          <!-- 可用格式列表 -->
          <div class="formats-section">
            <h3 class="section-title">可用下载格式</h3>
            
            <div class="formats-grid">
              <div 
                v-for="(format, index) in visibleFormats" 
                :key="format.format_id"
                class="format-card"
              >
                <div class="format-badge">{{ format.ext.toUpperCase() }}</div>
                
                <div class="format-header">
                  <span class="resolution">{{ formatResolution(format) }}</span>
                  <span v-if="format.fps" class="fps">{{ format.fps }}fps</span>
                </div>
                
                <div class="format-details">
                   <div class="detail-row"><span>编码:</span> <span class="val">{{ format.vcodec !== 'none' ? format.vcodec : format.acodec }}</span></div>
                   <div class="detail-row"><span>大小:</span> <span class="val">{{ formatFilesize(format) }}</span></div>
                </div>
                
                <button 
                  @click="downloadFormat(format.format_id)"
                  :disabled="downloadingId === format.format_id"
                  class="btn btn-primary w-full"
                  :class="{ 'btn-loading': downloadingId === format.format_id }"
                >
                   <span v-if="downloadingId === format.format_id" class="spinner-sm"></span>
                   <span v-else>{{ downloadingId === format.format_id ? '添加中...' : '下载此版本' }}</span>
                </button>
              </div>
            </div>
          </div>

          <template #footer>
            <div v-if="result.formats.length > 6" class="more-formats">
               <button @click="showAllFormats = !showAllFormats" class="btn btn-outline w-full">
                 {{ showAllFormats ? '收起部分格式' : `显示全部 ${result.formats.length} 个格式` }}
               </button>
            </div>
          </template>
        </ParserResultCard>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import ParserResultCard from '@/components/business/ParserResultCard.vue'
import { universalApi } from '@/api/universal'
import { globalConfigApi, licenseApi } from '@/api'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const toast = useToast()

// 状态
const url = ref('')
const cookie = ref('')
const showCookie = ref(false)
const loading = ref(false)
const result = ref(null)
const error = ref(null)
const downloadingId = ref(null)
const showAllFormats = ref(false)

// 授权状态 - 优先读取本地缓存
const cachedLicense = localStorage.getItem('license_status')
const licenseValid = ref(cachedLicense === 'true')
const checkingLicense = ref(cachedLicense === null)

// 计算属性
const visibleFormats = computed(() => {
    if (!result.value || !result.value.formats) return []
    const list = result.value.formats
    return showAllFormats.value ? list : list.slice(0, 6)
})

// 初始化
onMounted(async () => {
    checkLicense(false)  // false = 使用后端缓存检查，不强制刷新
    const savedUrl = localStorage.getItem('universal_last_url')
    if (savedUrl) url.value = savedUrl
    try {
        const res = await globalConfigApi.getConfig()
        if (res && res.wnxt_cookie) {
            cookie.value = res.wnxt_cookie
        }
    } catch (e) {
        console.warn('Failed to load cookies', e)
    }
})

async function checkLicense(force = false) {
    if (cachedLicense === null) {
        checkingLicense.value = true
    }
    try {
        // 只有在手动强制刷新时，才请求后端去授权服务器验证
        if (force) {
            try {
                await licenseApi.refresh()
            } catch (e) {
                console.warn('刷新授权失败，将使用缓存状态', e)
            }
        }
        
        const res = await licenseApi.getStatus()
        licenseValid.value = res.is_licensed
        localStorage.setItem('license_status', res.is_licensed)
        
        if (force && res.is_licensed) {
             toast.success('授权状态已刷新')
        }
    } catch (e) {
        if (cachedLicense === null) {
             licenseValid.value = false
        }
        console.error('License check failed:', e)
    } finally {
        checkingLicense.value = false
    }
}

async function handlePaste() {
  try {
    const text = await navigator.clipboard.readText()
    url.value = text
  } catch (e) {
    toast.error('无法读取剪贴板，请手动粘贴链接')
  }
}

async function clearInput() {
  url.value = ''
  result.value = null
  error.value = null
}

async function saveCookie() {
    if (!cookie.value.trim()) return
    try {
        await globalConfigApi.saveConfig({ wnxt_cookie: cookie.value })
        toast.success('Cookie 已保存')
    } catch (e) {
        toast.error('Cookie 保存失败: ' + (e.message || '未知错误'))
    }
}

async function clearCookie() {
    try {
        await globalConfigApi.clearConfig(['wnxt_cookie'])
        cookie.value = ''
        toast.success('Cookie 已清除')
    } catch (e) {
       toast.error('Cookie 清除失败: ' + (e.message || '未知错误'))
    }
}

async function handleParse() {
    if (!url.value) return
    loading.value = true
    error.value = null
    result.value = null
    localStorage.setItem('universal_last_url', url.value)
    try {
        const res = await universalApi.parse(url.value)
        if (res && res.success) {
            result.value = res.data
        } else {
            throw new Error(res.error || '解析未返回数据')
        }
    } catch (e) {
        error.value = e.response?.data?.detail || e.message || '解析请求失败'
    } finally {
        loading.value = false
    }
}

async function downloadFormat(formatId) {
    if (downloadingId.value) return
    downloadingId.value = formatId
    try {
        await universalApi.download({
            url: result.value.webpage_url || url.value,
            format_id: formatId
        })
        toast.success('下载任务已添加，可前往「下载任务」页面查看')
    } catch (e) {
        const msg = e.response?.data?.detail || e.message || '添加任务失败'
        toast.error('添加下载任务失败: ' + msg)
    } finally {
        downloadingId.value = null
    }
}

function formatDuration(seconds) {
    if (!seconds) return '未知'
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}` : `${m}:${s.toString().padStart(2, '0')}`
}

function formatNumber(num) {
    return new Intl.NumberFormat().format(num || 0)
}

function formatDate(dateStr) {
    if (!dateStr || dateStr.length !== 8) return dateStr
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
}

function formatFilesize(format) {
    const bytes = format.filesize || format.filesize_approx
    if (!bytes) return '未知'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatResolution(format) {
    // 视频格式：有分辨率高度
    if (format.height && format.height > 0) {
        return `${format.height}P`
    }
    
    // 纯音频：无高度，vcodec 通常为 'none'，我们在后端把 resolution 设为 'audio'
    const isAudio = format.resolution === 'audio' || format.vcodec === 'none'
    if (isAudio) {
        const ext = (format.ext || '').toUpperCase()
        const bitrate = format.tbr || format.abr
        if (bitrate) {
            return `音频 · ${ext || 'AUDIO'} · ${Math.round(bitrate)}kbps`
        }
        return `音频 · ${ext || 'AUDIO'}`
    }
    
    // 兜底
    return 'Audio/Unknown'
}
</script>

<style scoped>
/* 页面布局 */
.content-view {
  min-height: 100%;
  padding: var(--spacing-xl) var(--spacing-lg);
  display: flex;
  justify-content: center;
  align-items: flex-start;
}

.content-container {
  width: 100%;
  max-width: 900px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-md);
  padding: var(--spacing-xl);
}

/* 标题区域 */
.header-section {
  text-align: center;
  margin-bottom: 30px;
}

.icon-glow.theme-gradient {
  width: 60px;
  height: 60px;
  border-radius: 16px;
  background: var(--gradient-header);
  color: white;
  box-shadow: 0 8px 16px var(--color-primary-light);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 15px;
}

[data-theme="dark"] .icon-glow.theme-gradient {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  background: linear-gradient(135deg, #af3024 0%, #c47d0e 100%);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

h1 {
  font-size: 2rem;
  font-weight: 800;
  margin-bottom: 8px;
  background: linear-gradient(135deg, var(--color-text-primary), var(--color-text-secondary));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: var(--color-text-tertiary);
}

.input-section {
  margin-bottom: 30px;
}

.input-tools-top {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  justify-content: flex-end;
}

[data-theme="dark"] .btn-danger:not(.btn-clear-action) {
  background: rgba(239, 68, 68, 0.15) !important;
  color: #ff6b6b !important;
  border: 1px solid rgba(239, 68, 68, 0.2) !important;
}

[data-theme="dark"] .btn-secondary {
  background: rgba(255, 255, 255, 0.05) !important;
  color: var(--color-text-secondary) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
}

.input-wrapper {
  position: relative;
  background: var(--color-bg-primary);
  border: 2px solid var(--color-border);
  border-radius: 16px;
  padding: 4px;
  transition: all 0.3s ease;
}

.input-wrapper:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px rgba(var(--color-primary-rgb), 0.1);
}

.input-wrapper input {
  width: 100%;
  border: none;
  background: transparent;
  padding: 16px;
  font-size: 1rem;
  color: var(--color-text-primary);
  outline: none;
}

/* Cookie 区域 */
.cookie-section {
  margin-top: var(--spacing-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: var(--color-bg-tertiary);
}

.cookie-toggle {
  width: 100%;
  padding: var(--spacing-md) var(--spacing-lg);
  background: transparent;
  border: none;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  color: var(--color-text-primary);
  transition: background var(--transition-fast);
}

.cookie-toggle:hover {
  background: var(--color-bg-hover);
}

.toggle-label {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  gap: 4px;
  font-size: 0.95rem;
  font-weight: 500;
}

.toggle-label .label-text {
  display: flex;
  align-items: center;
  gap: 6px;
}

.toggle-label .optional {
  font-size: 0.85rem;
  color: var(--color-text-tertiary);
  font-weight: 400;
}

.toggle-label .tip {
  font-size: 0.8rem;
  color: var(--color-text-tertiary);
  font-weight: 400;
}

.cookie-content {
  padding: var(--spacing-lg);
  background: var(--color-bg-card);
  border-top: 1px solid var(--color-border);
}

.cookie-input {
  width: 100%;
  padding: var(--spacing-md);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 0.9rem;
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-md);
  resize: vertical;
  font-family: 'Consolas', 'Monaco', monospace;
}

.cookie-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(230, 126, 34, 0.1);
}

.cookie-actions {
  display: flex;
  gap: var(--spacing-md);
}

.action-section {
  margin-bottom: 30px;
}

/* 按钮特定宽度 */
.btn-submit {
  width: 100%;
  margin-top: var(--spacing-lg);
  padding: 1rem;
}

[data-theme="dark"] .btn-primary.btn-lg {
  background: linear-gradient(135deg, #af3024 0%, #c47d0e 100%);
  border: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

[data-theme="dark"] .btn-primary.btn-lg:hover:not(:disabled) {
  background: linear-gradient(135deg, #bd3427 0%, #d68910 100%);
}

/* 视频信息卡片 */
.video-info-card {
  overflow: hidden;
}

.info-layout {
  display: flex;
  gap: var(--spacing-xl);
  flex-direction: column;
}

@media (min-width: 768px) {
  .info-layout { flex-direction: row; }
}

.thumbnail-wrapper {
  position: relative;
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  min-width: 280px;
  flex-shrink: 0;
}

.thumbnail-wrapper img {
  width: 100%;
  aspect-ratio: 16/9;
  display: block;
  object-fit: cover;
}

.duration-badge {
  position: absolute;
  bottom: 12px;
  right: 12px;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(4px);
  color: white;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.75rem;
  font-weight: 600;
}

.video-title {
  margin: 0 0 var(--spacing-md) 0;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.3;
  color: var(--color-text-primary);
}

.meta-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-lg);
}

.tag {
  font-size: 0.85rem;
  color: var(--color-text-secondary);
  background: var(--color-bg-secondary);
  padding: 4px 12px;
  border-radius: var(--radius-full);
}

.description {
  font-size: 0.9rem;
  line-height: 1.6;
  color: var(--color-text-tertiary);
  background: var(--color-bg-tertiary);
  padding: var(--spacing-lg);
  border-radius: var(--radius-lg);
  max-height: 120px;
  overflow-y: auto;
}

/* 格式选择 */
.formats-section {
  margin-top: var(--spacing-xl);
}

.section-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-lg);
}

.formats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--spacing-lg);
}

.format-card {
  position: relative;
  display: flex;
  flex-direction: column;
}

.format-card:hover {
  transform: translateY(-4px);
  border-color: var(--color-primary);
}

.format-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: 0.75rem;
  padding: 2px 8px;
  font-weight: 700;
  border-radius: var(--radius-sm);
}

.format-header {
  margin-bottom: var(--spacing-md);
}

.resolution {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--color-text-primary);
  margin-right: var(--spacing-xs);
}

.fps {
  color: var(--color-text-muted);
  font-size: 0.9rem;
}

.format-details {
  font-size: 0.875rem;
  color: var(--color-text-tertiary);
  margin-bottom: var(--spacing-lg);
  flex: 1;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid var(--color-border);
}

.val {
  color: var(--color-text-secondary);
  font-weight: 600;
}

/* 授权提示 */
.license-alert {
  text-align: center;
  background: var(--color-bg-card);
  border: 2px dashed var(--color-error);
  border-radius: var(--radius-xl);
  padding: 3rem 4rem;
  margin: 2rem auto;
  max-width: 800px;
  box-shadow: var(--shadow-xl);
}

.license-icon {
  font-size: 3rem;
  margin-bottom: var(--spacing-lg);
}

.license-alert h2 {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 12px;
  color: var(--color-text-primary);
}

.license-alert p {
  color: var(--color-text-secondary);
  margin-bottom: 24px;
}

.license-features {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px 40px;
  margin: 32px 0;
  text-align: left;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
  font-size: 15px;
  white-space: nowrap;
}

.feature-item .icon {
  color: var(--color-success);
}

.license-actions {
  margin-top: var(--spacing-xl);
  display: flex;
  justify-content: center;
  gap: var(--spacing-lg);
}

.license-actions .btn {
  padding: 10px 32px;
  font-size: 16px;
  font-weight: 500;
  border-radius: 12px;
}

/* 动画与微交互 */
.spinner {
  width: 20px;
  height: 20px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.arrow-icon { transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
.rotate { transform: rotate(180deg); }

/* 移动端适配 */
@media (max-width: 780px) {
  .content-view {
    padding: 0;
  }

  .content-container {
    padding: var(--spacing-md);
    border-radius: var(--radius-lg);
    border: none;
    box-shadow: none;
  }

  .license-alert {
    padding: 24px 18px;
    margin: 20px 16px;
    border-radius: 18px;
  }

  .license-icon {
    font-size: 2.4rem;
  }

  .license-alert h2 {
    font-size: 22px;
  }

  .license-alert p {
    font-size: 14px;
  }

  .license-features {
    grid-template-columns: 1fr;
    gap: 10px 0;
    margin: 20px 0;
  }

  .feature-item {
    font-size: 13px;
    white-space: normal;
  }

  .license-actions {
    flex-direction: column;
    gap: 10px;
  }

  .license-actions .btn {
    width: 100%;
    padding: 10px 0;
    font-size: 14px;
  }

  .header-section {
    margin-bottom: var(--spacing-md);
  }

  .icon-glow.theme-gradient {
    width: 50px;
    height: 50px;
  }

  [data-theme="dark"] .btn-danger:not(.btn-clear-action) {
    background: rgba(239, 68, 68, 0.15) !important;
    color: #ff6b6b !important;
    border: 1px solid rgba(239, 68, 68, 0.2) !important;
  }
}
</style>
