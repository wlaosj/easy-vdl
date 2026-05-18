import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { subscriptionsApi } from '@/api/subscriptions'

export const useSubscriptionsStore = defineStore('subscriptions', () => {
    // 状态
    const subscriptions = ref([])
    const loading = ref(false)
    const error = ref(null)

    // 计算属性
    const activeSubscriptions = computed(() =>
        subscriptions.value.filter(s => s.status === 'active')
    )

    const pausedSubscriptions = computed(() =>
        subscriptions.value.filter(s => s.status === 'paused')
    )

    const errorSubscriptions = computed(() =>
        subscriptions.value.filter(s => s.status === 'error')
    )

    // 按平台分组
    const groupedByPlatform = computed(() => {
        const groups = {}
        subscriptions.value.forEach(sub => {
            const platform = sub.platform || 'other'
            if (!groups[platform]) {
                groups[platform] = []
            }
            groups[platform].push(sub)
        })
        return groups
    })

    const stats = computed(() => ({
        total: subscriptions.value.length,
        active: activeSubscriptions.value.length,
        paused: pausedSubscriptions.value.length,
        error: errorSubscriptions.value.length
    }))

    // Actions
    async function fetchSubscriptions() {
        loading.value = true
        error.value = null
        try {
            const data = await subscriptionsApi.getList()
            // API返回的数据结构可能是 { subscriptions: [...] } 或直接是数组
            subscriptions.value = data.subscriptions || data || []
        } catch (e) {
            error.value = e.message
            console.error('获取订阅列表失败:', e)
            subscriptions.value = [] // 确保有默认值
        } finally {
            loading.value = false
        }
    }

    function updateSubscription(subId, updates) {
        const index = subscriptions.value.findIndex(s => s.id === subId)
        if (index !== -1) {
            subscriptions.value[index] = { ...subscriptions.value[index], ...updates }
        }
    }

    function addSubscription(subscription) {
        subscriptions.value.unshift(subscription)
    }

    function removeSubscription(subId) {
        const index = subscriptions.value.findIndex(s => s.id === subId)
        if (index !== -1) {
            subscriptions.value.splice(index, 1)
        }
    }

    return {
        // State
        subscriptions,
        loading,
        error,
        // Getters
        activeSubscriptions,
        pausedSubscriptions,
        errorSubscriptions,
        groupedByPlatform,
        stats,
        // Actions
        fetchSubscriptions,
        updateSubscription,
        addSubscription,
        removeSubscription
    }
})
