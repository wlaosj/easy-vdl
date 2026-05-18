<template>
  <div class="content-view">
    <div class="content-container">
      
      <!-- 头部区域 -->
      <header class="header-section">
        <div class="icon-glow theme-gradient">
          <Icon name="music" :size="40" />
        </div>
        <h1>网易云音乐</h1>
        <p class="subtitle">支持单曲、歌单、解析下载</p>
      </header>

      <!-- 主内容区域（基础功能，无需授权） -->
      <!-- Mode Switcher -->
      <div class="mode-toggle">
        <button 
          class="tab-btn"
          :class="{ active: mode === 'search' }"
          @click="mode = 'search'"
        >
          按歌名搜索
        </button>
        <button 
          class="tab-btn"
          :class="{ active: mode === 'url' }"
          @click="mode = 'url'"
        >
          按链接解析
        </button>
      </div>

      <!-- Single Mode Input (Search by keyword) -->
      <div v-if="mode === 'search'" class="input-section">
        <div class="input-tools-top">
          <button type="button" class="btn btn-xs btn-secondary" @click="handlePasteKeyword" title="粘贴">
            <Icon name="file-text" :size="14" /> 粘贴
          </button>
          <button type="button" class="btn btn-xs btn-danger" @click="clearSearch" title="清空">
            <Icon name="trash" :size="14" /> 清空
          </button>
          <button type="button" class="btn btn-xs btn-warning" @click="goToCookieSettings" title="Cookie设置">
            <Icon name="settings" :size="14" /> Cookie设置
          </button>
        </div>
        <div class="input-wrapper">
          <input
            v-model="keyword"
            type="text"
            placeholder="输入歌曲名或 歌曲名 歌手名，例如：起风了 买辣椒也用券"
            @keyup.enter="handleSearch"
            :disabled="loading"
          />
        </div>
      </div>

      <!-- URL Mode Input -->
      <div v-else class="input-section">
        <div class="input-tools-top">
          <button type="button" class="btn btn-xs btn-secondary" @click="handlePaste" title="粘贴">
            <Icon name="file-text" :size="14" /> 粘贴
          </button>
          <button type="button" class="btn btn-xs btn-danger" @click="clearInput" title="清空">
            <Icon name="trash" :size="14" /> 清空
          </button>
          <button type="button" class="btn btn-xs btn-warning" @click="goToCookieSettings" title="Cookie设置">
            <Icon name="settings" :size="14" /> Cookie设置
          </button>
        </div>
        <div class="input-wrapper">
          <input 
            v-model="url" 
            type="url" 
            placeholder="支持单曲和歌单链接 (music.163.com)" 
            @keyup.enter="handleParse"
            :disabled="loading"
          />
        </div>
      </div>

      <!-- Action Button -->
      <div class="action-section">
        <button 
          class="btn btn-primary btn-lg w-full" 
          :disabled="loading || (mode === 'search' ? !keyword : !url)"
          @click="mode === 'search' ? handleSearch() : handleParse()"
        >
          <span v-if="loading" class="spinner"></span>
          <span v-else class="btn-content">
            {{ mode === 'search' ? '搜索歌曲' : '开始解析' }}
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

        <!-- 搜索结果列表 -->
        <div v-if="mode === 'search' && searchResults.length" class="search-results">
          <div class="search-results-header">
            <h3>搜索结果</h3>
            <span class="result-count">共 {{ searchTotal }} 首，当前显示 {{ searchResults.length }} 首</span>
          </div>
          <div class="songs-list">
            <div
              v-for="song in searchResults"
              :key="song.id"
              class="song-item"
            >
              <div class="song-header">
                <div class="song-info">
                  <div class="song-details">
                    <div class="song-title">
                      {{ song.title }}
                    </div>
                    <div class="song-artist">
                      <span v-if="song.artist">{{ song.artist }}</span>
                      <span v-if="song.album"> · {{ song.album }}</span>
                    </div>
                  </div>
                </div>
                <div class="song-actions">
                  <span class="song-duration" v-if="song.duration">{{ formatDuration(song.duration) }}</span>
                  <button
                    type="button"
                    class="btn btn-xs btn-secondary"
                    @click="openSongInNetease(song)"
                  >
                    打开网易云
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs btn-primary"
                    @click="useSongAsUrl(song)"
                  >
                    解析下载
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 解析结果展示 - 单曲 -->
        <ParserResultCard
          v-if="result && !result.is_playlist"
          :title="result.title"
          :thumbnail="result.thumbnail"
          platform="netease"
        >
          <!-- 可用格式列表 -->
          <div class="formats-section">
            <h3 class="section-title">可用下载格式</h3>
            
            <div class="formats-grid">
              <div 
                v-for="(format, index) in result.formats" 
                :key="format.format_id"
                class="format-card"
              >
                <div class="format-badge">{{ format.ext.toUpperCase() }}</div>
                
                <div class="format-header">
                  <span class="resolution">{{ format.resolution }}</span>
                </div>
                
                <div class="format-details">
                   <div class="detail-row"><span>编码:</span> <span class="val">{{ format.acodec || format.ext }}</span></div>
                   <div class="detail-row"><span>大小:</span> <span class="val">{{ formatFilesize(format) }}</span></div>
                </div>
                
                <button 
                  @click="downloadFormat(format.format_id)"
                  :disabled="downloadingId === format.format_id"
                  class="btn btn-primary w-full"
                  :class="{ 'btn-loading': downloadingId === format.format_id }"
                >
                   <span v-if="downloadingId === format.format_id" class="spinner-sm"></span>
                   <span v-else>下载此格式</span>
                </button>
              </div>
            </div>
          </div>
        </ParserResultCard>

        <!-- 解析结果展示 - 歌单 -->
        <div v-if="result && result.is_playlist" class="playlist-result">
          <div class="playlist-header">
            <div class="header-left">
              <h2>{{ result.title || '网易云歌单' }}</h2>
              <div class="playlist-count">{{ result.songs?.length || 0 }} 首歌曲</div>
            </div>
            <div class="header-actions">
              <label class="checkbox-wrapper">
                <input type="checkbox" :checked="isAllSelected" @change="toggleSelectAll" :disabled="downloadingId === 'batch'">
                <span>全选</span>
              </label>
              
              <button 
                class="btn btn-primary" 
                :disabled="!selectedSongs.size || downloadingId === 'batch'"
                @click="openBatchConfirm"
              >
                <div v-if="downloadingId === 'batch'" class="spinner-sm"></div>
                <span v-else>下载选中 ({{ selectedSongs.size }})</span>
              </button>
            </div>
          </div>

          <div class="songs-list">
            <div 
              v-for="(song, index) in result.songs" 
              :key="song.id"
              class="song-item"
            >
              <div class="song-header" @click="toggleSongFormats(index)">
                <div class="song-info">
                  <div class="checkbox-container" @click.stop>
                    <input 
                      type="checkbox" 
                      :checked="selectedSongs.has(song.id)"
                      @change="toggleSongSelection(song.id)"
                    >
                  </div>
                  <span class="song-index">#{{ index + 1 }}</span>
                  <div class="song-details">
                    <div class="song-title">{{ song.title }}</div>
                    <div class="song-artist" v-if="song.artist">{{ song.artist }}</div>
                  </div>
                </div>
                <div class="song-actions">
                  <span class="song-duration" v-if="song.duration">{{ formatDuration(song.duration) }}</span>
                  <svg 
                    xmlns="http://www.w3.org/2000/svg" 
                    width="20" height="20" 
                    viewBox="0 0 24 24" 
                    fill="none" 
                    stroke="currentColor" 
                    stroke-width="2"
                    class="expand-icon"
                    :class="{ 'expanded': expandedSongs.has(index) }"
                  >
                    <polyline points="6 9 12 15 18 9"></polyline>
                  </svg>
                </div>
              </div>

              <!-- 格式列表 -->
              <div v-if="expandedSongs.has(index)" class="song-formats">
                <div class="formats-grid">
                  <div 
                    v-for="format in song.formats" 
                    :key="format.format_id"
                    class="format-card"
                  >
                    <div class="format-badge">{{ format.ext.toUpperCase() }}</div>
                    <div class="format-header">
                      <span class="resolution">{{ format.resolution }}</span>
                    </div>
                    <div class="format-details">
                      <div class="detail-row"><span>编码:</span> <span class="val">{{ format.acodec || format.ext }}</span></div>
                      <div class="detail-row"><span>大小:</span> <span class="val">{{ formatFilesize(format) }}</span></div>
                    </div>
                    <button 
                      @click="downloadSongFormat(song, format.format_id)"
                      :disabled="downloadingId === `${song.id}_${format.format_id}`"
                      class="btn btn-primary w-full"
                      :class="{ 'btn-loading': downloadingId === `${song.id}_${format.format_id}` }"
                    >
                      <span v-if="downloadingId === `${song.id}_${format.format_id}`" class="spinner-sm"></span>
                      <span v-else>下载此格式</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

      <!-- 批量下载确认弹窗 -->
      <Modal
        v-model:show="showBatchConfirm"
        title="确认批量下载"
        type="info"
        width="400px"
        :show-confirm="false"
      >
        <p>您已选中 {{ selectedSongs.size }} 首歌曲，确定要全部添加下载任务吗？</p>
        <div class="text-sm text-tertiary mt-2">
          注：系统将自动控制下载速度，避免触发频率限制。
        </div>
        
        <template #footer>
          <button class="btn btn-secondary" @click="showBatchConfirm = false">取消</button>
          <button class="btn btn-primary" @click="confirmBatchDownload">确认下载</button>
        </template>
      </Modal>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import ParserResultCard from '@/components/business/ParserResultCard.vue'
