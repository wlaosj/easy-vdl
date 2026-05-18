<template>
  <div class="content-view">
    <div class="content-container">
      <div class="header-section">
        <div class="icon-glow theme-gradient">
          <Icon name="youtube" :size="40" />
        </div>
        <h1>油管B站</h1>
        <p class="subtitle">支持 4K/8K 极清视频解析，智能识别剪贴板链接</p>
      </div>

      <div class="input-section">
        <div class="input-tools-top">
          <button class="btn btn-xs btn-secondary" @click="handlePaste">
            <Icon name="file-text" :size="14" /> 粘贴
          </button>
          <button class="btn btn-xs btn-danger" @click="clearInput">
            <Icon name="trash" :size="14" /> 清空
          </button>
          <button class="btn btn-xs btn-warning" @click="goToCookieSettings">
            <Icon name="link" :size="14" /> Cookie设置
          </button>
        </div>
        <div class="input-wrapper">
          <input 
            v-model="inputUrl" 
            type="text" 
            placeholder="支持 YouTube(youtube.com, youtu.be) 和 B站(bilibili.com, b23.tv)..." 
            @paste="onPaste"
            @keyup.enter="startParse"
          />
        </div>
        <div class="url-hint" v-if="urlError">{{ urlError }}</div>
      </div>

      <div class="action-section">
        <button 
          class="btn btn-primary btn-lg w-full" 
          :disabled="loading || !inputUrl"
          @click="startParse"
        >
          <span v-if="loading" class="spinner"></span>
          <span v-else>获取视频信息</span>
        </button>
      </div>

      <!-- Loading State -->
      <transition name="fade">
        <div v-if="loading" class="loading-status">
          <div class="loading-pulse"></div>
          <p class="funny-tip">{{ currentTip }}</p>
        </div>
      </transition>

      <!-- Result Card -->
      <ParserResultCard
        v-if="videoInfo"
        :title="videoInfo.title"
        :author="videoInfo.uploader"
        :thumbnail="videoInfo.thumbnailUrl"
        :duration="videoInfo.duration"
        :platform="videoInfo.platform || 'youtube'"
      >
        <!-- Formats Section -->
        <div class="formats-section" v-if="videoInfo.formats && videoInfo.formats.length">
           <h3>🎬 选择下载格式</h3>
           
           <!-- Featured Tiers -->
           <div class="formats-grid featured">
              <div class="grid-label">精选格式 (兼容优先)</div>
              <div 
                v-for="(f, idx) in featuredFormats" 
                :key="'feat_' + idx"
                class="format-card"
                :class="{ 
                  selected: selectedFormat === f,
                  disabled: isFormatDisabled(f)
                }"
                @click="selectFormat(f)"
              >
                <div class="format-license-badge" v-if="isFormatDisabled(f)">👑 高级功能</div>
                <div class="format-header">
                  <span class="resolution">{{ f.resolution }} <span v-if="f.fps > 30" class="fps">{{f.fps}}fps</span></span>
                  <span class="tag" :class="{ compat: isCompat(f) }">{{ getFormatTag(f) }}</span>
                </div>
                <div class="format-tech">
                  {{ (f.ext || 'mp4').toUpperCase() }} · {{ (f.vcodec || '').split('.')[0].toUpperCase() }}
                </div>
                <div class="format-footer">
                  <span class="filesize">{{ formatSize(f.filesize || f.filesize_str) }}</span>
                  <span class="id-tag">ID: {{ f.format_id }}</span>
                </div>
              </div>
           </div>

           <!-- More Toggle -->
           <div class="more-formats-wrapper" v-if="moreFormats.length">
              <button class="btn btn-outline w-full" @click="showMore = !showMore">
                {{ showMore ? '收起更多清晰度' : '显示更多清晰度' }}
                <Icon :name="showMore ? 'chevron-up' : 'chevron-down'" :size="16" />
              </button>
           </div>

           <!-- More Tiers -->
           <transition name="slide-down">
             <div class="formats-grid more" v-if="showMore && moreFormats.length">
                <div 
                  v-for="(f, idx) in moreFormats" 
                  :key="'more_' + idx"
                  class="format-card small"
                  :class="{ 
                    selected: selectedFormat === f,
                    disabled: isFormatDisabled(f)
                  }"
                  @click="selectFormat(f)"
                >
                  <div class="format-license-badge" v-if="isFormatDisabled(f)">👑</div>
                  <div class="format-header">
                    <span class="resolution">{{ f.resolution }}</span>
                    <span class="tag micro">{{ getFormatTag(f) }}</span>
                  </div>
                  <div class="format-footer">
                    <span class="filesize">{{ formatSize(f.filesize || f.filesize_str) }}</span>
                    <span class="id-tag">{{ f.format_id }}</span>
                  </div>
                </div>
             </div>
           </transition>
        </div>
        
        <div v-else class="no-formats">
           ⚠️ 未找到可用格式
        </div>

        <template #footer>
          <!-- Options & Action -->
          <div class="download-config-card">
             <div class="options-row">
                <label><input type="checkbox" v-model="downloadOptions.subtitles"> 下载字幕</label>
                <label><input type="checkbox" v-model="downloadOptions.thumbnail"> 下载封面</label>
             </div>
             <div class="action-row">
                <button 
                  class="btn btn-primary flex-1"
                  :disabled="!selectedFormat || downloading || isFormatDisabled(selectedFormat)"
                  @click="startDownload"
                >
                  {{ downloading ? '任务提交中...' : '开始下载' }}
                </button>
             </div>
          </div>
        </template>
      </ParserResultCard>

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
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const inputUrl = ref('')
const loading = ref(false)
const downloading = ref(false)
const videoInfo = ref(null)
const error = ref('')
const urlError = ref('')
const currentTip = ref('')
const selectedFormat = ref(null)
const showMore = ref(false)

