<template>
  <div class="dashboard">
    <!-- 左侧主内容区 -->
    <div class="dashboard-left">


      <!-- 双栏布局：(快捷操作/核心服务) + 最近活动 -->
      <div class="content-split-row">
        <!-- 左栏：快捷操作 + 核心服务 -->
        <div class="split-col side-col">
          <!-- 合并后的下载与订阅统计卡片 -->
          <DownloadStatsCard
            :downloading="systemStore.metrics.downloads.downloading"
            :total-completed="totalCompleted"
            :queued="systemStore.metrics.downloads.queued"
            :total-failed="totalFailed"
          >
            <template #mobile-stats>
              <!-- Video Monitor Stats (Mobile Only) -->
              <div class="live-stats-row mobile-stats-append">
                <div class="live-stat-item" @click="goToSubscriptionsWithFilter('', 'active')">
                  <span class="stat-mini-label">视频订阅</span>
                  <div class="live-stat-val text-success">{{ subscriptionStatusStats.active }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item" @click="goToSubscriptionsWithFilter('', 'paused')">
                  <span class="stat-mini-label">暂停订阅</span>
                  <div class="live-stat-val">{{ subscriptionStatusStats.paused }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item" @click="goToSubscriptionsWithFilter('', 'error')">
                  <span class="stat-mini-label">异常订阅</span>
                  <div class="live-stat-val text-error">{{ subscriptionStatusStats.error }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item" @click="goToSubscriptionsWithFilter('', 'invalid')">
                  <span class="stat-mini-label">失效订阅</span>
                  <div class="live-stat-val text-error">{{ subscriptionStatusStats.invalid }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item" @click="router.push('/downloads')">
                  <span class="stat-mini-label">存储</span>
                  <div class="live-stat-val" style="min-height: 20px; display: flex; align-items: center; justify-content: center; font-size: 13px !important;">{{ formatBytes(systemStore.storage.directory_size_bytes || 0, 2).replace(' ', '') }}</div>
                </div>
              </div>
              <div class="live-stats-row mobile-stats-append">
                <div class="live-stat-item" @click="router.push('/live-record?status=all&platform=all')">
                  <span class="stat-mini-label">直播监控</span>
                  <div class="live-stat-val">{{ liveStats.total_subscriptions }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item" @click="router.push('/live-record?status=live&platform=all')">
                  <span class="stat-mini-label">正在直播</span>
                  <div class="live-stat-val" :class="{ 'text-success': liveStats.live_count > 0 }">{{ liveStats.live_count }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item recording" @click="router.push('/live-record?status=recording')">
                  <span class="stat-mini-label">正在录制</span>
                  <div class="live-stat-val">{{ liveStats.recording_count }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item" @click="router.push({ path: '/live-record', query: { action: 'history' } })">
                  <span class="stat-mini-label">今日成果</span>
                  <div class="live-stat-val">{{ liveStats.today_records }}</div>
                </div>
                <div class="stat-divider-vertical"></div>
                <div class="live-stat-item" @click="router.push('/live-record')">
                  <span class="stat-mini-label">空间</span>
                  <div class="live-stat-val" style="min-height: 20px; display: flex; align-items: center; justify-content: center; font-size: 13px !important;">{{ formatBytes(liveStats.total_size, 2).replace(' ', '') }}</div>
                </div>
              </div>
            </template>
          </DownloadStatsCard>

          <!-- 直播订阅监控 -->
          <LiveMonitorCard
            :segments="livePieChartSegments"
            :total="liveStats.total_subscriptions"
            :platform-distribution="livePlatformDistribution"
            :stats="liveStats"
            :total-enabled="totalEnabledLiveSubscriptions"
          />

          <!-- 视频订阅系统监控 -->
          <SubscriptionMonitorCard
            :segments="pieChartSegments"
            :total="subscriptionStats?.total || subscriptionsStore.stats.total"
            :platform-distribution="platformDistribution"
            :status-stats="subscriptionStatusStats"
            :storage-size="systemStore.storage.directory_size_bytes || 0"
            :active-download-count="systemStore.metrics.downloads?.active_subscriptions || 0"
            :auto-download-enabled-count="autoDownloadEnabledCount"
          />

        </div>

        <!-- 右栏：最近活动 + 直播监控 (占据半宽) -->
        <div class="split-col activity-col">
          <div class="stats-left-group">
            <!-- 公告中心（电脑端放在最前面） -->
            <AnnouncementsCard
              :has-app-update="systemStore.hasAppUpdate"
              :has-unread-notice="systemStore.hasUnreadNotice"
              @click="showAnnouncementsModal"
            />

            <!-- 高级功能授权卡片 -->
            <LicenseCard
              :has-license="systemStore.hasLicense"
              :is-loading="systemStore.license.isLoading"
              :remaining-days="systemStore.license.remaining_days"
            />
            
            <!-- 磁盘存储卡片 (移入 stats-left-group) -->
            <StorageCard
              :total-bytes="totalStorageBytes"
              :used-bytes="usedStorageBytes"
              :free-bytes="freeStorageBytes"
              :unit-mode="storageUnitMode"
              @toggle-unit="toggleStorageUnit"
            />
            <GpuMonitorCard
              :gpu-stats="gpuStats"
              :is-loading="gpuLoading"
              :gpu-history="gpuHistory"
              :gpu-chart-points="gpuChartPoints"
              :gpu-max-percent="gpuMaxPercent"
              :grid-scroll-x="gridScrollX"
            />
          </div>
          <!-- 核心服务 -->
          <ServiceStatusCard
            :services="filteredSupervisorServices"
            :network-status="networkStatus"
          />

          <RecentActivityCard
            :activities="recentActivity"
            :thumbnail-cache="thumbnailCache"
          />
        </div>
      </div>
    </div>

    <!-- 右侧侧边栏：专门放置监控 (系统状态) -->
    <SystemStatusSection
      :metrics="systemStore.metrics"
      :app-version="systemStore.app.version"
      :core-version="systemStore.core.current_version"
      :core-latest-version="systemStore.core.latest_version"
      :core-has-update="systemStore.core.has_update"
      :is-checking-core="isCheckingCore"
      :cpu-history="cpuHistory"
      :cpu-chart-points="cpuChartPoints"
      :cpu-max-percent="cpuMaxPercent"
      :grid-scroll-x="gridScrollX"
      :network-history="networkHistory"
      :network-chart-points="networkChartPoints"
      :network-max-speed="networkMaxSpeed"
      @core-update="checkCoreUpdate"
    />

    <!-- 公告详情模态框 -->
    <div class="announcement-modal-overlay" v-if="showAnnouncementModal" @click="closeAnnouncementModal">
      <div class="announcement-modal" @click.stop>
        <div class="announcement-modal-header">
          <h2 class="modal-title">公告中心</h2>
          <button class="modal-close-btn" @click="closeAnnouncementModal">
            <Icon name="x" :size="20" />
          </button>
        </div>
        
        <div class="announcement-modal-content">
          <!-- 版本更新提示 -->
          <div v-if="systemStore.hasAppUpdate" class="version-alert">
            <Icon name="zap" :size="18" class="alert-icon" />
            <div class="alert-content">
              <div class="alert-title">发现新版本</div>
              <div class="alert-version">
                <div>当前: {{ systemStore.app.version }}</div>
                <div>最新: {{ systemStore.latestAppVersion }}</div>
              </div>
            </div>
          </div>

          <div v-if="isLoadingAnnouncements" class="announcements-loading-modal">
            <Icon name="refresh" :size="22" class="loading-icon" />
            <span>正在加载更新日志...</span>
          </div>
          <template v-else>
            <!-- 公告列表（只在没有选中公告时显示） -->
            <div v-if="!selectedAnnouncement">
              <div v-if="systemStore.announcements.length === 0" class="announcements-empty-modal">
                <Icon name="info" :size="24" />
                <span>暂无公告</span>
              </div>
              
              <div v-else class="announcements-list-modal">
                <div 
                  v-for="(ann, index) in systemStore.announcements" 
                  :key="ann.id || index"
                  class="announcement-list-item"
                  :class="{ 'sticky': ann.sticky }"
                  @click="selectedAnnouncement = ann"
                >
                  <div class="ann-list-header">
                    <div class="ann-list-content">
                      <div class="ann-list-title-row">
                        <span class="ann-list-title">{{ ann.title }}</span>
                        <span v-if="ann.sticky" class="ann-sticky-tag">置顶</span>
                      </div>
                      <div class="ann-list-time">{{ formatAnnouncementDateTime(ann.updated_at || ann.start_at) }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 公告详情（选中公告时显示，默认显示最新一条） -->
            <div v-if="selectedAnnouncement" class="announcement-detail-card">
              <div class="ann-detail-header">
                <h3 class="ann-detail-title">{{ selectedAnnouncement.title }}</h3>
                <button class="btn btn-sm btn-outline ann-back-btn" @click="selectedAnnouncement = null">
                  返回列表
                </button>
              </div>
              <div class="ann-detail-time">{{ formatAnnouncementDateTime(selectedAnnouncement.updated_at || selectedAnnouncement.start_at) }}</div>
              
              <div class="ann-detail-body">
                <div class="ann-detail-content" v-html="formatAnnouncementContent(selectedAnnouncement.content)"></div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>

</template>


<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import { useSystemStore } from '@/stores/system'
import { useDownloadsStore } from '@/stores/downloads'
import { useSubscriptionsStore } from '@/stores/subscriptions'
import { subscriptionsApi } from '@/api/subscriptions'
import { wsService } from '@/utils/websocket'
import { tasksApi } from '@/api/tasks'
import { systemApi as coreApi } from '@/api/index'
import liveApi from '@/api/live'
import DownloadStatsCard from '@/components/dashboard/DownloadStatsCard.vue'
import LiveMonitorCard from '@/components/dashboard/LiveMonitorCard.vue'
import SubscriptionMonitorCard from '@/components/dashboard/SubscriptionMonitorCard.vue'
import AnnouncementsCard from '@/components/dashboard/AnnouncementsCard.vue'
import LicenseCard from '@/components/dashboard/LicenseCard.vue'
import StorageCard from '@/components/dashboard/StorageCard.vue'
import GpuMonitorCard from '@/components/dashboard/GpuMonitorCard.vue'
import ServiceStatusCard from '@/components/dashboard/ServiceStatusCard.vue'
import RecentActivityCard from '@/components/dashboard/RecentActivityCard.vue'
import SystemStatusSection from '@/components/dashboard/SystemStatusSection.vue'
import { pickPrimaryGpu } from '@/utils/gpu'

const router = useRouter()
const systemStore = useSystemStore()
const downloadsStore = useDownloadsStore()
const subscriptionsStore = useSubscriptionsStore()
const subscriptionStats = ref(null)
const STORAGE_UNIT_MODE_KEY = 'dashboard_storage_unit_mode'
const storageUnitMode = ref(localStorage.getItem(STORAGE_UNIT_MODE_KEY) === 'binary' ? 'binary' : 'decimal')
const gpuStats = computed(() => systemStore.metrics?.gpu_stats || { summary: { has_gpu: false }, gpus: [] })
const gpuLoading = computed(() => !systemStore.metrics?.timestamp)

// 饼图交互
const hoveredSegment = ref(null)
const hoveredLiveSegment = ref(null)

// 公告详情模态框
const showAnnouncementModal = ref(false)
const selectedAnnouncement = ref(null)
const isLoadingAnnouncements = ref(false)

// 显示公告列表（参考旧版本的 showAnnouncements：用户点击查看时才获取）
const showAnnouncementsModal = async () => {
  // 先打开弹窗，立即给用户反馈
  showAnnouncementModal.value = true
  selectedAnnouncement.value = null

  // 如果公告列表为空，先获取公告列表
  if (!systemStore.announcements.length) {
    isLoadingAnnouncements.value = true
    try {
      await systemStore.fetchAnnouncements() // 用户主动查看，不应用防抖
    } catch (err) {
      console.error('获取公告列表失败:', err)
    } finally {
      isLoadingAnnouncements.value = false
    }
  }

  // 默认选中第一条公告
  if (systemStore.announcements.length > 0) {
    selectedAnnouncement.value = systemStore.announcements[0]
    // 标记为已读
    systemStore.markAnnouncementsRead()
  } else {
    selectedAnnouncement.value = null
  }
}

// 关闭公告详情模态框
const closeAnnouncementModal = () => {
  showAnnouncementModal.value = false
  isLoadingAnnouncements.value = false
  setTimeout(() => {
    selectedAnnouncement.value = null
  }, 300)
}

// 格式化公告时间（相对时间）
const formatAnnouncementTime = (timeStr) => {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const now = new Date()
  const diff = Math.floor((now - date) / 1000)
  
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 604800) return `${Math.floor(diff / 86400)}天前`
  
  // 超过一周显示具体日期
  const Y = date.getFullYear()
  const M = (date.getMonth() + 1).toString().padStart(2, '0')
  const D = date.getDate().toString().padStart(2, '0')
  return `${Y}-${M}-${D}`
}

// 格式化公告时间（完整日期时间）
const formatAnnouncementDateTime = (timeStr) => {
  if (!timeStr) return ''
  const date = new Date(timeStr)
  const Y = date.getFullYear()
  const M = (date.getMonth() + 1).toString().padStart(2, '0')
  const D = date.getDate().toString().padStart(2, '0')
  const h = date.getHours().toString().padStart(2, '0')
  const m = date.getMinutes().toString().padStart(2, '0')
  const s = date.getSeconds().toString().padStart(2, '0')
  return `${Y}/${M}/${D} ${h}:${m}:${s}`
}

// 格式化公告内容（解析特殊格式）
const formatAnnouncementContent = (content) => {
  if (!content) return ''
  // 将换行符转换为 <br>
  let formatted = content.replace(/\n/g, '<br>')
  // 匹配链接并转换为可点击链接
  formatted = formatted.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" class="ann-detail-link">$1</a>')
  return formatted
}

// 直播统计
const liveStats = ref({
  total_subscriptions: 0,
  live_count: 0,  // 正在直播的数量
  recording_count: 0,
  today_records: 0,
  total_size: 0
})

// 直播平台分布
const livePlatformDistribution = ref({})
const totalEnabledLiveSubscriptions = ref(0)

// 直播饼图数据
const livePieChartSegments = computed(() => {
  const platforms = livePlatformDistribution.value
  
  if (Object.keys(platforms).length === 0) return []
  
  const total = Object.values(platforms).reduce((sum, data) => sum + data.count, 0) || 1
  // SVG 饼图周长 (r=40) => 2 * PI * 40
  const circumference = 2 * Math.PI * 40
  
  let currentOffset = 0
  const segments = []

  // 按数量排序，相同数量时按平台名称排序（确保排序稳定，避免刷新后乱跳）
  const sorted = Object.entries(platforms).sort((a, b) => {
    // 首先按数量降序
    if (b[1].count !== a[1].count) {
      return b[1].count - a[1].count
    }
    // 数量相同时，按平台名称排序（确保稳定）
    return a[0].localeCompare(b[0])
  })

  sorted.forEach(([platform, data]) => {
    const percent = data.count / total
    const dashArray = circumference * percent
    
    // 统一平台标识：将 xhs 统一映射为 redbook 以匹配颜色配置
    const knownPlatforms = ['douyin', 'tiktok', 'youtube', 'bilibili', 'redbook', 'xhs', 'huya', 'douyu', 'migu', 'kuaishou', 'weibo', 'cc']
    let colorId = knownPlatforms.includes(platform) ? platform : 'other'
    if (colorId === 'xhs') colorId = 'redbook' // 强制映射到红色系

    segments.push({
      platform,
      colorId,
      name: data.name,
      count: data.count,
      percent: Math.round((data.count / total) * 100),
      dashArray,
      dashOffset: -currentOffset
    })
    
    currentOffset += dashArray
  })
  
  return segments
})

// 获取订阅轻量统计（替代全量 fetchSubscriptions）
async function fetchSubscriptionStats() {
  try {
    const data = await subscriptionsApi.getStats()
    subscriptionStats.value = data
  } catch (err) {
    console.error('Failed to fetch subscription stats:', err)
    try {
      await subscriptionsStore.fetchSubscriptions()
    } catch (_) {}
  }
}

// 获取直播平台分布
async function fetchLivePlatformStats() {
  try {
    const res = await liveApi.getLiveSubscriptions()
    let list = []
    // 兼容不同的返回结构
    if (res && res.data && Array.isArray(res.data)) list = res.data
    else if (Array.isArray(res)) list = res
    else if (res && res.items && Array.isArray(res.items)) list = res.items

    const dist = {}
    const names = {
      'douyin': '抖音',
      'tiktok': 'TikTok',
      'youtube': 'YouTube',
      'bilibili': 'Bilibili',
      'huya': '虎牙',
      'douyu': '斗鱼',
      'migu': '咪咕',
      'redbook': '小红书',
      'xhs': '小红书',
      'kuaishou': '快手',
      'weibo': '微博',
      'cc': '网易CC'
    }

    let enabledCount = 0
    list.forEach(sub => {
      // 统计开启录播的订阅
      if (String(sub.auto_record) === 'true' || sub.auto_record === true) {
        enabledCount++
      }

      const p = sub.platform
      if (!dist[p]) {
        dist[p] = { name: names[p] || p, count: 0 }
      }
      dist[p].count++
    })
    
    totalEnabledLiveSubscriptions.value = enabledCount
    livePlatformDistribution.value = dist
  } catch (err) {
    console.error('Fetch live platform stats failed:', err)
  }
}


// 最近活动
const recentActivity = ref([])

// 已下载总数
const totalCompleted = ref(0)
const totalFailed = ref(0)


// 格式化数据大小
function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 B'
  const k = storageUnitMode.value === 'binary' ? 1024 : 1000
  const dm = decimals < 0 ? 0 : decimals
  const sizes = storageUnitMode.value === 'binary'
    ? ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB']
    : ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]
}

const totalStorageBytes = computed(() => {
  if (systemStore.storage.total_bytes > 0) return systemStore.storage.total_bytes
  return Math.round((systemStore.storage.total_gb || 0) * (1000 ** 3))
})

const usedStorageBytes = computed(() => {
  if (systemStore.storage.used_bytes > 0) return systemStore.storage.used_bytes
  return Math.round((systemStore.storage.used_gb || 0) * (1000 ** 3))
})

const freeStorageBytes = computed(() => {
  if (systemStore.storage.free_bytes > 0) return systemStore.storage.free_bytes
  return Math.round((systemStore.storage.free_gb || 0) * (1000 ** 3))
})

function toggleStorageUnit() {
  storageUnitMode.value = storageUnitMode.value === 'decimal' ? 'binary' : 'decimal'
}


// 核心版本检测相关
const isCheckingCore = ref(false)

async function checkCoreUpdate() {
  if (isCheckingCore.value) return
  isCheckingCore.value = true
  try {
    await systemStore.fetchCoreVersion(false) // 完整检测
  } finally {
    isCheckingCore.value = false
  }
}

function getCoreDisplayText() {
  if (isCheckingCore.value) return '检测中...'
  const { current_version, latest_version, has_update } = systemStore.core
  if (has_update && latest_version) {
    return `${latest_version} (新)`
  }
  return current_version || '检查中...'
}

function getCoreTitle() {
  if (isCheckingCore.value) return '正在与服务器通信...'
  if (systemStore.core.has_update) return '发现新版本，请更新镜像'
  return '点击检测更新'
}

// 格式化相对时间
function formatTime(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now - date) / 1000)
  
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

// 获取活动图标名称
function getActivityIcon(type) {
  const map = {
    download: 'download',
    subscription: 'refresh',
    system: 'settings',
    delete: 'trash'
  }
  return map[type] || 'activity'
}

// 缩略图缓存
const thumbnailCache = ref({})
const thumbnailLoadedKeys = ref({})
const thumbnailLoadingKeys = ref({})

function getThumbnailLoadKey(item) {
  return [item.id, item.updated_at || '', item.filename || '', item.status || ''].join('|')
}

function pruneThumbnailCache(items) {
  const keepIds = new Set(items.map(item => item.id))
  Object.keys(thumbnailCache.value).forEach((id) => {
    if (!keepIds.has(id)) delete thumbnailCache.value[id]
  })
  Object.keys(thumbnailLoadedKeys.value).forEach((id) => {
    if (!keepIds.has(id)) delete thumbnailLoadedKeys.value[id]
  })
  Object.keys(thumbnailLoadingKeys.value).forEach((id) => {
    if (!keepIds.has(id)) delete thumbnailLoadingKeys.value[id]
  })
}

// 加载活动缩略图（仅本地缩略图，不加载在线缩略图）
async function loadActivityThumbnail(item) {
  // 只加载已完成任务的本地缩略图
  if (item.status !== 'COMPLETED' || !item.filename) {
    return
  }

  const loadKey = getThumbnailLoadKey(item)
  if (thumbnailLoadedKeys.value[item.id] === loadKey || thumbnailLoadingKeys.value[item.id] === loadKey) {
    return
  }
  thumbnailLoadingKeys.value[item.id] = loadKey
  
  try {
    const platform = normalizePlatform(item.source)
    const isSubscription = !!item.subscription_id || (item.filename && item.filename.includes('subscriptions/'))
    
    let fullPath = item.filename.replace(/^\/+/, '').replace(/\/+$/, '')
    let subscriptionPath = fullPath
    let videoFilename = null
    
    // 检查是否是视频或音频文件（支持网易云等音频任务）
    if (fullPath.match(/\.(mp4|mkv|avi|mov|flv|webm|mp3|flac|m4a|wav|aac|ogg)$/i)) {
      const pathParts = fullPath.split('/')
      videoFilename = pathParts[pathParts.length - 1]
      subscriptionPath = pathParts.slice(0, -1).join('/')
    }
    
    const parts = subscriptionPath.split('/')
    let apiPlatform = platform
    let folderPath = ''
    
    if (isSubscription) {
      if (parts[0] === 'subscriptions' && parts.length >= 3) {
        apiPlatform = parts[1]
        const authorName = parts[2]
        const folderName = parts[3]
        folderPath = folderName ? `${authorName}/${folderName}` : authorName
      } else {
        folderPath = subscriptionPath
      }
    } else {
      if (parts.length >= 2 && (parts[0] === apiPlatform || parts[0] === 'others' || parts[0] === 'netease')) {
        apiPlatform = parts[0]
        folderPath = parts.slice(1).join('/')
      } else {
        folderPath = subscriptionPath
      }
    }
    
    const apiParams = {
      platform: apiPlatform,
      folder_path: folderPath || '.',
      subscription: isSubscription
    }
    
    if (videoFilename) {
      apiParams.video_filename = videoFilename
    }
    
    const data = await tasksApi.getGalleryThumbnail(apiParams)
    
    if (data && data.success && data.thumbnail_path) {
      const encodedThumbPath = data.thumbnail_path.split('/').map(encodeURIComponent).join('/')
      const fullPath = encodedThumbPath.startsWith('downloads/') 
        ? `/${encodedThumbPath}` 
        : `/downloads/${encodedThumbPath}`
      const ts = item.updated_at ? new Date(item.updated_at).getTime() : Date.now()
      thumbnailCache.value[item.id] = `${fullPath}?t=${ts}`
      thumbnailLoadedKeys.value[item.id] = loadKey
    }
  } catch (error) {
    console.error('[Activity Thumbnail] Error loading local thumbnail:', error)
  } finally {
    if (thumbnailLoadingKeys.value[item.id] === loadKey) {
      delete thumbnailLoadingKeys.value[item.id]
    }
  }
}

function normalizePlatform(source) {
  if (!source) return 'others'
  const platform = source.toLowerCase()
  if (platform.includes('douyin')) return 'douyin'
  if (platform.includes('bilibili')) return 'bilibili'
  if (platform.includes('youtube')) return 'youtube'
  if (platform.includes('migu')) return 'migu'
  if (platform.includes('tiktok')) return 'tiktok'
  if (platform.includes('instagram')) return 'instagram'
  if (platform.includes('xiaohongshu')) return 'xiaohongshu'
  if (platform.includes('netease')) return 'netease'
  if (platform.includes('kuaishou')) return 'kuaishou'
  return 'others'
}

// Supervisor 服务名称映射
function getServiceName(name) {
  const map = {
    'easy-vdl-unified-service': '主程序',
    'filebrowser': '文件管理',
    'fluxbox': '窗口管理',
    'nginx': 'Web服务',
    'postgresql': '数据库',
    'websockify': 'VNC代理',
    'x11vnc': '远程桌面',
    'xvfb': '虚拟显卡'
  }
  return map[name] || name.replace('easy-vdl-', '')
}

function getThumbnail(item) {
  return thumbnailCache.value[item.id] || null
}


// --- 渲染状态管理 ---
const lastUpdateTs = ref(Date.now())      // 上次收到数据的时间
const virtualTime = ref(Date.now())      // 虚拟动画时间轴
const updateInterval = 1000              // 预期数据间隔 (ms)
let animationFrameId = null

// CPU 用到的变量
const cpuHistory = ref(new Array(60).fill(0))
const cpuChartPoints = ref('')
const cpuMaxPercent = ref(100)
const cpuTargetValue = ref(0) // 当前正在流入的目标值

// GPU 用到的变量（与 CPU 同步逻辑）
const gpuHistory = ref(new Array(60).fill(0))
const gpuChartPoints = ref('')
const gpuMaxPercent = ref(100)
const gpuTargetValue = ref(0)

// 网络用到的变量
const networkHistory = ref({
  rx: new Array(60).fill(0),
  tx: new Array(60).fill(0)
})
const networkChartPoints = ref({ download: '', upload: '' })
const networkMaxSpeed = ref(100 * 1024)
const netRxTarget = ref(0)
const netTxTarget = ref(0)
// 网络数据平滑处理（指数平滑）
const netRxSmoothed = ref(0)  // 平滑后的下载速度
const netTxSmoothed = ref(0)  // 平滑后的上传速度
const networkSmoothingFactor = 0.3  // 平滑系数（0-1，越小越平滑）

// 网格动画相关
const gridScrollX = ref(0)
const gridTickCount = ref(0)
const chartGap = 200 / 59 // chartWidth / (maxPoints - 1)


/**
 * 核心指标接收器：不再直接计算，只负责“喂”数据
 */
function onMetricsReceived(payload) {
  const now = Date.now()
  
  // 1. CPU 数据入队
  cpuHistory.value.push(cpuTargetValue.value)
  if (cpuHistory.value.length > 60) cpuHistory.value.shift()
  cpuTargetValue.value = payload.cpu_percent || 0

  // 1.1 GPU 数据入队（主卡利用率）
  gpuHistory.value.push(gpuTargetValue.value)
  if (gpuHistory.value.length > 60) gpuHistory.value.shift()
  const primaryGpu = pickPrimaryGpu(payload.gpu_stats || {})
  const nextGpuTarget = Number(primaryGpu?.util_percent ?? 0)
  gpuTargetValue.value = Number.isFinite(nextGpuTarget) ? Math.max(0, Math.min(100, nextGpuTarget)) : 0
  
  // 2. 网络数据入队（使用平滑处理）
  const newRx = payload.net?.rx_bps || 0
  const newTx = payload.net?.tx_bps || 0
  
  // 关键：先将当前的平滑值固定下来入队，然后再更新平滑值
  // 这样可以确保历史数据点一旦入队就不会再改变
  const currentSmoothedRx = netRxSmoothed.value
  const currentSmoothedTx = netTxSmoothed.value
  
  // 将当前的平滑值入队（固定历史数据点）
  networkHistory.value.rx.push(currentSmoothedRx)
  networkHistory.value.tx.push(currentSmoothedTx)
  if (networkHistory.value.rx.length > 60) {
    networkHistory.value.rx.shift()
    networkHistory.value.tx.shift()
  }
  
  // 然后更新平滑值（用于下一次入队和当前插值）
  // 使用指数平滑算法（EMA）平滑网络数据
  // 公式：smoothed = old * (1 - factor) + new * factor
  if (netRxSmoothed.value === 0 && newRx > 0) {
    // 初始化：如果平滑值为0且新值大于0，直接使用新值
    netRxSmoothed.value = newRx
  } else {
    netRxSmoothed.value = netRxSmoothed.value * (1 - networkSmoothingFactor) + newRx * networkSmoothingFactor
  }
  
  if (netTxSmoothed.value === 0 && newTx > 0) {
    netTxSmoothed.value = newTx
  } else {
    netTxSmoothed.value = netTxSmoothed.value * (1 - networkSmoothingFactor) + newTx * networkSmoothingFactor
  }
  
  // 保存原始目标值用于显示当前速度
  netRxTarget.value = newRx
  netTxTarget.value = newTx
  
  // 增加 tick 计数用于网格同步
  gridTickCount.value++

  // 3. 关键：平滑处理动画时间轴
  // 如果当前落后太多则追赶，如果太快则微调步伐
  const drift = now - lastUpdateTs.value
  lastUpdateTs.value = now
  
  // 初始启动
  if (virtualTime.value === 0) virtualTime.value = now - updateInterval
}

/**
 * 每一帧的丝滑渲染循环
 */
function animateCharts() {
  const now = Date.now()
  
  // 计算虚拟进度：我们让动画比真实数据慢 1 个周期，这样就有足够的“存货”来应对延迟
  // 计算基于上一次数据到达后的流逝比例
  let progress = (now - lastUpdateTs.value) / updateInterval
  if (progress > 1.2) progress = 1.2 // 极致兜底，防止过大跳变
  
  const chartWidth = 200
  const chartHeight = 60
  const maxPoints = 60
  const gap = chartWidth / (maxPoints - 1)

  // --- 1. 动态自适应坐标轴 (渐进式缩放) ---
  // CPU 锁定 100%
  cpuMaxPercent.value = 100

  const rawMaxNet = Math.max(...networkHistory.value.rx, ...networkHistory.value.tx, netRxTarget.value, 100 * 1024)
  // 只增不减 (Peak Hold) Logic: 记录网页加载后的最大值
  if (rawMaxNet > networkMaxSpeed.value) {
    networkMaxSpeed.value = rawMaxNet
  }
  
  // 计算网格滚动位置
  // 这里的计算是为了让网格线跟随数据点一起向左移动
  // 每一个数据周期的移动距离是 gap
  // 总位移 = (已经过的周期数 + 当前周期进度) * gap
  const totalShift = (gridTickCount.value + progress) * gap
  
  // 我们设定网格每隔 5 个数据点有一条竖线 (约17px)
  const gridStepPoints = 5 
  const patternWidth = gap * gridStepPoints
  
  // 取模得到当前 pattern 的偏移量 (向左移动，所以是负数)
  gridScrollX.value = -(totalShift % patternWidth)

  // --- 2. CPU 曲线渲染 (使用 SVG Path 实现平滑曲线) ---
  if (cpuHistory.value.length > 0) {
    const lastPoint = cpuHistory.value[cpuHistory.value.length - 1]
    const currentVal = lastPoint + (cpuTargetValue.value - lastPoint) * Math.min(progress, 1)
    
    const points = []
    cpuHistory.value.forEach((val, i) => {
      const x = chartWidth - ((cpuHistory.value.length - i) * gap) - (progress * gap) + gap
      const y = chartHeight - (val / cpuMaxPercent.value) * (chartHeight - 4) - 2
      points.push({ x, y })
    })
    // 补齐正在“涌入”的最右侧点
    points.push({
      x: chartWidth,
      y: chartHeight - (currentVal / cpuMaxPercent.value) * (chartHeight - 4) - 2
    })
    
    cpuChartPoints.value = generateSmoothPath(points)
  }

  // --- 2.1 GPU 曲线渲染（主卡利用率）---
  if (gpuHistory.value.length > 0) {
    const lastPoint = gpuHistory.value[gpuHistory.value.length - 1]
    const currentVal = lastPoint + (gpuTargetValue.value - lastPoint) * Math.min(progress, 1)

    const points = []
    gpuHistory.value.forEach((val, i) => {
      const x = chartWidth - ((gpuHistory.value.length - i) * gap) - (progress * gap) + gap
      const y = chartHeight - (val / gpuMaxPercent.value) * (chartHeight - 4) - 2
      points.push({ x, y })
    })
    points.push({
      x: chartWidth,
      y: chartHeight - (currentVal / gpuMaxPercent.value) * (chartHeight - 4) - 2
    })

    gpuChartPoints.value = generateSmoothPath(points)
  }

  // --- 3. 网络曲线渲染（使用平滑后的目标值）---
  const renderNet = (history, smoothedTarget, key) => {
    if (history.length === 0) return
    
    const last = history[history.length - 1] || 0
    const easedProgress = Math.min(progress, 1) 
    const current = last + (smoothedTarget - last) * easedProgress
    
    const points = []
    history.forEach((val, i) => {
      const x = chartWidth - ((history.length - i) * gap) - (progress * gap) + gap
      const y = chartHeight - (val / networkMaxSpeed.value) * (chartHeight - 4) - 2
      points.push({ x, y })
    })
    points.push({
      x: chartWidth,
      y: chartHeight - (current / networkMaxSpeed.value) * (chartHeight - 4) - 2
    })
    
    networkChartPoints.value[key] = generateSmoothPath(points)
  }
  
  // 使用平滑后的值进行渲染
  renderNet(networkHistory.value.rx, netRxSmoothed.value, 'download')
  renderNet(networkHistory.value.tx, netTxSmoothed.value, 'upload')

  animationFrameId = requestAnimationFrame(animateCharts)
}



// 订阅系统监控
function normalizePlatformKey(platform) {
  if (platform.startsWith('youtube')) return 'youtube'
  if (platform.startsWith('douyin')) return 'douyin'
  if (platform.startsWith('bilibili')) return 'bilibili'
  if (platform.startsWith('kuaishou')) return 'kuaishou'
  if (['xiaohongshu', 'redbook', 'xhs'].includes(platform)) return 'xiaohongshu'
  return platform
}

function mergePlatformDistribution(entries, total) {
  const platformNames = {
    'youtube': 'YouTube', 'douyin': '抖音', 'tiktok': 'TikTok',
    'instagram': 'Instagram', 'netease': '网易云', 'bilibili': 'Bilibili',
    'xiaohongshu': '小红书', 'redbook': '小红书', 'xhs': '小红书', 'x': 'X',
    'migu': '咪咕', 'kuaishou': '快手'
  }
  const merged = {}
  entries.forEach(([platform, count]) => {
    const key = normalizePlatformKey(platform)
    if (!merged[key]) {
      merged[key] = { name: platformNames[key] || key, count: 0, percent: 0 }
    }
    merged[key].count += count
  })
  Object.values(merged).forEach(d => { d.percent = Math.round((d.count / total) * 100) })
  return Object.entries(merged)
    .sort((a, b) => b[1].count - a[1].count)
    .reduce((obj, [key, value]) => { obj[key] = value; return obj }, {})
}

const platformDistribution = computed(() => {
  const stats = subscriptionStats.value
  if (stats && stats.by_platform) {
    const entries = Object.entries(stats.by_platform)
    return mergePlatformDistribution(entries, stats.total || 1)
  }
  // 降级：从 store 中获取全量数据计算
  const grouped = subscriptionsStore.groupedByPlatform
  const total = subscriptionsStore.stats.total || 1
  const entries = Object.entries(grouped).map(([platform, subs]) => [platform, subs.length])
  return mergePlatformDistribution(entries, total)
})

const subscriptionStatusStats = computed(() => {
  const stats = subscriptionStats.value
  if (stats) {
    const total = stats.total || 0
    const active = stats.active_count || 0
    const error = stats.by_status?.error || 0
    const invalid = stats.by_status?.invalid || 0
    const paused = Math.max(0, total - active - error - invalid)
    return { active, paused, error, invalid }
  }
  // 降级：从 store 中获取全量数据计算
  const subs = subscriptionsStore.subscriptions
  let active = 0, paused = 0, error = 0, invalid = 0
  subs.forEach(sub => {
    if (sub.status === 'invalid') invalid++
    else if (sub.status === 'error') error++
    else if (sub.status === 'active' && (sub.check_interval > 0 || sub.update_interval > 0) && (sub.auto_download === true || sub.auto_download === 'true')) active++
    else paused++
  })
  return { active, paused, error, invalid }
})

const autoDownloadEnabledCount = computed(() => {
  const stats = subscriptionStats.value
  if (stats) return stats.auto_download_enabled || 0
  return subscriptionsStore.subscriptions.filter(
    sub => sub.auto_download === true || sub.auto_download === 'true'
  ).length
})

// 饼图分段计算
const pieChartSegments = computed(() => {
  const platforms = platformDistribution.value
  const total = subscriptionStats.value?.total || subscriptionsStore.stats.total || 1
  const circumference = 2 * Math.PI * 40 // r=40
  
  let currentOffset = 0
  const segments = []
  
  Object.entries(platforms).forEach(([platform, data]) => {
    const percent = data.count / total
    const dashArray = circumference * percent
    
    // Map to supported gradients (与 PieChart 组件的 colorId 对应)
    const knownPlatforms = ['youtube', 'bilibili', 'douyin', 'tiktok', 'instagram', 'xiaohongshu', 'redbook', 'xhs', 'netease', 'x']
    let colorId = knownPlatforms.includes(platform) ? platform : 'other'
    // 统一将小红书相关平台映射到 redbook 以匹配颜色配置
    if (platform === 'xiaohongshu' || platform === 'redbook' || platform === 'xhs') {
      colorId = 'redbook'
    }
    
    segments.push({
      platform,
      colorId, // 添加 colorId 字段，用于 PieChart 组件
      name: data.name,
      count: data.count,
      percent: Math.round(percent * 100),
      dashArray,
      dashOffset: -currentOffset
    })
    
    currentOffset += dashArray
  })
  
  return segments
})

function goToSubscriptionsWithFilter(platform = '', status = '') {
  const query = {}
  if (platform) {
    query.platform = platform
  }
  if (status) {
    query.status = status
  }
  
  // 跳转到订阅管理页面，带上参数
  router.push({ path: '/subscriptions', query })
}

// Supervisor 状态
const supervisorServices = ref([])
const CORE_SERVICE_NAMES = ['easy-vdl-unified-service', 'nginx', 'postgresql']

const filteredSupervisorServices = computed(() => {
  if (!supervisorServices.value) return []
  return supervisorServices.value.filter(svc => CORE_SERVICE_NAMES.includes(svc.name))
})

const hasServiceError = computed(() => {
  return filteredSupervisorServices.value.some(svc => 
    svc.state !== 'RUNNING' && svc.state !== 'STARTING'
  )
})

// Supervisor 状态 (已移至 WebSocket 推送)
// async function fetchSupervisorStatus() { ... }

// 网络连通性检测
const networkStatus = ref([
  { name: 'youtube', label: 'YouTube', icon: '🌍', status: 'checking', latency_ms: 0 },
  { name: 'bilibili', label: 'Bilibili', icon: '🇨🇳', status: 'checking', latency_ms: 0 }
])

async function checkNetworkConnectivity() {
  try {
    const res = await coreApi.checkNetwork()
    if (res.status === 'success' && res.data) {
      networkStatus.value = [
        { 
          name: 'youtube', 
          label: 'YouTube', 
          icon: '🌍', 
          ...res.data.youtube 
        },
        { 
          name: 'bilibili', 
          label: 'Bilibili', 
          icon: '🇨🇳', 
          ...res.data.bilibili 
        }
      ]
    }
  } catch (err) {
    console.error('Network check failed:', err)
    // 标记为失败状态
    networkStatus.value.forEach(site => {
      site.status = 'failed'
      site.latency_ms = 0
    })
  }
}

function getNetworkClass(site) {
  if (site.status === 'ok') {
    if (site.latency_ms < 200) return 'network-good'
    if (site.latency_ms < 1000) return 'network-slow'
    return 'network-very-slow'
  }
  if (site.status === 'checking') return 'network-checking'
  return 'network-failed'
}

function getNetworkStatusText(status) {
  const map = {
    'checking': '检测中',
    'timeout': '超时',
    'failed': '失败',
    'error': '错误'
  }
  return map[status] || '未知'
}

function getNetworkTooltip(site) {
  if (site.status === 'ok') {
    return `${site.label} 连接正常 (${site.latency_ms}ms)`
  }
  if (site.message) {
    return `${site.label}: ${site.message}`
  }
  return `${site.label}: ${getNetworkStatusText(site.status)}`
}

onMounted(() => {
  // 0. 获取系统服务状态 (WS推送)
  // fetchSupervisorStatus()
  
  // 0.1 网络连通性检测 (已移至 WebSocket metrics 频道推送，无需初始 HTTP 调用)
  // checkNetworkConnectivity() // 已移除：改为通过 WebSocket metrics 推送
  // const networkInterval = setInterval(checkNetworkConnectivity, 30000) // 已移除

  // 1. 获取基础数据
  // 注意：以下数据已改为 WebSocket 推送，无需初始 HTTP 调用：
  // - 存储使用情况 (storage) - 通过 metrics 频道推送
  // - 已下载总数/失败总数 (downloads.completed/failed) - 通过 metrics 频道推送
  // - 直播统计 (live_stats) - 通过 metrics 频道推送
  // - 授权信息 (license) - 通过 metrics 频道推送（Sidebar 组件有初始 HTTP 调用作为兜底）
  // - 网络连通性 (network) - 通过 metrics 频道推送（30秒缓存）
  // - 最近活动 (recent_activity) - 通过 metrics 频道推送（10秒缓存）
  // - 公告状态和版本信息 (announcement) - 通过 metrics 频道推送（60秒缓存）
  systemStore.fetchCoreVersion() // 保持 HTTP：静态数据，变化频率极低
  systemStore.fetchBuildVersion() // 保持 HTTP：静态数据，变化频率极低
  // 改用轻量统计接口替代全量订阅列表，减少首屏数据传输量
  fetchSubscriptionStats()
  fetchLivePlatformStats() // 获取直播平台分布数据（用于显示饼图和开启录播数量）
  // 公告列表不在页面加载时主动获取，参考旧版本逻辑：
  // - 只通过 checkAnnouncementState() 检查状态
  // - 如果没有未读公告，会通过 fetchAnnouncements() 获取（用于检查版本更新）
  // - 用户点击查看时再获取完整列表
  // fetchRecentActivity() // 已移除：改为通过 WebSocket metrics 推送

  // 2. 连接 WebSocket (metrics & downloads 频道)
  wsService.connect('metrics')
  wsService.connect('downloads')
  
  // 3. 注册指标接收器
  const unregisterMetrics = wsService.onMessage((id, data) => {
    if (id === 'metrics' && data.type === 'metrics') {
      const payload = data.payload
      
      // 注意：全局属性（存储、授权、下载数、公告）已由 App.vue 层的全局监听器处理
      // 此处再次调用以确保 Dashboard 页面内部逻辑与 Store 状态同步（兜底）
      systemStore.handleGlobalMetrics(payload)
      
      // 以下为仪表盘特有的 UI 响应逻辑
      if (payload.supervisor) {
        supervisorServices.value = payload.supervisor
      }
      if (payload.live_stats) {
        // 智能合并直播统计数据
        if (payload.live_stats.total_size > 0) {
          liveStats.value = payload.live_stats
        } else if (liveStats.value.total_size > 0) {
          const { total_size, ...others } = payload.live_stats
          liveStats.value = { ...liveStats.value, ...others }
        } else {
          liveStats.value = payload.live_stats
        }
      }
      
      // 更新下载总量统计
      if (payload.downloads) {
        if (payload.downloads.completed !== undefined) totalCompleted.value = payload.downloads.completed
        if (payload.downloads.failed !== undefined) totalFailed.value = payload.downloads.failed
      }
      
      // 更新网络节点连通性 (带30s缓存)
      if (payload.network) {
        if (payload.network.youtube) {
          const youtubeIndex = networkStatus.value.findIndex(s => s.name === 'youtube')
          if (youtubeIndex >= 0) networkStatus.value[youtubeIndex] = { name: 'youtube', label: 'YouTube', icon: '🌍', ...payload.network.youtube }
        }
        if (payload.network.bilibili) {
          const bilibiliIndex = networkStatus.value.findIndex(s => s.name === 'bilibili')
          if (bilibiliIndex >= 0) networkStatus.value[bilibiliIndex] = { name: 'bilibili', label: 'Bilibili', icon: '🇨🇳', ...payload.network.bilibili }
        }
      }
      
      // 更新最近活动列表 (带10s缓存)
      if (payload.recent_activity && Array.isArray(payload.recent_activity)) {
        recentActivity.value = payload.recent_activity.map(task => ({
          id: task.id,
          type: task.source,
          source: task.source,
          filename: task.filename || task.url,
          url: task.url,
          original_url: task.original_url,
          status: task.status,
          subscription_id: task.subscription_id,
          action: task.status === 'COMPLETED' ? '下载完成' : (task.status === 'ERROR' ? '下载失败' : '正在下载'),
          user: task.author_info?.nickname,
          time: formatTime(task.updated_at),
          updated_at: task.updated_at
        }))
        pruneThumbnailCache(recentActivity.value)
        recentActivity.value.forEach(item => loadActivityThumbnail(item))
      }
      
      // 更新图表目标值及平滑动画
      onMetricsReceived(payload)
    }
  })


  // 3.1 注册下载任务接收器
  const unregisterDownloads = wsService.onMessage((id, data) => {
    if (id === 'downloads' && data.type === 'progress_update') {
      // 当有下载状态变化时，最近活动会通过 metrics 频道自动更新（10秒缓存）
      // 如果需要立即刷新，可以在这里触发一次 HTTP 请求（但通常不需要）
      // fetchRecentActivity() // 可选：立即刷新（会触发 HTTP 请求）
    }
  })

  // 4. 启动图表动画循环
  animateCharts()

  // 组件卸载时清理
  onUnmounted(() => {
    if (animationFrameId) cancelAnimationFrame(animationFrameId)
    unregisterMetrics()
    unregisterDownloads()
    wsService.close('metrics')
    wsService.close('downloads')
    // networkInterval 已移除（网络检测改为 WebSocket 推送）
  })
})

async function fetchRecentActivity() {
  try {
    const data = await tasksApi.getTasks({ limit: 6 })
    if (data && data.tasks) {
      recentActivity.value = data.tasks.map(task => ({
        id: task.id,
        type: task.source,
        source: task.source,
        filename: task.filename || task.url,
        url: task.url,
        original_url: task.original_url,
        status: task.status,
        subscription_id: task.subscription_id,
        action: task.status === 'COMPLETED' ? '下载完成' : (task.status === 'ERROR' ? '下载失败' : '正在下载'),
        user: task.author_info?.nickname,
        time: formatTime(task.updated_at),
        updated_at: task.updated_at
      }))
      
      // 异步加载缩略图
      recentActivity.value.forEach(item => {
        loadActivityThumbnail(item)
      })
    }
  } catch (err) {
    console.error('Failed to fetch recent activity:', err)
  }
}

function getSystemFreePercent() {
  const total = totalStorageBytes.value
  const free = freeStorageBytes.value
  if (total <= 0) return 0
  return (free / total) * 100
}

function getSystemStorageClass() {
  const free = getSystemFreePercent()
  if (free <= 10) return 'critical'
  if (free <= 25) return 'warning'
  if (free <= 40) return 'caution'
  return 'normal'
}

// 生成平滑的贝塞尔曲线路径 (Catmull-Rom spline)
function generateSmoothPath(points) {
  if (points.length === 0) return ''
  if (points.length === 1) return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`
  
  let d = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`
  
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(0, i - 1)]
    const p1 = points[i]
    const p2 = points[i + 1]
    const p3 = points[Math.min(points.length - 1, i + 2)]
    
    // CP1 = P1 + (P2 - P0) / 6
    const cp1x = p1.x + (p2.x - p0.x) / 6
    const cp1y = p1.y + (p2.y - p0.y) / 6
    
    // CP2 = P2 - (P3 - P1) / 6
    const cp2x = p2.x - (p3.x - p1.x) / 6
    const cp2y = p2.y - (p3.y - p1.y) / 6
    
    d += ` C ${cp1x.toFixed(2)} ${cp1y.toFixed(2)}, ${cp2x.toFixed(2)} ${cp2y.toFixed(2)}, ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`
  }
  return d
}

watch(storageUnitMode, (mode) => {
  localStorage.setItem(STORAGE_UNIT_MODE_KEY, mode)
})


</script>

<style scoped>
.dashboard {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: var(--spacing-lg);
  align-items: stretch;
  overflow-x: hidden; /* 防止伪元素或动画导致的微小溢出 */
}

/* Left Column */
.dashboard-left {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  min-width: 0; /* 允许在 grid 中缩放 */
  overflow-x: hidden;
  flex: 1;
}

/* Right Column (Monitoring) */
.dashboard-right {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  order: -1;
  overflow-x: hidden;
}

/* Stats Row with Announcements (Main Flex Container) */
.stats-row-with-announcements {
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: stretch;
  gap: 16px;
  width: 100%;
}

.stats-left-group {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  min-width: 0;
  margin-bottom: 12px;
}

@media (max-width: 1550px) {
  .stats-left-group {
    grid-template-columns: 1fr;
  }
}



.stat-card {
  padding: var(--spacing-md);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

/* 公共卡片样式 - 自适应宽度 */
.announcements-card.compact {
  flex: 1.2;
  min-width: 0;
}

.storage-card {
  width: auto !important;
  max-width: none !important;
}

.stats-left-group .gpu-monitor-card {
  width: auto !important;
}

.stats-left-group .storage-card.full-width {
  grid-column: 1 / -1;
}

.license-card.compact-dashboard {
  flex: 1;
  min-width: 0;
  cursor: pointer; /* 明确手型指针 */
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

/* 骨架屏样式 */
.license-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.skeleton-icon {
  width: 40px;
  height: 40px;
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

.skeleton-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skeleton-line-title {
  width: 80px;
  height: 20px;
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

.skeleton-line-sub {
  width: 100%;
  height: 6px;
  background: var(--color-bg-tertiary);
  border-radius: 3px;
  animation: skeleton-pulse 1.5s infinite ease-in-out;
}

@keyframes skeleton-pulse {
  0% { opacity: 0.6; }
  50% { opacity: 0.3; }
  100% { opacity: 0.6; }
}

.combined-stats-card,
.live-monitor-card {
  height: auto !important;
  min-height: auto !important;
  padding: 22px !important;
  margin-bottom: var(--spacing-md);
  display: flex;
  flex-direction: column;
  justify-content: center;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
}

.combined-stats-card:hover,
.live-monitor-card:hover {
  /* 移除所有悬停效果 */
}

.combined-stats-card:active,
.live-monitor-card:active {
  /* 移除所有激活效果 */
}

.combined-stats-card {
  padding: 12px !important;
}

/* 保持高度统一 */
.announcements-card.compact,
.license-card.compact-dashboard,
.stat-card {
  min-height: 110px;
  height: 110px;
}

[data-theme="dark"] .license-card.compact-dashboard {
  background: linear-gradient(to bottom right, var(--color-bg-card), rgba(230, 126, 34, 0.05));
  border-color: rgba(230, 126, 34, 0.2);
}

.license-card.compact-dashboard:hover:not(.is-lifetime) {
  /* transform: translateY(-4px) scale(1.02);  已禁用：防止被右侧卡片遮挡 */
  box-shadow: 0 4px 12px rgba(230, 126, 34, 0.15); /* 阴影稍微收敛一点，因为没有上浮了 */
  border-color: rgba(230, 126, 34, 0.6);
  background: var(--color-bg-hover);
}

.license-card.compact-dashboard:hover:not(.is-lifetime) .license-crown svg {
  transform: scale(1.2); /* 仅保留缩放 */
}

.license-card .license-crown svg {
  transition: transform 0.3s ease;
}

.license-card .license-header-compact {
  display: flex;
  align-items: center;
  gap: 12px;
}

.license-card .license-crown {
  color: #e67e22;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}

/* 未激活状态样式 */
.license-card.inactive-license .license-crown {
  color: #bdc3c7; /* 灰色皇冠 */
  opacity: 0.8;
}

.license-card.inactive-license .license-label {
  color: var(--color-text-secondary);
}

.license-card.inactive-license .usage-fill {
  background: linear-gradient(90deg, #bdc3c7, #95a5a6); /* 灰色进度条 */
  opacity: 0.5;
}

.license-card.inactive-license .license-status-tag {
  color: #95a5a6;
}

.license-card .license-crown svg {
  filter: drop-shadow(0 2px 4px rgba(230, 126, 34, 0.25));
}

.license-card .license-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.license-card .license-label {
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1.2;
}

.license-card .license-status-tag {
  font-size: 11px;
  font-weight: 600;
  color: #27ae60;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.license-card .license-status-tag.active {
  color: #27ae60;
}

.license-card .license-status-tag.inactive {
  color: #95a5a6;
}

.license-card .license-usage {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.license-card .usage-text {
  font-size: 11px;
  color: var(--color-text-tertiary);
}

.license-card .usage-info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.license-card .license-feedback-btn {
  font-size: 11px;
  color: #fff;
  cursor: pointer;
  padding: 4px 10px;
  border-radius: 20px;
  background: linear-gradient(135deg, #e67e22, #f39c12);
  font-weight: 600;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 2px 6px rgba(230, 126, 34, 0.3);
  display: flex;
  align-items: center;
  gap: 4px;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.license-card:not(.is-lifetime) .license-feedback-btn:hover {
  transform: translateY(-2px) scale(1.05);
  box-shadow: 0 4px 12px rgba(230, 126, 34, 0.5);
  filter: brightness(1.1);
}

.license-card .license-feedback-btn:active {
  transform: scale(0.95);
}

.license-card .usage-bar {
  height: 6px;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 3px;
  overflow: hidden;
  width: 100%;
}

[data-theme="dark"] .license-card .usage-bar {
  background: rgba(255, 255, 255, 0.1);
}

.license-card .usage-fill {
  height: 100%;
  background: linear-gradient(90deg, #e74c3c, #f39c12);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.stat-card.gradient-blue {
  border-color: rgba(59, 130, 246, 0.3);
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), transparent);
}

.stat-card.gradient-purple {
  border-color: rgba(99, 102, 241, 0.3);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), transparent);
}

.stat-card.gradient-dark {
  border-color: var(--color-border);
}

/* 存储空间卡片动画 */
.storage-card {
  position: relative;
  overflow: hidden;
  transition: all 0.3s ease;
}

.storage-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
  animation: storage-shine 3s infinite;
}

@keyframes storage-shine {
  0% {
    left: -100%;
  }
  50%, 100% {
    left: 100%;
  }
}

.storage-card.storage-normal {
  border-color: rgba(34, 197, 94, 0.3);
}

.storage-card.storage-caution {
  border-color: rgba(234, 179, 8, 0.3);
  animation: storage-pulse 2s ease-in-out infinite;
}

.storage-card.storage-warning {
  border-color: rgba(249, 115, 22, 0.3);
  animation: storage-pulse 1.5s ease-in-out infinite;
}

.storage-card.storage-critical {
  border-color: rgba(239, 68, 68, 0.4);
  animation: storage-pulse 1s ease-in-out infinite;
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.3);
}

@keyframes storage-pulse {
  0%, 100% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);
  }
  50% {
    transform: scale(1.02);
    box-shadow: 0 0 8px rgba(239, 68, 68, 0.3);
  }
}

/* 存储进度条包装器 */
.storage-progress-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

/* 存储进度条容器 */
.storage-progress-container {
  flex: 1;
  height: 6px;
  background: var(--color-bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
  position: relative;
}

/* 存储进度条 */
.storage-progress-bar {
  height: 100%;
  border-radius: 3px;
  position: relative;
  overflow: hidden;
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  background: linear-gradient(90deg, #22c55e, #16a34a);
}

.storage-card.storage-caution .storage-progress-bar {
  background: linear-gradient(90deg, #eab308, #ca8a04);
}

.storage-card.storage-warning .storage-progress-bar {
  background: linear-gradient(90deg, #f97316, #ea580c);
}

.storage-card.storage-critical .storage-progress-bar {
  background: linear-gradient(90deg, #ef4444, #dc2626);
}

/* 进度条光泽动画 */
.storage-progress-shine {
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.4), transparent);
  animation: progress-shine 2s infinite;
}

@keyframes progress-shine {
  0% {
    left: -100%;
  }
  100% {
    left: 100%;
  }
}

/* 存储百分比显示 */
.storage-percentage {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 0.3s ease;
  min-width: 35px;
  text-align: right;
}

.storage-card.storage-normal .storage-percentage {
  color: #22c55e;
}

.storage-card.storage-caution .storage-percentage {
  color: #eab308;
}

.storage-card.storage-warning .storage-percentage {
  color: #f97316;
}

.storage-card.storage-critical .storage-percentage {
  color: #ef4444;
  font-weight: 700;
}

.stat-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

.stat-labels-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-xs);
}

.stat-value {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
}

.stat-value-group {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-xs);
}

.stat-suffix {
  font-size: var(--font-size-md);
  color: var(--color-text-muted);
}

.stat-sub-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin-top: 4px;
  display: block;
}

/* 并列显示已下载和正在下载 */
.stat-values-row.compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  gap: 4px;
  padding: 8px 0;
}

.stat-value-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  text-align: center;
  min-width: 0;
  cursor: pointer;
  transition: all 0.2s ease;
  border-radius: var(--radius-md);
  padding: 4px 0;
}

.stat-value-item:hover {
  background: var(--color-bg-hover);
  transform: scale(1.05);
}

.stat-value-item .stat-value {
  font-size: 22px;
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1.1;
  margin: 2px 0;
}

.stat-value-label {
  font-size: 10px;
  color: var(--color-text-muted);
  font-weight: 500;
}

.stat-label-inline {
  font-size: 11px;
  color: var(--color-text-tertiary);
  font-weight: 600;
}

.stat-divider-vertical {
  width: 1px;
  height: 40px;
  background: var(--color-border);
  margin: 0 4px;
  opacity: 0.6;
}

/* Quick Actions Card */
.action-buttons {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-md);
}

