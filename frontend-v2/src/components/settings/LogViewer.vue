<template>
  <div class="log-viewer">
    <div class="log-container">
      <!-- 顶部工具栏 -->
      <div class="log-toolbar">
        <div class="toolbar-left">
          <div class="select-wrapper">
            <Icon name="file-text" :size="16" class="select-icon" />
            <select 
              v-model="selectedLog" 
              @change="selectLogFile(selectedLog)"
              class="log-select"
            >
              <option v-for="log in logFiles" :key="log.name" :value="log.name">
                {{ log.name }} ({{ formatSize(log.size) }})
              </option>
              <option v-if="logFiles.length === 0" value="">暂无日志文件</option>
            </select>

          </div>
          
          <!-- 日志等级选择 -->
          <div class="select-wrapper" style="width: 180px;">
            <Icon name="activity" :size="16" class="select-icon" />
            <select 
              v-model="currentLogLevel" 
              @change="changeLogLevel"
              class="log-select"
              title="临时设置系统日志等级（重启后失效）"
            >
              <option value="INFO">等级: INFO</option>
              <option value="DEBUG">等级: DEBUG</option>
              <option value="WARNING">等级: WARN</option>
              <option value="ERROR">等级: ERROR</option>
            </select>
          </div>
          

        </div>

        <div class="toolbar-right">
          <button @click="copyCurrentLogPage" :disabled="!logContent" class="btn btn-outline btn-sm">
            <Icon name="copy" :size="14" />
            <span>复制当前页</span>
          </button>
          <button @click="exportLogs" class="btn btn-outline btn-sm">
            <Icon name="download" :size="14" />
            <span>导出</span>
          </button>
          <button @click="clearAllLogs" class="btn btn-outline btn-sm text-danger">
            <Icon name="trash" :size="14" />
            <span>清空全部</span>
          </button>
        </div>
      </div>

      <!-- 日志内容区域 -->
      <div class="log-content-area">
        <div class="log-content" v-if="logContent">
          <div class="log-header">
            <div class="header-left">
              <span class="log-stats">{{ totalLines }} 行 (最后 {{ returnedLines }} 行)</span>
              <span class="log-order-hint">显示顺序：{{ orderHint }}</span>
            </div>
            <div class="header-right">
              <button
                @click="scrollToTop"
                class="btn btn-icon jump-top-btn"
                :title="jumpTopTitle"
                :aria-label="jumpTopTitle"
              >
                <Icon name="chevron-up" :size="16" />
              </button>
              <button
                @click="scrollToBottomAndFollow"
                class="btn btn-icon jump-bottom-btn"
                :title="jumpBottomTitle"
                :aria-label="jumpBottomTitle"
              >
                <Icon :name="followLatestIcon" :size="16" />
              </button>
              <button 
                @click="clearCurrentLog" 
                :disabled="!selectedLog" 
                class="btn btn-icon text-danger" 
                title="清空当前日志"
              >
                <Icon name="trash" :size="16" />
              </button>
            </div>
          </div>
          <div class="log-lines" ref="logLinesRef" @scroll="handleLogScroll">
            <div 
              v-for="(line, index) in logLines" 
              :key="index"
              :class="['log-line', getLogLevel(line)]"
            >
              {{ line }}
            </div>
          </div>
        </div>

        <div v-else class="log-placeholder">
          <Icon name="logs" :size="64" />
          <p>请选择一个日志文件查看</p>
        </div>
      </div>
    </div>

    <!-- 确认弹窗 -->
    <Modal v-model:show="showConfirmModal" :title="confirmTitle" type="warning">
      <div v-html="confirmMessage"></div>
      <template #footer>
        <button class="btn btn-secondary" @click="handleConfirmCancel">取消</button>
        <button class="btn btn-primary" @click="handleConfirmOk">确定</button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { logsApi } from '@/api/settings'
import { useToast } from '@/composables/useToast'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'

const toast = useToast()
const logFiles = ref([])
const selectedLog = ref('')
const logContent = ref('')
const totalLines = ref(0)
const returnedLines = ref(0)

const logLinesRef = ref(null)
const currentLogLevel = ref('INFO') // 默认为 INFO
const autoFollowBottom = ref(true)
const hasNewLogs = ref(false)
const newestFirst = ref(true)