import Modal from '@/components/common/Modal.vue'
import { neteaseApi } from '@/api/netease'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const toast = useToast()

// 状态
const mode = ref('search') // 'search' | 'url'
const url = ref('')
const keyword = ref('')
const loading = ref(false)
const result = ref(null)
const error = ref(null)
const searching = ref(false)
const downloadingId = ref(null)
const expandedSongs = ref(new Set())
const selectedSongs = ref(new Set())
const searchResults = ref([])
const searchTotal = ref(0)
const stopBatchDownload = ref(false)
const showBatchConfirm = ref(false)

const isAllSelected = computed(() => {
  return result.value?.songs?.length > 0 && selectedSongs.value.size === result.value.songs.length
})

// 初始化
onMounted(async () => {
    const savedUrl = localStorage.getItem('netease_last_url')
    if (savedUrl) url.value = savedUrl
})

async function handlePaste() {
  try {
    const text = await navigator.clipboard.readText()
    url.value = text
  } catch (e) {
    toast.error('无法读取剪贴板，请手动粘贴链接')
  }
}

async function handlePasteKeyword() {
  try {
    const text = await navigator.clipboard.readText()
    keyword.value = text
  } catch (e) {
    toast.error('无法读取剪贴板，请手动粘贴关键词')
  }
}

