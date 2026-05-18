import client from './client';

export const tasksApi = {
    /**
     * 获取任务列表
     * @param {Object} params - { limit, offset, status, subscription_id, author_name, platform, manual_only }
     */
    getTasks(params = {}) {
        return client.get('/tasks/', { params });
    },

    getTask(taskId) {
        return client.get(`/tasks/${taskId}`);
    },

    deleteTask(taskId, deleteFile = true, deleteRelated = true) {
        return client.delete(`/tasks/${taskId}/`, {
            params: { delete_file: deleteFile, delete_related: deleteRelated }
        });
    },

    retryTask(taskId) {
        return client.post(`/tasks/${taskId}/retry`);
    },

    clearTasks(params = {}, adminSecret = null) {
        const config = { params };
        if (adminSecret) {
            config.headers = { 'X-Admin-Secret': adminSecret };
        }
        return client.delete('/tasks/clear', config);
    },

    getGalleryThumbnail(params = {}) {
        return client.get('/gallery-thumbnail/', { params });
    },

    getGalleryFiles(params = {}) {
        return client.get('/gallery-files/', { params });
    },

    getAuthors(params = {}) {
        return client.get('/tasks/authors/', { params });
    }
};
