<template>
  <div class="batch-download-tasks-page">
    <div class="page-header">
      <div class="header-left">
        <button class="btn btn-outline btn-back" @click="goBack">
          <Icon name="chevron-left" :size="16" />
          返回
        </button>
        <h1 class="page-title">订阅系统任务</h1>
      </div>
    </div>

    <SkeletonLoader 
      v-if="loading && tasks.length === 0"
      :loading="true"
      text="正在加载订阅任务..."
      type="list"
      :count="6"
      itemHeight="140px"
    />

    <template v-else>
      <div v-if="tasks.length === 0" class="empty-container">
        <Icon name="inbox" :size="48" class="empty-icon" />
        <p class="empty-text">暂无正在批量下载的任务</p>
        <p class="empty-hint">订阅系统的批量下载任务将显示在这里</p>
      </div>

      <div v-else class="tasks-container">
      <div 
        v-for="task in tasks" 
        :key="task.id" 
        class="batch-task-item"
      >
        <div class="task-header">
          <div class="task-info">
            <div class="avatar-wrapper">
              <img 
                :src="proxyImage(task.avatar_url)" 
                :alt="task.nickname"
                class="task-avatar"
                @error="handleImageError"
              />
            </div>
            <span class="platform-badge" :class="`badge-${task.platform}`">
              {{ getPlatformDisplayName(task.platform) }}
            </span>
            <div class="task-author">
              <span class="author-name">{{ task.nickname }}</span>
              <span class="task-status" :class="getStatusClass(task.batch_download_status)">
                {{ getStatusText(task.batch_download_status) }}
              </span>
            </div>
          </div>
          <button 
            v-if="['completed', 'partial_completed', 'error', 'cancelled'].includes(task.batch_download_status)"
            class="btn btn-sm btn-outline btn-clear-task"
            @click="removeTask(task.id)"
          >
            清除
          </button>
          <button 
            v-else
            class="btn btn-sm btn-outline text-danger"
            :disabled="task.batch_download_status === 'cancelling'"
            @click="cancelTask(task)"
          >
            <span v-if="task.batch_download_status === 'cancelling'">取消中...</span>
            <span v-else>取消</span>
          </button>
        </div>
        
        <div class="progress-section">
          <div class="progress-bar-container">
            <div 
              class="progress-bar-fill" 
              :class="getProgressClass(task.batch_download_status)"
              :style="{ width: `${task.progressPercent || 0}%` }"
            >
              <div class="progress-bar-shine"></div>
            </div>
          </div>
          <div class="progress-info">
            <span class="progress-percent">{{ task.progressPercent || 0 }}%</span>
            <span class="progress-stats">
              完成: {{ task.batch_download_completed || 0 }} / {{ task.batch_download_total || 0 }}
              <span v-if="(task.batch_download_failed || 0) > 0" class="failed-count">
                · 失败: {{ task.batch_download_failed || 0 }}
              </span>
            </span>
          </div>
        </div>
        </div>
      </div>
    </template>

    <!-- 取消任务确认模态框 -->
    <Modal 
      v-model:show="showCancelModal" 
      title="确认取消" 
      type="warning"
      width="420px"
    >
      <p>确定要取消"{{ currentCancelTask?.nickname || '' }}"的批量下载吗？</p>
      <template #footer>
        <button class="btn btn-outline" @click="showCancelModal = false">
          取消
        </button>
        <button class="btn btn-primary" @click="confirmCancel">
          确定
        </button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/common/Icon.vue'
import Modal from '@/components/common/Modal.vue'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import { subscriptionsApi, resolveAvatarUrl, handleImageError as sharedHandleImageError } from '@/api/subscriptions'
import { useBatchDownloadProgress } from '@/composables/useBatchDownloadProgress'
import { wsService } from '@/utils/websocket'

// 使用统一的进度管理 Composable
const {
  progressStates,
  updateTrigger,
  getProgressState,
  removeTask,
  restoreProgressStates,
  startWebSocketListener,
  startPolling,
  cleanup
} = useBatchDownloadProgress()

