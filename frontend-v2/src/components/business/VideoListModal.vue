<template>
  <Teleport to="body">
    <div class="video-list-modal-overlay" v-if="show" @click="handleOverlayClick">
      <div class="video-list-modal-content" @click.stop>
      <!-- 关闭按钮 -->
      <button class="modal-close-btn" @click="$emit('update:show', false)">&times;</button>
      
      <!-- 标题 -->
      <h2 class="modal-title">
        <span class="platform-name" v-if="platformDisplayName">[{{ platformDisplayName }}]</span>
        <span class="nickname-title">{{ nickname || '博主' }}</span>
        <span>{{ isNetease ? ' 的歌曲列表' : ' 的视频列表' }}</span>
      </h2>
      
      <!-- 提示信息和批量操作 -->
      <div class="tip-info">
        <div class="tip-items">
          <div class="tip-item">自动跳过已下载</div>
          <div class="tip-item">并发高更快，注意封IP</div>
        </div>
        
        <div class="batch-controls">
          <div class="config-row">
            <div class="filter-group">
              <select v-model="batchType" class="form-select-sm">
                <option value="count">按数量</option>
                <option value="time" :disabled="!supportsDateBatchDownload">按时间</option>
              </select>
              
              <select v-if="batchType === 'count'" v-model="batchCount" class="form-select-sm">
                <option value="10">最近10个</option>
                <option value="20">最近20个</option>
                <option value="50">最近50个</option>
                <option value="-1">所有视频</option>
              </select>
              
              <select v-else v-model="batchDays" class="form-select-sm">
                <option value="7">最近7天</option>
                <option value="30">最近30天</option>
                <option value="90">最近90天</option>
              </select>
              
              <div class="concurrent-group">
                <label class="concurrent-label">并发:</label>
                <select v-model="concurrentLimit" class="form-select-sm concurrent-select">
                  <option value="1">1</option>
                  <option value="2">2</option>
                  <option value="3">3</option>
                  <option value="4">4</option>
                  <option value="5">5</option>
                </select>
              </div>
            </div>
          </div>
          <div v-if="!supportsDateBatchDownload" class="batch-mode-tip">
            {{ dateBatchDownloadTip }}
          </div>
          
          <div class="actions-row">
            <!-- 画质选择 (仅YouTube和B站) -->
            <div class="filter-group quality-group" v-if="isYouTube || isBilibili">
              <select v-model="selectedQuality" class="form-select-sm">
                <option value="bestvideo+bestaudio">最高画质</option>
                <option value="bestvideo[height<=4320]+bestaudio" v-if="isYouTube">8K</option>
                <option value="bestvideo[height<=2160]+bestaudio">4K</option>
                <option value="bestvideo[height<=1440]+bestaudio">2K</option>
                <option value="bestvideo[height<=1080]+bestaudio">1080p</option>
                <option value="bestvideo[height<=720]+bestaudio">720p</option>
                <option value="bestvideo[height<=480]+bestaudio">480p</option>
              </select>
              <button class="btn btn-sm btn-secondary" @click="saveQuality">保存画质</button>
            </div>
            
            <div class="main-buttons">
              <button 
                class="btn btn-primary btn-sm btn-action-animate" 
                @click="startBatchDownload"
                :disabled="isDownloading || isStarting"
              >
                <span v-if="isStarting" class="btn-loading-content">
                  <span class="spinner-small-btn"></span>
                  <span>提交中...</span>
                </span>
                <span v-else-if="isDownloading" class="btn-downloading-content">
                  <span class="pulse-dot"></span>
                  <span>批量下载中...</span>
                </span>
                <span v-else>开始下载</span>
              </button>
              
              <button 
                v-if="stats.failed_count > 0" 
                class="btn btn-warning btn-sm" 
                @click="retryFailed"
              >
                重试失败任务 ({{ stats.failed_count }})
              </button>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 状态统计 -->
      <div class="video-stats">
        <div class="stats-header">
          下载状态统计 (共 {{ stats.total }} 个{{ showVideoNoteBreakdown ? `内容：${stats.video_count || 0} 个视频，${stats.note_count || 0} 个${secondaryMediaLabel}` : (isNetease ? '首歌曲' : '视频') }})
        </div>
        <div class="stats-filters">
          <button 
            v-for="status in statusList" 
            :key="status.value"
            class="status-filter-btn"
            :class="{ active: currentFilter === status.value }"
            @click="filterByStatus(status.value)"
          >
            <span class="status-dot" :style="{ background: status.color }"></span>
            <span>{{ status.label }}: <strong>{{ stats[status.countKey] || 0 }}</strong></span>
          </button>
          <button 
            class="status-filter-btn"
            :class="{ active: currentFilter === 'all' }"
            @click="filterByStatus('all')"
          >
            <span class="status-dot" style="background: #adb5bd"></span>
            <span>清除筛选</span>
          </button>
        </div>
        
        <!-- 进度条 -->
        <div class="progress-section">
          <div class="progress-label">
            <span>下载进度</span>
            <span>{{ stats.downloaded_count || 0 }} / {{ stats.total }}</span>
          </div>
          <div class="progress-bar">
            <div 
              class="progress-fill" 
              :style="{ width: progressPercent + '%' }"
            ></div>
          </div>
        </div>
      </div>
      
      <!-- 视频列表 -->
      <div class="video-list-container" ref="videoListContainer" @scroll="handleScroll">
        <div v-if="loading && videos.length === 0" class="loading-state">
          <div class="spinner"></div>
          <p>加载中...</p>
        </div>
        
        <div v-else-if="videos.length === 0" class="empty-state">
          <p>{{ isNetease ? '暂无歌曲' : '暂无视频' }}</p>
        </div>
        
        <div v-else class="video-items">
          <div 
            v-for="video in videos" 
            :key="video.id"
            class="video-item"
            :data-status="video.status || 'not_downloaded'"
          >
            <img 
              v-if="getVideoCoverSrc(video)"
              :src="getVideoCoverSrc(video)"
              class="video-cover"
              loading="lazy"
              @error="handleImageError(video, $event)"
            />
            <div v-else class="video-cover-placeholder"></div>
            
            <div class="video-details">
              <div class="video-title">
                <a :href="video.url" target="_blank" class="video-link" title="点此跳转网页查看原视频">
                  <span
                    class="content-type-badge"
                    :class="{ 'is-note': isNote(video) }"
                    :title="isNetease ? '音乐' : getMediaTypeLabel(video)"
                  >
                    {{ isNetease ? '音乐' : getMediaTypeLabel(video) }}
                  </span>
                  {{ video.title }}
                </a>
              </div>
              <div class="video-time">
                <span v-if="isXiaohongshu || isNetease || isYouTubeShorts">入库时间: {{ formatDate(video.created_at || video.publish_time) }}</span>
                <span v-else>发布时间: {{ formatDate(video.publish_time) }}</span>
              </div>
              <div class="video-actions">
                <template v-if="video.status === 'downloaded'">
                  <span class="status-tag success">已下载</span>
                  <button
                    class="btn btn-xs btn-primary"
                    :title="video.download_task_id ? `${getPreviewActionLabel(video)}此${getMediaActionLabel(video)}` : `缺少任务ID，无法直接${getPreviewActionLabel(video)}`"
                    :disabled="!video.download_task_id"
                    @click="playVideo(video)"
                  >
                    {{ getPreviewActionLabel(video) }}
                  </button>
                  <button 
                    class="btn btn-xs btn-warning" 
                    :title="`强制重新下载此${getMediaActionLabel(video)}`"
                    @click="redownloadVideo(video)"
                  >
                    重新下载
                  </button>
                  <button
                    class="btn btn-xs btn-secondary"
                    :title="getNfoButtonTitle(video)"
                    :disabled="isNfoButtonDisabled(video)"
                    @click="openNfoEditor(video)"
                  >
                    编辑NFO
                  </button>
                </template>
                <span v-if="video.status === 'downloaded' && video.removed_from_source" class="status-tag archived">
                  本地存档 · 源已移除
                </span>
                
                <template v-else-if="video.status === 'failed'">
                  <span class="status-tag error" :title="video.error_message">下载失败</span>
                  <button class="btn btn-xs btn-warning" @click="redownloadVideo(video)">
                    重新下载
                  </button>
                  <span v-if="video.error_message" class="error-message" :title="video.error_message">
                    {{ video.error_message }}
                  </span>
                </template>
                
                <span v-else-if="video.status === 'cancelled'" class="status-tag warning">
                  下载已取消
                </span>
                
                <span v-else-if="video.status === 'downloading'" class="status-tag info">
                  下载中...
                </span>
                
                <span v-else-if="video.status === 'orphaned'" class="status-tag warning">
                  本地文件缺失
                </span>
                <button
                  v-if="video.status === 'orphaned'"
                  class="btn btn-xs btn-danger"
                  :disabled="isCleaningOrphans"
                  :title="`清理本订阅全部孤儿任务（当前 ${stats.orphaned_count || 0} 个）`"
                  @click="cleanupOrphans"
                >
                  {{ isCleaningOrphans ? '清理中...' : '清理本订阅全部孤儿' }}
                </button>
                
                  <button
                    v-else-if="video.status !== 'downloaded'"
                    class="btn btn-xs btn-primary"
                    @click="downloadSingleVideo(video.id)"
                  >
                    {{ isNetease ? '下载音乐' : `下载${getMediaActionLabel(video)}` }}
                  </button>

                  <!-- 红色删除按钮 -->
                  <button 
                    class="btn btn-xs btn-delete" 
                    title="从列表中移除此视频记录"
                    @click="handleDeleteVideo(video)"
                  >
                    删除
                  </button>
                </div>
            </div>
          </div>
        </div>
        
        <div v-if="hasMore && !loading" class="load-more">
          <div class="spinner-sm"></div>
          <span>加载更多...</span>
        </div>
      </div>
    </div>
  </div>
  </Teleport>

  <!-- 提示弹窗 -->
  <Modal v-model:show="showTipModal" :title="tipTitle" :type="tipType" :z-index="30000">
    <div v-html="tipMessage"></div>
    <template #footer>
      <template v-if="tipType === 'confirm' || tipType === 'warning'">
        <button class="btn btn-secondary" @click="handleTipCancel">{{ cancelBtnText }}</button>
        <button class="btn btn-primary" @click="handleTipConfirm">{{ confirmBtnText }}</button>
      </template>
      <template v-else>
        <button class="btn btn-primary" @click="handleTipClose">确定</button>
      </template>
    </template>
  </Modal>

  <!-- NFO编辑弹窗 -->
  <Modal
    :z-index="30000"
    v-model:show="showNfoEditor"
    :title="nfoEditorTitle"
    :showConfirm="false"
    width="820px"
    containerHeight="70vh"
    bodyFill
    bodyPadding="12px 16px"
  >
    <div class="nfo-editor-wrap">
      <div v-if="nfoEditorLoading" class="nfo-editor-loading">
        <div class="spinner"></div>
        <p>正在加载 NFO...</p>
      </div>
      <textarea
        v-else
        v-model="nfoEditorContent"
        class="nfo-editor-textarea"
        spellcheck="false"
      ></textarea>
    </div>
    <template #footer>
      <button class="btn btn-secondary" :disabled="nfoEditorSaving" @click="closeNfoEditor">取消</button>
      <button class="btn btn-primary" :disabled="nfoEditorLoading || nfoEditorSaving" @click="saveNfoEditor">
        {{ nfoEditorSaving ? '保存中...' : '保存' }}
      </button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { subscriptionsApi } from '@/api/subscriptions'
