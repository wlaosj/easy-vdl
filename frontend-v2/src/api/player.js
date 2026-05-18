import client from './client'

export const playerApi = {
    // Get random videos for playback
    // params: { order_by: 'random' | 'date', subscription_id: optional }
    getRandomVideos: (params) => client.get('/random-player/videos', { params }),

    // Video stream encoder status
    getEncoderStatus: () => client.get('/video/encoder', { cache: 'no-store' }),

    // 获取播放记录
    getPlaybackRecord: (subscriptionId) => client.get(`/playback/record/${subscriptionId}`),

    // 保存播放记录
    savePlaybackRecord: (subscriptionId, data) => client.put(`/playback/record/${subscriptionId}`, data),

    // 获取视频元数据（真实时长）
    getVideoMetadata: (filename) => client.get('/video/metadata', { params: { filename } }),

    // 获取视频可用字幕列表（动态扫描）
    getVideoSubtitles: (filename) => client.get('/video/subtitles', { params: { filename } })
}
