import client from './client';

export const systemApi = {
    getStorageUsage() {
        return client.get('/system/storage-usage');
    },

    getGpuStats(forceRefresh = false) {
        return client.get('/system/gpu-stats', { params: { force_refresh: forceRefresh } });
    },

    getGpuDebugReport() {
        return client.get('/system/gpu-debug-report');
    },

    getTranscodeSettings() {
        return client.get('/system/transcode/settings');
    },

    updateTranscodeSettings(payload) {
        return client.put('/system/transcode/settings', payload);
    },

    getTranscodeProfiles(forceRefresh = false) {
        return client.get('/system/transcode/profiles', { params: { force_refresh: forceRefresh } });
    },

    reprobeTranscodeProfiles() {
        return client.post('/system/transcode/reprobe');
    },

    getCoreVersion(fast = false) {
        return client.get('/system/core-version', { params: { fast } });
    },

    getBuildVersion() {
        return client.get('/build-version');
    },

    getMemoryCurrent() {
        return client.get('/system/memory/current');
    },

    getMemoryHistory() {
        return client.get('/system/memory/history');
    },
    getDatabasePoolStatus() {
        return client.get('/system/database/pool-status');
    },
    getContainerTime() {
        return client.get('/system/time');
    },

    getAnnouncements(limit = 5) {
        return client.get('/community/public/announcements', { params: { limit } });
    },

    getFeedbackProgress(limit = 100, status = '') {
        const params = { limit };
        if (status) params.status = status;
        return client.get('/community/public/feedback-progress', { params });
    },

    getAnnouncementState() {
        return client.get('/announcements/state');
    },

    markAnnouncementsRead() {
        return client.post('/announcements/ack');
    }
};