const downloadOptions = ref({
  subtitles: true,
  thumbnail: true
})

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

// Format grouping state
const featuredFormats = ref([])
const moreFormats = ref([])

let tipInterval = null

const TIPS = [
  "🤖 正在分析视频链接...",
  "🔍 检测到这是一个精彩的视频...",
  "📺 正在与平台服务器对话...",
  "🎬 视频信息获取中，请稍候...",
  "💫 正在提取高清视频地址...",
  "✨ 解析进度：正在处理中...",
  "🎯 解析即将完成，请耐心等待..."
]

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

const validateUrl = (url) => {
  const youtubePattern = /^(https?:\/\/)?([a-z0-9-]+\.)?(youtube\.com|youtu\.be)\/.+/i
  const bilibiliPattern = /^(https?:\/\/)?([a-z0-9-]+\.)?(bilibili\.com|b23\.tv)\/.+/i
  return youtubePattern.test(url) || bilibiliPattern.test(url)
}

const handlePaste = async () => {
  try {
    const text = await navigator.clipboard.readText()
    inputUrl.value = text
  } catch (e) {
    error.value = '无法读取剪贴板'
  }
}

const onPaste = () => {
  // Logic to auto-submit could go here
}

const clearInput = () => {
  inputUrl.value = ''
  videoInfo.value = null
  selectedFormat.value = null
  error.value = ''
  urlError.value = ''
}

const goToCookieSettings = () => {
  router.push({ path: '/settings', query: { tab: 'cookie' } })
}