const orderHint = computed(() => (newestFirst.value ? '最新在上' : '最新在下'))
const jumpTopTitle = computed(() => (
  newestFirst.value ? '跳到最新（顶部）' : '跳到最旧（顶部）'
))
const jumpBottomTitle = computed(() => (
  newestFirst.value ? '跳到最旧（底部）' : '跳到最新（底部）'
))
const followLatestIcon = computed(() => 'chevron-down')

// 确认弹窗状态
const showConfirmModal = ref(false)
const confirmTitle = ref('确认')
const confirmMessage = ref('')
let confirmResolve = null

// 自定义确认函数
function customConfirm(title, message) {
  return new Promise((resolve) => {
    confirmTitle.value = title
    confirmMessage.value = message
    showConfirmModal.value = true
    confirmResolve = resolve
  })
}

function handleConfirmOk() {
  showConfirmModal.value = false
  if (confirmResolve) {
    confirmResolve(true)
    confirmResolve = null
  }
}

function handleConfirmCancel() {
  showConfirmModal.value = false
  if (confirmResolve) {
    confirmResolve(false)
    confirmResolve = null
  }
}

const logLines = computed(() => {
  if (!logContent.value) return []
  const lines = logContent.value.split('\n').filter(line => line.trim())
  return newestFirst.value ? lines.reverse() : lines
})

function formatSize(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function getLogLevel(line) {
  if (line.includes('ERROR') || line.includes('CRITICAL')) return 'error'
  if (line.includes('WARNING') || line.includes('WARN')) return 'warning'
  if (line.includes('INFO')) return 'info'
  if (line.includes('DEBUG')) return 'debug'
  return ''
}

async function loadLogFiles() {
  try {
    const data = await logsApi.getLogFiles()
    if (data.success) {
      logFiles.value = data.files
      
      // 默认选择 easy-vdl.log，如果不存在则选择第一个
      if (logFiles.value.length > 0 && !selectedLog.value) {
        const defaultLog = logFiles.value.find(f => f.name === 'easy-vdl.log')
        if (defaultLog) {
          selectLogFile(defaultLog.name)
        } else {
          selectLogFile(logFiles.value[0].name)
        }
      }
    }
  } catch (err) {
    console.error('Failed to load log files:', err)
    toast.error('加载日志文件列表失败')
  }
}

async function loadCurrentLogLevel() {
  try {
    const data = await logsApi.getLogLevel()
    const level = String(data?.level || '').toUpperCase()
    if (['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].includes(level)) {
      currentLogLevel.value = level
    }
  } catch (err) {
    console.warn('Failed to load current log level:', err)
  }
}

function selectLogFile(logName) {
  selectedLog.value = logName
  autoFollowBottom.value = true
  hasNewLogs.value = false
  loadLog()
}

async function loadLog() {
  if (!selectedLog.value) {
    logContent.value = ''
    return
  }

  try {
    const data = await logsApi.getLogContent(selectedLog.value, 500)
    if (data.success) {
      logContent.value = data.content
      totalLines.value = data.total_lines
      returnedLines.value = data.returned_lines
      
      // 智能跟随：仅在“跟随底部”开启时自动跳底，避免每次刷新都突兀跳动
      await nextTick()
      if (logLinesRef.value) {
        if (autoFollowBottom.value) {
          logLinesRef.value.scrollTop = newestFirst.value ? 0 : logLinesRef.value.scrollHeight
          hasNewLogs.value = false
        } else {
          hasNewLogs.value = true
        }
      }
    }
  } catch (err) {
    console.error('Failed to load log:', err)
    toast.error('加载日志内容失败')
  }
}

function isNearBottom(threshold = 24) {
  if (!logLinesRef.value) return true
  const el = logLinesRef.value
  if (newestFirst.value) {
    return el.scrollTop <= threshold
  }
  return (el.scrollHeight - el.scrollTop - el.clientHeight) <= threshold
}

function handleLogScroll() {
  const nearBottom = isNearBottom()
  autoFollowBottom.value = nearBottom
  if (nearBottom) {
    hasNewLogs.value = false
  }
}

function scrollToBottomAndFollow() {
  autoFollowBottom.value = !newestFirst.value
  if (autoFollowBottom.value) {
    hasNewLogs.value = false
  }
  if (logLinesRef.value) {
    logLinesRef.value.scrollTop = logLinesRef.value.scrollHeight
  }
}

function scrollToTop() {
  autoFollowBottom.value = newestFirst.value
  if (autoFollowBottom.value) {
    hasNewLogs.value = false
  }
  if (logLinesRef.value) {
    logLinesRef.value.scrollTop = 0
  }
}

async function refreshLogs() {
  await loadLogFiles()
  if (selectedLog.value) {
    await loadLog()
  }
}

async function clearCurrentLog() {
  if (!selectedLog.value) return
  const confirmed = await customConfirm('确认清空', `确定要清空日志文件 "${selectedLog.value}" 吗?`)
  if (!confirmed) return

  try {
    const data = await logsApi.clearLog(selectedLog.value)
    if (data.success) {
      toast.success('日志已清空')
      await loadLog()
    }
  } catch (err) {
    console.error('Failed to clear log:', err)
    toast.error('清空日志失败')
  }
}

async function exportLogs() {
  try {
    toast.info('正在打包日志文件，请稍候...')
    // API 返回的是 blob 数据
    const blob = await logsApi.exportLogs()
    
    // 创建下载链接
    const url = window.URL.createObjectURL(new Blob([blob]))
    const link = document.createElement('a')
    link.href = url
    
    // 生成带时间戳的文件名
    const date = new Date().toISOString().slice(0, 10)
    link.setAttribute('download', `easy-vdl-logs-${date}.zip`)
    
    document.body.appendChild(link)
    link.click()
    
    // 清理
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    
    toast.success('日志导出成功')
  } catch (err) {
    console.error('Failed to export logs:', err)
    toast.error('导出日志失败')
  }
}

async function copyCurrentLogPage() {
  if (!logContent.value) {
    toast.warning('当前没有可复制的日志内容')
    return
  }

  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(logContent.value)
      toast.success('当前页日志已复制到剪贴板')
      return
    }

    const textArea = document.createElement('textarea')
    textArea.value = logContent.value
    textArea.style.position = 'fixed'
    textArea.style.left = '-999999px'
    textArea.style.top = '-999999px'
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textArea)

    if (!ok) throw new Error('execCommand copy failed')
    toast.success('当前页日志已复制到剪贴板')
  } catch (err) {
    console.error('Failed to copy logs:', err)
    toast.error('复制失败，请手动选择日志内容复制')
  }
}

