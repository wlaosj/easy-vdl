/**
 * 批量下载进度管理 Composable
 * 统一管理订阅卡片和批量任务页面的进度显示逻辑
 */
import { ref, reactive } from 'vue'
import { wsService } from '@/utils/websocket'
import { subscriptionsApi } from '@/api/subscriptions'

// 使用外部变量确保单例模式，跨组件/页面共享状态
const progressStates = reactive(new Map())
const updateTrigger = ref(0)
let refreshInterval = null
// 支持多个调用者注册/注销 ws 监听器（引用计数模式）
let wsListenerCount = 0
let wsUnregister = null

export function useBatchDownloadProgress() {
    /**
     * 初始化进度状态
     * @param {string} subscriptionId - 订阅ID
     * @param {object} initialData - 初始数据
     * @returns {object} 进度状态对象
     */
    function initProgressState(subscriptionId, initialData = {}) {
        if (!progressStates.has(subscriptionId)) {
            const state = {
                visible: true,
                message: '正在下载...',
                current: initialData.completed || 0,
                total: initialData.total || 0,
                failed: initialData.failed || 0,
                percent: 0,
                status: initialData.status || 'downloading',
                statusClass: 'text-primary',
                type: 'batch_download_progress',
                // 额外信息（用于订阅卡片）
                nickname: initialData.nickname || '',
                platform: initialData.platform || '',
                avatar_url: initialData.avatar_url || ''
            }
            progressStates.set(subscriptionId, state)
            updateTrigger.value++ // 触发更新
        }
        updateProgressPercent(subscriptionId)
        return progressStates.get(subscriptionId)
    }

    /**
     * 更新进度百分比
     * @param {string} subscriptionId - 订阅ID
     */
    function updateProgressPercent(subscriptionId) {
        const state = progressStates.get(subscriptionId)
        if (state && state.total > 0) {
            state.percent = Math.round((state.current / state.total) * 100)
        } else if (state) {
            state.percent = 0
        }
    }

    /**
     * 处理 WebSocket 进度更新
     * @param {object} data - WebSocket 消息数据
     */
    function handleProgressUpdate(data) {
        const subscriptionId = data.subscription_id
        if (!subscriptionId) {
            console.warn('批量下载进度更新缺少 subscription_id:', data)
            return
        }

        let state = progressStates.get(subscriptionId)

        // 如果状态不存在且是活跃状态，创建新状态
        if (!state && (data.status === 'downloading' || data.status === 'cancelling')) {
            // 尝试从消息中获取额外信息
            const extraData = {}
            if (data.subscription && typeof data.subscription === 'object') {
                extraData.nickname = data.subscription.nickname || data.subscription.name
                extraData.platform = data.subscription.platform
                extraData.avatar_url = data.subscription.avatar_url
            }

            state = initProgressState(subscriptionId, {
                ...extraData,
                completed: data.completed,
                total: data.total,
                failed: data.failed,
                status: data.status
            })
        }

        if (!state) return

        // 更新状态数据
        if (data.status !== undefined) state.status = data.status
        if (data.completed !== undefined) state.current = data.completed
        if (data.total !== undefined) state.total = data.total
        if (data.failed !== undefined) state.failed = data.failed

        // 如果订阅信息为空且新消息中包含订阅信息，则更新（用于解决添加任务后头像不显示的问题）
        if (data.subscription && typeof data.subscription === 'object') {
            if (!state.nickname && data.subscription.nickname) {
                state.nickname = data.subscription.nickname || data.subscription.name
            }
            if (!state.platform && data.subscription.platform) {
                state.platform = data.subscription.platform
            }
            if (!state.avatar_url && data.subscription.avatar_url) {
                state.avatar_url = data.subscription.avatar_url
            }
        }

        updateProgressPercent(subscriptionId)

        // 更新消息和样式
        if (data.status === 'downloading') {
            state.message = '正在下载...'
            state.statusClass = 'text-primary'
            state.visible = true
        } else if (data.status === 'cancelling') {
            state.message = '正在取消...'
            state.statusClass = 'text-warning'
            state.visible = true
        } else if (data.status === 'completed') {
            state.message = '下载完成'
            state.statusClass = 'bg-success'
            state.percent = 100
            // 3秒后隐藏或移除
            setTimeout(() => {
                if (state.message === '下载完成') {
                    progressStates.delete(subscriptionId)
                    wsService.close(`subscribe_${subscriptionId}`)
                }
            }, 3000)
        } else if (data.status === 'partial_completed') {
            state.message = '部分下载失败'
            state.statusClass = 'bg-warning'
            state.percent = 100
            // 3秒后隐藏或移除
            setTimeout(() => {
                if (state.message === '部分下载失败') {
                    progressStates.delete(subscriptionId)
                    wsService.close(`subscribe_${subscriptionId}`)
                }
            }, 3000)
        } else if (data.status === 'cancelled') {
            state.message = `已取消 (完成: ${data.completed || 0}, 失败: ${data.failed || 0})`
            state.statusClass = 'text-warning'
            state.percent = 100
            setTimeout(() => {
                if (state.message.includes('已取消')) {
                    progressStates.delete(subscriptionId)
                    wsService.close(`subscribe_${subscriptionId}`)
                }
            }, 3000)
        } else if (data.status === 'error') {
            state.message = '下载失败'
            state.statusClass = 'bg-danger'
            state.percent = 100
            setTimeout(() => {
                if (state.message === '下载失败') {
                    progressStates.delete(subscriptionId)
                    wsService.close(`subscribe_${subscriptionId}`)
                }
            }, 3000)
        }
    }

    /**
     * 从数据库恢复进度状态
     * @param {Array} subscriptions - 订阅列表
     */
    async function restoreProgressStates(subscriptions) {
        const downloadingSubscriptions = subscriptions.filter(
            sub => sub.batch_download_status === 'downloading' ||
                sub.batch_download_status === 'cancelling'
        )

        downloadingSubscriptions.forEach(sub => {
            initProgressState(sub.id, {
                completed: sub.batch_download_completed || 0,
                total: sub.batch_download_total || 0,
                failed: sub.batch_download_failed || 0,
                status: sub.batch_download_status,
                nickname: sub.nickname,
                platform: sub.platform,
                avatar_url: sub.avatar_url
            })

            // 为活跃任务建立 WebSocket 连接
            wsService.connect(`subscribe_${sub.id}`)
        })

        updateTrigger.value++ // 恢复后强制触发一次 UI 更新
        console.log(`恢复了 ${downloadingSubscriptions.length} 个批量下载进度状态`)
    }

    /**
     * 启动 WebSocket 监听（引用计数，支持多个调用者）
     */
    function startWebSocketListener() {
        if (wsListenerCount === 0) {
            wsUnregister = wsService.onMessage((id, data) => {
                if (data.type === 'batch_download_progress') {
                    handleProgressUpdate(data)
                }
            })
        }
        wsListenerCount++
    }

    /**
     * 启动轻量级轮询（已弃用）
     * 现已完全切换到 WebSocket 推送，此函数为空实现以保持兼容
     */
    function startPolling() {
        // WebSocket 已经足够稳定，无需轮询
        // console.log('Polling is deprecated, using WebSocket only.')
    }

    /**
     * 停止轮询（已弃用）
     */
    function stopPolling() {
        if (refreshInterval) {
            clearInterval(refreshInterval)
            refreshInterval = null
        }
    }

    /**
     * 清理资源（组件级清理，引用计数减一）
     * 当所有调用者都清理后，才真正注销 ws 监听器
     */
    function cleanup() {
        stopPolling()
        wsListenerCount = Math.max(0, wsListenerCount - 1)
        if (wsListenerCount === 0 && wsUnregister) {
            wsUnregister()
            wsUnregister = null
        }
    }

    /**
     * 强力清理（真正清空所有状态）
     */
    function clearAll() {
        stopPolling()

        if (wsUnregister) {
            wsUnregister()
            wsUnregister = null
        }
        wsListenerCount = 0

        // 关闭所有 WebSocket 连接
        progressStates.forEach((_, subscriptionId) => {
            wsService.close(`subscribe_${subscriptionId}`)
        })

        progressStates.clear()
        updateTrigger.value++
    }

    /**
     * 获取指定订阅的进度状态
     * @param {string} subscriptionId - 订阅ID
     * @returns {object|undefined} 进度状态对象
     */
    function getProgressState(subscriptionId) {
        return progressStates.get(subscriptionId)
    }

    /**
     * 手动添加任务（用于新建任务后立即显示）
     * @param {string} subscriptionId - 订阅ID
     * @param {object} initialData - 初始数据
     * @returns {object} 进度状态对象
     */
    function addTask(subscriptionId, initialData = {}) {
        const state = initProgressState(subscriptionId, initialData)
        wsService.connect(`subscribe_${subscriptionId}`)
        console.log(`添加批量下载任务: ${subscriptionId}`)
        return state
    }

    /**
     * 移除任务
     * @param {string} subscriptionId - 订阅ID
     */
    function removeTask(subscriptionId) {
        progressStates.delete(subscriptionId)
        wsService.close(`subscribe_${subscriptionId}`)
    }

    /**
     * 获取所有活跃任务
     * @returns {Array} 活跃任务列表
     */
    function getActiveTasks() {
        return Array.from(progressStates.entries()).map(([id, state]) => ({
            id,
            ...state
        }))
    }

    return {
        // 状态
        progressStates,
        updateTrigger,

        // 方法
        getProgressState,
        addTask,
        removeTask,
        getActiveTasks,
        restoreProgressStates,
        startWebSocketListener,
        startPolling,
        stopPolling,
        cleanup,
        clearAll
    }
}
