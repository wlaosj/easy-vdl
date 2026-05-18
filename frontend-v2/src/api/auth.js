import client from './client';


export const authApi = {
    getInitStatus() {
        return client.get('/auth/init-status');
    },

    login(username, password) {
        return client.post('/auth/login', { username, password });
    },

    verify() {
        return client.get('/auth/verify');
    },

    me() {
        return client.get('/auth/me');
    },

    verifyPassword(password) {
        return client.post('/auth/verify-password', { password });
    },

    register(userData) {
        return client.post('/auth/register', userData);
    },

    // API Token 管理
    createToken(tokenData) {
        return client.post('/auth/tokens', tokenData);
    },

    listTokens() {
        return client.get('/auth/tokens');
    },

    getToken(tokenId) {
        return client.get(`/auth/tokens/${tokenId}`);
    },

    deleteToken(tokenId) {
        return client.delete(`/auth/tokens/${tokenId}`);
    },

    regenerateToken(tokenId) {
        return client.post(`/auth/tokens/${tokenId}/regenerate`);
    },

    updateToken(tokenId, tokenData) {
        return client.patch(`/auth/tokens/${tokenId}`, tokenData);
    }
};
