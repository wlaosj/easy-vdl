<template>
  <div class="content-view">
    <div class="content-container">
      <!-- Header Section -->
      <div class="header-section">
        <div class="icon-glow theme-gradient">
          <Icon name="video" :size="40" />
        </div>
        <h1>某音某书</h1>
        <p class="subtitle">支持抖音、小红书平台无水印视频提取</p>
      </div>

      <!-- Mode Switcher -->
      <div class="mode-toggle">
        <button 
          class="tab-btn"
          :class="{ active: mode === 'single' }"
          @click="mode = 'single'"
        >
          单链接解析
        </button>
        <button 
          class="tab-btn"
          :class="{ active: mode === 'batch' }"
          @click="mode = 'batch'"
        >
          批量解析
        </button>
      </div>

      <!-- Single Mode Input -->
      <div v-if="mode === 'single'" class="input-section">
        <div class="input-tools-top">
          <button class="btn btn-xs btn-secondary" @click="handlePaste" title="粘贴并自动提取">
            <Icon name="file-text" :size="14" /> 粘贴
          </button>
          <button class="btn btn-xs btn-danger" @click="clearInput" title="清空">
            <Icon name="trash" :size="14" /> 清空
          </button>
          <button class="btn btn-xs btn-warning" @click="goToCookieSettings" title="Cookie设置">
            <Icon name="link" :size="14" /> Cookie设置
          </button>
        </div>
        <div class="input-wrapper">
          <input 
            v-model="inputUrl" 
            type="text" 
            placeholder="粘贴视频链接，支持自动提取分享口令..." 
            @paste="onPaste"
            @keyup.enter="startParse"
          />
        </div>
        <transition name="fade">
          <div v-if="extractionTip" class="extraction-tip">
            ✅ {{ extractionTip }}
          </div>
        </transition>
      </div>

      <!-- Batch Mode Input -->
      <div v-else class="input-section">
        <div class="input-tools-top">
          <button class="btn btn-xs btn-warning" @click="goToCookieSettings" title="Cookie设置">
            <Icon name="link" :size="14" /> Cookie设置
          </button>
        </div>
        <div class="batch-tips">
          <div class="tip-header">
            <span class="emoji">📦</span>
            <span>批量处理 (单次最多5个)</span>
          </div>
          <div class="tip-content">
            支持混合抖音和小红书链接，自动提取有效网址
          </div>
        </div>
        <div class="input-wrapper">
          <textarea 
            v-model="batchInput" 
            placeholder="每行输入一个链接，支持：&#10;✓ douyin.com/video/xxx&#10;✓ v.douyin.com/xxx&#10;✓ xiaohongshu.com/explore/xxx"
            rows="6"
          ></textarea>
        </div>
      </div>

      <!-- Action Button -->
      <div class="action-section">
        <button 
          class="btn btn-primary btn-lg w-full" 
          :disabled="loading || (mode === 'single' ? !inputUrl : !batchInput)"
          @click="startParse"
        >
          <span v-if="loading" class="spinner"></span>
          <span v-else>{{ mode === 'single' ? '开始解析' : '批量解析' }}</span>
        </button>
      </div>

      <!-- Loading State & Funny Tips -->
      <transition name="fade">
        <div v-if="loading" class="loading-status">
          <div class="loading-pulse"></div>
          <p class="funny-tip">{{ currentTip }}</p>
        </div>
      </transition>

      <!-- Single Result -->
      <ParserResultCard 
        v-if="result && mode === 'single'"
        :title="result.title"
        :author="result.author"
        :thumbnail="getProxyImage(result.thumbnail_url, result.platform)"
        :platform="result.platform"
        :time="result.create_time"
      >
        <div class="short-video-info">
          <!-- 这里可以放一些短视频特有的额外信息，比如点赞数等，目前保持简洁 -->
        </div>

        <template #footer>
             <div class="primary-actions">
                <button class="btn btn-primary flex-1" @click="downloadVideo('server')" :disabled="serverDownloading || browserDownloading">
                  <span v-if="serverDownloading" class="spinner btn-spinner"></span>
                  <span v-else>服务器下载</span>
                </button>
                <button class="btn btn-primary flex-1" @click="downloadVideo('browser')" :disabled="serverDownloading || browserDownloading">
                  <span v-if="browserDownloading" class="spinner btn-spinner"></span>
                  <span v-else>本地下载</span>
                </button>
             </div>
            
            <div class="checkbox-row">
               <label title="下载时生成NFO元数据文件">
                  <input type="checkbox" v-model="generateNfo"> 生成NFO文件
               </label>
            </div>
        </template>
      </ParserResultCard>

      <!-- Batch Results -->
      <transition name="slide-up">
        <div v-if="batchResults.length > 0 && mode === 'batch'" class="batch-results">
          <div class="batch-header">
            <h3>解析结果 ({{ batchSuccessCount }}/{{ batchResults.length }})</h3>
            <div class="batch-actions" v-if="batchSuccessCount > 0">
               <button class="btn btn-primary" @click="batchDownloadServer">
                 批量下载全部成功项
               </button>
            </div>
          </div>
          
          <div class="batch-list">
            <div 
              v-for="(item, idx) in batchResults" 
              :key="idx" 
              class="batch-item"
              :class="{ success: item.success, error: !item.success }"
            >
              <div v-if="item.success" class="batch-item-content">
                <img :src="getProxyImage(item.thumbnail_url, item.platform)" class="batch-thumb" />
                <div class="batch-info">
                  <div class="batch-title">{{ item.title || '视频 ' + (idx+1) }}</div>
                  <div class="batch-meta">{{ item.platform }} · {{ item.author || '未知作者' }}</div>
                </div>
                <div class="batch-status">
                  <Icon name="check" :size="18" />
                </div>
              </div>
              <div v-else class="batch-item-content error">
                <div class="batch-error-icon"><Icon name="alert-triangle" :size="20"/></div>
                <div class="batch-info">
                  <div class="batch-title">解析失败</div>
                  <div class="batch-meta">{{ item.url }}</div>
                  <div class="error-msg">{{ item.error }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </transition>

      <!-- Error Message -->
      <transition name="fade">
        <div v-if="error" class="error-banner">
          <Icon name="alert-triangle" :size="20" />
          <span>{{ error }}</span>
          <button @click="error = ''" class="close-btn"><Icon name="x" :size="14"/></button>
        </div>
      </transition>

      <!-- Global Modal -->
      <Modal 
        v-model:show="modal.show"
        :title="modal.title"
        :type="modal.type"
      >
        <div style="font-size: 1.1rem; padding: 10px 0;">
          {{ modal.message }}
        </div>
        <template #footer>
          <button class="btn btn-primary" @click="modal.show = false">确定</button>
        </template>
      </Modal>

      <!-- Confirm Modal -->
      <Modal 
        v-model:show="confirmModal.show"
        :title="confirmModal.title"
        :type="confirmModal.type"
      >
        <div style="font-size: 1.1rem; padding: 10px 0;">
          {{ confirmModal.message }}
        </div>
        <template #footer>
          <div style="display: flex; gap: 12px; justify-content: flex-end;">
            <button class="btn btn-secondary" @click="handleConfirmCancel">取消</button>
            <button class="btn btn-primary" @click="handleConfirmOk">确定</button>
          </div>
        </template>
      </Modal>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'
import ParserResultCard from '@/components/business/ParserResultCard.vue'
import { scraperApi } from '@/api/scraper'

const router = useRouter()
const route = useRoute()
const mode = ref('single')
const inputUrl = ref('')
const batchInput = ref('')
const loading = ref(false)
const result = ref(null)
const batchResults = ref([])
const error = ref('')
const currentTip = ref('')
const extractionTip = ref('')
const generateNfo = ref(true)

const serverDownloading = ref(false)
const browserDownloading = ref(false)
const downloading = computed(() => serverDownloading.value || browserDownloading.value)

const modal = ref({
  show: false,
  title: '',
  message: '',
  type: 'info'
})

const showModal = (title, message, type = 'info') => {
  modal.value = {
    show: true,
    title,
    message,
    type
  }
}

// 确认对话框
const confirmModal = ref({
  show: false,
  title: '',
  message: '',
  type: 'info',
  resolve: null
})

const showConfirm = (title, message, type = 'info') => {
  return new Promise((resolve) => {
    confirmModal.value = {
      show: true,
      title,
      message,
      type,
      resolve
    }
  })
}

const handleConfirmOk = () => {
  if (confirmModal.value.resolve) {
    confirmModal.value.resolve(true)
  }
  confirmModal.value.show = false
  confirmModal.value.resolve = null
}

const handleConfirmCancel = () => {
  if (confirmModal.value.resolve) {
    confirmModal.value.resolve(false)
  }
  confirmModal.value.show = false
  confirmModal.value.resolve = null
}

let tipInterval = null

// Funny tips data
const TIPS = [
  "🤖 正在分析视频链接...",
  "🔍 检测到这是一个有趣的视频...",
  "📱 正在与平台服务器对话...",
  "🎬 视频信息获取中，请稍候...",
  "💫 正在提取无水印视频地址...",
  "✨ 解析进度：正在处理中...",
  "🌟 马上就好，再等一下下...",
  "🎯 解析即将完成，请耐心等待...",
  "🚀 正在整理数据...",
  "🎨 正在为视频添加魔法效果...",
  "🎪 小机器人正在努力工作...",
  "🎭 正在破解视频密码...",
]

const batchSuccessCount = computed(() => {
  return batchResults.value.filter(r => r.success).length
})

const startTips = () => {
  currentTip.value = TIPS[0]
  let idx = 0
  tipInterval = setInterval(() => {
    idx = (idx + 1) % TIPS.length
    currentTip.value = TIPS[idx]
  }, 1500)
}

const stopTips = () => {
  if (tipInterval) clearInterval(tipInterval)
  tipInterval = null
}

const extractUrl = (text) => {
  if (!text) return ''
  // 抖音匹配（支持短链 v.douyin.com 和原生链）
  const douyinRegex = /https?:\/\/([a-z0-9-]+\.)?(douyin\.com|iesdouyin\.com)\/[a-zA-Z0-9/._?=&%-]+/gi
  const douyinMatch = text.match(douyinRegex)
  if (douyinMatch) return douyinMatch[0]

  // 小红书匹配（支持 xiaohongshu.com 和 xhslink.com 短链）
  const xhsRegex = /https?:\/\/([a-z0-9-]+\.)?(xiaohongshu\.com|xhslink\.com)\/[a-zA-Z0-9/._?=&%-]+/gi
  const xhsMatch = text.match(xhsRegex)
  if (xhsMatch) return xhsMatch[0]

  return ''
}

const validateUrl = (url) => {
  const douyinPattern = /https?:\/\/([a-z0-9-]+\.)?(douyin\.com|iesdouyin\.com)/i
  const xhsPattern = /https?:\/\/([a-z0-9-]+\.)?(xiaohongshu\.com|xhslink\.com)/i
  return douyinPattern.test(url) || xhsPattern.test(url)
}

const handlePaste = async () => {
  try {
    const text = await navigator.clipboard.readText()
    const extracted = extractUrl(text)
    if (extracted) {
      inputUrl.value = extracted
      extractionTip.value = `已自动提取: ${extracted}`
      setTimeout(() => extractionTip.value = '', 3000)
    } else {
      inputUrl.value = text
    }
  } catch (e) {
    error.value = '无法访问剪贴板，请手动粘贴'
  }
}

const onPaste = (e) => {
  // Allow default paste, then clean up
  setTimeout(() => {
    const raw = inputUrl.value
    const extracted = extractUrl(raw)
    if (extracted && extracted !== raw) {
      inputUrl.value = extracted
      extractionTip.value = '已自动净化链接'
      setTimeout(() => extractionTip.value = '', 3000)
    }
  }, 100)
}

const clearInput = () => {
  inputUrl.value = ''
  result.value = null
  error.value = ''
}

const goToCookieSettings = () => {
  router.push({ path: '/settings', query: { tab: 'cookie' } })
}

const getProxyImage = (url, platform) => {
  if (!url) return ''
  if (url.startsWith('data:')) return url
  return `/api/dyd/proxy-image?url=${encodeURIComponent(url)}&platform=${platform || 'douyin'}`
}

const handleImageError = (e) => {
  e.target.style.display = 'none'
  // Could Show fallback icon
}

const startParse = async () => {
  loading.value = true
  error.value = ''
  result.value = null
  batchResults.value = []
  
  startTips()

  try {
    if (mode.value === 'single') {
       if (!inputUrl.value) throw new Error('请输入链接')
       const cleanUrl = extractUrl(inputUrl.value) || inputUrl.value
       
       if (!validateUrl(cleanUrl)) {
         throw new Error('仅支持抖音或小红书链接')
       }
       
       const res = await scraperApi.parseShortVideo(cleanUrl)
       if (res.status === 'success') {
         // Standardize response
         result.value = {
           ...res,
           platform: res.platform || 'douyin' // default
         }
       } else {
         throw new Error(res.detail || '解析失败')
       }
    } else {
       // Batch
       if (!batchInput.value) throw new Error('请输入链接')
       const urls = batchInput.value.split('\n').map(u => u.trim()).filter(u => u)
       if (urls.length > 5) throw new Error('批量解析最多支持5个链接')
       if (urls.length === 0) throw new Error('没有有效的链接')

       const douyinUrls = urls.filter(u => !u.includes('xiaohongshu') && !u.includes('xhslink'))
       const xhsUrls = urls.filter(u => u.includes('xiaohongshu') || u.includes('xhslink'))
       
       let results = []
       
       if (douyinUrls.length) {
         try {
           const dRes = await scraperApi.parseBatchShortVideo(douyinUrls)
           if (dRes.status === 'success' && dRes.results) {
              results = [...results, ...dRes.results]
           }
         } catch(e) {
           results = [...results, ...douyinUrls.map(u => ({ url: u, success: false, error: '批量接口请求失败' }))]
         }
       }
       
       if (xhsUrls.length) {
         const xPromises = xhsUrls.map(async u => {
           try {
             const res = await scraperApi.parseShortVideo(u)
             return { ...res, url: u, success: res.status === 'success' }
           } catch(e) {
             return { url: u, success: false, error: e.message }
           }
         })
         const xRes = await Promise.all(xPromises)
         results = [...results, ...xRes]
       }
       
       batchResults.value = results
    }

  } catch (e) {
    error.value = e.message || '请求失败'
  } finally {
    loading.value = false
    stopTips()
  }
}

const downloadVideo = async (method) => {
  if (!result.value) return 
  
  if (method === 'browser') {
     // Proxy download with authentication
     browserDownloading.value = true
     try {
       const platform = result.value.platform || 'douyin'
       const title = result.value.title || `${platform}_video`
       const safeTitle = title.replace(/[<>:"/\\|?*]/g, '_').slice(0, 80)
       const filename = safeTitle
       const url = `/api/dyd/proxy-download?url=${encodeURIComponent(result.value.video_url)}&filename=${encodeURIComponent(filename)}`
       
       // 获取认证token
       const token = localStorage.getItem('token')
       const headers = {}
       if (token) {
         headers['Authorization'] = `Bearer ${token}`
       }
       
       // 使用 fetch 下载，携带认证头
       const response = await fetch(url, { headers })
       
       if (!response.ok) {
         if (response.status === 403) {
           throw new Error('下载失败：认证失败或视频链接已过期，请重新解析')
         } else if (response.status === 404) {
           throw new Error('下载失败：视频链接不存在')
         } else {
           throw new Error(`下载失败：服务器返回错误 ${response.status}`)
         }
       }
       
       // 获取 blob 数据
       const blob = await response.blob()
       
       // 创建下载链接
       const blobUrl = window.URL.createObjectURL(blob)
       const link = document.createElement('a')
       link.href = blobUrl
       link.download = filename + '.mp4'
       document.body.appendChild(link)
       link.click()
       document.body.removeChild(link)
       
       // 清理 blob URL
       window.URL.revokeObjectURL(blobUrl)
       
       showModal('下载成功', '✅ 视频已开始下载', 'success')
     } catch(e) {
       showModal('下载失败', '❌ ' + (e.message || '下载失败，请稍后重试'), 'error')
     } finally {
       browserDownloading.value = false
     }
  } else {
     // Server download
     serverDownloading.value = true
     try {
       await scraperApi.downloadShortVideo(result.value.original_url || inputUrl.value, generateNfo.value)
       showModal('提交成功', '✅ 下载任务已添加至后台', 'success')
     } catch(e) {
       showModal('添加失败', '❌ 添加失败: ' + e.message, 'error')
     } finally {
       serverDownloading.value = false
     }
  }
}

const batchDownloadServer = async () => {
    const confirmed = await showConfirm(
      '批量下载确认',
      `确定要添加 ${batchSuccessCount.value} 个任务到后台下载吗？`,
      'info'
    )
    if (!confirmed) return
    
    // Iterate and add
    let count = 0;
    for(const item of batchResults.value) {
        if(item.success) {
            try {
                await scraperApi.downloadShortVideo(item.original_url || item.url, true)
                count++
            } catch(e) {
                console.error(e)
            }
        }
    }
    showModal('批量提交', `✅ 已添加 ${count} 个任务`, 'success')
}


const checkAutoParse = () => {
  const url = route.query.url
  if (url) {
    inputUrl.value = decodeURIComponent(url)
    setTimeout(() => {
      startParse()
    }, 100)
  }
}

onMounted(() => {
  checkAutoParse()
})

watch(() => route.query.url, () => {
  checkAutoParse()
})

onBeforeUnmount(() => {
  stopTips()
})
</script>

<style scoped>
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

/* Header */
.header-section {
  text-align: center;
  margin-bottom: 30px;
}

.icon-glow {
  width: 60px;
  height: 60px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 15px;
  transition: all 0.3s ease;
}

.icon-glow.theme-gradient {
  background: var(--gradient-header);
  color: white;
  box-shadow: 0 8px 16px var(--color-primary-light);
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
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  color: var(--color-text-tertiary);
}

/* Mode Switcher */
.mode-toggle {
  display: inline-flex;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  padding: 2px;
  margin-bottom: var(--spacing-md);
  background: var(--color-bg-primary);
  width: fit-content;
  margin-left: auto;
  margin-right: auto;
}

.tab-btn {
  border: none;
  background: transparent;
  padding: 6px 16px;
  border-radius: 999px;
  font-size: 0.9rem;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: all var(--transition-fast);
}

.tab-btn:hover:not(.active) {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.tab-btn.active {
  background: var(--color-primary);
  color: white;
  box-shadow: var(--shadow-sm);
}

[data-theme="dark"] .mode-toggle {
  background: #1e1e1e;
  border-color: rgba(255, 255, 255, 0.08);
}

[data-theme="dark"] .tab-btn.active {
  background: linear-gradient(135deg, #af3024 0%, #c47d0e 100%);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

[data-theme="dark"] .tab-btn:not(.active) {
  color: var(--color-text-tertiary);
}

[data-theme="dark"] .btn-primary.btn-lg {
  background: linear-gradient(135deg, #af3024 0%, #c47d0e 100%);
  border: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

[data-theme="dark"] .btn-primary.btn-lg:hover:not(:disabled) {
  background: linear-gradient(135deg, #bd3427 0%, #d68910 100%);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
}

/* Input Section */
.input-section {
  margin-bottom: 30px;
}

.input-tools-top {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  justify-content: flex-end;
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
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
}

.input-wrapper input,
.input-wrapper textarea {
  width: 100%;
  border: none;
  background: transparent;
  padding: 16px;
  font-size: 1rem;
  color: var(--color-text-primary);
  outline: none;
  resize: none;
}

.tool-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 8px;
  border: none;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.tool-btn.paste {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.tool-btn.clear {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.tool-btn:hover {
  filter: brightness(0.95);
}

[data-theme="dark"] .btn-danger:not(.btn-clear-action) {
  background: rgba(239, 68, 68, 0.15) !important;
  color: #ff6b6b !important;
  border: 1px solid rgba(239, 68, 68, 0.2) !important;
}

.extraction-tip {
  margin-top: 8px;
  color: var(--color-success);
  font-size: 0.9rem;
  font-weight: 500;
  text-align: center;
}

.batch-tips {
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}

.tip-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #d97706;
  margin-bottom: 4px;
}

.tip-content {
  color: #b45309;
  font-size: 0.9rem;
}

/* Action Button */
.parse-btn {
  width: 100%;
  padding: 16px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
  font-size: 1.1rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
}

.parse-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  background: var(--color-bg-tertiary);
  color: var(--color-text-muted);
}

.parse-btn:not(:disabled):hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px -6px rgba(37, 99, 235, 0.4);
}

.spinner {
  display: inline-block;
  width: 24px;
  height: 24px;
  border: 3px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.btn-spinner {
  width: 1.2rem;
  height: 1.2rem;
  border-width: 2px;
  margin: 0 auto;
}

/* Loading Status */
.loading-status {
  text-align: center;
  margin-top: 20px;
}

.funny-tip {
  margin-top: 12px;
  color: var(--color-text-secondary);
  font-size: 0.95rem;
  font-weight: 500;
  animation: fadeIn 0.5s ease;
}

/* Result Card */
.result-card {
  margin-top: 30px;
  border-radius: 16px;
  overflow: hidden;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
}

.result-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.platform-tag {
  background: #000;
  color: white;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: capitalize;
}

.success-badge {
  color: var(--color-success);
  font-weight: 600;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 4px;
}

.video-content {
  padding: 20px;
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 24px;
  
  @media (max-width: 768px) {
    grid-template-columns: 1fr;
  }
}

.thumbnail-wrapper {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  aspect-ratio: 16/9;
  background: #000;
}

.thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.play-icon-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 48px;
  height: 48px;
  background: rgba(255,255,255,0.2);
  backdrop-filter: blur(4px);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.info-wrapper {
  display: flex;
  flex-direction: column;
}

.video-title {
  font-size: 1.1rem;
  font-weight: 700;
  margin-bottom: 8px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta-info {
  display: flex;
  gap: 16px;
  color: var(--color-text-tertiary);
  font-size: 0.9rem;
  margin-bottom: 24px;
}

.download-options {
  margin-top: auto;
}

.primary-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

/* 移除冗余的局部下载按钮样式，改用全局 .btn 系列类 */

.modal-btn {
  padding: 8px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  font-size: 0.95rem;
}

.modal-btn.confirm {
  background: var(--color-primary);
  color: white;
}

.dl-btn:disabled {
  opacity: 0.7;
  cursor: wait;
}

.checkbox-row {
  font-size: 0.9rem;
  color: var(--color-text-secondary);
}

/* Batch Results */
.batch-results {
  margin-top: 30px;
}

.batch-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.batch-dl-btn {
  background: var(--color-primary);
  color: white;
  border: none;
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 0.9rem;
  cursor: pointer;
}

.batch-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.batch-item {
  background: var(--color-bg-primary);
  border-radius: 12px;
  padding: 12px;
  border: 1px solid var(--color-border);
}

.batch-item.error {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.05);
}

.batch-item-content {
  display: flex;
  gap: 16px;
  align-items: center;
}

.batch-thumb {
  width: 80px;
  height: 60px;
  border-radius: 6px;
  object-fit: cover;
  background: #000;
}

.batch-info {
  flex: 1;
  min-width: 0;
}

.batch-title {
  font-weight: 600;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.batch-meta {
  font-size: 0.85rem;
  color: var(--color-text-tertiary);
}

.batch-status {
  color: var(--color-success);
}

.batch-error-icon {
  color: #ef4444;
  padding: 0 16px;
}

.error-msg {
  color: #ef4444;
  font-size: 0.85rem;
}

/* Error Banner */
.error-banner {
  margin-top: 20px;
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  padding: 12px 16px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.close-btn {
  margin-left: auto;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
}

/* Transitions */
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* 移除冗余的局部样式 */

.slide-up-enter-active, .slide-up-leave-active { transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1); }
.slide-up-enter-from, .slide-up-leave-to { opacity: 0; transform: translateY(20px); }

/* 移动端适配 */
@media (max-width: 768px) {
  .content-view {
    padding: 0;
  }

  .content-container {
    padding: var(--spacing-md);
    border-radius: var(--radius-lg);
    border: none;
    box-shadow: none;
  }

  .header-section {
    margin-bottom: var(--spacing-md);
  }

  .icon-glow {
    width: 50px;
    height: 50px;
  }

  h1 {
    font-size: 1.5rem;
  }

  .subtitle {
    font-size: 0.9rem;
  }

  /* 模式切换器 */
  .mode-switcher {
    width: fit-content;
    max-width: 100%;
    margin-left: auto;
    margin-right: auto;
    margin-bottom: var(--spacing-md);
  }

  .mode-btn {
    flex: 1;
    padding: 10px 16px;
  }

  /* 输入框优化 */
  .input-wrapper input,
  .input-wrapper textarea {
    padding: 12px;
    font-size: 0.9rem;
  }

  .parse-btn {
    padding: 12px;
    font-size: 1rem;
  }

  /* 批量提示 */
  .batch-tips {
    padding: 12px;
  }

  .tip-content {
    font-size: 0.85rem;
  }

  /* 下载操作 */
  .primary-actions {
    flex-direction: column;
  }

  .primary-actions .btn {
    width: 100%;
  }

  /* 批量结果 */
  .batch-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-sm);
  }

  .batch-actions {
    width: 100%;
  }

  .batch-actions .btn {
    width: 100%;
  }

  .batch-item-content {
    flex-direction: column;
    align-items: flex-start;
  }

  .batch-thumb {
    width: 100%;
    height: auto;
    aspect-ratio: 16/9;
  }
}

/* 超窄屏优化 */
@media (max-width: 400px) {
  .content-container {
    padding: var(--spacing-sm);
  }

  h1 {
    font-size: 1.3rem;
  }

  .mode-btn {
    padding: 8px 12px;
    font-size: 0.9rem;
  }

  .input-tools {
    flex-wrap: wrap;
  }

  .tool-btn {
    padding: 5px 10px;
    font-size: 0.8rem;
  }
}
</style>