.action-btn {
  padding: var(--spacing-md);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
}

.action-btn:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border-light);
  color: var(--color-text-primary);
  transform: translateY(-2px);
}

.action-btn.primary {
  background: #ffffff;
  color: #e67e22;
  border: 2px solid #e67e22;
}

/* Announcements Card */
.announcements-card {
  padding: var(--spacing-md);
  position: relative;
  transition: all 0.3s ease;
}

/* 紧凑版公告中心（与统计卡片同一行） */
.announcements-card.compact {
  padding: var(--spacing-md);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: 100%;
}

.announcements-card.compact .card-title {
  font-size: var(--font-size-sm);
  margin-bottom: 0;
}

.announcements-card.compact .card-header-with-badge {
  margin-bottom: var(--spacing-sm);
  flex-shrink: 0;
}

/* 新版本特效 - 简化版 */
.announcements-card.has-update {
  border: 1px solid #FF4D4D;
  background: rgba(255, 77, 77, 0.03);
}

[data-theme="dark"] .announcements-card.has-update {
  background: rgba(255, 77, 77, 0.1);
}

.announcements-card.has-update .card-title {
  color: #FF4D4D;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.update-icon {
  color: #FF4D4D;
}

.update-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  background: #FF4D4D;
  color: white;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 600;
}

