<template>
  <div class="live-timeline-view" :class="{ 'has-sidebar': !isFullscreen && subId }">
    <!-- 桌面端侧边列表 (仅在已选择主播时显示) -->
    <aside v-if="!isFullscreen && subId" class="player-sidebar pc-only">
      <div class="sidebar-header">
        <h3>主播回放列表</h3>
        <button class="header-action-btn" @click="$router.push('/live-record')" title="去管理直播订阅">
          <Icon name="settings" :size="15" />
        </button>
      </div>
      <div class="sidebar-search">
        <div class="search-input-wrapper">
          <Icon name="search" :size="14" class="search-icon" />
          <input v-model="searchQuery" type="text" placeholder="搜索主播..." class="search-input" />
        </div>
      </div>
      <div class="streamer-list custom-scrollbar">
        <div 
          v-for="sub in subscriptionCards"
          :key="sub.id"
          class="streamer-item"
          :class="{ active: subId === sub.id, 'has-records': timelineAvailability[sub.id]?.available }"
          @click="selectStreamer(sub)"
        >
          <img v-if="sub.avatar_url" :src="sub.avatar_url" class="item-avatar" referrerpolicy="no-referrer" />
          <div v-else class="item-avatar-placeholder">{{ (sub.anchor_name || '未')[0] }}</div>
          <div class="item-info">
            <div class="item-name" :title="sub.anchor_name">{{ sub.anchor_name }}</div>
            <div class="item-platform">{{ sub._platformName }}</div>
          </div>
          <div v-if="timelineAvailability[sub.id]?.available" class="record-dot" title="有回放记录"></div>
        </div>
      </div>
    </aside>

    <div class="timeline-main">
      <!-- 播放模式头部 -->
      <div class="page-header" v-if="subId && !isFullscreen">
        <button class="back-btn" @click="goBack" title="返回主播选择">
          <Icon name="chevron-left" :size="20" />
          <span class="pc-only">选择主播</span>
        </button>
        <div class="header-divider pc-only"></div>
        <div class="current-streamer">
           <img v-if="activeSubAvatar" :src="activeSubAvatar" class="header-avatar" referrerpolicy="no-referrer" />
           <div v-else class="header-avatar-placeholder">{{ (activeSubName || '播')[0] }}</div>
           <div class="header-info">
             <span class="header-name">{{ activeSubName }}</span>
             <span class="header-platform">{{ activeSubPlatformName }}</span>
           </div>
        </div>
        <div class="header-spacer"></div>
        <button class="header-action-btn mobile-only" @click="$router.push('/live-record')" title="管理直播订阅">
          <Icon name="settings" :size="18" />
        </button>
      </div>

      <!-- 播放器区域 -->
      <div v-if="subId" class="player-wrapper">
        <TimelinePlayer
          :key="subId"
          :sub-id="subId"
          :sub-name="activeSubName"
          :sub-avatar="activeSubAvatar"
          :sub-platform-name="activeSubPlatformName"
          :date="date"
          @date-change="handleDateChange"
          @fullscreen-change="handleFullscreenChange"
        />
      </div>
      
      <!-- 授权与列表区域 -->
      <div v-else class="selection-screen custom-scrollbar">
        <!-- 授权检测提示 -->
        <div v-if="!licenseValid" class="license-alert">
          <div class="license-icon">🔒</div>
          <h2>{{ checkingLicense ? '正在验证...' : '需要授权' }}</h2>
          <p v-if="!checkingLicense">该功能为高级功能，请前往发卡平台购买授权</p>
          
          <div class="license-features" v-if="!checkingLicense">
            <div class="feature-item">
              <Icon name="check" :size="16" />
              <span>支持 抖音 / 斗鱼 / B站 / 虎牙 / 小红书 / YouTube / 咪咕</span>
            </div>
            <div class="feature-item">
              <Icon name="check" :size="16" />
              <span>自动检测开播 + 全自动开启录制</span>
            </div>
            <div class="feature-item">
              <Icon name="check" :size="16" />
              <span>TG / 微信 / Server酱 开播消息通知</span>
            </div>
            <div class="feature-item">
              <Icon name="check" :size="16" />
              <span>录制结束自动转码 MP4 + 智能分段</span>
            </div>
             <div class="feature-item">
              <Icon name="check" :size="16" />
              <span>7x24小时无人值守全自动录制挂机</span>
            </div>
             <div class="feature-item">
              <Icon name="check" :size="16" />
              <span>录制历史管理、在线播放与空间统计</span>
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

        <!-- 正常内容 (已授权) -->
        <template v-else>
          <!-- 加载中 -->
          <Transition name="fade" mode="out-in">
            <SkeletonLoader 
              v-if="loading"
              :loading="true"
              text="正在拉取直播库..."
              type="grid"
              :count="12"
              itemHeight="180px"
              itemMinWidth="160px"
              gap="24px"
            />

            <!-- 列表/选择器 -->
            <div v-else class="selection-content-wrapper">
            <div class="selection-header">
              <div class="header-left-side">
                <div class="brand-orb">
                  <svg width="48" height="48" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                      <linearGradient id="brandGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stop-color="#FF4D4D" stop-opacity="1" />
                        <stop offset="100%" stop-color="#F9CB28" stop-opacity="1" />
                      </linearGradient>
                    </defs>
                    <rect x="6" y="10" width="22" height="20" rx="4" stroke="url(#brandGradient)" stroke-width="2.5" />
                    <path d="M28 15L34.6 11.2C35.3 10.8 36 11.3 36 12V28C36 28.7 35.3 29.2 34.6 28.8L28 25" stroke="url(#brandGradient)" stroke-width="2.5" stroke-linecap="round" />
                    <path d="M14 15.5L20 20L14 24.5V15.5Z" fill="url(#brandGradient)" />
                  </svg>
                </div>
                <div class="title-meta">
                  <h2>直播回放</h2>
                  <p class="pc-only">请选择一个主播进入播放页面</p>
                </div>
              </div>
              
              <div class="header-right-side">
                <div class="selection-search-row">
                  <div class="search-input-wrapper wider">
                    <Icon name="search" :size="18" class="search-icon" />
                    <input v-model="searchQuery" type="text" placeholder="搜索名称或平台..." class="search-input" />
                  </div>
                  <button class="btn btn-outline manage-btn" @click="$router.push('/live-record')" title="前往管理/添加直播订阅">
                    <Icon name="settings" :size="16" />
                    <span class="pc-only">管理订阅</span>
                  </button>
                </div>

                <!-- 平台快捷过滤 -->
                <div class="platform-filters custom-scrollbar">
                  <button 
                    v-for="p in platforms" 
                    :key="p.key"
                    class="filter-tag"
                    :class="{ active: selectedPlatform === p.key }"
                    @click="selectedPlatform = p.key"
                  >
                    {{ p.name }}
                  </button>
                </div>
              </div>
            </div>

            <div v-if="recentResumeEntries.length" class="recent-resume-panel">
              <div class="recent-resume-header">
                <h3>最近播放</h3>
                <span class="recent-resume-note">（只在本机浏览器保存，清理缓存会丢失）</span>
                <div class="recent-resume-actions">
                  <button class="recent-clear-btn" @click="clearResumeHistory">清理记录</button>
                  <span class="recent-resume-hint">点击可继续播放</span>
                </div>
              </div>
              <div class="recent-resume-list custom-scrollbar" @wheel.prevent="handleRecentWheel">
                <div
                  v-for="entry in recentResumeCards"
                  :key="entry.sub.id"
                  class="recent-resume-card"
                  @click="selectStreamerWithDate(entry.sub, entry.resumeDate, entry.timeOfDay)"
                >
                <div class="recent-avatar-col">
                  <div class="recent-avatar">
                    <img v-if="entry.sub.avatar_url" :src="entry.sub.avatar_url" referrerpolicy="no-referrer" />
                    <div v-else class="recent-avatar-placeholder">{{ (entry.sub.anchor_name || '播')[0] }}</div>
                  </div>
                  <div class="recent-platform-below">{{ entry._platformName }}</div>
                </div>
                <div class="recent-info">
                  <div class="recent-name">{{ entry.sub.anchor_name }}</div>
                  <div class="recent-meta">
                    <span class="recent-time">{{ entry._time }}</span>
                    <span class="recent-ago">{{ entry._relativeTime }}</span>
                    <span class="recent-date">{{ entry.resumeDate }}</span>
                  </div>
                  </div>
                </div>
              </div>
            </div>
            
            <div v-if="subscriptionCards.length > 0" class="streamer-grid">
               <div 
                v-for="sub in subscriptionCards"
                :key="sub.id"
                class="grid-card"
                @click="selectStreamer(sub)"
              >
                <!-- 动态色彩背景层 -->
                <div v-if="sub.avatar_url" class="card-blur-bg" :style="{ backgroundImage: `url(${sub.avatar_url})` }"></div>
                
                <!-- 顶部标识区域 -->
                <div class="card-platform-tag" :class="`tag-${sub.platform}`">{{ sub._platformName }}</div>
                <div class="card-record-badge" :class="{ 'badge-empty': !timelineAvailability[sub.id]?.available }">
                  {{ timelineAvailability[sub.id]?.available ? '有回放' : '无回放' }}
                </div>
                
                <div class="card-avatar-wrapper">
                  <img v-if="sub.avatar_url" :src="sub.avatar_url" class="card-avatar" referrerpolicy="no-referrer" />
                  <div v-else class="card-avatar-placeholder">{{ (sub.anchor_name || '未')[0] }}</div>
                </div>
                <div class="card-info">
                  <div class="card-name">{{ sub.anchor_name }}</div>
                </div>
              </div>
            </div>

            <div v-else class="empty-state">
              <div class="empty-icon">
                <Icon name="tv" :size="64" />
              </div>
              <h3>{{ searchQuery ? '未搜索到相关主播' : '暂无直播订阅' }}</h3>
              <p>{{ searchQuery ? '请尝试换个关键词搜索' : '请先在直播订阅页面添加感兴趣的主播' }}</p>
              <button v-if="!searchQuery" class="btn btn-primary" @click="$router.push('/live-record')">
                去添加主播
              </button>
              <button v-else class="btn btn-outline" @click="searchQuery = ''">
                清空搜索
              </button>
            </div>
            </div>
          </Transition>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TimelinePlayer from '@/components/TimelinePlayer.vue'
