import client from './client';

export const chatApi = {
    /**
     * 发送消息给 AI 助手
     * @param {string} message - 用户消息
     * @param {string} [sessionId] - 可选的会话 ID
     * @returns {Promise<{success: boolean, reply: string, actions: Array, session_id: string}>}
     */
    send(message, sessionId = null) {
        return client.post('/chat/send', {
            message,
            session_id: sessionId,
        });
    },

    /**
     * 清除对话历史
     * @param {string} [sessionId] - 可选的会话 ID
     */
    clear(sessionId = null) {
        return client.post('/chat/clear', {
            session_id: sessionId,
        });
    },
};