.card-header-with-badge {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-md);
  gap: var(--spacing-xs);
}

.unread-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  background: #e74c3c;
  color: white;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 600;
  animation: pulse-badge 2s infinite;
}

@keyframes pulse-badge {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(1.05); }
}

/* 公告状态显示（不显示具体内容，参考旧版本） */
.announcements-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  padding: var(--spacing-sm) 0;
}

.ann-status-content {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  flex: 1;
}

.ann-status-icon {
  color: var(--color-text-tertiary);
  opacity: 0.6;
}

.ann-status-text {
  flex: 1;
}

.ann-status-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: 2px;
}

.ann-status-desc {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin-top: 2px;
}

.btn-sm {
  padding: 6px 16px;
  font-size: var(--font-size-sm);
  white-space: nowrap;
}

/* 左侧统计卡片和公告卡片布局优化 */
.announcements-card.compact {
  min-height: 110px;
  max-height: 110px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
}

.card-header-with-badge {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  line-height: 1;
}

.announcements-status {
  flex: 1;
  display: flex;
  align-items: center;
}

.ann-status-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ann-status-icon {
  opacity: 0.8;
}

.ann-status-title {
  font-size: 14px !important;
  font-weight: 600;
  margin: 0 !important;
  display: flex;
  align-items: center;
}