import Modal from '@/components/common/Modal.vue'

const props = defineProps({
  show: Boolean,
  subscriptionId: String,
  platform: String,
  youtubeTabType: String,
  subscriptionType: String,
  currentQuality: String,
  isDownloading: Boolean,
  nickname: String
})

const platformDisplayName = computed(() => {
  if (!props.platform) return ''
  const map = {
    'douyin': '抖音',
    'douyin_collection': '抖音合集',
    'tiktok': 'TikTok',
    'instagram': 'Instagram',
    'youtube': 'YouTube',
    'youtube_playlist': 'YouTube列表',
    'youtube_channel': 'YouTube频道',
    'youtube_shorts': 'YouTube Shorts',
    'bilibili': 'B站',
    'bilibili_collection': 'B站合集',
    'xiaohongshu': '小红书',
    'netease': '网易云'
  }
  return map[props.platform] || props.platform
})

const router = useRouter()

const emit = defineEmits(['update:show', 'qualityUpdated', 'batchDownloadStarted'])

// 数据状态
const videos = ref([])
const stats = ref({
  total: 0,
  downloaded_count: 0,
  downloading_count: 0,
  not_downloaded_count: 0,
  failed_count: 0,
  removed_count: 0,
  cancelled_count: 0,
  orphaned_count: 0,
  charging_count: 0,
  video_count: 0,
  note_count: 0
})