async function clearAllLogs() {
  const confirmed = await customConfirm('确认清空', '确定要清空所有日志文件吗? 此操作不可撤销!')
  if (!confirmed) return

  try {
    const data = await logsApi.clearAllLogs()
    if (data.success) {
      toast.success('所有日志已清空')
      selectedLog.value = ''
      logContent.value = ''
      await loadLogFiles()
    }
  } catch (err) {
    console.error('Failed to clear all logs:', err)
    toast.error('清空所有日志失败')
  }
}

async function changeLogLevel() {
  const previousLevel = currentLogLevel.value
  try {
    const level = currentLogLevel.value
    await logsApi.setLogLevel(level)
    toast.success(`日志等级已设置为 ${level}`)
    // 自动刷新一下当前日志，以便看到可能产生的新日志
    if (selectedLog.value) {
      setTimeout(loadLog, 500)
    }
  } catch (err) {
    console.error('Failed to set log level:', err)
    toast.error('设置日志等级失败')
    // 回退到变更前值，避免误导性显示为 INFO
    currentLogLevel.value = previousLevel
  }
}

onMounted(() => {
  loadCurrentLogLevel()
  loadLogFiles()
})
</script>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  width: 100%;
}

.log-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: calc(100vh - var(--header-height) - 100px);
  min-height: 550px;
}

/* 顶部工具栏 */
.log-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  padding: 10px 16px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  flex-shrink: 0;
  box-shadow: var(--shadow-sm);
}

@media (max-width: 1100px) {
  .log-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .toolbar-left, .toolbar-right {
    width: 100%;
  }
  .select-wrapper {
    flex: 1;
    width: auto !important;
  }
  .toolbar-right {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  }
}

.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.select-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  width: 260px;
}

.select-icon {
  position: absolute;
  left: 12px;
  color: var(--color-text-tertiary);
  pointer-events: none;
  z-index: 1;
}

