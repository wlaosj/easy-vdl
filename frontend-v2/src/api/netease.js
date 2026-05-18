import client from './client';

export const neteaseApi = {
    // 解析网易云链接（支持单曲和歌单）
    parse(url) {
        return client.post('/netease/parse', { url }, { timeout: 300000 });
    },

    // 搜索歌曲（依赖后端配置的 NETEASE_SEARCH_API）
    search(params) {
        // params: { keyword, limit?, offset? }
        return client.post('/netease/search', params);
    },

    // 下载指定格式
    // data: { url, format_id, song_id? }
    download(data) {
        return client.post('/netease/download', data);
    },

    // 批量下载
    // data: { songs: [{ url, format_id, song_id, title? }] }
    batchDownload(data) {
        return client.post('/netease/batch-download', data);
    }
};

