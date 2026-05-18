import axios from 'axios';
import router from '@/router';

const client = axios.create({
    baseURL: '/api',
    timeout: 60000, // 增加到 60 秒，解决视频解析超时问题
});

// Request interceptor: Attach JWT token
client.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('token');
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Response interceptor: Handle common errors
client.interceptors.response.use(
    (response) => response.data,
    (error) => {
        if (error.response) {
            const { status } = error.response;
            if (status === 401) {
                // Unauthorized: Clear token and redirect to login (SPA navigation, no full reload)
                localStorage.removeItem('token');
                if (router.currentRoute.value.path !== '/login') {
                    router.push('/login');
                }
            }
        }
        return Promise.reject(error);
    }
);

export default client;