import Icon from '@/components/common/Icon.vue'
import liveApi from '@/api/live'
import { licenseApi } from '@/api/index'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const subscriptions = ref([])
const timelineAvailability = ref({})
const searchQuery = ref('')
const isFullscreen = ref(false)
const selectedPlatform = ref('all')
const recentResumeEntries = ref([])

const platforms = [
  { key: 'all', name: '全部' },
  { key: 'douyin', name: '抖音' },
  { key: 'bilibili', name: 'B站' },
  { key: 'douyu', name: '斗鱼' },
  { key: 'huya', name: '虎牙' },
  { key: 'xhs', name: '小红书' },
  { key: 'youtube', name: 'YouTube' },
  { key: 'migu', name: '咪咕' },
  { key: 'kuaishou', name: '快手' }
]

// 授权状态 - 优先读取本地缓存，避免闪烁
let cachedLicense = null
try { cachedLicense = localStorage.getItem('license_status') } catch (e) { /* 隐私模式下可能被阻止 */ }
const licenseValid = ref(cachedLicense === 'true')
const checkingLicense = ref(cachedLicense === null)
const date = computed(() => route.query.date || '')

const subId = computed(() => route.params.subId)

// 获取当前激活主播的信息
const activeSub = computed(() => {
  if (!subId.value) return null
  return subscriptions.value.find(s => s.id === subId.value)
})

