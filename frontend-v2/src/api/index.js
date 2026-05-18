import client from './client'

export const downloadsApi = {
    // 获取统计数据
    getStats: () => client.get('/stats'),

    // 获取任务列表
    getTasks: (params) => client.get('/tasks/', { params }),

    // 新建下载任务
    create: (data) => client.post('/download', data),

    // 删除任务
    deleteTask: (id, deleteFile = false) => client.delete(`/tasks/${id}/`, { params: { delete_file: deleteFile } }),

    // 重试任务
    retryTask: (id) => client.post(`/tasks/${id}/retry`),

    // 清空任务
    clearTasks: (type = 'all') => client.post(`/tasks/clear`, { type })
}

export const subscriptionsApi = {
    // 获取订阅列表
    getList: () => client.get('/subscribe/list'),
    // 创建订阅
    create: (data) => client.post('/subscribe/add', data),
    // 删除订阅
    delete: (id) => client.delete(`/subscribe/${id}`),
    // 更新订阅
    update: (id, data) => client.patch(`/subscribe/${id}`, data),
    // 立即同步
    sync: (id) => client.post(`/subscribe/${id}/sync`),
    // 获取订阅下的视频
    getVideos: (id, params) => client.get(`/subscribe/${id}/videos`, { params })
};

export const filesApi = {
    // 获取文件列表 (后端目前主要通过 tasks 列表获取，此处保留 placeholder)
    list: (path = '') => client.get('/files', { params: { path } }),
}

export const systemApi = {
    // 获取存储使用情况
    getStorageUsage: () => client.get('/system/storage-usage'),
    // 获取 GPU 监控数据
    getGpuStats: () => client.get('/system/gpu-stats'),
    // 获取 GPU 调试报告
    getGpuDebugReport: () => client.get('/system/gpu-debug-report'),
    // 获取核心版本
    getCoreVersion: (fast = false) => client.get('/system/core-version', { params: { fast } }),
    getMemoryCurrent: () => client.get('/system/memory/current'),
    // 获取数据库连接池状态
    getDatabasePoolStatus: () => client.get('/system/database/pool-status'),
    // 获取Supervisord状态
    getSupervisorStatus: () => client.get('/system/supervisor/status'),
    // 检测网络连通性
    checkNetwork: () => client.get('/system/network/check')
}

export const authApi = {
    // 登录
    login: (data) => client.post('/auth/login', data),
    // 验证 Token
    verify: (data) => client.post('/auth/verify', data),
    // 获取当前用户
    me: () => client.get('/auth/me')
}

export const licenseApi = {
    // 获取授权状态
    getStatus: () => client.get('/license/status'),
    // 刷新授权
    refresh: () => client.post('/license/refresh'),
    // 获取环境密钥
    getEnvKey: () => client.get('/license/env-key')
}

// 导出设置相关的 API 模块
export {
    globalConfigApi,
    cookieApi,
    notificationsApi,
    backgroundApi,
    logsApi
} from './settings';