const formatDuration = (seconds) => {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return h > 0 ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` 
               : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
}

const formatSize = (val) => {
  if (typeof val === 'string') return val
  if (!val) return '未知大小'
  return (val / 1024 / 1024).toFixed(1) + ' MB'
}

const parseHeight = (res) => {
  if (!res) return 0
  const m = String(res).match(/(\d+)[xX](\d+)/)
  return m ? parseInt(m[2], 10) : 0
}

const isCompat = (f) => f.ext === 'mp4' && /avc1/i.test(f.vcodec || '')

const getFormatTag = (f) => {
  if (isCompat(f)) {
    return (f.mergeAudio || /\+/.test(f.format_id)) ? '音视频合成' : (f.type || '完整')
  }
  return '可能不兼容'
}

const isFormatDisabled = (f) => {
  if (f.requires_license) {
    // Check if user is licensed (assuming authStore has this property or we default to false)
    // For now assuming we don't block unless we know for sure videoInfo says so
    // If we want to strictly enforce:
    /* return !authStore.user?.is_licensed */
    return false // Relaxed for now until is_licensed is confirmed
  }
  return false
}

const processFormats = (formats) => {
  const tiers = [4320, 2160, 1440, 1080, 720, 480, 360, 240]
  const groups = {}
  
  // Group by Tier
  formats.forEach(f => {
     const h = parseHeight(f.resolution)
     const tier = tiers.find(t => h >= t) || 0
     if (!tier) return
     if (!groups[tier]) groups[tier] = []
     groups[tier].push(f)
  })
  
  const availableTiers = tiers.filter(t => groups[t] && groups[t].length)
  
  // Helper to pick best in group
  const pickRepresentative = (list) => {
      // Priority: Compatibility > FPS > Size
      const score = (f) => [
          isCompat(f) ? 0 : 1, // 0 is better
          f.fps ? (f.fps >= 60 ? 0 : 1) : 2,
          (f.filesize || f.filesize_str) ? 0 : 1
      ]
      return [...list].sort((a,b) => {
          const sA = score(a), sB = score(b)
          return sA[0]-sB[0] || sA[1]-sB[1] || sA[2]-sB[2]
      })[0]
  }

  const feat = []
  const more = []
  
  // Top 2 tiers go to Featured
  availableTiers.slice(0, 2).forEach(t => {
      const best = pickRepresentative(groups[t])
      if (best) feat.push(best)
  })
  
  // Rest go to More (picked representative)
  availableTiers.slice(2).forEach(t => {
      const best = pickRepresentative(groups[t])
      if (best) more.push(best)
  })
  
  // If no standard tiers found, just pick top 3 from raw
  if (feat.length === 0 && more.length === 0) {
     // Sort by resolution desc, then compat
     const sorted = [...formats].sort((a,b) => parseHeight(b.resolution) - parseHeight(a.resolution))
     featuredFormats.value = sorted.slice(0, 3)
     moreFormats.value = []
  } else {
     featuredFormats.value = feat
     moreFormats.value = more
  }
  
  // Auto select first featured
  if (featuredFormats.value.length > 0) {
      selectFormat(featuredFormats.value[0])
  }
}

const selectFormat = (f) => {
  if (isFormatDisabled(f)) return
  selectedFormat.value = f
}

const startParse = async () => {
  if (!validateUrl(inputUrl.value)) {
    urlError.value = '请输入有效的 YouTube 或 B站链接'
    return
  }
  urlError.value = ''
  error.value = ''
  videoInfo.value = null
  loading.value = true
  startTips()
  
  try {
     const res = await scraperApi.getYoutubeInfo(inputUrl.value)
     // Process Formats
     processFormats(res.formats || [])
     
     // Handle Thumbnail (Legacy logic ported)
     const url = inputUrl.value
     let thumbnailUrl = res.thumbnailUrl || res.thumbnail || ''
     
     // Bilibili Proxy - 扩充检测关键词，确保覆盖所有B站静态资源域名
     const isBiliUrl = /bilibili\.com|b23\.tv|hdslb\.com|biliimg\.com/.test(url) || 
                      /bilibili\.com|hdslb\.com|biliimg\.com/.test(thumbnailUrl) ||
                      (res.platform === 'bilibili')
                      
     if (isBiliUrl && thumbnailUrl && !thumbnailUrl.includes('proxy-bili-cover')) {
       // 转换代理地址
       thumbnailUrl = `/api/ytd/proxy-bili-cover?url=${encodeURIComponent(thumbnailUrl)}`
     }
     
     // Youtube Fallback
     if (!thumbnailUrl && (url.includes('youtube.com') || url.includes('youtu.be'))) {
        let videoId = url.match(/(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})/i)?.[1]
        if (!videoId) videoId = url.match(/youtube\.com\/shorts\/([^"&?\/\s]{11})/i)?.[1]
        
        if (videoId) {
          const isShorts = url.includes('/shorts/')
          thumbnailUrl = `https://i.ytimg.com/vi/${videoId}/${isShorts ? 'hqdefault' : 'maxresdefault'}.jpg`
        }
     }
     
     // 最后统一赋值，确保触发响应式更新
     res.thumbnailUrl = thumbnailUrl
     videoInfo.value = res
     
  } catch (e) {
     error.value = e.message || '获取信息失败'
  } finally {
     loading.value = false
     stopTips()
  }
}