const loading = ref(false)
const currentPage = ref(1)
const hasMore = ref(true)
const currentFilter = ref('all')
const isStarting = ref(false)
const isCleaningOrphans = ref(false)
const localCoverMap = ref({})
const localCoverLoadingMap = ref({})
const localCoverFailedMap = ref({})
const nfoAvailabilityMap = ref({})
const nfoAvailabilityLoadingMap = ref({})

// 批量下载配置
const batchType = ref('count')
const batchCount = ref('10')
const batchDays = ref('7')
const concurrentLimit = ref('1')
const selectedQuality = ref(props.currentQuality || 'bestvideo+bestaudio')

// 平台判断
const isYouTube = computed(() => 
  props.platform === 'youtube' || 
  props.platform === 'youtube_playlist' ||
  props.platform === 'youtube_channel' ||
  props.platform === 'youtube_shorts'
)

const isBilibili = computed(() => 
  props.platform === 'bilibili' || 
  props.platform === 'bilibili_collection'
)

const isDouyin = computed(() => 
  props.platform === 'douyin' ||
  props.platform === 'douyin_collection' ||
  props.platform === 'douyin_favorite'
)

const isXiaohongshu = computed(() => props.platform === 'xiaohongshu')
const isInstagram = computed(() => props.platform === 'instagram')
const isNetease = computed(() => props.platform === 'netease')
const secondaryMediaLabel = computed(() => isInstagram.value ? '图片' : '图集')
const isYouTubeShorts = computed(() => {
  const platform = (props.platform || '').toLowerCase()
  const tabType = (props.youtubeTabType || '').toLowerCase()
  return platform === 'youtube_shorts' || (platform === 'youtube' && tabType === 'shorts')
})
const supportsDateBatchDownload = computed(() => !isYouTubeShorts.value && !isXiaohongshu.value && !isNetease.value)
const dateBatchDownloadTip = computed(() => {
  if (isYouTubeShorts.value) {
    return '当前平台为 YouTube Shorts，发布时间稳定性不足，已禁用“按时间”下载，请使用“按数量”。'
  }
  if (isXiaohongshu.value) {
    return '当前平台为小红书，发布时间稳定性不足，已禁用“按时间”下载，请使用“按数量”。'
  }
  if (isNetease.value) {
    return '当前平台为网易云，当前列表按歌曲处理，已禁用“按时间”下载，请使用“按数量”。'
  }
  return '当前平台暂不支持“按时间”下载，请使用“按数量”。'
})

// 抖音、小红书等需要区分「视频 / 图集」展示
const showVideoNoteBreakdown = computed(() => isDouyin.value || isXiaohongshu.value || isInstagram.value)

// 进度百分比
const progressPercent = computed(() => {
  if (stats.value.total === 0) return 0
  return Math.round((stats.value.downloaded_count / stats.value.total) * 100)
})

// 状态列表
const statusList = computed(() => {
  const list = [
    { value: 'downloaded', label: '已下载', color: '#28a745', countKey: 'downloaded_count' },
    { value: 'downloading', label: '下载中', color: '#007bff', countKey: 'downloading_count' },
    { value: 'not_downloaded', label: '未下载', color: '#6c757d', countKey: 'not_downloaded_count' },
    { value: 'failed', label: '下载失败', color: '#dc3545', countKey: 'failed_count' },
    { value: 'orphaned', label: '孤儿', color: '#fd7e14', countKey: 'orphaned_count' },
    { value: 'removed', label: '已移除', color: '#9333ea', countKey: 'removed_count' }
  ]
  
  if (isBilibili.value && props.subscriptionType !== 'favorite') {
    list.push({ value: 'charging', label: '充电专属', color: '#fb7299', countKey: 'charging_count' })
  }
  
  return list
})

const videoListContainer = ref(null)

// 提示弹窗状态
const showTipModal = ref(false)
const tipTitle = ref('提示')
const tipMessage = ref('')
const tipType = ref('info') // info, success, warning, error
const confirmBtnText = ref('确定')
const cancelBtnText = ref('取消')
let onConfirmCallback = null

// NFO编辑状态
const showNfoEditor = ref(false)
const nfoEditorLoading = ref(false)
const nfoEditorSaving = ref(false)
const nfoEditorContent = ref('')
const nfoEditingVideo = ref(null)

const nfoEditorTitle = computed(() => {
  const title = nfoEditingVideo.value?.title || ''
  if (!title) return '编辑 NFO'
  return `编辑 NFO - ${title}`
})

// 自定义提示函数
function customAlert(title, message, type = 'info', confirmText = '确定', cancelText = '取消', onConfirm = null) {
  tipTitle.value = title
  tipMessage.value = message
  tipType.value = type
  confirmBtnText.value = confirmText
  cancelBtnText.value = cancelText
  onConfirmCallback = onConfirm
  showTipModal.value = true
}

// 关闭提示弹窗
function handleTipClose() {
  showTipModal.value = false
}

// 确认对话框 - 确认
function handleTipConfirm() {
  showTipModal.value = false
  if (onConfirmCallback) {
    onConfirmCallback()
    onConfirmCallback = null
  }
  if (window._retryConfirmResolve) {
    window._retryConfirmResolve(true)
    window._retryConfirmResolve = null
  }
}

// 确认对话框 - 取消
function handleTipCancel() {
  showTipModal.value = false
  if (window._retryConfirmResolve) {
    window._retryConfirmResolve(false)
    window._retryConfirmResolve = null
  }
}

function getExtraDataObject(video) {
  if (!video?.extra_data) return {}
  if (typeof video.extra_data === 'object' && video.extra_data !== null) {
    return video.extra_data
  }
  if (typeof video.extra_data === 'string' && video.extra_data.trim()) {
    try {
      return JSON.parse(video.extra_data)
    } catch (e) {
      return {}
    }
  }
  return {}
}

