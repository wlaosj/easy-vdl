import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
    const user = ref(null)
    const token = ref(localStorage.getItem('token'))
    const isAuthenticated = computed(() => !!token.value)

    async function login(username, password) {
        try {
            const data = await authApi.login(username, password)
            if (data.access_token) {
                token.value = data.access_token
                localStorage.setItem('token', data.access_token)
                await fetchUserInfo()
                return true
            }
            return false
        } catch (err) {
            console.error('Login failed:', err)
            throw err
        }
    }

    async function getInitStatus() {
        try {
            const data = await authApi.getInitStatus()
            return data.initialized
        } catch (err) {
            console.error('Check init status failed:', err)
            throw err
        }
    }

    async function register(username, password) {
        try {
            await authApi.register({ username, password })
            // 注册成功后自动登录
            return await login(username, password)
        } catch (err) {
            console.error('Register failed:', err)
            throw err
        }
    }

    async function fetchUserInfo() {
        if (!token.value) return
        try {
            const data = await authApi.me()
            user.value = data
        } catch (err) {
            console.error('Fetch user info failed:', err)
            logout()
        }
    }

    async function verifyToken() {
        if (!token.value) return false
        try {
            const data = await authApi.verify({ token: token.value })
            return data.valid
        } catch (err) {
            return false
        }
    }

    function logout() {
        user.value = null
        token.value = null
        localStorage.removeItem('token')
    }

    return {
        user,
        token,
        isAuthenticated,
        login,
        fetchUserInfo,
        verifyToken,
        logout,
        getInitStatus,
        register
    }
})