async function clearSearch() {
  keyword.value = ''
  searchResults.value = []
  searchTotal.value = 0
}

async function clearInput() {
  url.value = ''
  result.value = null
  error.value = null
  expandedSongs.value = new Set()
}

function goToCookieSettings() {
  router.push({ path: '/settings', query: { tab: 'cookie' } })
}


async function handleParse() {
    if (!url.value) return
    loading.value = true
    error.value = null
    result.value = null
    expandedSongs.value = new Set()
    selectedSongs.value = new Set()
    localStorage.setItem('netease_last_url', url.value)
    
    try {
        const res = await neteaseApi.parse(url.value)
        result.value = res
    } catch (e) {
        error.value = e.response?.data?.detail || e.message || '解析请求失败'
        toast.error('解析失败: ' + error.value)
    } finally {
        loading.value = false
    }
}

async function handleSearch() {
    if (!keyword.value) return
    loading.value = true
    error.value = null
    result.value = null
    expandedSongs.value = new Set()
    searchResults.value = []
    searchTotal.value = 0

    try {
        const res = await neteaseApi.search({
            keyword: keyword.value,
            limit: 50,
            offset: 0
        })
        searchResults.value = res.songs || []
        searchTotal.value = res.total || searchResults.value.length
        if (!searchResults.value.length) {
            toast.info('未找到匹配的歌曲，请尝试修改关键词')
        }
    } catch (e) {
        const msg = e.response?.data?.detail || e.message || '搜索请求失败'
        error.value = msg
        toast.error('搜索失败: ' + msg)
    } finally {
        loading.value = false
    }
}

function toggleSongFormats(index) {
    if (expandedSongs.value.has(index)) {
        expandedSongs.value.delete(index)
    } else {
        expandedSongs.value.add(index)
    }
    expandedSongs.value = new Set(expandedSongs.value)
}

function toggleSongSelection(songId) {
  if (selectedSongs.value.has(songId)) {
    selectedSongs.value.delete(songId)
  } else {
    selectedSongs.value.add(songId)
  }
  selectedSongs.value = new Set(selectedSongs.value)
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedSongs.value.clear()
  } else {
    result.value.songs.forEach(song => selectedSongs.value.add(song.id))
  }
}