// 判断是否为图集/图片（抖音：URL 含 /note/；小红书：extra_data.type === 'normal'；Instagram：platform_media_type === 'image'）
function isNote(video) {
  if (!video) return false
  
  const extra = getExtraDataObject(video)
  if (extra && extra.platform_media_type === 'image') {
    return true
  }
  if (extra && extra.type === 'normal') {
    return true
  }
  if (typeof video.extra_data === 'string' && video.extra_data.trim()) {
    const normalized = video.extra_data.replace(/\s+/g, '')
    if (
      normalized.includes('"type":"normal"') ||
      normalized.includes("'type':'normal'") ||
      normalized.includes('"platform_media_type":"image"')
    ) {
      return true
    }
  }
  
  // 抖音：URL 含 /note/ 视为图集
  if (video.url && typeof video.url === 'string' && video.url.includes('/note/')) {
    return true
  }
  
  return false
}

function getMediaTypeLabel(video) {
  if (isNote(video)) {
    return isInstagram.value ? '图片' : '图集'
  }
  return '视频'
}

function getMediaActionLabel(video) {
  if (isNote(video)) {
    return isInstagram.value ? '图片' : '图集'
  }
  return '视频'
}

function getPreviewActionLabel(video) {
  return isNote(video) && isInstagram.value ? '查看' : '播放'
}

