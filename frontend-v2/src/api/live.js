/**
 * 直播录制API
 */
import client from './client'

export default {
    // ==================== 订阅管理 ====================

    /**
     * 获取所有直播订阅
     * @param {string} platform - 平台筛选(可选)
     */
    getLiveSubscriptions(platform) {
        const params = platform ? { platform } : {}
        return client.get('/live/subscriptions', { params })
    },

    /**
     * 添加直播订阅
     * @param {Object} data - 订阅数据
     * @param {string} data.room_url - 直播间URL
     * @param {string} data.platform - 平台(默认douyin)
     * @param {string} data.quality - 画质(默认原画)
     * @param {boolean} data.auto_record - 是否自动录制
     * @param {boolean} data.monitor_enabled - 是否启用周期检测
     * @param {number} data.check_interval - 检测间隔(秒)
     */
    addLiveSubscription(data) {
        const params = new URLSearchParams()
        params.append('room_url', data.room_url)
        if (data.platform) params.append('platform', data.platform)
        if (data.quality) params.append('quality', data.quality)
        if (data.auto_record !== undefined) params.append('auto_record', data.auto_record)
        if (data.monitor_enabled !== undefined) params.append('monitor_enabled', data.monitor_enabled)
        if (data.check_interval) params.append('check_interval', data.check_interval)
        if (data.notification_enabled !== undefined) params.append('notification_enabled', data.notification_enabled)
        if (data.danmu_enabled !== undefined) params.append('danmu_enabled', data.danmu_enabled)
        if (data.stream_name) params.append('stream_name', data.stream_name)

        return client.post('/live/subscriptions?' + params.toString())
    },

    /**
     * 批量添加直播订阅
     * @param {Object} data - 批量数据
     * @param {Array<Object>} data.subscriptions - 订阅列表
     */
    batchAddLiveSubscriptions(data) {
        return client.post('/live/subscriptions/batch', data)
    },

    /**
     * 更新直播订阅
     * @param {string} id - 订阅ID
     * @param {Object} data - 更新数据
     */
    updateLiveSubscription(id, data) {
        const params = new URLSearchParams()
        if (data.quality) params.append('quality', data.quality)
        if (data.auto_record !== undefined) params.append('auto_record', data.auto_record)
        if (data.monitor_enabled !== undefined) params.append('monitor_enabled', data.monitor_enabled)
        if (data.check_interval) params.append('check_interval', data.check_interval)
        if (data.notification_enabled !== undefined) params.append('notification_enabled', data.notification_enabled)
        if (data.danmu_enabled !== undefined) params.append('danmu_enabled', data.danmu_enabled)

        return client.put(`/live/subscriptions/${id}?` + params.toString())
    },

    /**
     * 删除直播订阅
     * @param {string} id - 订阅ID
     */
    deleteLiveSubscription(id) {
        return client.delete(`/live/subscriptions/${id}`)
    },

    // ==================== 直播状态 ====================

    /**
     * 获取所有直播间状态
     */
    getLiveStatus() {
        return client.get('/live/status')
    },

    /**
     * 刷新单个直播间状态
     * @param {string} id - 订阅ID
     */
    refreshLiveStatus(id) {
        return client.post(`/live/status/refresh/${id}`)
    },

    /**
     * 获取直播流播放地址
     * @param {string} id - 订阅ID
     */
    getPlayUrl(id) {
        return client.get(`/live/play/${id}`)
    },

    // ==================== 录制控制 ====================

    /**
     * 开始录制
     * @param {string} id - 订阅ID
     */
    startRecording(id) {
        return client.post(`/live/record/start/${id}`)
    },

    /**
     * 停止录制
     * @param {string} id - 订阅ID
     */
    stopRecording(id) {
        return client.post(`/live/record/stop/${id}`)
    },

    /**
     * 获取录制状态
     * @param {string} id - 订阅ID
     */
    getRecordingStatus(id) {
        return client.get(`/live/record/status/${id}`)
    },

    // ==================== 自定义流探测 ====================

    /**
     * 探测自定义流地址是否在线
     * @param {string} url - 流地址
     */
    probeStreamUrl(url) {
        return client.post(`/live/probe?url=${encodeURIComponent(url)}`)
    },

    // ==================== 录制历史 ====================

    /**
     * 获取录制历史
     * @param {Object} params - 查询参数
     * @param {string} params.subscription_id - 订阅ID筛选
     * @param {string} params.status - 状态筛选
     * @param {number} params.page - 页码
     * @param {number} params.page_size - 每页数量
     */
    getRecordHistory(params = {}) {
        return client.get('/live/records', { params })
    },

    /**
     * 批量获取时间轴可用性（是否存在可播放 MP4 历史）
     * @param {Array<string>} ids - 订阅ID列表
     */
    getTimelineAvailability(ids = []) {
        const params = {}
        if (ids.length > 0) {
            params.ids = ids.join(',')
        }
        return client.get('/live/records/timeline-availability', { params })
    },

    /**
     * 删除录制记录
     * @param {string} id - 记录ID
     * @param {boolean} deleteFile - 是否同时删除文件
     */
    deleteRecord(id, deleteFile = false) {
        return client.delete(`/live/records/${id}`, {
            params: { delete_file: deleteFile }
        })
    },

    /**
     * 更新录制记录备注
     * @param {string} id - 记录ID
     * @param {string} remark - 备注内容
     */
    updateRecordRemark(id, remark = '') {
        const params = new URLSearchParams()
        params.append('remark', remark)
        return client.put(`/live/records/${id}/remark?${params.toString()}`)
    },

    /**
     * 清空所有录制历史
     * @param {boolean} deleteFiles - 是否同时删除文件
     * @param {string|null} subscriptionId - 可选，指定订阅ID
     */
    clearAllRecords(deleteFiles = false, subscriptionId = null) {
        const params = { delete_files: deleteFiles }
        if (subscriptionId) {
            params.subscription_id = subscriptionId
        }
        return client.delete('/live/records/clear', { params })
    },

    // ==================== 统计信息 ====================

    /**
     * 获取直播录制统计
     */
    getLiveStats() {
        return client.get('/live/stats')
    },

    // ==================== 视频转码 ====================

    /**
     * 转码录制文件为MP4
     * @param {string} recordId - 录制记录ID
     * @param {boolean} deleteOriginal - 是否删除原文件
     */
    convertToMp4(recordId, deleteOriginal = true) {
        const params = new URLSearchParams()
        params.append('delete_original', deleteOriginal)
        return client.post(`/live/convert/${recordId}?${params.toString()}`)
    },

    /**
     * 批量转码录制文件
     * @param {Array} recordIds - 录制记录ID列表
     * @param {boolean} deleteOriginal - 是否删除原文件
     */
    batchConvertToMp4(recordIds, deleteOriginal = true) {
        const params = new URLSearchParams()
        recordIds.forEach(id => params.append('record_ids', id))
        params.append('delete_original', deleteOriginal)
        return client.post(`/live/convert-batch?${params.toString()}`)
    },

    /**
     * 一键转码全部未转码记录（可按订阅ID过滤）
     * @param {string|null} subscriptionId - 可选，订阅ID
     * @param {boolean} deleteOriginal - 是否删除原文件
     */
    convertUnconvertedToMp4(subscriptionId = null, deleteOriginal = true) {
        const params = new URLSearchParams()
        if (subscriptionId) params.append('subscription_id', subscriptionId)
        params.append('delete_original', deleteOriginal)
        return client.post(`/live/convert-unconverted?${params.toString()}`)
    },

    /**
     * 获取待转码记录数量（可按订阅ID过滤）
     * @param {string|null} subscriptionId - 可选，订阅ID
     */
    getUnconvertedCount(subscriptionId = null) {
        const params = {}
        if (subscriptionId) params.subscription_id = subscriptionId
        return client.get('/live/convert-unconverted/count', { params })
    },

    // ==================== 高级配置 ====================

    /**
     * 获取订阅的完整配置
     * @param {string} subId - 订阅ID
     */
    getSubscriptionConfig(subId) {
        return client.get(`/live/subscriptions/${subId}/config`)
    },

    /**
     * 更新订阅配置
     * @param {string} subId - 订阅ID
     * @param {Object} config - 配置对象
     */
    updateSubscriptionConfig(subId, config) {
        const params = new URLSearchParams()
        if (config.quality !== undefined) params.append('quality', config.quality)
        if (config.auto_record !== undefined) params.append('auto_record', config.auto_record)
        if (config.monitor_enabled !== undefined) params.append('monitor_enabled', config.monitor_enabled)
        if (config.check_interval !== undefined) params.append('check_interval', config.check_interval)
        if (config.output_format !== undefined) params.append('output_format', config.output_format)
        if (config.split_enabled !== undefined) params.append('split_enabled', config.split_enabled)
        if (config.split_duration !== undefined) params.append('split_duration', config.split_duration)
        if (config.max_duration !== undefined) params.append('max_duration', config.max_duration)
        if (config.generate_subtitle !== undefined) params.append('generate_subtitle', config.generate_subtitle)
        if (config.auto_convert_mp4 !== undefined) params.append('auto_convert_mp4', config.auto_convert_mp4)
        if (config.notification_enabled !== undefined) params.append('notification_enabled', config.notification_enabled)
        if (config.danmu_enabled !== undefined) params.append('danmu_enabled', config.danmu_enabled)
        if (config.compat_mode !== undefined) params.append('compat_mode', config.compat_mode)
        return client.put(`/live/subscriptions/${subId}/config?${params.toString()}`)
    },

    /**
     * 批量更新订阅配置
     * @param {Array} ids - 订阅ID列表
     * @param {Object} config - 配置对象
     */
    bulkUpdateSubscriptionConfig(ids, config) {
        const params = new URLSearchParams()
        params.append('ids', ids.join(','))
        if (config.auto_record !== undefined) params.append('auto_record', config.auto_record)
        if (config.monitor_enabled !== undefined) params.append('monitor_enabled', config.monitor_enabled)
        if (config.quality !== undefined) params.append('quality', config.quality)
        if (config.notification_enabled !== undefined) params.append('notification_enabled', config.notification_enabled)
        if (config.split_enabled !== undefined) params.append('split_enabled', config.split_enabled)
        if (config.split_duration !== undefined) params.append('split_duration', config.split_duration)
        if (config.generate_subtitle !== undefined) params.append('generate_subtitle', config.generate_subtitle)
        if (config.auto_convert_mp4 !== undefined) params.append('auto_convert_mp4', config.auto_convert_mp4)
        if (config.danmu_enabled !== undefined) params.append('danmu_enabled', config.danmu_enabled)
        if (config.compat_mode !== undefined) params.append('compat_mode', config.compat_mode)
        if (config.check_interval !== undefined) params.append('check_interval', config.check_interval)
        return client.put(`/live/subscriptions/bulk-config?${params.toString()}`)
    },

    /**
     * 批量删除直播订阅
     * @param {Array} ids - 订阅ID列表
     */
    bulkDeleteSubscriptions(ids) {
        const params = new URLSearchParams()
        params.append('ids', ids.join(','))
        return client.delete(`/live/subscriptions/bulk?${params.toString()}`)
    },

    /**
     * 更新分段录制配置
     * @param {string} subId - 订阅ID
     * @param {boolean} enabled - 是否启用
     * @param {number} duration - 分段时长(秒)
     */
    updateSegmentConfig(subId, enabled, duration = 3600) {
        const params = new URLSearchParams()
        params.append('enabled', enabled)
        params.append('duration', duration)
        return client.put(`/live/subscriptions/${subId}/segment?${params.toString()}`)
    },

    /**
     * 更新字幕生成配置
     * @param {string} subId - 订阅ID
     * @param {boolean} enabled - 是否启用
     */
    updateSubtitleConfig(subId, enabled) {
        const params = new URLSearchParams()
        params.append('enabled', enabled)
        return client.put(`/live/subscriptions/${subId}/subtitle?${params.toString()}`)
    },

    // ==================== 直播订阅备份（使用 backup 模块） ====================

    /**
     * 导出所有直播订阅配置（仅订阅列表）
     */
    exportLiveBackup() {
        return client.get('/backup/live_subscriptions')
    },

    /**
     * 导入直播订阅配置备份
     * @param {Object} data - 从备份文件解析出的 JSON 对象
     */
    importLiveBackup(data) {
        return client.post('/backup/live_subscriptions/import', data)
    }
}