.ann-status-title .text-xl {
  font-size: 24px !important; /* 显著增大“发现新版本” */
  font-weight: 800;
  letter-spacing: 0.5px;
}

.announcements-card.has-update .ann-status-title .text-xl {
  color: #ffffff;
  text-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.view-btn {
  position: static !important; /* 移除绝对定位 */
  padding: 3px 10px !important;
  font-size: 11px !important;
  height: 22px;
  line-height: 1;
}

.announcements-card.compact .ann-status-content {
  gap: var(--spacing-xs);
  width: 100%;
}

.announcements-card.compact .ann-status-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.announcements-card.compact .ann-status-title {
  font-size: var(--font-size-md); /* 从 lg 还原到 md，适中 */
  line-height: 1.2;
  margin-bottom: 2px;
  color: var(--color-text-primary);
  font-weight: 600;
}

.announcements-card.has-update .ann-status-title {
  color: #ffffff; 
  font-weight: 800;
  text-shadow: 0 1px 4px rgba(0,0,0,0.3);
  font-size: 1.05rem; /* 再次微调，略大于普通 md，但小于之前的 1.1rem */
}

.announcements-card.compact .ann-status-desc {
  font-size: var(--font-size-xs); /* 减小字号 */
  line-height: 1.2;
  margin-top: 2px;
  word-break: break-all;
  color: var(--color-text-tertiary);
}

.announcements-card.has-update .ann-status-desc {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(0, 0, 0, 0.4); 
  padding: 4px 10px; /* 减小内边距 */
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px; /* 减小行间距 */
  font-family: monospace;
  backdrop-filter: blur(2px);
  margin-top: 6px; /* 减小顶部边距 */
  max-width: fit-content;
}

.version-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px; /* 从 12px 进一步微调到 11px */
  white-space: nowrap;
}