function openBatchConfirm() {
  if (selectedSongs.value.size === 0) return
  showBatchConfirm.value = true
}

async function confirmBatchDownload() {
  showBatchConfirm.value = false
  downloadingId.value = 'batch'
  
  try {
    // 构造批量下载请求数据
    const songsToDownload = result.value.songs
      .filter(s => selectedSongs.value.has(s.id))
      .map(song => ({
        url: song.webpage_url,
        format_id: song.formats?.[0]?.format_id || 'best',
        song_id: song.id,
        title: song.title
      }))
    
    // 一次性提交到后端
    const res = await neteaseApi.batchDownload({ songs: songsToDownload })
    
    // 清空选中状态
    selectedSongs.value.clear()
    
    toast.success(res.message || `已添加 ${res.success_count} 个下载任务`)
    
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '批量下载失败'
    toast.error('批量下载失败: ' + msg)
  } finally {
    downloadingId.value = null
    stopBatchDownload.value = false
  }
}

async function downloadFormat(formatId) {
    if (downloadingId.value) return
    downloadingId.value = formatId
    try {
        await neteaseApi.download({
            url: url.value,
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

async function downloadSongFormat(song, formatId) {
    const downloadKey = `${song.id}_${formatId}`
    if (downloadingId.value) return
    downloadingId.value = downloadKey
    try {
        await neteaseApi.download({
            url: song.webpage_url,
            format_id: formatId,
            song_id: song.id
        })
        toast.success('下载任务已添加，可前往「下载任务」页面查看')
    } catch (e) {
        const msg = e.response?.data?.detail || e.message || '添加任务失败'
        toast.error('添加下载任务失败: ' + msg)
    } finally {
        downloadingId.value = null
    }
}

function openSongInNetease(song) {
    if (!song || !song.id) return
    const link = `https://music.163.com/#/song?id=${song.id}`
    window.open(link, '_blank')
}

function useSongAsUrl(song) {
    if (!song || !song.id) return
    url.value = `https://music.163.com/#/song?id=${song.id}`
    mode.value = 'url'
    // 自动触发解析
    handleParse()
}

function formatDuration(seconds) {
    if (!seconds) return '未知'
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
}

function formatFilesize(format) {
    const bytes = format.filesize
    if (!bytes && format.filesize_str) return format.filesize_str
    if (!bytes) return '未知'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
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

.btn-primary {
  margin-top: var(--spacing-lg);
}

[data-theme="dark"] .btn-primary:not(.btn-xs) {
  background: linear-gradient(135deg, #af3024 0%, #c47d0e 100%);
  border: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.action-section {
  margin-bottom: 30px;
}

[data-theme="dark"] .btn-primary:not(.btn-xs):hover:not(:disabled) {
  background: linear-gradient(135deg, #bd3427 0%, #d68910 100%);
}

.btn-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
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
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--spacing-lg);
}

.format-card {
  position: relative;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-lg);
  display: flex;
  flex-direction: column;
  transition: all var(--transition-fast);
}

.format-card:hover {
  transform: translateY(-4px);
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
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
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--color-text-primary);
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

/* 歌单列表 */
.playlist-result {
  margin-top: var(--spacing-xl);
}

.search-results {
  margin-top: var(--spacing-xl);
}
.search-results-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--spacing-md);
}
.search-results-header h3 {
  margin: 0;
}
.result-count {
  font-size: 0.85rem;
  color: var(--color-text-tertiary);
}

.playlist-header {
  margin-bottom: var(--spacing-xl);
  padding-bottom: var(--spacing-lg);
  border-bottom: 2px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left h2 {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-xs);
}


.header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* 响应式适配 */
@media (max-width: 768px) {
  .content-view {
    padding: var(--spacing-sm);
  }

  .content-container {
    padding: var(--spacing-lg) var(--spacing-md);
    border-radius: var(--radius-lg);
  }

  h1 {
    font-size: 1.75rem;
  }

  .icon-glow.theme-gradient {
    width: 48px;
    height: 48px;
  }

  [data-theme="dark"] .btn-danger:not(.btn-clear-action) {
    background: rgba(239, 68, 68, 0.15) !important;
    color: #ff6b6b !important;
    border: 1px solid rgba(239, 68, 68, 0.2) !important;
  }

  .icon-glow svg {
    width: 24px;
    height: 24px;
  }

  /* 移动端 Tab 变宽以便点击 */
  .mode-toggle {
    width: 100%;
    display: flex;
    padding: 4px;
    background: var(--color-bg-tertiary); /* 更明显的背景 */
  }

  .tab-btn {
    flex: 1;
    text-align: center;
    padding: 10px 0;
  }

  /* 搜索/粘贴区域调整 */
  .form-group label {
    display: block;
    margin-bottom: 8px;
  }

  .input-tools-top {
    margin-bottom: 8px;
    gap: 12px; /* 增加间距 */
  }

  /* 增大触摸热区 */
  .input-tools-top .btn {
    padding: 8px 14px;
  }


  .formats-grid {
    grid-template-columns: 1fr; /* 移动端强制单列 */
    gap: var(--spacing-md);
  }

  /* 歌单头部调整 */
  .playlist-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-md);
  }

  .header-actions {
    width: 100%;
    justify-content: space-between;
  }

  /* 歌曲列表项调整 */
  .song-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-sm);
    padding: var(--spacing-md);
  }

  .song-info {
    width: 100%;
  }

  .song-actions {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: var(--spacing-xs);
    border-top: 1px solid var(--color-bg-secondary);
    padding-top: var(--spacing-sm);
  }
  
  .song-duration {
    font-size: var(--font-size-sm);
  }

  /* 按钮尺寸优化 */
  .btn-lg {
    padding: 0.75rem 1.5rem;
    font-size: 1rem;
  }
}

