import { useDownloadsStore } from '@/stores/downloads'
import { buildAuthedWsUrl } from '@/utils/wsAuth'

class WebSocketService {
    constructor() {
        this.connections = new Map()
        this.reconnectAttempts = new Map()
        // 初始重连间隔 2秒
        this.baseReconnectInterval = 2000
        // 最大重连间隔 60秒
        this.maxReconnectInterval = 60000
        this.onMessageHandlers = new Set()
        this.heartbeatTimers = new Map()
        this.heartbeatInterval = 20000 // 20秒心跳一次
    }

    /**
     * 连接到指定的订阅 ID
     * @param {string} subscriptionId - 例如 'metrics', 'downloads', 'batch_tasks'
     */
    connect(subscriptionId = 'metrics') {
        if (this.connections.has(subscriptionId)) return
        const token = localStorage.getItem('token')
        if (!token) {
            console.log(`[WS] Skip connect ${subscriptionId}: missing token`)
            return
        }

        const url = buildAuthedWsUrl(`/api/ws/subscribe/${subscriptionId}/progress`)

        console.log(`[WS] Connecting to ${subscriptionId}: ${url}`)
        const ws = new WebSocket(url)

        ws.onopen = () => {
            console.log(`[WS] ${subscriptionId} Connected`)
            this.reconnectAttempts.set(subscriptionId, 0)
            this.startHeartbeat(subscriptionId)
        }

        ws.onmessage = (event) => {
            if (event.data === 'pong') {
                return
            }
            try {
                const data = JSON.parse(event.data)
                this.handleMessage(subscriptionId, data)
            } catch (e) {
                console.error(`[WS] Failed to parse message for ${subscriptionId}:`, e)
            }
        }

        ws.onclose = (event) => {
            console.log(`[WS] ${subscriptionId} Closed: code=${event.code}, reason=${event.reason}`)
            this.stopHeartbeat(subscriptionId)
            this.connections.delete(subscriptionId)

            // 1008 代表鉴权失败（缺少/无效 token），停止自动重连避免日志刷屏。
            if (event.code === 1008) {
                console.warn(`[WS] ${subscriptionId} Unauthorized (1008), stop reconnect`)
                localStorage.removeItem('token')
                this.closeAll()
                return
            }

            // 只有当不是正常关闭时才尝试重连
            if (event.code !== 1000) {
                this.attemptReconnect(subscriptionId)
            }
        }

        ws.onerror = (error) => {
            console.error(`[WS] ${subscriptionId} Error:`, error)
        }

        this.connections.set(subscriptionId, ws)
    }

    closeAll() {
        for (const [subscriptionId, ws] of this.connections.entries()) {
            try {
                ws.close()
            } catch (e) { }
            this.stopHeartbeat(subscriptionId)
        }
        this.connections.clear()
    }

    attemptReconnect(subscriptionId) {
        const attempts = this.reconnectAttempts.get(subscriptionId) || 0
        this.reconnectAttempts.set(subscriptionId, attempts + 1)

        // 指数回退算法核心逻辑
        // 第1次: 2s, 第2次: 4s, 第3次: 8s... 直到 60s 后保持每分钟尝试一次
        const delay = Math.min(
            this.baseReconnectInterval * Math.pow(1.5, attempts),
            this.maxReconnectInterval
        )

        console.log(`[WS] Reconnecting ${subscriptionId} in ${Math.round(delay / 1000)}s (Attempt ${attempts + 1})...`)

        setTimeout(() => {
            // 再次检查是否已经有连接，防止并发重连
            if (!this.connections.has(subscriptionId)) {
                this.connect(subscriptionId)
            }
        }, delay)
    }

    startHeartbeat(subscriptionId) {
        this.stopHeartbeat(subscriptionId)
        const timer = setInterval(() => {
            const ws = this.connections.get(subscriptionId)
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send('ping')
            } else {
                this.stopHeartbeat(subscriptionId)
            }
        }, this.heartbeatInterval)
        this.heartbeatTimers.set(subscriptionId, timer)
    }

    stopHeartbeat(subscriptionId) {
        const timer = this.heartbeatTimers.get(subscriptionId)
        if (timer) {
            clearInterval(timer)
            this.heartbeatTimers.delete(subscriptionId)
        }
    }

    handleMessage(subscriptionId, data) {
        // 调用所有注册的处理器
        this.onMessageHandlers.forEach(handler => handler(subscriptionId, data))

        // 特殊处理下载 Store
        if (subscriptionId === 'downloads') {
            const downloadsStore = useDownloadsStore()
            if (data.type === 'progress_update') {
                downloadsStore.handleProgressUpdate(data)
            }
        }
    }

    /**
     * 注册消息处理器
     */
    onMessage(handler) {
        this.onMessageHandlers.add(handler)
        return () => this.onMessageHandlers.delete(handler)
    }

    send(subscriptionId, data) {
        const ws = this.connections.get(subscriptionId)
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(typeof data === 'string' ? data : JSON.stringify(data))
        }
    }

    close(subscriptionId) {
        const ws = this.connections.get(subscriptionId)
        if (ws) {
            ws.close()
            this.connections.delete(subscriptionId)
        }
    }
}

export const wsService = new WebSocketService()
