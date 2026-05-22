import client from './client';

/**
 * 全局配置 API (代理设置)
 */
export const globalConfigApi = {
    // 获取全局配置
    getConfig() {
        return client.get('/global-config/');
    },

    // 保存全局配置
    saveConfig(config) {
        return client.post('/global-config/', config);
    },

    // 清除配置
    clearConfig(clearKeys = ['proxy', 'no_proxy']) {
        return client.post('/global-config/clear', { clear_keys: clearKeys });
    },

    // 测试代理连接
    testProxy(proxyUrl, testUrl = 'https://httpbin.org/ip') {
        return client.post('/ytd/test-proxy', { proxy: proxyUrl, test_url: testUrl });
    },

};

/**
 * AI 配置 API
 */
export const aiConfigApi = {
    // 获取 AI 配置
    getConfig() {
        return client.get('/ai-config/');
    },

    // 保存 AI 配置
    saveConfig(config) {
        return client.post('/ai-config/', config);
    },

    // 清除 AI 配置
    clearConfig(clearKeys = []) {
        return client.post('/ai-config/clear', { clear_keys: clearKeys });
    },

    // 列出 ASR 模型缓存
    listAsrModels() {
        return client.get('/ai-config/asr-models');
    },

    // 下载 ASR 模型
    downloadAsrModel(modelName) {
        return client.post(`/ai-config/asr-models/${encodeURIComponent(modelName)}/download`);
    },

    // 删除 ASR 模型缓存
    deleteAsrModel(modelName) {
        return client.delete(`/ai-config/asr-models/${encodeURIComponent(modelName)}`);
    },

    // 测试 MiniMax 配置
    testMinimax(config = {}) {
        return client.post('/global-config/test-minimax', config);
    },

    // 测试 Ollama 配置
    testOllama(config = {}) {
        return client.post('/global-config/test-ollama', config);
    },

    // 测试 OpenAI 兼容平台配置
    testOpenAiCompatible(config = {}) {
        return client.post('/global-config/test-openai-compatible', config);
    },

    // 检测 Ollama 图像能力
    testOllamaVision(config = {}) {
        return client.post('/global-config/test-ollama-vision', config);
    },

    // 读取 Ollama 模型元数据能力
    getOllamaCapabilities(config = {}) {
        return client.post('/global-config/ollama-capabilities', config);
    },

    // 测试 DeepSeek 配置
    testDeepseek(config = {}) {
        return client.post('/global-config/test-deepseek', config);
    }
};

/**
 * Cookie 管理 API
 */
export const cookieApi = {
    // 获取所有Cookie状态
    getStatus() {
        return client.get('/cookie/status');
    },

    // YouTube Cookie
    saveYoutubeCookie(cookieContent) {
        return client.post('/cookie/save/youtube', { cookie_content: cookieContent });
    },

    updateYoutubeCookie() {
        return client.post('/cookie/update/youtube');
    },

    clearYoutubeCookie() {
        return client.delete('/cookie/clear/youtube');
    },

    setYoutubeAutoUpdate(enabled, intervalMinutes = 10) {
        return client.post('/cookie/auto-update/youtube', {
            enabled,
            interval_minutes: intervalMinutes
        });
    },

    // Bilibili Cookie
    saveBilibiliCookie(cookieContent) {
        return client.post('/cookie/save/bilibili', { cookie_content: cookieContent });
    },

    updateBilibiliCookie() {
        return client.post('/cookie/update/bilibili');
    },

    clearBilibiliCookie() {
        return client.delete('/cookie/clear/bilibili');
    },

    setBilibiliAutoUpdate(enabled, intervalMinutes = 10) {
        return client.post('/cookie/auto-update/bilibili', {
            enabled,
            interval_minutes: intervalMinutes
        });
    },

    // TikTok Cookie
    saveTiktokCookie(cookieContent) {
        return client.post('/cookie/save/tiktok', { cookie_content: cookieContent });
    },

    clearTiktokCookie() {
        return client.delete('/cookie/clear/tiktok');
    },

    // Instagram 账号密码
    saveInstagramCredentials(username, password) {
        return client.post('/cookie/save/instagram', { username, password });
    },

    getInstagramCredentials() {
        return client.get('/cookie/content/instagram');
    },

    clearInstagramCookie() {
        return client.delete('/cookie/clear/instagram');
    },

    // X Cookie
    saveXCookie(cookieContent) {
        return client.post('/cookie/save/x', { cookie_content: cookieContent });
    },

    clearXCookie() {
        return client.delete('/cookie/clear/x');
    },

    // 网易云音乐 Cookie
    saveNeteaseCookie(cookieContent) {
        return client.post('/cookie/save/netease', { cookie_content: cookieContent });
    },

    clearNeteaseCookie() {
        return client.delete('/cookie/clear/netease');
    },

    // 小红书 Cookie
    saveXiaohongshuCookie(cookieContent) {
        return client.post('/cookie/save/xiaohongshu', { cookie_content: cookieContent });
    },

    clearXiaohongshuCookie() {
        return client.delete('/cookie/clear/xiaohongshu');
    },

    updateXiaohongshuCookie() {
        return client.post('/cookie/update/xiaohongshu');
    },

    setXiaohongshuAutoUpdate(enabled, intervalMinutes = 10) {
        return client.post('/cookie/auto-update/xiaohongshu', {
            enabled,
            interval_minutes: intervalMinutes
        });
    },

    // 快手 Cookie
    saveKuaishouCookie(cookieContent) {
        return client.post('/cookie/save/kuaishou', { cookie_content: cookieContent });
    },

    clearKuaishouCookie() {
        return client.delete('/cookie/clear/kuaishou');
    }
};