.checkbox-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  font-weight: 600;
  color: var(--color-text-primary);
}

.checkbox-container {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
}

input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
}

.playlist-count {
  font-size: 0.9rem;
  color: var(--color-text-tertiary);
}

.songs-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.song-item {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: all var(--transition-fast);
}

.song-item:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-sm);
}

.song-header {
  padding: var(--spacing-lg);
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.song-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  flex: 1;
}

.song-index {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text-tertiary);
  min-width: 40px;
}

.song-details {
  flex: 1;
}

.song-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 4px;
}

.song-artist {
  font-size: 0.875rem;
  color: var(--color-text-tertiary);
}

.song-actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.song-duration {
  font-size: 0.875rem;
  color: var(--color-text-tertiary);
}

.expand-icon {
  transition: transform var(--transition-fast);
  color: var(--color-text-tertiary);
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.song-formats {
  padding: var(--spacing-lg);
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-tertiary);
}

.song-formats .formats-grid {
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
}

/* 授权提示 */
.license-alert {
  text-align: center;
  background: var(--color-bg-card);
  border: 2px dashed var(--color-error);
  border-radius: var(--radius-xl);
  padding: 3rem;
}

.license-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto var(--spacing-lg);
  color: var(--color-error);
  opacity: 0.8;
  display: flex;
  align-items: center;
  justify-content: center;
}

.license-actions {
  margin-top: var(--spacing-xl);
  display: flex;
  justify-content: center;
  gap: var(--spacing-lg);
}

/* 动画 */
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

.btn-loading {
  opacity: 0.7;
  cursor: not-allowed;
}

.alert {
  padding: var(--spacing-lg);
  border-radius: var(--radius-lg);
  margin-bottom: var(--spacing-lg);
  display: flex;
  gap: var(--spacing-md);
  align-items: flex-start;
}

.alert-error {
  background: var(--color-error-light);
  border: 1px solid var(--color-error);
  color: var(--color-error);
}

.alert-content h3 {
  margin: 0 0 var(--spacing-xs) 0;
  font-size: 1rem;
  font-weight: 600;
}

.alert-content p {
  margin: 0;
  font-size: 0.9rem;
}
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
    margin-bottom: 20px;
  }

  h1 {
    font-size: 1.5rem;
  }

  .subtitle {
    font-size: 0.9rem;
  }

  .tab-btn {
    padding: 6px 12px;
    font-size: 0.85rem;
  }

  .song-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .song-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .formats-grid {
    grid-template-columns: 1fr;
  }

  .playlist-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 15px;
  }

  .header-actions {
    width: 100%;
    justify-content: space-between;
  }

  /* 扁平化处理：移除内部卡片边框和背景 */
  .card, .search-card {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin-bottom: var(--spacing-lg) !important;
  }
}
</style>

