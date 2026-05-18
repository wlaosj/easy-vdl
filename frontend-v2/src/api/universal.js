import client from './client';

export const universalApi = {
    // 解析 URL
    parse(url) {
        return client.post('/universal/parse', { url });
    },

    // 下载指定格式
    // data: { url, format_id }
    download(data) {
        return client.post('/universal/ytdlp-download', data);
    }
};