/**
 * 通知设置 API
 */
export const notificationsApi = {
    // 获取通知设置
    getSettings() {
        return client.get('/notifications/settings');
    },

    // 更新通知设置
    updateSettings(settings) {
        return client.put('/notifications/settings', settings);
    },

    // 测试微信机器人
    testWechatBot(webhookUrl, message = '这条是一条测试通知消息') {
        return client.post('/notifications/test/wechat-bot', { webhook_url: webhookUrl, message });
    },

    // 测试 Server酱³
    testServerChan3(uid, sendkey, message = '这条是一条测试通知消息') {
        return client.post('/notifications/test/serverchan3', { uid, sendkey, message });
    },

    // 测试 Telegram Bot
    testTelegramBot(token, chatId, proxy, message = 'Easy-VDL: 这是一条测试通知') {
        return client.post('/notifications/test/telegram-bot', {
            token,
            chat_id: chatId,
            proxy,
            message
        });
    },

    // 测试 Bark
    testBark(payload) {
        return client.post('/notifications/test/bark', payload);
    },

    // 测试媒体服务器连接
    testMediaServer(serverUrl, apiKey, serverType = 'jellyfin') {
        return client.post('/notifications/test/media-server', {
            server_url: serverUrl,
            api_key: apiKey,
            server_type: serverType
        });
    },

    // 获取通知列表
    getNotifications(skip = 0, limit = 50, status = null, type = null) {
        return client.get('/notifications/', {
            params: { skip, limit, status, notification_type: type }
        });
    },

    // 标记通知已读
    markAsRead(notificationId) {
        return client.put(`/notifications/${notificationId}/read`);
    },

    // 删除通知
    deleteNotification(notificationId) {
        return client.delete(`/notifications/${notificationId}`);
    }
};

/**
 * 背景设置 API
 */
export const backgroundApi = {
    // 获取背景状态
    getStatus() {
        return client.get('/background/status');
    },

    // 设置背景图片
    setBackground(url) {
        return client.post('/background/set', null, { params: { url } });
    },

    // 清除背景图片
    clearBackground() {
        return client.delete('/background/clear');
    },

    // 获取随机网络图片 URL (Unsplash API)
    getRandomImage() {
        // 使用 Unsplash 随机图片 API
        return Promise.resolve({
            url: 'https://source.unsplash.com/random/1920x1080/?nature,landscape'
        });
    }
};

/**
 * 日志查看 API
 */
export const logsApi = {
    // 获取日志文件列表
    getLogFiles() {
        return client.get('/system/logs');
    },

    // 获取日志文件内容
    getLogContent(filename, lines = 200) {
        return client.get(`/system/logs/${filename}`, { params: { lines } });
    },

    // 清除日志文件
    clearLog(filename) {
        return client.delete(`/system/logs/${filename}`);
    },

    // 清除所有日志
    clearAllLogs() {
        return client.delete('/system/logs');
    },

    // 导出日志
    exportLogs() {
        return client.post('/system/logs/export', null, { responseType: 'blob' });
    },

    // 设置日志等级
    setLogLevel(level) {
        return client.post('/system/log-level', { level });
    },

    // 获取当前日志等级
    getLogLevel() {
        return client.get('/system/log-level');
    }
};

export default {
    globalConfigApi,
    cookieApi,
    notificationsApi,
    backgroundApi,
    logsApi
};