// 代理图片（委托共享工具）
function proxyImage(url) {
  return resolveAvatarUrl(url)
}

// 图片加载失败处理（委托共享工具）
function handleImageError(event) {
  sharedHandleImageError(event)
}

const router = useRouter()
const loading = ref(true)
const showCancelModal = ref(false)
const currentCancelTask = ref(null)

// 从进度状态生成任务列表
const tasks = computed(() => {
  // 访问 updateTrigger 以确保响应式更新
  updateTrigger.value
  
  return Array.from(progressStates.entries()).map(([id, state]) => ({
    id,
    nickname: state.nickname,
    platform: state.platform,
    avatar_url: state.avatar_url,
    batch_download_status: state.status,
    batch_download_completed: state.current,
    batch_download_total: state.total,
    batch_download_failed: state.failed,
    progressPercent: state.percent
  }))
})

// 加载正在批量下载的订阅
async function loadTasks() {
  try {
    loading.value = true
    const subscriptions = await subscriptionsApi.getList()
    
    // 使用 Composable 恢复进度状态
    await restoreProgressStates(subscriptions)
    
  } catch (error) {
    console.error('加载批量下载任务失败:', error)
  } finally {
    loading.value = false
  }
}

// 取消批量下载
function cancelTask(task) {
  if (task.batch_download_status === 'cancelling' || 
      task.batch_download_status === 'completed' || 
      task.batch_download_status === 'cancelled') {
    return
  }
  
  // 显示取消确认模态框
  currentCancelTask.value = task
  showCancelModal.value = true
}

// 确认取消
async function confirmCancel() {
  const task = currentCancelTask.value
  if (!task) {
    showCancelModal.value = false
    return
  }
  
  try {
    // 立即更新本地状态
    const state = getProgressState(task.id)
    if (state) {
      state.status = 'cancelling'
      state.message = '正在取消...'
      state.statusClass = 'text-warning'
    }
    
    // 关闭模态框
    showCancelModal.value = false
    
    await subscriptionsApi.cancelBatchDownload(task.id)
    // WebSocket 会推送更新，这里不需要手动更新 UI
  } catch (error) {
    console.error('取消批量下载失败:', error)
    // 恢复状态
    const state = getProgressState(task.id)
    if (state && state.status === 'cancelling') {
      state.status = 'downloading'
      state.message = '正在下载...'
      state.statusClass = 'text-primary'
    }
    alert(error.response?.data?.detail || error.message || '取消下载失败')
  } finally {
    currentCancelTask.value = null
  }
}

// 获取平台显示名称
function getPlatformDisplayName(platform) {
  const map = {
    'douyin': '抖音',
    'douyin_collection': '抖音合集',
    'xiaohongshu': '小红书',
    'tiktok': 'TikTok',
    'instagram': 'Instagram',
    'youtube': '油管',
    'bilibili': 'B站',
    'netease': '网易云音乐',
    'x': 'X',
    'others': '其他'
  }
  return map[platform] || platform || '未知'
}

// 获取状态文本
function getStatusText(status) {
  const map = {
    'downloading': '下载中',
    'cancelling': '取消中',
    'completed': '已完成',
    'cancelled': '已取消',
    'partial_completed': '部分失败',
    'error': '下载失败'
  }
  return map[status] || status || '未知'
}

// 获取状态样式类
function getStatusClass(status) {
  return {
    'status-downloading': status === 'downloading',
    'status-cancelling': status === 'cancelling',
    'status-completed': status === 'completed',
    'status-cancelled': status === 'cancelled',
    'status-partial-completed': status === 'partial_completed',
    'status-error': status === 'error'
  }
}

// 获取进度条样式类
function getProgressClass(status) {
  if (status === 'cancelling') return 'progress-cancelling'
  if (status === 'downloading') return 'progress-downloading'
  if (status === 'completed') return 'progress-completed'
  if (status === 'partial_completed') return 'progress-partial-completed'
  if (status === 'error') return 'progress-error'
  return 'progress-default'
}