const activeSubName = computed(() => activeSub.value?.anchor_name || route.query.name || '正在加载...')
const activeSubAvatar = computed(() => activeSub.value?.avatar_url || route.query.avatar || '')
const activeSubPlatformName = computed(() => activeSub.value ? getPlatformName(activeSub.value.platform) : (route.query.platform_name || ''))

const filteredSubscriptions = computed(() => {
  let list = subscriptions.value

  if (selectedPlatform.value !== 'all') {
    list = list.filter(sub => sub.platform === selectedPlatform.value)
  }

  if (!searchQuery.value) return list

  const q = searchQuery.value.toLowerCase()
  return list.filter(s =>
    s.anchor_name.toLowerCase().includes(q) ||
    getPlatformName(s.platform).toLowerCase().includes(q)
  )
})

// 预计算订阅列表展示字段，避免模板中重复调用函数
const subscriptionCards = computed(() => {
  return filteredSubscriptions.value.map(sub => ({
    ...sub,
    _platformName: getPlatformName(sub.platform),
  }))
})

// 预计算最近播放条目的展示字段
const recentResumeCards = computed(() => {
  return recentResumeEntries.value.map(entry => ({
    ...entry,
    _platformName: getPlatformName(entry.sub.platform),
    _time: formatTime(entry.timeOfDay),
    _relativeTime: formatRelativeTime(entry.updatedAt),
  }))
})

let storageListener = null
let resumeChannel = null
let resumeEventListener = null
let visibilityListener = null
let focusListener = null