.v-tag {
  font-size: 10px;
  font-weight: bold;
  opacity: 0.7;
  text-transform: uppercase;
  min-width: 32px;
}

.version-latest {
  color: #fff;
  font-weight: bold;
}

.announcements-card.compact .announcements-status {
  position: relative; /* 为按钮定位提供参考 */
}

.announcements-card.compact .view-btn {
  position: absolute;
  top: -30px; /* 调整位置以适应固定高度卡片 */
  right: 0;
  margin-top: 0;
  padding: 4px 12px;
  border-radius: var(--radius-full);
}

.announcements-card.has-update .view-btn {
  background: #ffffff;
  color: #e67e22;
  border: none;
  font-weight: bold;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.announcements-card.compact .btn-sm {
  padding: 4px 12px;
  font-size: var(--font-size-xs);
  margin-top: var(--spacing-xs);
  align-self: flex-end;
}

/* 公告详情模态框 */
.announcement-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--spacing-lg);
}

.announcement-modal {
  width: 100%;
  max-width: 600px;
  max-height: 80vh;
  background: var(--color-bg-card);
  border-radius: var(--radius-xl);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: modalScaleIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* 公告中心更新特效 */
.announcements-card.has-update {
  position: relative;
  border-color: transparent;
  background-clip: padding-box;
  z-index: 1;
  background: linear-gradient(135deg, #e67e22, #d35400) !important;
  display: flex;
  flex-direction: column;
}

.announcements-card.has-update .announcements-status {
  display: flex;
  align-items: center;
  justify-content: center; /* 居中显示大标题 */
  height: 100%;
}

.announcements-card.has-update .card-title,
.announcements-card.has-update .ann-status-icon {
  color: #ffffff !important;
}

.announcements-card.has-update::before {
  content: '';
  position: absolute;
  top: -1px;
  left: -1px;
  right: -1px;
  bottom: -1px;
  background: linear-gradient(
    45deg, 
    #e67e22, #f39c12, #e74c3c, #f39c12, #e67e22
  );
  background-size: 400% 400%;
  z-index: -1;
  border-radius: var(--radius-lg);
  animation: border-gradient 4s ease infinite;
}

.announcements-card.has-update .update-icon {
  color: #e74c3c;
  animation: icon-glitch 1.5s infinite;
}

.announcements-card.has-update .unread-badge {
  background: var(--color-error);
  box-shadow: 0 0-10px rgba(231, 76, 60, 0.5);
  animation: badge-pop 1s infinite alternate;
}

.announcements-card.has-update::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: var(--radius-lg);
  box-shadow: 0 0 15px rgba(230, 126, 34, 0.2);
  pointer-events: none;
  animation: card-pulse 2s infinite;
}

@keyframes border-gradient {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

@keyframes icon-glitch {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.2) rotate(5deg); opacity: 0.8; }
}