// 返回上一页
function goBack() {
  router.back()
}

onMounted(async () => {
  await loadTasks()

  // 连接批量任务全局频道，确保独立打开页面也能收到实时进度
  wsService.connect('batch_tasks')
  // 启动 WebSocket 监听和轮询
  startWebSocketListener()
  startPolling()
})

onUnmounted(() => {
  // 清理资源
  cleanup()
  wsService.close('batch_tasks')
})
</script>

<style scoped>
.batch-download-tasks-page {
  min-height: 100vh;
  background: var(--color-bg-primary);
  padding: 20px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-back {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid var(--color-border);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-back:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.page-title {
  font-size: 24px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
}

.empty-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  text-align: center;
  background: var(--color-bg-card);
  border-radius: 16px;
  border: 1px dashed var(--color-border);
  margin: 40px auto;
  max-width: 600px;
}

[data-theme="dark"] .empty-container {
  background: rgba(255, 255, 255, 0.02);
  border-color: rgba(255, 255, 255, 0.1);
}

.loading-spinner {
  width: 48px;
  height: 48px;
  border: 4px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-icon {
  color: var(--color-primary);
  opacity: 0.3;
  margin-bottom: 24px;
}

.empty-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0 0 12px 0;
}

.empty-hint {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
  max-width: 280px;
  line-height: 1.6;
}

.tasks-container {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.batch-task-item {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 16px;
  transition: all 0.2s;
}

[data-theme="dark"] .batch-task-item {
  background: #1e1e1e;
  border-color: rgba(255, 255, 255, 0.08);
}

.batch-task-item:hover {
  border-color: var(--color-primary);
  box-shadow: 0 2px 8px rgba(230, 126, 34, 0.1);
}

.task-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.task-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.avatar-wrapper {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  overflow: hidden;
  background: var(--color-bg-secondary);
  border: 2px solid var(--color-border);
}

.task-avatar {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.platform-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: var(--font-weight-semibold);
  background: var(--color-primary-light);
  color: var(--color-primary);
  flex-shrink: 0;
  white-space: nowrap;
}

/* 平台标识颜色 - 抖音系列 */
.platform-badge.badge-douyin,
.platform-badge.badge-douyin_collection,
.platform-badge.badge-douyin_favorite {
  background: linear-gradient(135deg, #25F4EE 0%, #FE2C55 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 1px 1px 0px rgba(37, 244, 238, 0.5), -1px -1px 0px rgba(254, 44, 85, 0.5);
}

/* TikTok：以App图标的黑底为主，强调青色边缘 */
.platform-badge.badge-tiktok {
  background: #121212;
  border: 1.5px solid #25F4EE;
  color: #25F4EE;
  font-weight: 700;
}

.platform-badge.badge-youtube,
.platform-badge.badge-youtube_channel,
.platform-badge.badge-youtube_shorts,
.platform-badge.badge-youtube_playlist {
  background: linear-gradient(135deg, #FF0000 0%, #E60000 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.2);
}

.platform-badge.badge-bilibili,
.platform-badge.badge-bilibili_collection,
.platform-badge.badge-bilibili_favorite {
  background: linear-gradient(135deg, #00A1D6 0%, #0079A1 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.platform-badge.badge-netease {
  background: linear-gradient(135deg, #E62E4D 0%, #C91E3A 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.2);
}

.platform-badge.badge-instagram {
  background: linear-gradient(135deg, #f58529 0%, #dd2a7b 55%, #515bd4 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.2);
}

.platform-badge.badge-x {
  background: linear-gradient(135deg, #111111 0%, #2F2F2F 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.2);
}

.platform-badge.badge-xiaohongshu {
  background: linear-gradient(135deg, #FF5252 0%, #FF1744 100%);
  color: #ffffff;
  font-weight: 700;
  text-shadow: 0 1px 1px rgba(0,0,0,0.2);
}

.task-author {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.author-name {
  font-size: 15px;
  font-weight: 500;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
  flex-shrink: 0;
}

.status-downloading {
  background: rgba(230, 126, 34, 0.1);
  color: #e67e22;
}

.status-cancelling {
  background: rgba(255, 152, 0, 0.1);
  color: #ff9800;
}

.status-completed {
  background: rgba(76, 175, 80, 0.1);
  color: #4caf50;
}

.status-cancelled {
  background: rgba(158, 158, 158, 0.1);
  color: #9e9e9e;
}

.status-partial-completed {
  background: rgba(243, 156, 18, 0.1);
  color: #f39c12;
}

.status-error {
  background: rgba(244, 67, 54, 0.1);
  color: #f44336;
}

.progress-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-bar-container {
  height: 16px;
  background: var(--color-bg-secondary);
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  width: 100%;
  border: 1px solid var(--color-border);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.05);
}

[data-theme="dark"] .progress-bar-container {
  background: #2a2a2a;
  border-color: rgba(255, 255, 255, 0.1);
}

.progress-bar-fill {
  height: 100%;
  transition: width 0.3s ease;
  border-radius: 8px;
  width: 0;
  position: relative;
  overflow: hidden;
}

.progress-bar-shine {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.3) 50%,
    transparent 100%
  );
  animation: progress-shine 2s infinite;
}

@keyframes progress-shine {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.progress-downloading {
  background: linear-gradient(90deg, var(--color-primary) 0%, #f39c12 100%);
  box-shadow: 0 0 8px rgba(230, 126, 34, 0.4);
}

.progress-downloading::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image: linear-gradient(
    45deg,
    rgba(255, 255, 255, 0.25) 25%,
    transparent 25%,
    transparent 50%,
    rgba(255, 255, 255, 0.25) 50%,
    rgba(255, 255, 255, 0.25) 75%,
    transparent 75%,
    transparent
  );
  background-size: 1rem 1rem;
  animation: progress-bar-stripes 1s linear infinite;
  opacity: 0.6;
}

.progress-cancelling {
  background: linear-gradient(90deg, #ff9800 0%, #ff6f00 100%);
  box-shadow: 0 0 8px rgba(255, 152, 0, 0.4);
}

.progress-completed {
  background: linear-gradient(90deg, #4caf50 0%, #66bb6a 100%);
  box-shadow: 0 0 8px rgba(76, 175, 80, 0.4);
}

.progress-partial-completed {
  background: linear-gradient(90deg, #f39c12 0%, #f1c40f 100%);
  box-shadow: 0 0 8px rgba(243, 156, 18, 0.4);
}

.progress-error {
  background: linear-gradient(90deg, #e74c3c 0%, #c0392b 100%);
  box-shadow: 0 0 8px rgba(231, 76, 60, 0.4);
}

.progress-default {
  background: #9e9e9e;
}

.btn-clear-task {
  border-color: var(--color-border);
  color: var(--color-text-secondary);
}

.btn-clear-task:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: rgba(230, 126, 34, 0.05);
}

.progress-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.progress-percent {
  font-weight: 600;
  color: var(--color-primary);
}

.progress-stats {
  color: var(--color-text-secondary);
}

.failed-count {
  color: #f44336;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .batch-download-tasks-page {
    padding: 12px;
  }
  
  .page-header {
    margin-bottom: 16px;
  }
  
  .page-title {
    font-size: 20px;
  }
  
  .btn-back {
    padding: 6px 12px;
    font-size: 14px;
  }
  
  .tasks-container {
    grid-template-columns: 1fr;
  }
  
  .batch-task-item {
    padding: 12px;
  }
  
  .task-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 12px;
  }
  
  .task-info {
    width: 100%;
  }
  
  .avatar-wrapper {
    width: 40px;
    height: 40px;
  }
  
  .task-header .btn {
    width: 100%;
    justify-content: center;
  }
  
  .progress-info {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    font-size: 12px;
  }
}

@keyframes progress-bar-stripes {
  from { background-position: 1rem 0; }
  to { background-position: 0 0; }
}
</style>
