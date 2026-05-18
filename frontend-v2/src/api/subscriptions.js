import client from './client'

export const subscriptionsApi = {
    // 获取订阅列表
    async getList() {
        return await client.get('/subscribe/list')
    },

    // 添加订阅
    async add(data) {
        return await client.post('/subscribe/add', data, { timeout: 60000 })
    },

    // 添加抖音点赞订阅
    async addDouyinFavorite(data) {
        return await client.post('/subscribe/douyin/add_favorite_subscription', data)
    },

    // 批量添加抖音博主订阅（后台异步任务）
    async batchAddDouyin(data) {
        return await client.post('/subscribe/douyin/batch_add', data)
    },

    // 更新订阅
    async update(id, data) {
        return await client.put(`/subscribe/${id}`, data)
    },

    // 删除订阅
    async delete(id) {
        return await client.delete(`/subscribe/${id}`)
    },

    // 检查更新 (改用POST方法)
    async checkUpdate(id, manualRefresh = true) {
        return await client.post(`/subscribe/${id}/check`, null, {
            params: { manual_refresh: manualRefresh }
        })
    },

    // 同步视频
    async syncVideos(id) {
        return await client.post(`/subscribe/${id}/sync_videos`)
    },

    // 获取订阅详情
    async getDetail(id) {
        return await client.get(`/subscribe/${id}`)
    },

    // 获取订阅视频列表
    async getVideos(id, page = 1, pageSize = 20) {
        return await client.get(`/subscribe/${id}/videos?page=${page}&page_size=${pageSize}`)
    },

    // 获取订阅视频本地缩略图（网络封面兜底）
    async getVideoLocalThumbnail(subscriptionId, videoId) {
        return await client.get(`/subscribe/${subscriptionId}/video/${videoId}/local-thumbnail`)
    },

    // 获取订阅视频 NFO 文本
    async getVideoNfo(subscriptionId, videoId) {
        return await client.get(`/subscribe/${subscriptionId}/video/${videoId}/nfo`)
    },

    // 检查订阅视频是否存在 NFO
    async checkVideoNfoExists(subscriptionId, videoId) {
        return await client.get(`/subscribe/${subscriptionId}/video/${videoId}/nfo/exists`)
    },

    // 更新订阅视频 NFO 文本
    async updateVideoNfo(subscriptionId, videoId, content) {
        return await client.put(`/subscribe/${subscriptionId}/video/${videoId}/nfo`, { content })
    },

    // 下载视频
    async downloadVideo(videoId) {
        return await client.post(`/subscribe/video/${videoId}/download`)
    },

    // 删除单个视频记录
    async deleteVideo(videoId) {
        return await client.delete(`/subscribe/video/${videoId}`)
    },

    // 清理订阅孤儿视频（文件缺失）
    async cleanupOrphanVideos(subscriptionId) {
        return await client.post(`/subscribe/${subscriptionId}/videos/orphan/cleanup`)
    },

    // 重新下载视频
    async redownloadVideo(videoId) {
        return await client.post(`/subscribe/video/${videoId}/redownload`)
    },

    // 批量下载
    async batchDownload(id, data) {
        return await client.post(`/subscribe/${id}/batch_download`, data)
    },

    // 开始批量下载
    async startBatchDownload(id, data) {
        return await client.post(`/subscribe/${id}/batch_download/start`, data)
    },

    // 重试批量下载
    async retryBatchDownload(id) {
        return await client.post(`/subscribe/${id}/batch_download/retry`)
    },

    // 取消批量下载
    async cancelBatchDownload(id) {
        return await client.post(`/subscribe/${id}/batch_download/cancel`)
    },

    // 更新画质
    async updateQuality(id, quality) {
        return await client.put(`/subscribe/${id}/quality`, { quality })
    },

    // 重试失败任务
    async retryFailed(id, params = null) {
        if (params) {
            return await client.post(`/subscribe/${id}/retry_failed`, params)
        }
        return await client.post(`/subscribe/${id}/retry_failed`)
    },

    // 批量检测更新
    async batchCheckFiltered(filters) {
        return await client.post('/subscribe/batch_check_filtered', filters)
    },

    // 批量同步视频
    async batchSyncFiltered(filters) {
        return await client.post('/subscribe/batch_sync_filtered', filters)
    },

    // 导出订阅配置（通过 backup 模块）
    async exportConfig() {
        return await client.get('/backup/subscriptions')
    },

    // 导入订阅配置（通过 backup 模块）
    async importConfig(file) {
        const text = await file.text()
        const json = JSON.parse(text)
        // 直接把 JSON 作为请求体发给 /backup/subscriptions/import
        return await client.post('/backup/subscriptions/import', json)
    },

    // 重置浏览器
    async resetBrowser() {
        return await client.post('/subscribe/reset-browser')
    },

    // 清理缓存
    async clearCache() {
        return await client.post('/cache/clear')
    },

    // 抖音登录
    async douyinLogin() {
        return await client.post('/subscribe/douyin/login')
    },

    // YouTube登录
    async youtubeLogin() {
        return await client.post('/subscribe/youtube/login')
    },

    // B站登录
    async bilibiliLogin() {
        return await client.post('/subscribe/bilibili/login')
    },

    // 小红书登录
    async xiaohongshuLogin() {
        return await client.post('/subscribe/xiaohongshu/login')
    },

    // 关闭登录窗口
    async closeLogin(platform) {
        return await client.post(`/subscribe/${platform}/close`)
    },

    // VNC登录心跳（用于防止空闲回收）
    async browserHeartbeat(platform, source = 'vnc_login_modal') {
        return await client.post('/subscribe/browser/heartbeat', { platform, source })
    },

    // 获取YouTube播放列表
    async getYoutubePlaylists(channelId) {
        return await client.get(`/subscribe/youtube/playlists?channel_id=${channelId}`)
    },

    // 批量检测更新
    async batchCheckFiltered(subscriptionIds, adminSecret) {
        return await client.post('/subscribe/batch_check_filtered', subscriptionIds, {
            headers: { 'X-Admin-Secret': adminSecret || '' }
        })
    },

    // 批量同步视频
    async batchSyncFiltered(subscriptionIds, adminSecret) {
        return await client.post('/subscribe/batch_sync_filtered', subscriptionIds, {
            headers: { 'X-Admin-Secret': adminSecret || '' }
        })
    },

    // 代理图片
    proxyImage(url) {
        return `/api/subscribe/proxy/image?url=${encodeURIComponent(url)}`
    }
}
