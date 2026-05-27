import client from './client';

export const licenseApi = {
    getStatus() {
        return client.get('/license/status');
    },

    refresh() {
        return client.post('/license/refresh');
    },

    getEnvKey() {
        return client.get('/license/env-key');
    },

    getCommunityKey() {
        return client.get('/system/community-key');
    },

    saveKey(licenseKey) {
        return client.post('/license/save-key', { license_key: licenseKey });
    }
};