const handleImageError = (e) => {
  e.target.style.display = 'none'
}

const startDownload = async () => {
  if (!selectedFormat.value) return
  downloading.value = true
  try {
    let formatId = selectedFormat.value.format_id
    if (selectedFormat.value.mergeAudio && selectedFormat.value.audioFormatId) {
        formatId = `${selectedFormat.value.format_id}+${selectedFormat.value.audioFormatId}`
    }
  
    await scraperApi.downloadYoutubeVideo({
       url: videoInfo.value.url || inputUrl.value,
       format_id: formatId,
       subtitles: downloadOptions.value.subtitles,
       thumbnail: downloadOptions.value.thumbnail
    })
    
    showModal('任务提交', '✅ 下载任务已添加! 请前往下载管理查看。', 'success')
  } catch (e) {
    showModal('下载失败', '❌ 下载请求失败: ' + e.message, 'error')
  } finally {
    downloading.value = false
  }
}


const checkAutoParse = () => {
  const url = route.query.url
  if (url) {
    inputUrl.value = decodeURIComponent(url)
    // 稍微延迟确保清理完成
    setTimeout(() => {
      startParse()
    }, 100)
  }
}

onMounted(() => {
  checkAutoParse()
})

// 监听路由变化，处理已在解析页面时的二次跳转
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

[data-theme="dark"] .btn-warning {
  background: linear-gradient(135deg, #96610b 0%, #b3740d 100%) !important;
  color: rgba(255, 255, 255, 0.9) !important;
  border: 1px solid rgba(255, 255, 255, 0.05) !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2) !important;
}

h1 {
  font-size: 2rem;
  font-weight: 800;
  margin-bottom: 8px;
  color: var(--color-text-primary);
}

.subtitle {
  color: var(--color-text-tertiary);
}

.input-section {
  margin-bottom: 24px;
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
  transition: all 0.3s;
}

.input-wrapper:focus-within {
  border-color: #8b5cf6;
  box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.1);
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

.tool-btn {
  border: none;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: filter 0.2s;
}

.tool-btn.paste { background: rgba(139, 92, 246, 0.1); color: #8b5cf6; }
.tool-btn.clear { background: rgba(239, 68, 68, 0.1); color: #ef4444; }
.tool-btn:hover { filter: brightness(0.95); }

[data-theme="dark"] .btn-danger:not(.btn-clear-action) {
  background: rgba(239, 68, 68, 0.15) !important;
  color: #ff6b6b !important;
  border: 1px solid rgba(239, 68, 68, 0.2) !important;
}

.url-hint {
  color: #ef4444;
  font-size: 0.9rem;
  margin-top: 8px;
  margin-left: 8px;
}

.parse-btn {
  width: 100%;
  padding: 16px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%); /* YouTube Red */
  color: white;
  font-size: 1.1rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s;
}

.parse-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  filter: grayscale(1);
}

.parse-btn:not(:disabled):hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px -6px rgba(185, 28, 28, 0.4);
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

.loading-status {
  text-align: center;
  margin-top: 20px;
}

.funny-tip {
  margin-top: 12px;
  color: var(--color-text-secondary);
}

/* Result Card */
.result-card {
  margin-top: 30px;
  background: var(--color-bg-primary);
  border-radius: 16px;
  border: 1px solid var(--color-border);
  overflow: hidden;
}

.video-header {
  padding: 24px;
  border-bottom: 1px solid var(--color-border);
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 24px;
  
  @media (max-width: 768px) {
    grid-template-columns: 1fr;
  }
}

.thumbnail-wrapper {
  position: relative;
  background: #000;
  border-radius: 12px;
  overflow: hidden;
  aspect-ratio: 16/9;
}

.thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.duration-badge {
  position: absolute;
  bottom: 8px;
  right: 8px;
  background: rgba(0,0,0,0.8);
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 600;
}

.video-meta {
  display: flex;
  flex-direction: column;
}

.status-badge {
  background: #dcfce7;
  color: #166534;
  width: fit-content;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 12px;
}