@keyframes badge-pop {
  from { transform: scale(1); }
  to { transform: scale(1.2); }
}

@keyframes card-pulse {
  0% { box-shadow: 0 0 0 0 rgba(230, 126, 34, 0.3); }
  70% { box-shadow: 0 0 0 10px rgba(230, 126, 34, 0); }
  100% { box-shadow: 0 0 0 0 rgba(230, 126, 34, 0); }
}

@keyframes modalScaleIn {
  from {
    opacity: 0;
    transform: scale(0.9);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.announcement-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-lg);
  border-bottom: 1px solid var(--color-border);
}

.modal-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin: 0;
}

.modal-close-btn {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  border: none;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.modal-close-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.announcement-modal-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-lg);
}

/* 版本更新提示 */
.version-alert {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-sm);
  padding: var(--spacing-md);
  background: rgba(231, 76, 60, 0.1);
  border: 1px solid rgba(231, 76, 60, 0.3);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-lg);
}

[data-theme="dark"] .version-alert {
  background: rgba(231, 76, 60, 0.15);
  border-color: rgba(231, 76, 60, 0.4);
}

.alert-icon {
  color: #e74c3c;
  flex-shrink: 0;
}

.alert-content {
  flex: 1;
}

.alert-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: #e74c3c;
  margin-bottom: 4px;
}

.alert-version {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

/* 公告详情卡片 */
.announcement-detail-card {
  background: white;
  border-radius: var(--radius-lg);
  padding: var(--spacing-lg);
  border: 1px solid var(--color-border);
}

[data-theme="dark"] .announcement-detail-card {
  background: var(--color-bg-secondary);
}

.ann-detail-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
}

.ann-detail-header .ann-back-btn {
  margin-left: auto;
}

.ann-detail-icon {
  color: #f39c12;
}

.ann-detail-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin: 0;
}

.ann-detail-time {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin-bottom: var(--spacing-md);
}

.ann-detail-body {
  margin-top: var(--spacing-md);
}

.ann-detail-content {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
}

.ann-detail-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-xs);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.ann-detail-link {
  color: var(--color-primary);
  text-decoration: none;
  word-break: break-all;
}

.ann-detail-link:hover {
  text-decoration: underline;
}

/* 公告列表（模态框中） */
.announcements-empty-modal {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-xl);
  color: var(--color-text-tertiary);
  gap: var(--spacing-sm);
}

.announcements-loading-modal {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-sm);
  min-height: 160px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.loading-icon {
  color: var(--color-primary);
  animation: announcement-loading-spin 1s linear infinite;
}

@keyframes announcement-loading-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.announcements-list-modal {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-lg);
  max-height: 300px;
  overflow-y: auto;
}

  .announcement-list-item {
    padding: var(--spacing-sm) var(--spacing-md);
    background: var(--color-bg-secondary);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: all 0.2s ease;
    -webkit-tap-highlight-color: transparent;
  }

.announcement-list-item:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-primary-light);
}

.announcement-list-item.selected {
  border-color: var(--color-primary);
  background: rgba(230, 126, 34, 0.05);
}

[data-theme="dark"] .announcement-list-item.selected {
  background: rgba(230, 126, 34, 0.15);
}

.announcement-list-item.sticky {
  border-left: 3px solid #f39c12;
}

.ann-list-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.ann-list-icon {
  flex-shrink: 0;
}

.ann-list-icon.severity-error {
  color: #e74c3c;
}

.ann-list-icon.severity-warn {
  color: #f39c12;
}

.ann-list-icon.severity-info {
  color: #3498db;
}

.ann-list-content {
  flex: 1;
  min-width: 0;
}

.ann-list-title-row {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-bottom: 4px;
}

.ann-list-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ann-li.usage-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-tertiary);
  margin-bottom: 2px;
}

.ann-sticky-tag {
  display: inline-block;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 600;
  background: rgba(243, 156, 18, 0.1);
  color: #f39c12;
  border-radius: 4px;
  margin-left: 4px;
}

[data-theme="dark"] .ann-sticky-tag {
  background: rgba(243, 156, 18, 0.2);
  color: #ffb84d;
}

/* Subscription Monitor Card */
.subscription-monitor-card {
  padding: 22px !important;
}

.monitor-layout {
  display: flex;
  gap: 20px;
  margin-top: 15px;
  align-items: flex-start;
}

.monitor-column {
  flex: 1;
  min-width: 0;
}

.section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-tertiary);
  margin-bottom: 12px;
  letter-spacing: 0.8px;
  opacity: 0.8;
}

/* 饼图样式优化 */
.pie-chart-container {
  position: relative;
  width: 130px;
  height: 130px;
  margin: 5px auto 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.08));
}

.pie-chart {
  width: 125px;
  height: 125px;
  transform: rotate(-90deg);
  overflow: visible;
}

.pie-chart circle {
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.165, 0.84, 0.44, 1);
  stroke-width: 16;
}

.pie-chart circle:hover {
  opacity: 1;
  stroke-width: 22;
}

.pie-center-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  pointer-events: none;
}

.pie-total {
  font-size: 26px;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1;
  letter-spacing: -1px;
}

.pie-label {
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-top: 4px;
}

.pie-hover-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 2px;
}

.pie-hover-data {
  font-size: 18px;
  font-weight: 800;
  color: var(--color-primary);
}

/* 图例美化 */
.pie-legend {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px 12px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
  background: transparent;
}

.legend-item:hover {
  background: var(--color-bg-hover);
  transform: scale(1.02);
}