// 格式化日期
function formatDate(dateStr) {
  if (!dateStr) return '未知'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 代理图片
function proxyImage(url) {
  if (!url) return ''
  if (url.startsWith('data:')) return url
  // B站、小红书、Instagram、抖音 图片需要代理（防盗链、签名链接或请求头兼容性问题）
  if (
    url.includes('hdslb.com') ||
    url.includes('bilibili.com') ||
    url.includes('biliimg.com') ||
    url.includes('xhscdn.com') ||
    url.includes('cdninstagram.com') ||
    url.includes('fbcdn.net') ||
    url.includes('instagram.com') ||
    url.includes('douyinpic.com') ||
    url.includes('byteimg.com') ||
    url.includes('douyinstatic.com')
  ) {
    return `/api/subscribe/proxy/image?url=${encodeURIComponent(url)}`
  }
  return url
}

function getVideoCoverSrc(video) {
  if (!video || !video.id) return ''

  const localCover = localCoverMap.value[video.id]
  if (localCover) return localCover

  const remoteCover = (video.cover_url || '').trim()
  if (!remoteCover) return ''
  return proxyImage(remoteCover)
}

function encodeLocalThumbnailUrl(thumbnailUrl) {
  if (!thumbnailUrl) return ''
  if (thumbnailUrl.startsWith('http') || thumbnailUrl.startsWith('data:')) return thumbnailUrl

  const [path, query] = thumbnailUrl.split('?')
  const encodedPath = path
    .split('/')
    .map((part) => {
      if (!part) return part
      try {
        return encodeURIComponent(decodeURIComponent(part))
      } catch (e) {
        return encodeURIComponent(part)
      }
    })
    .join('/')

  return query ? `${encodedPath}?${query}` : encodedPath
}

async function loadLocalCover(video, options = {}) {
  if (!video || !video.id || !props.subscriptionId) return false
  if (localCoverMap.value[video.id]) return true
  if (localCoverLoadingMap.value[video.id]) return false
  if (localCoverFailedMap.value[video.id] && !options.force) return false

  if (options.force) {
    delete localCoverFailedMap.value[video.id]
  }
  localCoverLoadingMap.value[video.id] = true
  try {
    const data = await subscriptionsApi.getVideoLocalThumbnail(props.subscriptionId, video.id)
    const thumbnailUrl = data?.thumbnail_url
    if (data?.success && thumbnailUrl) {
      const ts = video.updated_at ? new Date(video.updated_at).getTime() : Date.now()
      const separator = thumbnailUrl.includes('?') ? '&' : '?'
      localCoverMap.value[video.id] = `${encodeLocalThumbnailUrl(thumbnailUrl)}${separator}t=${ts}`
      return true
    }
    localCoverFailedMap.value[video.id] = true
    return false
  } catch (error) {
    localCoverFailedMap.value[video.id] = true
    return false
  } finally {
    localCoverLoadingMap.value[video.id] = false
  }
}

async function hydratePreferredLocalCovers(videoList) {
  const localCoverCandidates = (videoList || []).filter((video) => {
    const remoteCover = (video?.cover_url || '').trim()
    const shouldPreferLocal = video?.status === 'downloaded'
    const shouldUseLocalFallback = !remoteCover
    return (
      !!video?.id &&
      (shouldPreferLocal || shouldUseLocalFallback) &&
      !localCoverMap.value[video.id] &&
      !localCoverFailedMap.value[video.id]
    )
  })

  if (localCoverCandidates.length === 0) return
  await Promise.allSettled(
    localCoverCandidates.map((video) => loadLocalCover(video, { force: video.status === 'downloaded' }))
  )
}

async function probeVideoNfoAvailability(video) {
  if (!video?.id || !props.subscriptionId) return
  if (video.status !== 'downloaded') return
  if (!video.download_task_id) {
    nfoAvailabilityMap.value[video.id] = false
    return
  }
  if (nfoAvailabilityMap.value[video.id] !== undefined) return
  if (nfoAvailabilityLoadingMap.value[video.id]) return

  nfoAvailabilityLoadingMap.value[video.id] = true
  try {
    const data = await subscriptionsApi.checkVideoNfoExists(props.subscriptionId, video.id)
    nfoAvailabilityMap.value[video.id] = !!data?.has_nfo
  } catch (error) {
    nfoAvailabilityMap.value[video.id] = false
  } finally {
    nfoAvailabilityLoadingMap.value[video.id] = false
  }
}

async function hydrateNfoAvailability(videoList) {
  const downloadedVideos = (videoList || []).filter((video) => video?.status === 'downloaded')
  if (downloadedVideos.length === 0) return
  await Promise.allSettled(downloadedVideos.map((video) => probeVideoNfoAvailability(video)))
}

function isNfoButtonDisabled(video) {
  if (!video || video.status !== 'downloaded') return true
  if (!video.download_task_id) return true
  if (nfoAvailabilityLoadingMap.value[video.id]) return true
  return nfoAvailabilityMap.value[video.id] === false
}

function getNfoButtonTitle(video) {
  if (!video || video.status !== 'downloaded') return '仅已下载视频支持编辑NFO'
  if (!video.download_task_id) return '缺少任务ID，无法定位NFO'
  if (nfoAvailabilityLoadingMap.value[video.id]) return '正在检查NFO...'
  if (nfoAvailabilityMap.value[video.id] === false) return '该视频暂无NFO文件'
  return '编辑NFO'
}

// 图片加载错误处理：优先尝试本地缩略图兜底
async function handleImageError(video, e) {
  if (!video || !video.id) {
    if (e?.target) e.target.style.display = 'none'
    return
  }

  if (localCoverMap.value[video.id]) {
    if (e?.target) e.target.style.display = 'none'
    return
  }

  const fallbackLoaded = await loadLocalCover(video, { force: video.status === 'downloaded' })
  if (!fallbackLoaded && e?.target) {
    e.target.style.display = 'none'
  }
}

// 加载视频列表（轻量接口：不在这里做重统计）
async function loadVideos(page = 1, append = false) {
  if (loading.value) return
  
  loading.value = true
  try {
    let url = `/api/subscribe/${props.subscriptionId}/videos?page=${page}&page_size=10&simple=true`
    if (currentFilter.value && currentFilter.value !== 'all') {
      url += `&status=${currentFilter.value}`
    }
    
    const response = await fetch(url)
    const data = await response.json()
    
    const pageVideos = data.videos || []

    if (append) {
      videos.value = [...videos.value, ...pageVideos]
    } else {
      videos.value = pageVideos
      // total 仍然来自列表接口，其余统计交给独立接口加载
      stats.value.total = data.total || 0
    }
    
    hasMore.value = pageVideos.length >= 10
    currentPage.value = page
    await hydratePreferredLocalCovers(pageVideos)
    await hydrateNfoAvailability(pageVideos)
  } catch (error) {
    console.error('加载视频失败:', error)
  } finally {
    loading.value = false
  }
}

// 加载全局统计（独立接口）
async function loadStats() {
  try {
    const response = await fetch(`/api/subscribe/${props.subscriptionId}/videos/stats`)
    const data = await response.json()
    stats.value = {
      total: data.total || 0,
      downloaded_count: data.downloaded_count || 0,
      downloading_count: data.downloading_count || 0,
      not_downloaded_count: data.not_downloaded_count || 0,
      failed_count: data.failed_count || 0,
      removed_count: data.removed_count || 0,
      cancelled_count: data.cancelled_count || 0,
      orphaned_count: data.orphaned_count || 0,
      charging_count: data.charging_count || 0,
      video_count: data.video_count || 0,
      note_count: data.note_count || 0
    }
  } catch (error) {
    console.error('加载视频统计失败:', error)
  }
}

// 滚动加载
function handleScroll() {
  if (!videoListContainer.value || loading.value || !hasMore.value) return
  
  const { scrollTop, scrollHeight, clientHeight } = videoListContainer.value
  if (scrollHeight - scrollTop - clientHeight < 50) {
    loadVideos(currentPage.value + 1, true)
  }
}

// 按状态筛选
function filterByStatus(status) {
  currentFilter.value = status
  currentPage.value = 1
  hasMore.value = true
  // 只需刷新列表，统计是全局的无需随状态变化
  loadVideos(1, false)
}

async function cleanupOrphans() {
  if (isCleaningOrphans.value || (stats.value.orphaned_count || 0) <= 0) return

  customAlert(
    '确认清理孤儿',
    `将批量清理本订阅中“本地文件缺失”的孤儿记录（当前 ${stats.value.orphaned_count || 0} 个）：<br>• 重置下载状态，支持重新下载<br>• 删除关联任务记录<br>• 默认清理残留文件/目录（若存在）<br><br>是否继续？`,
    'warning',
    '确认清理全部',
    '取消',
    async () => {
      isCleaningOrphans.value = true
      try {
        const result = await subscriptionsApi.cleanupOrphanVideos(props.subscriptionId)
        const matched = result?.matched || 0
        const resetVideos = result?.reset_videos || 0
        const deletedTasks = result?.deleted_tasks || 0
        const deletedPathsCount = result?.deleted_paths_count || 0

        customAlert(
          '清理完成',
          `已完成孤儿清理：<br>• 命中孤儿：${matched}<br>• 重置记录：${resetVideos}<br>• 删除任务：${deletedTasks}<br>• 清理残留路径：${deletedPathsCount}`,
          'success'
        )
        await loadVideos(1, false)
        await loadStats()
      } catch (error) {
        console.error('清理孤儿失败:', error)
        customAlert('清理失败', error.message || '未知错误', 'error')
      } finally {
        isCleaningOrphans.value = false
      }
    }
  )
}

// 下载单个视频
async function downloadSingleVideo(videoId) {
  try {
    await subscriptionsApi.downloadVideo(videoId)
    // 刷新列表
    await loadVideos(1, false)
  } catch (error) {
    console.error('下载视频失败:', error)
    customAlert('下载失败', error.message || '未知错误', 'error')
  }
}

// 重新下载
async function redownloadVideo(video) {
  const doRedownload = async () => {
    try {
      // 使用强制重下载接口，解决已下载视频无法重新触发下载的问题
      await subscriptionsApi.redownloadVideo(video.id)
      customAlert('下载已开始', '已重置状态并添加到下载队列', 'success')
      // 刷新列表
      await loadVideos(1, false)
    } catch (error) {
      console.error('重新下载失败:', error)
      customAlert('重新下载失败', error.message || '未知错误', 'error')
    }
  }

  if (video.status === 'downloaded') {
    customAlert(
      '确认重新下载',
      '该视频已下载。重新下载将创建新的任务，可能会覆盖现有文件。是否继续？',
      'warning', 
      '确定重新下载',
      '取消',
      doRedownload
    )
  } else {
    // 失败重试，直接重新下载
    await doRedownload()
  }
}

function closeNfoEditor() {
  showNfoEditor.value = false
  nfoEditingVideo.value = null
  nfoEditorContent.value = ''
  nfoEditorLoading.value = false
  nfoEditorSaving.value = false
}

async function openNfoEditor(video) {
  if (!video?.id) return
  if (isNfoButtonDisabled(video)) {
    customAlert('无法编辑NFO', getNfoButtonTitle(video), 'warning')
    return
  }
  nfoEditingVideo.value = video
  nfoEditorContent.value = ''
  nfoEditorLoading.value = true
  showNfoEditor.value = true

  try {
    const data = await subscriptionsApi.getVideoNfo(props.subscriptionId, video.id)
    if (!data?.success) {
      throw new Error('未找到NFO文件')
    }
    nfoEditorContent.value = data.content || ''
  } catch (error) {
    console.error('加载NFO失败:', error)
    closeNfoEditor()
    customAlert('无法编辑NFO', error.message || '未找到NFO文件', 'warning')
  } finally {
    nfoEditorLoading.value = false
  }
}

async function saveNfoEditor() {
  if (!nfoEditingVideo.value?.id || nfoEditorSaving.value) return

  nfoEditorSaving.value = true
  try {
    await subscriptionsApi.updateVideoNfo(
      props.subscriptionId,
      nfoEditingVideo.value.id,
      nfoEditorContent.value || ''
    )
    customAlert('保存成功', 'NFO 已更新', 'success')
    closeNfoEditor()
  } catch (error) {
    console.error('保存NFO失败:', error)
    customAlert('保存失败', error.message || 'NFO 更新失败', 'error')
  } finally {
    nfoEditorSaving.value = false
  }
}

// 播放已下载视频
function playVideo(video) {
  if (!video?.download_task_id) {
    customAlert('无法播放', '该视频缺少任务ID，无法直接跳转播放。', 'warning')
    return
  }

  const query = {
    task_id: video.download_task_id,
    subscription_id: props.subscriptionId
  }

  emit('update:show', false)
  router.push({ path: '/player', query }).then(() => {
    nextTick(() => {
      try {
        const container = document.querySelector('.main-content')
        if (container && typeof container.scrollTo === 'function') {
          container.scrollTo({ top: 0, behavior: 'auto' })
        } else {
          window.scrollTo({ top: 0, behavior: 'auto' })
        }
      } catch (e) {}
    })
  })
}

// 批量下载
async function startBatchDownload() {
  if (isStarting.value) return
  if (batchType.value === 'time' && !supportsDateBatchDownload.value) {
    customAlert(
      '不支持按时间下载',
      dateBatchDownloadTip.value,
      'warning'
    )
    return
  }
  isStarting.value = true
  try {
    // 构建请求参数，必须包含type字段
    const params = {
      type: batchType.value, // 必需字段：'count' 或 'time'
      batch_size: parseInt(concurrentLimit.value)
    }
    
    // 计算实际要下载的数量
    let estimatedTotal = 0
    
    // 根据类型设置count或days
    if (batchType.value === 'count') {
      const countValue = parseInt(batchCount.value)
      // -1表示下载所有视频
      if (countValue === -1) {
        params.count = -1
        estimatedTotal = stats.value.not_downloaded_count || 0
      } else {
        params.count = countValue
        // 实际下载数量是用户选择的数量和未下载数量的较小值
        estimatedTotal = Math.min(countValue, stats.value.not_downloaded_count || 0)
      }
    } else {
      params.days = parseInt(batchDays.value)
      // 按时间下载，使用未下载总数作为估算（后端会筛选）
      estimatedTotal = stats.value.not_downloaded_count || 0
    }
    
    // 设置画质（YouTube和B站需要）
    if (isYouTube.value || isBilibili.value) {
      params.quality = selectedQuality.value
    } else {
      // 其他平台使用默认值
      params.quality = 'best'
    }
    
    await subscriptionsApi.batchDownload(props.subscriptionId, params)
    
    // 通知父组件批量下载已开始（立即显示进度）
    emit('batchDownloadStarted', {
      subscriptionId: props.subscriptionId,
      total: estimatedTotal
    })
    
    // 修改弹窗，增加跳转按钮
    customAlert(
      '批量下载任务已提交', 
      '批量下载任务已成功提交，系统将自动开始下载', 
      'confirm',
      '查看任务进度',
      '留在原位',
      () => {
        emit('update:show', false) // 关闭当前模态框
        router.push('/batch-download-tasks') // 跳转到任务页面
      }
    )
    
    // 刷新列表
    await loadVideos(1, false)
  } catch (error) {
    console.error('批量下载失败:', error)
    const errorMessage = error.response?.data?.detail || error.message || '未知错误'
    customAlert('批量下载失败', errorMessage, 'error')
  } finally {
    isStarting.value = false
  }
}

// 获取画质显示名称
function getQualityDisplayName(quality) {
  const qualityMap = {
    'bestvideo+bestaudio': '最高画质',
    'bestvideo[height<=4320]+bestaudio': '8K',
    'bestvideo[height<=2160]+bestaudio': '4K',
    'bestvideo[height<=1440]+bestaudio': '2K',
    'bestvideo[height<=1080]+bestaudio': '1080p',
    'bestvideo[height<=720]+bestaudio': '720p',
    'bestvideo[height<=480]+bestaudio': '480p',
    'best': '自动选择最佳'
  }
  return qualityMap[quality] || quality
}

// 重试失败任务
async function retryFailed() {
  try {
    // 根据平台显示不同的画质信息
    let qualityInfo = ''
    if (isYouTube.value || isBilibili.value) {
      qualityInfo = `<br>• 画质：${getQualityDisplayName(selectedQuality.value)}`
    } else {
      qualityInfo = `<br>• 画质：自动选择最佳 (${props.platform === 'douyin' || props.platform === 'douyin_collection' ? '抖音' : ''}平台)`
    }

    // 显示确认对话框
    const confirmed = await new Promise((resolve) => {
      const message = `确定要重试所有失败的下载任务吗？<br><br><strong>当前设置：</strong><br>• 并发数：${concurrentLimit.value}${qualityInfo}`
      
      tipTitle.value = '重试失败任务'
      tipMessage.value = message
      tipType.value = 'confirm'
      showTipModal.value = true
      
      // 保存resolve函数供确认/取消按钮调用
      window._retryConfirmResolve = resolve
    })

    if (!confirmed) {
      return
    }

    // 准备请求参数
    const params = {
      batch_size: parseInt(concurrentLimit.value)
    }
    
    // 设置画质（YouTube和B站需要）
    if (isYouTube.value || isBilibili.value) {
      params.quality = selectedQuality.value
    } else {
      params.quality = 'best'
    }

    await subscriptionsApi.retryFailed(props.subscriptionId, params)
    customAlert('重试任务已提交', '重试任务已成功提交，系统将自动开始重试失败的下载', 'success')
    await loadVideos(1, false)
  } catch (error) {
    console.error('重试失败:', error)
    customAlert('重试失败', error.message || '未知错误', 'error')
  }
}

// 保存画质设置
async function saveQuality() {
  try {
    await subscriptionsApi.updateQuality(props.subscriptionId, selectedQuality.value)
    emit('qualityUpdated', selectedQuality.value)
    customAlert('画质设置已保存', '画质设置已成功保存', 'success')
  } catch (error) {
    console.error('保存画质失败:', error)
    customAlert('保存失败', error.message || '未知错误', 'error')
  }
}

// 删除单条视频记录
async function handleDeleteVideo(video) {
  customAlert(
    '确认删除',
    `确定从列表中删除视频 <strong>${video.title}</strong> 吗？<br><small style="color: #666">注：这仅删除展示记录，不会物理删除已下载的文件。</small>`,
    'confirm',
    '确定删除',
    '取消',
    async () => {
      try {
        await subscriptionsApi.deleteVideo(video.id)
        // 从当前数组移除
        videos.value = videos.value.filter(v => v.id !== video.id)
        // 刷新统计信息
        loadStats()
      } catch (error) {
        console.error('删除视频失败:', error)
        customAlert('删除失败', error.message || '未知错误', 'error')
      }
    }
  )
}

// 点击遮罩关闭
function handleOverlayClick(e) {
  if (e.target === e.currentTarget) {
    emit('update:show', false)
  }
}

// 监听显示状态
watch(() => props.show, (newVal) => {
  if (newVal) {
    // 立即清空旧数据，防止闪现上一个博主的内容
    videos.value = []
    localCoverMap.value = {}
    localCoverLoadingMap.value = {}
    localCoverFailedMap.value = {}
    nfoAvailabilityMap.value = {}
    nfoAvailabilityLoadingMap.value = {}
    stats.value = {
      total: 0,
      downloaded_count: 0,
      downloading_count: 0,
      not_downloaded_count: 0,
      failed_count: 0,
      removed_count: 0,
      cancelled_count: 0,
      orphaned_count: 0,
      charging_count: 0,
      video_count: 0,
      note_count: 0
    }
    
    currentPage.value = 1
    hasMore.value = true
    currentFilter.value = 'all'
    selectedQuality.value = props.currentQuality || 'bestvideo+bestaudio'
    if (!supportsDateBatchDownload.value && batchType.value === 'time') {
      batchType.value = 'count'
    }
    // 并发加载列表和统计数据
    loadVideos(1, false)
    loadStats()
  }
})

watch(supportsDateBatchDownload, (supported) => {
  if (!supported && batchType.value === 'time') {
    batchType.value = 'count'
  }
})
</script>

<style scoped>
.video-list-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  z-index: 20000;
  overflow: hidden;
}

