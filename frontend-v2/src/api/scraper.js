import client from './client'

export const scraperApi = {
    // --- Short Video (Douyin/TikTok/RedBook) ---

    /**
     * Parse a single short video URL
     * @param {string} url 
     */
    parseShortVideo(url) {
        const isXhs = url.includes('xiaohongshu.com') || url.includes('xhslink.com')
        const endpoint = isXhs ? '/xhs/parse' : '/dyd/parse'
        return client.post(endpoint, { url })
    },

    /**
     * Batch parse short video URLs
     * @param {string[]} urls 
     * @param {number} concurrentLimit 
     */
    parseBatchShortVideo(urls, concurrentLimit = 5) {
        // Note: The legacy backend for batch might be specific to DYD
        // XHS was handled individually in Promise.all in legacy code.
        // For simplicity here, we might need to replicate that logic in the component or here.
        // The backend endpoint `/api/dyd/parse-batch` takes { urls, concurrent_limit }
        return client.post('/dyd/parse-batch', { urls, concurrent_limit: concurrentLimit })
    },

    /**
     * Trigger server-side download for short video
     * @param {string} url 
     * @param {boolean} generateNfo 
     */
    downloadShortVideo(url, generateNfo = true) {
        const isXhs = url.includes('xiaohongshu.com') || url.includes('xhslink.com')
        const endpoint = isXhs ? '/xhs/download' : '/dyd/download'
        return client.post(endpoint, { url, generate_nfo: generateNfo })
    },

    // --- YouTube / Bilibili ---

    /**
     * Get video info for YouTube or Bilibili
     * @param {string} url 
     */
    getYoutubeInfo(url) {
        // Cookies are handled on backend
        return client.post('/ytd/info', {
            url,
            youtube_cookie: '',
            bilibili_cookie: ''
        })
    },

    /**
     * Download YouTube/Bilibili video
     * @param {object} payload { url, format_id, subtitles, thumbnail }
     */
    downloadYoutubeVideo(payload) {
        return client.post('/ytd/download', {
            url: payload.url,
            format_id: payload.format_id,
            youtube_cookie: '',
            bilibili_cookie: '',
            subtitles: payload.subtitles,
            thumbnail: payload.thumbnail
        })
    },

    /**
     * Share video to community
     * @param {object} payload 
     */
    shareToCommunity(payload) {
        return client.post('/community/public/share', payload)
    }
}