.log-select {
  width: 100%;
  padding: 8px 30px 8px 36px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  background-size: 14px;
  transition: all 0.2s;
}

.log-select:hover {
  border-color: var(--color-primary);
  background-color: var(--color-bg-hover);
}

.log-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* 日志内容区域 */
.log-content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.log-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #1a1a1a; /* 统一使用终端深色 */
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  min-height: 0;
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.2);
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: #252525;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.jump-bottom-btn {
  opacity: 0.9;
  color: #c7ced8;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.2);
  transition: opacity 0.2s ease, background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}

.jump-bottom-btn:hover {
  opacity: 1;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.14);
  border-color: rgba(255, 255, 255, 0.3);
}


.jump-top-btn {
  opacity: 0.9;
  color: #c7ced8;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.2);
  transition: opacity 0.2s ease, background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}

.jump-top-btn:hover {
  opacity: 1;
  color: #ffffff;
  background: rgba(255, 255, 255, 0.14);
  border-color: rgba(255, 255, 255, 0.3);
}


.log-stats {
  font-size: 12px;
  color: #888;
  font-family: inherit;
}

.log-order-hint {
  font-size: 12px;
  color: #9aa3ad;
}

.log-lines {
  flex: 1;
  overflow-y: auto;
  overflow-x: auto;
  padding: 16px;
  font-family: 'Fira Code', 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #d4d4d4;
  scroll-behavior: smooth;
}

/* 自定义滚动条 */
.log-lines::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
.log-lines::-webkit-scrollbar-track {
  background: #252525;
}
.log-lines::-webkit-scrollbar-thumb {
  background: #444;
  border-radius: 5px;
  border: 2px solid #252525;
}
.log-lines::-webkit-scrollbar-thumb:hover {
  background: #555;
}

.log-line {
  padding: 1px 0;
  word-break: break-all;
  white-space: pre-wrap;
}

.log-line.error { color: #f48771; }
.log-line.warning { color: #cca700; }
.log-line.info { color: #75beff; }
.log-line.debug { color: #b5cea8; }

.log-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  color: var(--color-text-tertiary);
  text-align: center;
}

.log-placeholder p {
  margin-top: 16px;
  font-size: 15px;
}

/* 按钮通用样式微调 */
.btn-sm {
  padding: 6px 12px;
  font-size: 12px;
}

.text-danger {
  color: #e74c3c !important;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .log-container {
    height: calc(100vh - 220px); /* 增加底部留白，避免过高 */
    min-height: 300px;
  }

  /* 移动端适配 */
  .log-toolbar {
    flex-direction: column;
    align-items: stretch;
    padding: 10px;
    gap: 8px;
    overflow: visible;
    flex-shrink: 0; /* 防止工具栏被压缩 */
  }

  .toolbar-left {
    width: 100%;
    justify-content: flex-start;
    min-width: 0; /* 允许子元素收缩 */
    gap: 8px;
  }

  .select-wrapper {
    flex: 1;
    width: auto;
    min-width: 100px; /* 稍微减小最小宽度 */
  }
  
  .toolbar-left .select-wrapper:last-child {
    flex: 0 0 130px;
    width: 130px !important;
    min-width: 130px;
  }

  .log-select {
    font-size: 13px;
    padding-left: 28px;
    padding-right: 24px; /* 减小右侧内边距 */
  }

  .toolbar-right {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    width: 100%;
    flex-shrink: 0;
  }

  .toolbar-right .btn {
    width: 100%;
    padding: 6px 8px;
    justify-content: center;
    min-width: 0;
  }

  .toolbar-right .btn span {
    display: inline;
  }

  .log-content-area {
    height: auto; /* 移除固定高度 */
    flex: 1; /* 撑满剩余高度 */
    min-height: 0; /* 允许 flex 子项收缩 */
  }
  
  .log-header {
    padding: 8px 10px;
    gap: 8px;
  }

  .header-left {
    flex: 1;
    min-width: 0;
  }

  .log-stats {
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .header-right {
    gap: 6px;
    flex-shrink: 0;
  }

  .header-right .btn.btn-icon {
    width: 34px;
    height: 34px;
    min-width: 34px;
    min-height: 34px;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .log-lines {
    font-size: 11px;
    padding: 12px;
  }
}
</style>