onMounted(async () => {
  await checkLicense()
  if (licenseValid.value) {
    await loadData()
  }
  loading.value = false

  storageListener = (e) => {
    if (e.key === TIMELINE_RESUME_STORE_KEY) {
      loadRecentResumeEntries()
    }
  }
  window.addEventListener('storage', storageListener)

  resumeEventListener = () => loadRecentResumeEntries()
  window.addEventListener('timeline-resume-updated', resumeEventListener)

  visibilityListener = () => {
    if (!document.hidden) loadRecentResumeEntries()
  }
  document.addEventListener('visibilitychange', visibilityListener)

  focusListener = () => loadRecentResumeEntries()
  window.addEventListener('focus', focusListener)

  if (typeof BroadcastChannel !== 'undefined') {
    resumeChannel = new BroadcastChannel(RESUME_BROADCAST_CHANNEL)
    resumeChannel.onmessage = () => loadRecentResumeEntries()
  }
})

onBeforeUnmount(() => {
  if (storageListener) {
    window.removeEventListener('storage', storageListener)
    storageListener = null
  }
  if (resumeEventListener) {
    window.removeEventListener('timeline-resume-updated', resumeEventListener)
    resumeEventListener = null
  }
  if (visibilityListener) {
    document.removeEventListener('visibilitychange', visibilityListener)
    visibilityListener = null
  }
  if (focusListener) {
    window.removeEventListener('focus', focusListener)
    focusListener = null
  }
  if (resumeChannel) {
    resumeChannel.close()
    resumeChannel = null
  }
})

async function checkLicense(force = false) {
  if (cachedLicense === null) {
      checkingLicense.value = true
  }
  
  try {
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
  } catch (e) {
      if (cachedLicense === null) {
           licenseValid.value = false
      }
      console.error('License check failed:', e)
  } finally {
      checkingLicense.value = false
  }
}

async function loadData() {
  try {
    const res = await liveApi.getLiveSubscriptions()
    subscriptions.value = res.data || []
    
    if (subscriptions.value.length > 0) {
      const ids = subscriptions.value.map(s => s.id)
      const availRes = await liveApi.getTimelineAvailability(ids)
      timelineAvailability.value = availRes.data || {}
    }
    loadRecentResumeEntries()
  } catch (e) {
    console.error('Failed to load subscriptions', e)
  }
}

const TIMELINE_DATE_STORAGE_KEY = 'live_record_timeline_date_by_sub_v1'
const TIMELINE_RESUME_STORE_KEY = 'timeline_player_resume_state_v3'
const RESUME_BROADCAST_CHANNEL = 'timeline-resume-updated'

function getTodayDateString() {
  const now = new Date()
  const y = now.getFullYear()
  const m = `${now.getMonth() + 1}`.padStart(2, '0')
  const d = `${now.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${d}`
}

function getTimelineDateForSub(subId) {
  const key = String(subId || '')
  if (!key) return getTodayDateString()
  
  try {
    const raw = localStorage.getItem(TIMELINE_DATE_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      const date = parsed[key]
      if (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
        return date
      }
    }
  } catch (e) { console.warn('读取时间线日期缓存失败', e) }

  return getTodayDateString()
}

function getResumeDateForSub(subId) {
  const key = String(subId || '')
  if (!key) return ''
  try {
    const raw = localStorage.getItem(TIMELINE_RESUME_STORE_KEY)
    if (!raw) return ''
    const parsed = JSON.parse(raw)
    if (!parsed || Number(parsed.version) !== 3 || typeof parsed.items !== 'object') return ''
    const entry = parsed.items[`${key}|__latest__`]
    const extrasDate = entry?.extras?.date
    if (typeof extrasDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(extrasDate)) {
      return extrasDate
    }
  } catch (e) {
    console.warn('load resume date failed', e)
  }
  return ''
}

function selectStreamer(sub) {
  const targetDate = getResumeDateForSub(sub.id) || getTimelineDateForSub(sub.id)
  selectStreamerWithDate(sub, targetDate)
}

function selectStreamerWithDate(sub, targetDate, resumeTime = 0) {
  const safeDate = typeof targetDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(targetDate)
    ? targetDate
    : getTimelineDateForSub(sub.id)
  const safeResumeTime = Number(resumeTime || 0)
  const hasResumeTime = Number.isFinite(safeResumeTime) && safeResumeTime > 0

  router.push({
    name: 'live-timeline',
    params: { subId: sub.id },
    query: {
      name: sub.anchor_name,
      avatar: sub.avatar_url,
      platform_name: getPlatformName(sub.platform),
      date: safeDate,
      ...(hasResumeTime ? { resume_at: String(safeResumeTime) } : {})
    }
  })
}