.video-list-modal-content {
  max-width: 1000px;
  width: 100%;
  max-height: 92vh;
  background: #fff;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  padding-top: 10px;
}

[data-theme="dark"] .video-list-modal-content {
  background: var(--color-bg-card);
}

.modal-close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 32px;
  height: 32px;
  border: none;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border-radius: 50%;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 100;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.modal-close-btn:hover {
  background: rgba(0, 0, 0, 0.1);
}

[data-theme="dark"] .modal-close-btn {
  background: rgba(255, 255, 255, 0.1);
  color: var(--color-text-primary);
}

[data-theme="dark"] .modal-close-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.modal-title {
  text-align: center;
  margin: 15px 0 10px;
  font-size: 1.25em;
  padding: 0 45px;
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.platform-name {
  color: var(--color-primary);
  font-size: 0.85em;
  font-weight: 500;
}

.nickname-title {
  color: #333;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

[data-theme="dark"] .nickname-title {
  color: var(--color-text-primary);
}

.tip-info {
  margin: 0 10px 8px;
  padding: 8px;
  background: #f8f9fa;
  border-radius: 8px;
  font-size: 0.9em;
}

[data-theme="dark"] .tip-info {
  background: var(--color-bg-tertiary);
}

.tip-items {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-bottom: 10px;
  color: #666;
  line-height: 1.4;
}

[data-theme="dark"] .tip-items {
  color: var(--color-text-secondary);
}

.tip-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.batch-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-row, .actions-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.batch-mode-tip {
  font-size: 0.85em;
  color: #b45309;
}

[data-theme="dark"] .batch-mode-tip {
  color: #fbbf24;
}

.actions-row {
  justify-content: flex-start;
  width: 100%;
}

.main-buttons {
  display: flex;
  gap: 8px;
}

.main-buttons .btn {
  white-space: nowrap;
  min-width: 120px; /* 设置个合理的最小宽度，防止太短 */
}

.concurrent-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.filter-group {
  display: flex;
  gap: 8px;
  align-items: center;
}

.form-select-sm {
  height: 30px;
  padding: 2px 6px;
  font-size: 0.9em;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: white;
}

[data-theme="dark"] .form-select-sm {
  background: var(--color-bg-tertiary);
  border-color: var(--color-border);
  color: var(--color-text-primary);
}

.concurrent-label {
  font-size: 0.9em;
  color: #666;
  white-space: nowrap;
}

[data-theme="dark"] .concurrent-label {
  color: var(--color-text-secondary);
}

.concurrent-select {
  width: 60px;
}

.quality-group {
  margin-left: 0;
}

.video-stats {
  margin: 0 10px 8px;
  padding: 8px;
  background: #f8f9fa;
  border: 1px solid #e9ecef;
  border-radius: 8px;
}

[data-theme="dark"] .video-stats {
  background: var(--color-bg-tertiary);
  border-color: var(--color-border);
}

.stats-header {
  font-weight: 500;
  margin-bottom: 6px;
  color: #495057;
  font-size: 0.95em;
}

[data-theme="dark"] .stats-header {
  color: var(--color-text-primary);
}

.stats-filters {
  display: flex;
  gap: 6px;
  font-size: 0.85em;
  overflow-x: auto;
  white-space: nowrap;
  padding-bottom: 4px;
  margin-bottom: 6px;
}

.status-filter-btn {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid #dfe3e6;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--color-text-primary);
}

[data-theme="dark"] .status-filter-btn {
  background: var(--color-bg-secondary);
  border-color: var(--color-border);
}

.status-filter-btn:hover {
  border-color: #adb5bd;
}

[data-theme="dark"] .status-filter-btn:hover {
  border-color: var(--color-border-light);
}

.status-filter-btn.active {
  border-color: var(--color-primary);
  background: rgba(var(--color-primary-rgb), 0.1);
}

.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.progress-section {
  margin-top: 6px;
}

.progress-label {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 0.85em;
  color: #6c757d;
}

[data-theme="dark"] .progress-label {
  color: var(--color-text-secondary);
}

.progress-bar {
  width: 100%;
  height: 4px;
  background: #e9ecef;
  border-radius: 3px;
  overflow: hidden;
}

[data-theme="dark"] .progress-bar {
  background: var(--color-bg-tertiary);
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #28a745, #20c997);
  transition: width 0.3s ease;
}

.video-list-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  border: 1px solid #e9ecef;
  border-radius: 8px;
  margin: 0 10px 10px;
}

[data-theme="dark"] .video-list-container {
  border-color: var(--color-border);
}

.video-items {
  display: flex;
  flex-direction: column;
}

.video-item {
  display: flex;
  gap: 10px;
  padding: 10px;
  border-bottom: 1px solid #eee;
  /* 布局隔离优化 */
  contain: layout;
}

[data-theme="dark"] .video-item {
  border-bottom-color: var(--color-border);
}

.video-item:last-child {
  border-bottom: none;
}

.video-cover,
.video-cover-placeholder {
  width: 120px;
  height: 67px;
  object-fit: cover;
  border-radius: 4px;
  flex-shrink: 0;
  background: #eee;
  /* GPU加速优化 */
  transform: translateZ(0);
  will-change: transform;
  backface-visibility: hidden;
}

[data-theme="dark"] .video-cover-placeholder {
  background: var(--color-bg-tertiary);
}

.video-details {
  flex: 1;
  min-width: 0;
}

.video-title {
  font-weight: bold;
  margin-bottom: 5px;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: break-word;
}

.video-link {
  color: var(--color-text-primary);
  text-decoration: none;
  transition: color 0.2s;
}

.video-link:hover {
  color: var(--color-primary);
  text-decoration: underline;
}

.content-type-badge {
  display: inline-block;
  margin-right: 6px;
  padding: 2px 6px;
  font-size: 0.75em;
  font-weight: 500;
  border-radius: 4px;
  background: #e9ecef;
  color: #495057;
  vertical-align: middle;
}

[data-theme="dark"] .content-type-badge {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
}

.content-type-badge.is-note {
  background: #fff3cd;
  color: #856404;
}

[data-theme="dark"] .content-type-badge.is-note {
  background: rgba(255, 243, 205, 0.3);
  color: #ffd700;
}

.video-time {
  font-size: 0.9em;
  color: #666;
  margin-bottom: 5px;
}

[data-theme="dark"] .video-time {
  color: var(--color-text-tertiary);
}

.video-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.status-tag {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 0.85em;
  white-space: nowrap;
}

.status-tag.success {
  background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
  color: white;
}

.status-tag.error {
  background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
  color: white;
}

.status-tag.warning {
  background: linear-gradient(135deg, #ffc107 0%, #e0a800 100%);
  color: #000;
}

.status-tag.info {
  background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
  color: white;
}

.status-tag.archived {
  background: linear-gradient(135deg, #9333ea 0%, #7c3aed 100%);
  color: white;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 0.85em;
}

.error-message {
  font-size: 0.85em;
  color: #d32f2f;
  max-width: 300px;
  word-break: break-word;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

[data-theme="dark"] .error-message {
  color: #ff6b6b;
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: #666;
}

[data-theme="dark"] .loading-state,
[data-theme="dark"] .empty-state {
  color: var(--color-text-secondary);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid var(--color-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.spinner-sm {
  width: 20px;
  height: 20px;
  border: 2px solid #f3f3f3;
  border-top: 2px solid var(--color-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.load-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 20px;
  color: #666;
  font-size: 0.9em;
}

/* 按钮动画效果 */
.btn-action-animate {
  transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  position: relative;
  overflow: hidden;
  min-width: 100px;
}

.btn-action-animate:active {
  transform: scale(0.95);
}

.btn-loading-content, .btn-downloading-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.spinner-small-btn {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  background-color: #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 rgba(255, 255, 255, 0.7);
  animation: pulse-effect 1.5s infinite;
}

@keyframes pulse-effect {
  0% {
    box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.7);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(255, 255, 255, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(255, 255, 255, 0);
  }
}

.btn-delete {
  background: transparent;
  color: #dc3545;
  border: 1px solid #dc3545;
  margin-left: auto; /* 将删除按钮推向最右侧 */
}

.btn-delete:hover {
  background: #dc3545;
  color: white;
}

.nfo-editor-wrap {
  display: flex;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  height: 100%;
  min-height: 320px;
}

.nfo-editor-loading {
  height: 100%;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #666;
}

[data-theme="dark"] .nfo-editor-loading {
  color: var(--color-text-secondary);
}

.nfo-editor-textarea {
  flex: 1 1 auto;
  width: auto;
  min-width: 0;
  height: 100%;
  min-height: 320px;
  resize: none;
  border: 1px solid #cfd6dd;
  border-radius: 8px;
  padding: 12px 14px;
  font-family: Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #2f3440;
  background: #fcfdff;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}

[data-theme="dark"] .nfo-editor-textarea {
  border-color: var(--color-border);
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

/* 移动端适配 */
@media screen and (max-width: 600px) {
  .video-list-modal-overlay {
    padding: 0;
    /* 移动端从顶部对齐，而不是居中 */
    align-items: flex-start;
  }

  .video-list-modal-content {
    /* 使用动态视口高度，自动排除浏览器UI（地址栏等） */
    max-height: 100dvh;
    height: 100dvh;
    border-radius: 0;
    padding-top: 15px;
  }

  .modal-title {
    font-size: 1.1em;
    gap: 4px;
    padding: 0 45px;
    margin-top: 10px;
  }
  
  .nickname-title {
    max-width: 120px;
  }
  
  .platform-name {
    font-size: 0.8em;
  }
  
  .batch-controls {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  
  .filter-group {
    flex-wrap: wrap;
    justify-content: center;
  }

  .video-item {
    padding: 10px;
  }
  
  .video-details {
    padding: 0 0 0 10px;
  }
  
  .video-title {
    font-size: 0.95em;
  }
}
</style>
