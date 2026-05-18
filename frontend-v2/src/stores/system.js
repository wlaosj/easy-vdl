import { defineStore } from 'pinia'
import { systemApi } from '@/api/system'
import { licenseApi } from '@/api/license'
import { buildAuthedWsUrl } from '@/utils/wsAuth'

export const useSystemStore = defineStore('system', {
    state: () => ({
        metrics: {
            uptime_seconds: 0,
            memory_mb: 0,
            downloads: { downloading: 0, queued: 0, active_subscriptions: 0 },
            net: { rx_bps: 0, tx_bps: 0 },
            cpu_percent: 0,
            browsers: { total_pages: 0 },
            watchdog: { cleanup_count: 0 },
            gpu_stats: {
                summary: { gpu_count: 0, has_gpu: false, vendors: [] },
                gpus: [],
                status: 'success',
                message: ''
            },
            timestamp: null
        },
        storage: {
            total_bytes: 0,
            used_bytes: 0,
            free_bytes: 0,
            total_gb: 0,
            used_gb: 0,
            free_gb: 0,
            usage_percentage: 0,
            directory_size_bytes: 0,
            directory_size_gb: 0
        },
        core: {
            current_version: null,
            latest_version: null,
            has_update: false
        },
        app: {
            version: 'Unknown',
            build_time: null
        },
        license: {
            is_licensed: false,
            status: 'invalid', // valid, invalid, expired
            remaining_days: 0,
            error: null,
            isLoading: true // 初始设为 true，表示尚未获知结果
        },
        _licenseInFlight: false,
        // 移动端和 UI 状态
        isMobile: false,
        sidebarOpen: false,
        theme: 'light', // 'light' | 'dark'

        // 公告与更新
        announcements: [],
        hasUnreadNotice: false,
        hasAppUpdate: false,
        latestAppVersion: null,
        _annWS: null,
        // 防抖机制
        _annStateInFlight: false,
        _annStateLastAt: 0,
        // 版本更新检查防抖（参考旧版本：5分钟）
        _versionCheckInFlight: false,
        _versionCheckLastAt: 0
    }),

    getters: {
        // 统一前端口径：用户只关心“当前是否可用”
        hasLicense: (state) => !!state.license.is_licensed
    },

    actions: {
        updateMetrics(newMetrics) {
            this.metrics = { ...this.metrics, ...newMetrics }
            this.metrics.timestamp = new Date().toISOString()
        },

        /**
         * 处理全局系统指标推送
         * 涵盖：基础性能、存储空间、授权状态、公告状态
         */
        handleGlobalMetrics(payload) {
            if (!payload) return

            // 1. 更新基础性能指标 (CPU, Net, Download Counts)
            this.updateMetrics(payload)

            // 2. 更新存储状态
            if (payload.storage) {
                const directory_size_bytes = payload.storage.directory_size_bytes || 0
                const total_bytes = payload.storage.total_bytes ?? Math.round((payload.storage.total_gb || this.storage.total_gb || 0) * (1000 ** 3))
                const used_bytes = payload.storage.used_bytes ?? Math.round((payload.storage.used_gb || this.storage.used_gb || 0) * (1000 ** 3))
                const free_bytes = payload.storage.free_bytes ?? Math.round((payload.storage.free_gb || this.storage.free_gb || 0) * (1000 ** 3))
                this.storage = {
                    total_bytes,
                    used_bytes,
                    free_bytes,
                    total_gb: payload.storage.total_gb || 0,
                    used_gb: payload.storage.used_gb || 0,
                    free_gb: payload.storage.free_gb || 0,
                    usage_percentage: payload.storage.usage_percentage || 0,
                    directory_size_bytes: directory_size_bytes,
                    directory_size_gb: directory_size_bytes ?
                        parseFloat((directory_size_bytes / (1000 ** 3)).toFixed(2)) : 0
                }
            }

            // 3. 更新授权状态
            if (payload.license) {
                this.license = {
                    ...this.license,
                    is_licensed: payload.license.is_licensed || false,
                    status: payload.license.status || 'invalid',
                    remaining_days: payload.license.remaining_days || 0,
                    isLoading: false
                }
            }

            // 4. 更新公告与版本状态
            if (payload.announcement) {
                this.hasUnreadNotice = payload.announcement.has_unread_notice || false
                this.hasAppUpdate = payload.announcement.has_app_update || false
                if (payload.announcement.latest_app_version) {
                    this.latestAppVersion = payload.announcement.latest_app_version
                }
                // 自动补齐未知的版本号
                if (payload.announcement.current_version && payload.announcement.current_version !== 'Unknown') {
                    if (!this.app.version || this.app.version === 'Unknown') {
                        this.app.version = payload.announcement.current_version
                    }
                }
            }
        },

        async fetchStorageUsage() {
            try {
                const data = await systemApi.getStorageUsage()
                if (data.status === 'success') {
                    this.storage = {
                        total_bytes: data.total_bytes ?? 0,
                        used_bytes: data.used_bytes ?? 0,
                        free_bytes: data.free_bytes ?? 0,
                        total_gb: data.total_gb,
                        used_gb: data.used_gb,
                        free_gb: data.free_gb,
                        usage_percentage: data.usage_percentage,
                        directory_size_bytes: data.directory_size_bytes,
                        directory_size_gb: data.directory_size_gb
                    }
                }
            } catch (err) {
                console.error('Failed to fetch storage usage:', err)
            }
        },

        async fetchCoreVersion(fast = true) {
            try {
                const data = await systemApi.getCoreVersion(fast)
                this.core = {
                    current_version: data.current_version,
                    latest_version: data.latest_version,
                    has_update: data.has_update
                }
            } catch (err) {
                console.error('Failed to fetch core version:', err)
            }
        },

        async fetchBuildVersion() {
            try {
                const data = await systemApi.getBuildVersion()
                this.app = {
                    version: data.version,
                    build_time: data.build_time
                }
            } catch (err) {
                console.error('Failed to fetch build version:', err)
            }
        },

        async fetchLicenseStatus() {
            if (this._licenseInFlight) return
            this._licenseInFlight = true
            this.license.isLoading = true
            try {
                const data = await licenseApi.getStatus()
                this.license = {
                    is_licensed: data.is_licensed,
                    status: data.status,
                    remaining_days: data.remaining_days,
                    license_key: data.license_key, // 存储API返回的脱敏Key
                    error: data.error,
                    isLoading: false
                }
            } catch (err) {
                console.error('Failed to fetch license status:', err)
                this.license.isLoading = false
            } finally {
                this._licenseInFlight = false
            }
        },

        // --- 复刻旧版公告逻辑 ---

        async fetchAnnouncements(forVersionCheck = false) {
            // 如果是用于版本更新检查，应用5分钟防抖（参考旧版本）
            if (forVersionCheck) {
                const now = Date.now()
                const VERSION_CHECK_COOLDOWN_MS = 300000 // 5分钟

                if (this._versionCheckInFlight || (now - this._versionCheckLastAt) < VERSION_CHECK_COOLDOWN_MS) {
                    return
                }

                this._versionCheckInFlight = true
                this._versionCheckLastAt = now
            }

            try {
                const data = await systemApi.getAnnouncements(5)
                const items = Array.isArray(data.items) ? data.items : []

                // 排序逻辑：置顶优先，其次按时间倒序
                this.announcements = items.sort((a, b) => {
                    const aSticky = !!a.sticky
                    const bSticky = !!b.sticky
                    if (aSticky !== bSticky) return aSticky ? -1 : 1
                    const at = new Date(a.updated_at || a.start_at || 0).getTime()
                    const bt = new Date(b.updated_at || b.start_at || 0).getTime()
                    return bt - at
                })

                this.checkAppUpdateFromAnnouncements()
            } catch (err) {
                console.error('Failed to fetch announcements:', err)
            } finally {
                if (forVersionCheck) {
                    this._versionCheckInFlight = false
                }
            }
        },

        async checkAnnouncementState() {
            // 防抖机制：1.5秒内忽略重复请求（参考旧版本）
            const now = Date.now()
            const COOLDOWN_MS = 1500

            if (this._annStateInFlight || (now - this._annStateLastAt) < COOLDOWN_MS) {
                return
            }

            this._annStateInFlight = true
            try {
                const data = await systemApi.getAnnouncementState()
                this.hasUnreadNotice = !!data.pending
                // 如果没有未读公告，主动检查是否有版本更新（会获取公告列表）
                if (!this.hasUnreadNotice) {
                    // 延迟获取，避免并发请求（用于版本更新检查，应用防抖）
                    setTimeout(() => {
                        this.fetchAnnouncements(true) // forVersionCheck = true
                    }, 500)
                }
            } catch (err) {
                console.error('Failed to check announcement state:', err)
            } finally {
                this._annStateLastAt = Date.now()
                this._annStateInFlight = false
            }
        },

        async markAnnouncementsRead() {
            try {
                await systemApi.markAnnouncementsRead()
                this.hasUnreadNotice = false
            } catch (err) {
                console.error('Failed to mark announcements as read:', err)
            }
        },

        checkAppUpdateFromAnnouncements() {
            if (this.announcements.length === 0) return

            const firstAnn = this.announcements[0]
            const content = firstAnn.content || ''
            // 复刻旧版正则：匹配 "版本号：v20250915.192920"
            const versionMatch = content.match(/版本号[：:]\s*(v[\d.]+)/i)
            const remoteVersion = versionMatch ? versionMatch[1] : null

            if (remoteVersion && this.app.version && this.app.version !== 'Unknown') {
                this.latestAppVersion = remoteVersion
                this.hasAppUpdate = this.app.version !== remoteVersion
            }
        },

        initAnnouncementsWS() {
            if (this._annWS && this._annWS.readyState === 1) return
            const token = localStorage.getItem('token')
            if (!token) return

            const wsUrl = buildAuthedWsUrl('/api/ws/subscribe/announcements/progress')
            const ws = new WebSocket(wsUrl)
            this._annWS = ws

            let pingInterval = null

            ws.onopen = () => {
                // 公告状态和版本信息现在主要通过 metrics 频道推送，这里作为兜底机制
                // 仅在 WebSocket 连接成功时检查一次（避免延迟）
                // this.checkAnnouncementState() // 已移除：改为通过 WebSocket metrics 推送
                pingInterval = setInterval(() => {
                    if (ws.readyState === 1) ws.send('ping')
                }, 30000)
            }

            ws.onmessage = (evt) => {
                try {
                    const data = JSON.parse(evt.data)
                    if (data.type === 'announcement_updated') {
                        this.hasUnreadNotice = true
                        this.fetchAnnouncements()
                    } else if (data.type === 'announcement_ack') {
                        this.hasUnreadNotice = false
                        this.fetchAnnouncements()
                    } else if (data.type === 'license_status_changed') {
                        // 授权状态变更（可能是被踢出或封禁）
                        // 注意：授权信息现在主要通过 metrics 频道推送，这里作为兜底机制
                        // 仅在状态异常时触发 HTTP 请求获取详细信息
                        if (data.status !== 'valid') {
                            // 如果是非有效状态，重新获取详细状态并弹窗提示
                            this.fetchLicenseStatus()
                            window.dispatchEvent(new CustomEvent('license-kicked', {
                                detail: { reason: data.error || '授权状态已变更，请检查' }
                            }))
                        } else {
                            // 状态恢复为有效，也重新获取一次确保数据同步
                            this.fetchLicenseStatus()
                        }
                    }
                } catch (e) { }
            }

            ws.onclose = (evt) => {
                if (pingInterval) clearInterval(pingInterval)
                this._annWS = null
                // 1008 为鉴权失败，停止重连，等待用户重新登录后由外层逻辑重建。
                if (evt?.code === 1008) return
                if (!localStorage.getItem('token')) return
                setTimeout(() => this.initAnnouncementsWS(), 5000)
            }

            ws.onerror = () => ws.close()
        },

        // 主题切换
        initTheme() {
            // 从localStorage读取主题设置
            const savedTheme = localStorage.getItem('theme') || 'light'
            this.theme = savedTheme
            this.applyTheme(savedTheme)
        },

        toggleTheme() {
            this.theme = this.theme === 'light' ? 'dark' : 'light'
            localStorage.setItem('theme', this.theme)
            this.applyTheme(this.theme)
        },

        applyTheme(theme) {
            const html = document.documentElement
            if (theme === 'dark') {
                html.setAttribute('data-theme', 'dark')
            } else {
                html.removeAttribute('data-theme')
            }
        }
    }
})