.legend-color {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.legend-color.color-youtube { background: linear-gradient(135deg, #FF6B6B, #FF7F7F); }
.legend-color.color-bilibili { background: linear-gradient(135deg, #00A1D6, #0082B3); }
.legend-color.color-douyin { background: linear-gradient(135deg, #FF8FA3, #FF9FB5); }
.legend-color.color-tiktok { background: linear-gradient(135deg, #25F4EE, #FE2C55); }
.legend-color.color-huya { background: linear-gradient(135deg, #FFAA00, #FF8800); }
.legend-color.color-cc { background: linear-gradient(135deg, #0D91E9, #00B0FF); }
.legend-color.color-douyu { background: linear-gradient(135deg, #FF5500, #FF4400); }
.legend-color.color-migu { background: linear-gradient(135deg, #1d8ef7, #4aa7ff); }
.legend-color.color-redbook { background: linear-gradient(135deg, #ff2442, #ff2442); }
.legend-color.color-xhs { background: linear-gradient(135deg, #ff2442, #ff2442); }
.legend-color.color-kuaishou { background: linear-gradient(135deg, #FF7D00, #FF5000); }

.legend-name {
  font-size: 12px;
  color: var(--color-text-secondary);
  flex: 1;
}

.legend-value {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-primary);
  opacity: 0.8;
}

/* 运行状态卡片优化 */
.status-stats {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.status-stat-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: transparent;
  border: 1px solid var(--color-border-subtle, rgba(0,0,0,0.05));
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.3s ease;
}

.status-stat-item:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
}

.status-stat-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  flex-shrink: 0;
  font-size: 1.2rem;
}

.status-stat-item.active .status-stat-icon {
  background: rgba(82, 196, 26, 0.1);
  color: #52c41a;
}

.status-stat-item.paused .status-stat-icon {
  background: rgba(250, 173, 20, 0.1);
  color: #faad14;
}

.status-stat-item.error .status-stat-icon {
  background: rgba(255, 77, 79, 0.1);
  color: #ff4d4f;
}

.status-stat-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex: 1;
}

.status-stat-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary);
}

.status-stat-value {
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text-primary);
  letter-spacing: -0.5px;
}

.status-icon.subscription {
  background: linear-gradient(135deg, #a463b3, #8e44ad);
  color: white;
  box-shadow: 0 4px 10px rgba(155, 89, 182, 0.25);
}

/* 移动端优化：保持左右布局但防止重叠 */
@media (max-width: 600px) {
  .subscription-monitor-card {
    padding: 12px 10px !important;
  }
  
  .monitor-layout {
    gap: 8px; /* 减小间距 */
  }

  .monitor-column.pie-column {
    flex: 0 0 135px; /* 给左侧固定一个较小的宽度 */
  }

  .pie-chart-container {
    width: 100px;
    height: 100px;
    margin: 5px auto 10px;
  }

  .pie-chart {
    width: 95px;
    height: 95px;
  }
  
  .pie-total {
    font-size: 20px;
  }
  
  .pie-label {
    font-size: 9px;
  }

  .pie-legend {
    grid-template-columns: 1fr; /* 极窄屏幕下图例切回单列以省空间 */
    gap: 4px;
  }
  
  .legend-item {
    padding: 2px 4px;
    gap: 6px;
  }

  .legend-name, .legend-value {
    font-size: 10px;
  }

  /* 右侧状态项优化 */
  .status-stat-item {
    padding: 8px 8px;
    gap: 8px;
  }

  .status-stat-icon {
    width: 28px;
    height: 28px;
    font-size: 1rem;
  }

  .status-stat-label {
    font-size: 11px;
  }

  .status-stat-value {
    font-size: 16px;
  }
}

/* Live Monitor Card */
.live-stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 15px;
}

.live-stat-item {
  background: var(--color-bg-secondary);
  padding: 16px 10px;
  border-radius: var(--radius-lg);
  text-align: center;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 90px;
}

.live-stat-item:hover {
  transform: translateY(-3px);
  border-color: var(--color-primary-light);
  background: var(--color-bg-hover);
  box-shadow: var(--shadow-md);
}

.live-stat-item.recording {
  background: rgba(255, 77, 79, 0.03);
  border-color: rgba(255, 77, 79, 0.2);
}

.stat-mini-label {
  display: none;
}

.mobile-only {
  display: none;
}

.desktop-only {
  display: block;
}

.stat-divider-horizontal {
  height: 1px;
  background: var(--color-border);
  margin: 8px 0;
  opacity: 0.3;
}

.live-stat-item.recording .live-stat-val {
  color: #ff4d4f;
  text-shadow: 0 0 10px rgba(255, 77, 79, 0.1);
}

.live-stat-val {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-text-primary);
  margin-bottom: 4px;
  line-height: 1.2;
}

.live-stat-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-tertiary);
  letter-spacing: 0.5px;
}

/* Activity Card */
.activity-card {
  padding: var(--spacing-md);
  flex: 1;
}

.activity-list {
  display: flex;
  flex-direction: column;
}

.activity-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-sm) 0;
  border-bottom: 1px solid var(--color-border);
}

.activity-item:last-child {
  border-bottom: none;
}

.activity-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
}

.activity-icon.download {
  color: var(--color-primary);
  background: var(--color-primary-light);
}

.activity-icon.subscription {
  color: var(--color-success);
  background: var(--color-success-light);
}

/* 布局优化 */
.content-split-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
}

.split-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

/* 让底部3列的最后一个卡片自动对齐到底部 */
.split-col.side-col > *:last-child,
.split-col.activity-col > *:last-child {
  margin-top: auto;
}

@media (max-width: 1024px) {
  .content-split-row {
     grid-template-columns: 1fr;
  }
}

.dashboard-left {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0; /* 防止子元素溢出 */
}

.activity-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.activity-main-info {
  display: flex;
  gap: var(--spacing-sm);
  align-items: center;
}

.activity-thumb {
  width: 80px;
  height: 45px;
  object-fit: cover;
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
  border: 1px solid var(--color-border);
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.activity-text {
  display: flex;
  flex-direction: column;
}

.activity-filename {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  line-clamp: 1;
  overflow: hidden;
}

.activity-user {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.activity-time {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
}

/* System Status Section (Unraid Style - Vertical Stack) */
.system-status-section {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}


.status-card {
  padding: var(--spacing-md);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.status-header {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-md);
}

.status-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: #e67e22;
  background: rgba(230, 126, 34, 0.1);
}

.status-title h4 {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 2px;
}

.status-subtitle {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.status-badge {
  margin-left: auto;
  padding: 4px 10px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.memory-badge {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  background: transparent;
  padding: 0;
}

.badge-title {
  font-size: 10px;
  color: var(--color-text-tertiary);
  font-weight: normal;
}

.badge-value {
  font-size: 18px;
  font-weight: var(--font-weight-bold);
  color: #e67e22;
  line-height: 1;
}

.badge-total {
  font-size: 10px;
  color: var(--color-text-muted);
  font-weight: normal;
}

/* System Stats */
.system-stats-row {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.system-stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.system-stat-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.system-stat-value {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

/* System Info Group */
.system-info-group {
  margin-top: var(--spacing-sm);
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.info-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border: 1px solid transparent;
}

.version-badge {
  color: var(--color-primary);
  background: rgba(230, 126, 34, 0.08);
}

.version-badge:hover {
  background: rgba(230, 126, 34, 0.15);
  transform: translateY(-1px);
}

.core-badge {
  cursor: pointer;
  position: relative;
}

.core-badge:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  transform: translateY(-1px);
}

.core-badge.has-update {
  background: rgba(39, 174, 96, 0.08);
  color: var(--color-success);
  border-color: rgba(39, 174, 96, 0.2);
  animation: badge-pulse 2s infinite;
}

.core-badge.has-update:hover {
  background: rgba(39, 174, 96, 0.15);
}

.update-dot {
  width: 5px;
  height: 5px;
  background: var(--color-success);
  border-radius: 50%;
  position: absolute;
  top: 2px;
  right: 2px;
  box-shadow: 0 0 4px var(--color-success);
}

.core-badge.checking .spin {
  animation: spin 1s linear infinite;
}

@keyframes badge-pulse {
  0% { box-shadow: 0 0 0 0 rgba(39, 174, 96, 0.4); }
  70% { box-shadow: 0 0 0 6px rgba(39, 174, 96, 0); }
  100% { box-shadow: 0 0 0 0 rgba(39, 174, 96, 0); }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.pie-empty-ring {
  stroke: var(--color-border);
  opacity: 0.3;
}

/* 直播监控列表样式 */
.live-status-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.live-list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--color-bg-tertiary);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.live-list-item:hover {
  background: var(--color-bg-card);
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  border-color: var(--color-border);
}

.live-list-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.live-list-label {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.live-list-value {
  font-size: 15px;
  font-weight: 600;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot.success { background: #2ecc71; box-shadow: 0 0 4px rgba(46, 204, 113, 0.4); }
.status-dot.error { background: #e74c3c; box-shadow: 0 0 4px rgba(231, 76, 60, 0.4); }
.status-dot.primary { background: #3498db; box-shadow: 0 0 4px rgba(52, 152, 219, 0.4); }

/* 存储卡片 */
.live-storage-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--color-bg-tertiary); 
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent; 
  margin-top: auto; /* Push to bottom if flex stretch */
}

.live-storage-card:hover {
  background: var(--color-bg-card);
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  border-color: var(--color-border);
}

.storage-icon {
  color: var(--color-text-secondary);
}

.storage-label {
  flex: 1;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.storage-value {
  font-size: 14px;
  font-weight: 600;
  font-family: monospace;
  color: var(--color-text-primary);
}

.status-dot.warning { background: #f39c12; box-shadow: 0 0 4px rgba(243, 156, 18, 0.4); }

/* CPU Load */
.cpu-load {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
}

.load-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.load-value {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-bold);
  color: #27ae60;
}

/* Database Stats */
.db-stats-row {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-sm);
}

.db-stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.db-stat-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.db-stat-value {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.db-stat-value.usage-normal { color: #27ae60; }
.db-stat-value.usage-caution { color: #f39c12; }
.db-stat-value.usage-warning { color: #e67e22; }
.db-stat-value.usage-critical { color: #e74c3c; }

.db-info-text {
  font-size: 10px;
  color: var(--color-text-tertiary);
  line-height: 1.4;
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--color-border);
}


.load-bar {
  flex: 1;
  height: 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.load-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  border-radius: var(--radius-full);
}

/* Chart Area */
.chart-area {
  background: var(--color-bg-primary);
  border-radius: var(--radius-md);
  padding: var(--spacing-sm) var(--spacing-md);
}

.area-chart {
  width: 100%;
  height: 36px;
}

.chart-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: var(--spacing-sm);
  font-size: var(--font-size-xs);
}

.chart-link {
  color: #e67e22;
}

.chart-time {
  color: var(--color-text-muted);
}

/* Network Speed Badge */
.network-speed-badge {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.speed-item {
  padding: 4px 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: var(--font-weight-medium);
  display: flex;
  align-items: center;
  gap: 4px;
}

.speed-icon {
  font-weight: bold;
}

.speed-item.download .speed-icon { color: #e74c3c; }
.speed-item.upload .speed-icon { color: #f39c12; }

/* CPU Stats */
.cpu-stats {
  margin-bottom: var(--spacing-md);
}

.cpu-stat-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.cpu-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.cpu-value {
  font-size: 24px;
  font-weight: var(--font-weight-bold);
  color: #e74c3c;
}

/* CPU Chart */
.cpu-chart {
  width: 100%;
  margin-top: var(--spacing-sm);
  background: #fafafa;
  border-radius: var(--radius-sm);
  padding: 4px;
  position: relative;
}

[data-theme="dark"] .cpu-chart {
  background: #2d2d2d;
}

.cpu-chart svg {
  width: 100%;
  height: 60px;
  display: block;
}

/* Network Chart */
.network-chart {
  width: 100%;
  margin-top: var(--spacing-sm);
  background: #fafafa;
  border-radius: var(--radius-sm);
  padding: 4px;
  position: relative;
}

[data-theme="dark"] .network-chart {
  background: #2d2d2d;
}

.chart-label-max {
  position: absolute;
  top: 4px;
  right: 8px;
  z-index: 10;
  font-size: 9px;
  color: #999;
  font-weight: 500;
  line-height: 1.2;
}

[data-theme="dark"] .chart-label-max {
  color: #888;
}

.chart-label-min {
  position: absolute;
  bottom: 4px;
  right: 8px;
  z-index: 10;
  font-size: 9px;
  color: #999;
  font-weight: 500;
  line-height: 1.2;
}

[data-theme="dark"] .chart-label-min {
  color: #888;
}

.network-chart svg {
  width: 100%;
  height: 60px;
  display: block;
}

/* 深色模式下的图表网格 */
[data-theme="dark"] .cpu-chart-svg .chart-grid-rect {
  fill: url(#cpu-grid-dark);
}

[data-theme="dark"] .network-chart-svg .chart-grid-rect {
  fill: url(#grid-dark);
}

.chart-legend {
  display: flex;
  gap: var(--spacing-lg);
  margin-top: var(--spacing-sm);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.legend-dot.red { background: #e74c3c; }
.legend-dot.orange { background: #f39c12; }

/* Responsive */
@media (max-width: 1200px) {
  .dashboard {
    grid-template-columns: 1fr;
  }
  
  .dashboard-right {
    order: 1; /* Moves to top on mobile */
  }
  
  .dashboard-left {
    order: 2; /* Moves to below on mobile */
  }
}

@media (max-width: 768px) {
  .dashboard {
    padding: 0;
    padding-bottom: var(--spacing-xl);
    gap: 12px;
    grid-template-columns: 1fr;
  }

  .dashboard-right {
    order: 1;
  }

  /* 核心修复：移动端将右侧活动列改为 Grid 布局 */
  .split-col.activity-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  
  /* 默认所有子元素跨两列 */
  .split-col.activity-col > * {
    grid-column: 1 / -1;
  }

  /* 调整移动端内部顺序 */
  .stats-left-group {
    order: 2; /* 移动到活动列表下方 */
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }

  .activity-card {
    order: 1; /* 活动列表优先 */
  }

  /* 清除行内样式带来的 margin */
  .license-card.compact-dashboard,
  .storage-card {
    margin-bottom: 0 !important;
  }

  /* 移动端：公告 + GPU 并列显示 */
  .announcements-card.compact {
    grid-column: 1;
    order: 0;
    width: 100%;
  }

  /* 优化高级版卡片和存储空间卡片布局 - Dashboard.vue 仅处理卡片间的 Grid 布局 */
  .license-card.compact-dashboard {
    grid-column: 1;
    order: 1;
    width: auto !important;
    flex: none;
  }

  .gpu-monitor-card {
    grid-column: 2;
    order: 0;
  }

  .stats-left-group .gpu-monitor-card {
    width: 100% !important;
    max-width: none !important;
    justify-self: stretch;
  }

  .storage-card {
    grid-column: 2;
    order: 2;
    width: auto !important;
    max-width: none;
  }

  /* 调整移动端列顺序：让下载统计排在前面点 */
  .split-col.activity-col {
    order: 2; /* 移动到底部 */
  }
  
  .split-col.side-col {
    order: 1; /* 概览居中 */
  }
  
  /* 统计卡片：2+1 排列（移动端显示在前面） */
  .stats-row {
    grid-template-columns: 1fr 1fr;
    gap: var(--spacing-sm);
    width: 100%;
    order: 2; /* 显示在存储空间之后 */
  }
  
  .stat-card {
    padding: var(--spacing-sm);
    min-height: 80px;
    min-width: 0;
    width: 100%;
    border-radius: var(--radius-md);
  }
  
  .stat-label {
    font-size: 11px;
  }
  
  .stat-value {
    font-size: 20px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .stat-suffix {
    font-size: 12px;
  }

  /* 移动端并列显示优化 */
  .stat-values-row {
    gap: var(--spacing-md);
  }

  .stat-value-item .stat-value {
    font-size: 18px;
  }

  .stat-value-label {
    font-size: 10px;
  }
  
  /* 移动端：公告与 GPU 并列 */
  .announcements-card.compact {
    min-width: 0;
    max-width: 100%;
    width: 100%;
    padding: var(--spacing-sm);
    min-height: auto;
    height: auto; /* 覆盖桌面端的 height: 100% */
    flex: none; /* 覆盖桌面端的 flex: 0 0 300px */
    justify-content: flex-start; /* 覆盖桌面端的 justify-content: space-between */
    grid-column: 1;
    order: 0;
  }

  .gpu-monitor-card {
    grid-column: 2;
    order: 0;
  }

  .announcements-card.compact .card-title {
    font-size: 13px;
  }

  .announcements-card.compact .ann-status-title {
    font-size: 12px;
  }

  .announcements-card.compact .ann-status-desc {
    font-size: 10px;
  }

  .announcements-card.compact .btn-sm {
    padding: 6px 12px;
    font-size: 11px;
  }

  /* 移动端公告状态区域优化 */
  .announcements-card.compact .announcements-status {
    gap: var(--spacing-sm);
    margin-top: var(--spacing-xs);
  }

  .announcement-card.compact .card-header-with-badge {
    margin-bottom: var(--spacing-xs);
  }

  /* 移动端侧栏卡片顺序恢复：快捷操作优先 */
  .split-col.side-col {
    display: flex;
    flex-direction: column;
  }

  .quick-actions-card {
    order: 1;
  }

  /* 核心服务卡片 - 移动端隐藏 */
  .status-card.service-horizontal {
    display: none;
  }
  
  /* 视频订阅监控卡片 */
  .subscription-monitor-card {
    order: 3;
  }

  /* 快捷操作 */
  .quick-actions-card {
    padding: var(--spacing-sm);
  }

  .action-buttons {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--spacing-sm);
  }
  
  .btn {
    padding: 10px 8px;
    font-size: 13px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-height: 44px; /* 触摸友好 */
  }

  /* 最近活动卡片 */
  .activity-card {
    padding: var(--spacing-sm);
  }

  .activity-item {
    padding: var(--spacing-xs) 0;
    gap: var(--spacing-sm);
  }

  .activity-icon {
    width: 28px;
    height: 28px;
  }

  .activity-thumb {
    width: 60px;
    height: 34px;
  }

  .activity-filename {
    font-size: 12px;
  }

  .activity-user {
    font-size: 10px;
  }

  .activity-time {
    font-size: 10px;
  }

  /* 公告模块 */
  .announcements-card {
    padding: var(--spacing-sm);
  }

  .announcement-item {
    padding: var(--spacing-xs);
  }

  .ann-item-icon-wrapper {
    width: 32px;
    height: 32px;
  }

  .ann-item-title {
    font-size: 13px;
  }

  .ann-item-time {
    font-size: 11px;
  }

  /* 公告详情模态框 */
  .announcement-modal-overlay {
    padding: var(--spacing-sm);
    align-items: flex-end; /* 移动端从底部弹出 */
  }

  .announcement-modal {
    max-height: 85vh;
    max-width: 100%;
    border-radius: var(--radius-xl) var(--radius-xl) 0 0;
    animation: modalSlideUp 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  }

  @keyframes modalSlideUp {
    from {
      opacity: 0;
      transform: translateY(100%);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .dashboard {
    padding: 8px 10px !important;
    gap: 10px !important;
    max-height: 100vh;
    overflow-y: auto;
  }
  
  .dashboard-left {
    gap: 8px !important;
  }

  /* 仪表盘标题间距优化 */
  .card-title {
    font-size: 13px !important;
    margin-bottom: 6px !important;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--color-border-subtle);
  }

  /* 隐藏桌面端才需要的副标题/说明 */
  .title-desc, .pc-only {
    display: none !important;
  }

  .modal-close-btn {
    width: 44px;
    height: 44px;
    min-width: 44px;
    min-height: 44px;
  }

  .announcement-modal-content {
    padding: var(--spacing-md);
  }

  .announcement-detail-card {
    padding: var(--spacing-md);
  }

  .ann-detail-title {
    font-size: var(--font-size-md);
  }

  .ann-detail-content {
    font-size: 13px;
  }

  .announcement-list-item {
    padding: var(--spacing-md);
    min-height: 48px;
  }

  .ann-list-header {
    gap: var(--spacing-sm);
  }

  .ann-list-title {
    font-size: 13px;
  }

  .ann-list-time {
    font-size: 10px;
  }

  /* 系统状态卡片 */
  .system-status-section {
    gap: var(--spacing-sm);
  }

  .status-card {
    padding: var(--spacing-sm);
    min-width: 0;
    border-radius: var(--radius-md);
  }
  
  .status-header {
    gap: var(--spacing-sm);
    margin-bottom: var(--spacing-sm);
  }

  .status-icon {
    width: 28px;
    height: 28px;
  }

  .status-title h4 {
    font-size: 14px;
  }
  
  .status-subtitle {
    font-size: 10px;
  }

  .status-badge {
    padding: 3px 8px;
    font-size: 12px;
  }

  .system-stats-row,
  .db-stats-row {
    gap: var(--spacing-sm);
  }

  .system-stat-label,
  .db-stat-label {
    font-size: 10px;
  }

  .system-stat-value,
  .db-stat-value {
    font-size: 16px;
  }

  .system-info-text {
    font-size: 9px;
    flex-wrap: wrap;
    gap: 4px;
  }

  .version-link,
  .version-action {
    font-size: 9px;
    min-height: 20px;
    display: inline-flex;
    align-items: center;
  }
  
  /* 调整图表高度和样式 */
  .cpu-chart,
  .network-chart {
    padding: 3px;
    border-radius: var(--radius-sm);
  }

  .cpu-chart svg,
  .network-chart svg {
    height: 45px;
  }

  .chart-label-max,
  .chart-label-min {
    font-size: 8px;
    right: 6px;
  }

  .network-speed-badge {
    gap: 6px;
  }

  .speed-item {
    padding: 3px 6px;
    font-size: 10px;
  }

  /* 确保最后一个监控卡片有足够的底部空间 */
  .dashboard-right .status-card:last-child {
    margin-bottom: var(--spacing-xl);
  }

  /* 左侧内容区优化 */
  .dashboard-left {
    gap: var(--spacing-md);
  }

  /* 卡片通用样式优化 */
  .card {
    border-radius: var(--radius-md);
  }

  .card-title {
    font-size: 14px;
    margin-bottom: var(--spacing-sm);
  }

  /* 显隐控制 */
  .mobile-only {
    display: block;
  }
  
  .desktop-only {
    display: none;
  }

  /* 合并后的统计卡片在移动端高度自适应 */
  .combined-stats-card {
    height: auto !important;
    min-height: auto !important;
    padding: 6px 0 !important;
    margin-bottom: 0 !important;
  }

  .stat-mini-label {
    display: block;
    font-size: 10px;
    color: var(--color-text-tertiary);
    font-weight: 600;
    margin-bottom: 1px;
  }

  .mobile-only {
    display: block;
  }

  .live-stats-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 2px;
    grid-template-columns: none;
    padding: 4px 0;
  }

  .live-stat-item {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    min-height: auto !important;
    flex: 1;
    box-shadow: none !important;
    transform: none !important;
  }

  .live-stat-val {
    font-size: 18px !important;
    font-weight: 800;
    color: var(--color-text-primary);
    line-height: 1.1;
    margin: 2px 0;
  }

  .live-stat-label {
    display: none !important;
  }

  .stat-label-inline {
    display: block;
    margin-bottom: 2px;
  }
}

/* 超小屏幕优化 */
@media (max-width: 480px) {
  .dashboard {
    padding: 6px 8px !important;
    gap: 6px !important;
  }

  .stat-card {
    padding: 10px;
    min-height: 70px;
  }

  .stat-value {
    font-size: 18px;
  }

  .action-buttons {
    gap: var(--spacing-xs);
  }

  .btn {
    padding: 8px 6px;
    font-size: 12px;
    min-height: 40px;
  }

  .status-card {
    padding: 10px;
  }

  .status-title h4 {
    font-size: 13px;
  }

  .system-stat-value,
  .db-stat-value {
    font-size: 14px;
  }
}


/* Supervisor Service List */
.supervisor-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.supervisor-item {
  display: flex;
  flex-direction: column;
  padding: 8px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  gap: 4px;
}

.svc-name-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.svc-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70%;
}

.svc-pid {
  font-size: 10px;
  color: var(--color-text-tertiary);
  font-family: monospace;
}

.svc-status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}

.svc-uptime {
  color: var(--color-text-secondary);
}

.svc-status {
  font-weight: bold;
  padding: 1px 6px;
  border-radius: 4px;
}

.svc-status.running {
  color: #27ae60;
  background: rgba(39, 174, 96, 0.1);
}

.svc-status.fatal, .svc-status.stopped, .svc-status.backoff {
  color: #e74c3c;
  background: rgba(231, 76, 60, 0.1);
}

.svc-status.starting {
  color: #f39c12;
  background: rgba(243, 156, 18, 0.1);
}


/* Supervisor Service List (Horizontal) */
.service-horizontal {
  padding: 12px 16px !important;
}

.status-header.compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.status-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-icon.small {
  width: 28px; /* 稍微加大一点 */
  height: 28px;
}

.status-icon.brand-style {
  background: linear-gradient(135deg, #e67e22, #d35400);
  color: white;
  box-shadow: 0 2px 6px rgba(230, 126, 34, 0.3);
}

/* 自定义主 Logo 样式 */
.status-icon.home-logo {
  background: transparent !important; /* 移除背景色，直接使用 SVG 自身的渐变 */
  box-shadow: none !important;
  width: 32px !important;
  height: 32px !important;
  padding: 0;
  overflow: visible;
}

.home-logo-svg {
  width: 100%;
  height: 100%;
  filter: drop-shadow(0 2px 4px rgba(230, 126, 34, 0.25));
  transition: transform 0.3s ease;
}

.status-icon.home-logo:hover .home-logo-svg {
  transform: scale(1.1) rotate(5deg);
}

.status-badge.small {
  padding: 2px 6px;
  font-size: 10px;
}

.supervisor-list-horizontal {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.supervisor-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-bg-tertiary); /* 默认背景 */
  border-radius: 20px;
  border: 1px solid var(--color-border);
  font-size: 12px;
  transition: all 0.2s;
}

.supervisor-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 5px rgba(0,0,0,0.05);
}

.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #bdc3c7; /* 默认灰色 */
}

.chip-name {
  color: var(--color-text-primary);
  font-weight: 500;
}

.chip-status {
  font-size: 10px;
  font-weight: bold;
  opacity: 0.8;
  margin-left: 2px;
}

/* 状态颜色 */
.chip-dot.running { background: #27ae60; box-shadow: 0 0 4px #27ae60; }
.chip-dot.fatal, .chip-dot.stopped, .chip-dot.backoff { background: #e74c3c; box-shadow: 0 0 4px #e74c3c; }
.chip-dot.starting { background: #f39c12; box-shadow: 0 0 4px #f39c12; }

/* 异常状态下的 Chip 背景高亮 */
.supervisor-chip.fatal, .supervisor-chip.stopped, .supervisor-chip.backoff {
  background: rgba(231, 76, 60, 0.1);
  border-color: rgba(231, 76, 60, 0.3);
}
.supervisor-chip.fatal .chip-name, .supervisor-chip.stopped .chip-name {
  color: #c0392b;
}

.supervisor-chip.starting {
  background: rgba(243, 156, 18, 0.1);
  border-color: rgba(243, 156, 18, 0.3);
}

.supervisor-chip.starting {
  background: rgba(243, 156, 18, 0.1);
  border-color: rgba(243, 156, 18, 0.3);
}

/* 网络状态分隔线 */
.network-status-divider {
  width: 1px;
  height: 24px;
  background: var(--color-border);
  margin: 0 4px;
}

/* 网络状态 Chip */
.network-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-bg-tertiary);
  border-radius: 20px;
  border: 1px solid var(--color-border);
  font-size: 12px;
  transition: all 0.2s;
  cursor: help;
}

.network-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 5px rgba(0,0,0,0.05);
}

.network-icon {
  font-size: 14px;
  line-height: 1;
}

.network-name {
  color: var(--color-text-primary);
  font-weight: 500;
}

.network-latency {
  font-size: 10px;
  font-weight: bold;
  font-family: monospace;
  opacity: 0.8;
}

.network-status-text {
  font-size: 10px;
  font-weight: bold;
  opacity: 0.8;
}

/* 网络状态颜色 */
.network-chip.network-good {
  background: rgba(39, 174, 96, 0.1);
  border-color: rgba(39, 174, 96, 0.3);
}

.network-chip.network-good .network-icon {
  filter: drop-shadow(0 0 2px #27ae60);
}

.network-chip.network-good .network-latency {
  color: #27ae60;
}

.network-chip.network-slow {
  background: rgba(243, 156, 18, 0.1);
  border-color: rgba(243, 156, 18, 0.3);
}

.network-chip.network-slow .network-latency {
  color: #f39c12;
}

.network-chip.network-very-slow {
  background: rgba(230, 126, 34, 0.1);
  border-color: rgba(230, 126, 34, 0.3);
}

.network-chip.network-very-slow .network-latency {
  color: #e67e22;
}

.network-chip.network-failed,
.network-chip.network-timeout {
  background: rgba(231, 76, 60, 0.1);
  border-color: rgba(231, 76, 60, 0.3);
}

.network-chip.network-failed .network-status-text {
  color: #e74c3c;
}

.network-chip.network-checking {
  background: rgba(52, 152, 219, 0.1);
  border-color: rgba(52, 152, 219, 0.3);
  animation: network-pulse 1.5s ease-in-out infinite;
}

.network-chip.network-checking .network-status-text {
  color: #3498db;
}

@keyframes network-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}


/* Battery Card Style for Dashboard (replicated from LiveRecord) */
.stat-card.storage-card.battery-card-style {
  position: relative;
  border: 2px solid var(--color-border);
  border-radius: 12px;
  overflow: visible;
  background: var(--color-bg-card);
  padding: 0;
  transition: all 0.3s ease;
  min-height: 110px;
}

.stat-card.storage-card.battery-card-style::after {
  content: '';
  position: absolute;
  top: 50%;
  right: -7px;
  transform: translateY(-50%);
  width: 5px;
  height: 24px;
  background: var(--color-border);
  border-radius: 0 4px 4px 0;
  transition: background-color 0.3s ease;
}

.stat-card.storage-card.battery-card-style:hover {
  border-color: var(--color-text-secondary);
}
.stat-card.storage-card.battery-card-style:hover::after {
  background: var(--color-text-secondary);
}

.battery-bg-fill {
  position: absolute;
  top: 3px;
  left: 3px;
  bottom: 3px;
  border-radius: 9px;
  transition: width 0.3s ease;
  z-index: 0;
  max-width: calc(100% - 6px);
}

.battery-bg-fill.normal { background: rgba(39, 174, 96, 0.15); }
.battery-bg-fill.caution { background: rgba(241, 196, 15, 0.15); }
.battery-bg-fill.warning { background: rgba(230, 126, 34, 0.15); }
.battery-bg-fill.critical { background: rgba(231, 76, 60, 0.15); }

.stat-content.relative-z {
  position: relative;
  z-index: 1;
  padding: 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.stat-footer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

.stat-percent-large {
  font-weight: 700;
  font-size: 14px;
}

.stat-percent-large.normal { color: #27ae60; }
.stat-percent-large.caution { color: #f1c40f; }
.stat-percent-large.warning { color: #e67e22; }
.stat-percent-large.critical { color: #e74c3c; }

.text-error {
  color: #e74c3c !important;
}

.text-success {
  color: #27ae60 !important;
}

.text-warning {
  color: #f39c12 !important;
}

/* Matrix Animation for Announcement Card */
.card.announcements-card.matrix-mode {
  position: relative;
  overflow: hidden;
  background: black !important; /* Force black background */
  border: 1px solid #333;
}

.card.announcements-card.matrix-mode canvas.matrix-bg {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 1;
  z-index: 0;
  pointer-events: none;
}

.card.announcements-card.matrix-mode .announcements-status {
  position: relative;
  z-index: 1; /* Ensure text is above canvas */
}

/* Ensure text color is green/visible on black background */
.card.announcements-card.matrix-mode .ann-status-title span {
  color: #0F0;
  text-shadow: 0 0 5px #0F0;
  font-family: 'Monaco', 'Menlo', monospace;
  font-weight: bold;
  letter-spacing: 1px;
}


</style>