.video-title {
  font-size: 1.25rem;
  line-height: 1.4;
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.author-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

/* Formats Grid */
.formats-section {
  padding: 24px;
}

h3 {
  margin-bottom: 16px;
  font-size: 1.1rem;
}

.grid-label {
  width: 100%;
  font-size: 0.9rem;
  color: var(--color-text-tertiary);
  margin-bottom: 12px;
  font-weight: 600;
}

.formats-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 20px;
}

.format-card {
  flex: 1 1 200px;
  background: var(--color-bg-tertiary);
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  min-width: 180px;
}

.format-card:hover { border-color: #8b5cf6; background: rgba(139, 92, 246, 0.05); }

.format-card.selected {
  border-color: #8b5cf6;
  background: rgba(139, 92, 246, 0.1);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.15);
}

.format-card.disabled {
  opacity: 0.7;
  cursor: not-allowed;
  filter: grayscale(0.5);
  border-color: gold; /* Special Highlighting for VIP features */
  background: linear-gradient(135deg, white, #fffbe6);
}

.format-license-badge {
  position: absolute;
  top: -8px;
  right: -8px;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: white;
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 12px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
  z-index: 10;
}

.format-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.resolution {
  font-weight: 700;
  font-size: 1.1rem;
  color: var(--color-text-primary);
}

.fps { font-size: 0.8rem; color: var(--color-text-tertiary); margin-left: 2px; }

.tag {
  background: #ef4444;
  color: white;
  font-size: 0.7rem;
  padding: 2px 6px;
  border-radius: 4px;
}

.tag.compat { background: #f59e0b; }
.tag.micro { font-size: 0.65rem; }

.format-tech {
  font-size: 0.85rem;
  color: var(--color-text-tertiary);
  margin-bottom: 8px;
}

.format-footer {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
}

.filesize { color: var(--color-success); font-weight: 600; }
.id-tag { color: var(--color-text-muted); }

/* Toggle */
.toggle-more-btn {
  width: 100%;
  padding: 10px;
  background: var(--color-bg-tertiary);
  border: none;
  border-radius: 8px;
  color: var(--color-text-secondary);
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 16px;
}

.toggle-more-btn:hover { background: var(--color-border); }

/* Download Actions */
.download-config-card {
  background: #f0fdf4; /* Light green bg */
  border: 1px solid #bbf7d0;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.options-row {
  display: flex;
  gap: 24px;
}

.options-row label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #166534;
  color: #166534;
  cursor: pointer;
}

.action-row {
  display: flex;
  gap: 12px;
}

/* 移除冗余的局部下载按钮样式，改用全局 .btn-primary */
.dl-action-btn { display: none; } /* 确保不再生效 */

/* 移除冗余的局部样式 */


/* 移除旧的下载按钮修饰类 */

.no-formats {
  padding: 40px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: 1.1rem;
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

.close-btn { margin-left: auto; background: none; border: none; color: inherit; cursor: pointer; }

/* Transitions */
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.slide-up-enter-active, .slide-up-leave-active { transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1); }
.slide-up-enter-from, .slide-up-leave-to { opacity: 0; transform: translateY(20px); }

.slide-down-enter-active, .slide-down-leave-active { transition: all 0.3s ease; max-height: 1000px; opacity: 1;}
.slide-down-enter-from, .slide-down-leave-to { max-height: 0; opacity: 0; overflow: hidden; }

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

  .icon-glow.theme-gradient {
    width: 50px;
    height: 50px;
  }

  h1 {
    font-size: 1.5rem;
  }

  .subtitle {
    font-size: 0.9rem;
  }

  /* 输入框优化 */
  .input-wrapper input {
    padding: 12px;
    font-size: 0.9rem;
  }

  .parse-btn {
    padding: 12px;
    font-size: 1rem;
  }

  /* 格式卡片 */
  .formats-grid {
    gap: var(--spacing-sm);
  }

  .format-card {
    flex: 1 1 100%;
    min-width: 0;
  }

  /* 下载配置 */
  .download-config-card {
    padding: var(--spacing-md);
  }

  .options-row {
    flex-direction: column;
    gap: var(--spacing-sm);
  }

  .action-row {
    flex-direction: column;
  }

  .action-row .btn {
    width: 100%;
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

  .format-card {
    padding: 12px;
  }

  .resolution {
    font-size: 1rem;
  }

  .input-tools {
    flex-wrap: wrap;
  }
}
</style>