function handleDateChange(newDate) {
  const query = { ...route.query, date: newDate }
  router.replace({ query }).catch(() => {})
}

function handleFullscreenChange(val) {
  isFullscreen.value = val
}

function goBack() {
  router.push('/live-timeline')
}

function getPlatformName(p) {
  const map = {
    douyin: '抖音',
    bilibili: 'B站',
    douyu: '斗鱼',
    huya: '虎牙',
    xhs: '小红书',
    youtube: 'YouTube',
    migu: '咪咕',
    kuaishou: '快手'
  }
  return map[p] || p
}

function formatTime(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${h}`.padStart(2, '0') + ':' + `${m}`.padStart(2, '0') + ':' + `${sec}`.padStart(2, '0')
}

function formatRelativeTime(timestamp) {
  const ts = Number(timestamp || 0)
  if (!ts) return '未知时间'
  const diffMs = Date.now() - ts
  if (diffMs < 0) return '刚刚'
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec} 秒前`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay} 天前`
}

function parseResumeStore() {
  try {
    const raw = localStorage.getItem(TIMELINE_RESUME_STORE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || Number(parsed.version) !== 3 || typeof parsed.items !== 'object') return null
    return parsed.items || {}
  } catch (e) {
    console.warn('parse resume store failed', e)
    return null
  }
}

function loadRecentResumeEntries() {
  const items = parseResumeStore()
  if (!items || !subscriptions.value.length) {
    recentResumeEntries.value = []
    return
  }

  const subsById = new Map(subscriptions.value.map(s => [String(s.id), s]))
  const entries = Object.entries(items)
    .filter(([key]) => key.endsWith('|__latest__'))
    .map(([key, payload]) => {
      const subId = key.split('|')[0]
      const sub = subsById.get(String(subId))
      if (!sub) return null
      const timeOfDay = Number(payload?.timeOfDay || 0)
      const updatedAt = Number(payload?.updatedAt || 0)
      const extras = payload?.extras || {}
      const resumeDate = (typeof extras?.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(extras.date))
        ? extras.date
        : getTimelineDateForSub(sub.id)
      return {
        sub,
        timeOfDay,
        updatedAt,
        resumeDate
      }
    })
    .filter(Boolean)
    .sort((a, b) => b.updatedAt - a.updatedAt)

  recentResumeEntries.value = entries
}

function handleRecentWheel(e) {
  const el = e?.currentTarget
  if (!el || typeof el.scrollLeft !== 'number') return
  const delta = Number(e?.deltaY || e?.deltaX || 0)
  if (!delta) return
  el.scrollLeft += delta
}

function clearResumeHistory() {
  try {
    localStorage.removeItem(TIMELINE_RESUME_STORE_KEY)
  } catch (e) {
    console.warn('clear resume history failed', e)
  }
  loadRecentResumeEntries()
  try {
    window.dispatchEvent(new CustomEvent('timeline-resume-updated'))
  } catch (e) { console.warn('触发 resume 更新事件失败', e) }
}

watch(subscriptions, () => {
  loadRecentResumeEntries()
})
</script>

<style scoped>
.live-timeline-view {
  height: 100%;
  flex: 1;
  display: flex;
  background: var(--color-bg-primary);
  overflow: hidden;
  color: var(--color-text-primary);
  position: relative;
  min-width: 0;
}

/* 授权提示样式 */
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
  margin-bottom: var(--spacing-lg);
  color: var(--color-error);
  display: flex;
  justify-content: center;
  font-size: 3rem;
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

@media (max-width: 768px) {
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
    width: 100%;
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
}

.player-sidebar {
  width: 280px;
  background: var(--color-bg-secondary);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  z-index: 10;
}

.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-action-btn {
  background: none;
  border: none;
  color: var(--color-text-tertiary);
  cursor: pointer;
  padding: 6px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition-fast);
}

.header-action-btn:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-primary);
}

.header-spacer {
  flex: 1;
}

.sidebar-search {
  padding: 12px;
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 10px;
  color: var(--color-text-tertiary);
}

.search-input {
  width: 100%;
  padding: 8px 12px 8px 32px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-bg-primary);
  font-size: 13px;
  transition: border-color var(--transition-fast);
}

.search-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.search-input-wrapper.wider {
  width: 100%;
  max-width: 400px;
}

.search-input-wrapper.wider .search-input {
  padding: 12px 12px 12px 42px;
  font-size: 15px;
}

.search-input-wrapper.wider .search-icon {
  left: 14px;
}

.streamer-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.streamer-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  margin-bottom: 4px;
  position: relative;
}

.streamer-item:hover {
  background: var(--color-bg-hover);
}

.streamer-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.item-avatar, .item-avatar-placeholder {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  border: 1px solid var(--color-border);
}

.item-avatar-placeholder {
  background: var(--color-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

.item-info {
  min-width: 0;
  flex: 1;
}

.item-name {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-platform {
  font-size: 11px;
  color: var(--color-text-tertiary);
}

.active .item-platform {
  color: var(--color-primary);
  opacity: 0.8;
}

.record-dot {
  width: 6px;
  height: 6px;
  background: var(--color-success);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--color-success);
}

.timeline-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.page-header {
  display: flex;
  align-items: center;
  padding: 12px 24px;
  background: var(--color-bg-secondary);
  border-bottom: 1px solid var(--color-border);
  gap: 16px;
  min-width: 0;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  background: none;
  border: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 6px 12px;
  border-radius: var(--radius-md);
  font-size: 14px;
  transition: all var(--transition-fast);
  flex-shrink: 0;
  white-space: nowrap;
}

.back-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.header-divider {
  width: 1px;
  height: 24px;
  background: var(--color-border);
}

.current-streamer {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.header-avatar, .header-avatar-placeholder {
  width: 28px;
  height: 28px;
  border-radius: 50%;
}

.header-avatar-placeholder {
  background: var(--color-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}

.header-info {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  min-width: 0;
}

.header-name {
  font-weight: 600;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-platform {
  font-size: 11px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.player-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.selection-screen {
  flex: 1;
  width: 100%;
  overflow-y: auto;
  padding: 40px clamp(16px, 3vw, 40px);
  display: flex;
  flex-direction: column;
  align-items: stretch; /* 改为 stretch 避免内容居中导致左侧切断 */
  box-sizing: border-box;
}

.selection-header {
  margin-bottom: 40px;
  width: 100%;
  max-width: 1860px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}

.recent-resume-panel {
  width: 100%;
  max-width: 1860px;
  background: var(--color-bg-card);
  border: 1px solid rgba(255, 140, 66, 0.2);
  border-radius: var(--radius-xl);
  padding: 18px 20px;
  margin-bottom: 28px;
  box-shadow: var(--shadow-md);
  overflow: visible;
}

.recent-resume-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.recent-resume-note {
  color: var(--color-text-tertiary);
  font-size: 12px;
  white-space: nowrap;
}

.recent-resume-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.recent-clear-btn {
  border: 1px solid rgba(255, 140, 66, 0.35);
  background: rgba(255, 255, 255, 0.6);
  color: var(--color-text-secondary);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.recent-clear-btn:hover {
  color: var(--color-text-primary);
  border-color: rgba(255, 140, 66, 0.6);
  background: rgba(255, 255, 255, 0.9);
}

.recent-resume-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.recent-resume-hint {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.recent-resume-list {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 6px;
  padding-top: 6px;
}

.recent-resume-card {
  min-width: 220px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px 12px 12px;
  background: linear-gradient(135deg, rgba(255, 140, 66, 0.08), rgba(255, 200, 85, 0.12));
  border: 1px solid rgba(255, 140, 66, 0.2);
  border-radius: 14px;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  position: relative;
}

.recent-resume-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-lg);
}

.recent-avatar img,
.recent-avatar-placeholder {
  width: 44px;
  height: 44px;
  border-radius: 12px;
}

.recent-avatar img {
  object-fit: cover;
}

.recent-avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 140, 66, 0.18);
  color: var(--color-text-primary);
  font-weight: 700;
}

.recent-avatar-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.recent-platform-below {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 6px;
  font-size: 11px;
  color: var(--color-text-secondary);
  background: rgba(255, 140, 66, 0.12);
  border-radius: 999px;
  white-space: nowrap;
}

.recent-info {
  flex: 1;
  min-width: 0;
  padding-top: 2px;
}

.recent-name {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-meta {
  display: flex;
  gap: 6px 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}

.recent-ago {
  color: var(--color-text-tertiary);
}


.header-left-side {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-top: 4px;
}

.brand-orb {
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  border: 1px solid var(--color-border);
}

.title-meta h2 {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 4px;
  background: var(--gradient-header);
  background-clip: text;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.title-meta p {
  color: var(--color-text-tertiary);
  font-size: 14px;
}

.header-right-side {
  flex: 1;
  max-width: 800px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.selection-search-row {
  width: 100%;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
}

.manage-btn {
  height: 46px;
  padding: 0 20px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.manage-btn:hover {
  background: var(--color-bg-tertiary);
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

.platform-filters {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  max-width: 100%;
  padding-bottom: 4px;
  justify-content: flex-end;
}

.filter-tag {
  padding: 6px 18px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.filter-tag:hover {
  border-color: var(--color-primary-light);
  color: var(--color-primary);
  background: var(--color-bg-primary);
}

.filter-tag.active {
  background: var(--gradient-header);
  border-color: transparent;
  color: white;
  box-shadow: 0 4px 12px rgba(231, 76, 60, 0.2);
}

@media (max-width: 768px) {
  .platform-filters {
    padding: 0 10px 8px;
    width: calc(100% + 20px);
    margin-left: -10px;
    margin-right: -10px;
    box-sizing: border-box;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    gap: 8px;
  }
  .filter-tag {
    padding: 5px 14px;
    font-size: 12px;
    flex-shrink: 0;
  }
}

.streamer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 24px;
  width: 100%;
  max-width: 1860px;
  margin: 0 auto; /* 如果空间足够，仍然居中显示 */
}

.grid-card {
  background: var(--color-bg-card);
  border-radius: var(--radius-xl);
  padding: 32px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.23, 1, 0.32, 1);
  border: 1px solid var(--color-border);
  position: relative;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
}

.grid-card:hover {
  transform: translateY(-8px) scale(1.02);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.08);
  border-color: var(--color-primary-light);
}

.card-blur-bg {
  position: absolute;
  top: -20%;
  left: -20%;
  width: 140%;
  height: 140%;
  background-size: cover;
  background-position: center;
  filter: blur(45px) saturate(1.8) opacity(0.12);
  z-index: 0;
  pointer-events: none;
  transition: all 0.5s ease;
}

.grid-card:hover .card-blur-bg {
  filter: blur(35px) saturate(2.2) opacity(0.18);
  transform: scale(1.1);
}

.card-avatar-wrapper {
  position: relative;
  margin-bottom: 16px;
}

.card-avatar, .card-avatar-placeholder {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  object-fit: cover;
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.12);
  position: relative;
  z-index: 1;
  border: 2px solid white;
}

.card-avatar-placeholder {
  background: var(--color-bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
}

.card-info {
  text-align: center;
  width: 100%;
}


.card-record-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 5;
  background: var(--color-success);
  color: white;
  font-size: 10px;
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  white-space: nowrap;
  transition: all 0.3s ease;
  transform: translateY(0);
  pointer-events: none;
}

.grid-card:hover .card-record-badge {
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(0,0,0,0.12);
}

.card-record-badge.badge-empty {
  background: var(--color-bg-tertiary);
  color: var(--color-text-tertiary);
  font-weight: 600;
  box-shadow: none;
}

.card-platform-tag {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 5;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 700;
  color: #ffffff;
  text-shadow: 0 1px 1px rgba(0,0,0,0.1);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  pointer-events: none;
}

.card-name {
  font-weight: 700;
  font-size: 16px;
  margin-top: 4px;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tag-douyin { background: linear-gradient(135deg, #25F4EE 0%, #FE2C55 100%); }
.tag-bilibili { background: linear-gradient(135deg, #00A1D6 0%, #0079A1 100%); }
.tag-douyu { background: linear-gradient(135deg, #ff5d23 0%, #ff821c 100%); }
.tag-huya { background: linear-gradient(135deg, #ff9d00 0%, #f9cb28 100%); }
.tag-xhs { background: linear-gradient(135deg, #FF2442 0%, #FF8999 100%); }
.tag-youtube { background: linear-gradient(135deg, #ff4d4d 0%, #ff0000 100%); }
.tag-migu { background: linear-gradient(135deg, #1d8ef7 0%, #4aa7ff 100%); }
.tag-kuaishou { background: linear-gradient(135deg, #FF7D00 0%, #FF5000 100%); }

.loading-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
}

.empty-state {
  padding: 60px 0;
  text-align: center;
}

.empty-icon {
  opacity: 0.15;
  margin-bottom: 24px;
  display: flex;
  justify-content: center;
  color: var(--color-text-primary);
}

@media (min-width: 2000px) {
  .selection-header, 
  .recent-resume-panel, 
  .streamer-grid {
    max-width: 2300px;
  }
  .streamer-grid {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 24px;
  }
  .grid-card {
    padding: 32px 20px;
  }
}

@media (max-width: 1300px) {
  .selection-header {
    flex-direction: column;
    align-items: stretch;
    gap: 20px;
  }
  .header-right-side {
    max-width: none;
    align-items: flex-start;
  }
  .selection-search-row {
    justify-content: flex-start;
  }
  .platform-filters {
    justify-content: flex-start;
  }
  .selection-content-wrapper {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
  }
}

@media (max-width: 1024px) {
  .player-sidebar {
    width: 240px;
  }
}

@media (max-width: 768px) {
  .live-timeline-view {
    height: 100dvh;
  }
  .player-sidebar {
    display: none;
  }
  .selection-screen {
    padding: 15px 10px;
  }
  .selection-header {
    margin-bottom: 15px;
  }
  .selection-header .header-left-side {
    display: none;
  }
  .header-right-side {
    width: 100%;
    align-items: stretch;
  }
  .selection-content-wrapper {
    width: 100%;
  }
  .streamer-grid {
    grid-template-columns: repeat(2, 1fr); /* 强制双列，避免手机上三列过挤 */
    gap: 12px;
  }
  .grid-card {
    padding: 16px 10px;
  }
  .card-platform-tag {
    top: 8px;
    left: 8px;
    transform: scale(0.9);
    transform-origin: top left;
  }
  .card-record-badge {
    top: 8px;
    right: 8px;
    transform: scale(0.9);
    transform-origin: top right;
  }
  .grid-card:hover .card-record-badge {
    transform: scale(0.9) translateY(-2px);
  }
  .card-avatar, .card-avatar-placeholder {
    width: 60px;
    height: 60px;
  }
  .selection-header h2 {
    font-size: 22px;
  }
  .selection-header {
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 20px;
    margin-bottom: 24px;
  }
  .recent-resume-panel {
    padding: 12px;
    margin-bottom: 16px;
    background: var(--color-bg-secondary);
    border-radius: 16px;
  }
  .recent-resume-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    gap: 10px;
  }
  .recent-resume-header h3 {
    font-size: 15px;
    margin: 0;
  }
  .recent-resume-note {
    display: none; /* 移动端隐藏过长的备注 */
  }
  .recent-resume-actions {
    width: auto;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .recent-clear-btn {
    padding: 2px 10px;
    font-size: 11px;
    border-radius: 6px;
  }
  .recent-resume-hint {
    display: none; /* 移动端隐藏提示文案 */
  }
  .recent-resume-list {
    gap: 12px;
    padding: 2px 0;
    display: flex;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .recent-resume-card {
    min-width: 180px; /* 横向布局需要更宽一点 */
    flex-direction: row !important; /* 强制改为横向布局以减少高度 */
    align-items: center;
    padding: 8px 10px;
    gap: 10px;
    background: var(--color-bg-card);
    border: 1px solid var(--color-border-light);
    border-radius: 12px;
  }
  .recent-avatar-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
  .recent-avatar img,
  .recent-avatar-placeholder {
    width: 32px;
    height: 32px;
    border-radius: 8px;
  }
  .recent-platform-below {
    font-size: 9px;
    padding: 0 4px;
  }
  .recent-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .recent-name {
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .recent-meta {
    display: flex;
    flex-direction: column;
    gap: 1px;
    font-size: 10px;
    color: var(--color-text-tertiary);
  }
  .recent-time {
    color: var(--color-primary);
    font-weight: 600;
  }
  .header-left-side {
    flex-direction: column;
    gap: 10px;
  }
  .header-right-side {
    width: 100%;
    align-items: stretch; /* 占满整宽 */
  }
  .selection-search-row {
    justify-content: space-between;
    width: 100%;
    gap: 10px;
  }
  .search-input-wrapper.wider {
    flex: 1; /* 搜索框自适应剩余宽度 */
    max-width: none;
  }
  .manage-btn {
    flex-shrink: 0;
    padding: 0 14px;
  }
  .platform-filters {
    justify-content: flex-start;
    margin-top: 12px;
  }
  .page-header {
    padding: 10px 12px;
    gap: 8px;
  }
  .back-btn {
    padding: 6px 4px;
  }
}

/* 响应式辅助类 */
.pc-only {
  display: none !important;
}
.mobile-only {
  display: flex !important;
}
@media (min-width: 768px) {
  .pc-only {
    display: inline-flex !important;
  }
  .mobile-only {
    display: none !important;
  }
}
</style>
