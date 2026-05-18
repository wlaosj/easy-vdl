import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { tasksApi } from '@/api/tasks'

export const useDownloadsStore = defineStore('downloads', () => {
    // 状态
    const tasks = ref([])
    const loading = ref(true)
    const error = ref(null)

    // 分页状态
    const currentPage = ref(1)
    const pageSize = ref(24) // 适配双列/三列/四列布局，避免最后一行留空
    const totalTasks = ref(0)

    // 过滤器状态
    const currentFilter = ref('all')
    const currentAuthorFilter = ref('')
    const currentPlatformFilter = ref('all')
    const currentManualOnly = ref(false)
    const currentOrphanOnly = ref(false)
    const searchQuery = ref('')

    // 博主列表
    const authorList = ref([])
    const taskCache = ref({})
    const fetchSeq = ref(0)

    // 计算属性
    const activeTasks = computed(() =>
        tasks.value.filter(t => ['DOWNLOADING', 'PROCESSING', 'PENDING'].includes(t.status))
    )

    const completedTasks = computed(() =>
        tasks.value.filter(t => t.status === 'COMPLETED')
    )

    const pendingTasks = computed(() =>
        tasks.value.filter(t => t.status === 'PENDING')
    )

    const errorTasks = computed(() =>
        tasks.value.filter(t => t.status === 'ERROR')
    )

    const cancelledTasks = computed(() =>
        tasks.value.filter(t => t.status === 'CANCELLED')
    )

    const stats = computed(() => ({
        total: totalTasks.value,
        active: activeTasks.value.length,
        completed: completedTasks.value.length,
        pending: pendingTasks.value.length,
        error: errorTasks.value.length,
        cancelled: cancelledTasks.value.length
    }))

    const totalPages = computed(() => Math.ceil(totalTasks.value / pageSize.value))

    const hasActiveFilters = computed(() => {
        return currentFilter.value !== 'all' ||
            currentAuthorFilter.value !== '' ||
            currentPlatformFilter.value !== 'all' ||
            currentManualOnly.value ||
            currentOrphanOnly.value ||
            searchQuery.value !== ''
    })

    // Actions
    async function fetchTasks(page = null) {
        const requestId = ++fetchSeq.value

        if (page !== null) {
            currentPage.value = page
        }

        loading.value = true
        error.value = null
        try {
            const params = {
                limit: pageSize.value,
                offset: (currentPage.value - 1) * pageSize.value
            }

            // 状态过滤
            if (currentFilter.value !== 'all') {
                params.status = currentFilter.value
            }

            // 博主过滤
            if (currentAuthorFilter.value) {
                params.subscription_id = currentAuthorFilter.value
            }

            // 平台过滤
            if (currentPlatformFilter.value && currentPlatformFilter.value !== 'all') {
                params.platform = currentPlatformFilter.value
            }

            // 仅手动任务
            if (currentManualOnly.value) {
                params.manual_only = 'true'
            }

            // 仅孤儿任务
            if (currentOrphanOnly.value) {
                params.orphan_only = 'true'
            }

            // 搜索关键词
            if (searchQuery.value) {
                params.query = searchQuery.value
            }

            const data = await tasksApi.getTasks(params)

            // 只应用最后一次请求的结果，避免旧请求覆盖新筛选
            if (requestId !== fetchSeq.value) return

            tasks.value = data.tasks || []
            totalTasks.value = data.total || 0

            // 缓存任务
            tasks.value.forEach(task => {
                if (task && task.id) {
                    taskCache.value[task.id] = task
                }
            })
        } catch (e) {
            if (requestId !== fetchSeq.value) return
            error.value = e.message
            console.error('获取下载任务失败:', e)
        } finally {
            if (requestId === fetchSeq.value) {
                loading.value = false
            }
        }
    }

    // 获取博主列表
    async function fetchAuthors() {
        try {
            const allAuthors = []
            const pageLimit = 200
            let offset = 0
            let hasMore = true

            while (hasMore) {
                const data = await tasksApi.getAuthors({ limit: pageLimit, offset })
                const chunk = data.authors || []
                allAuthors.push(...chunk)
                hasMore = Boolean(data.pagination?.has_more)
                offset += pageLimit
            }

            // 基于 subscription_id 去重，避免后端或并发导致重复项
            const dedupMap = new Map()
            allAuthors.forEach(author => {
                if (author?.subscription_id && !dedupMap.has(author.subscription_id)) {
                    dedupMap.set(author.subscription_id, author)
                }
            })
            authorList.value = Array.from(dedupMap.values())
            return authorList.value
        } catch (e) {
            console.error('获取博主列表失败:', e)
            return []
        }
    }

    function updateTask(taskId, updates) {
        const index = tasks.value.findIndex(t => t.id === taskId)
        if (index !== -1) {
            tasks.value[index] = { ...tasks.value[index], ...updates }
            // 更新缓存
            taskCache.value[taskId] = tasks.value[index]
        } else {
            // 如果任务不在当前列表中，但在缓存中，更新缓存
            if (taskCache.value[taskId]) {
                taskCache.value[taskId] = { ...taskCache.value[taskId], ...updates }
            }
        }
    }

    function addTask(task) {
        // 检查是否已存在
        const exists = tasks.value.find(t => t.id === task.id)
        if (!exists) {
            tasks.value.unshift(task)
            totalTasks.value++
        }
        // 更新缓存
        if (task && task.id) {
            taskCache.value[task.id] = task
        }
    }

    function removeTask(taskId) {
        const index = tasks.value.findIndex(t => t.id === taskId)
        if (index !== -1) {
            tasks.value.splice(index, 1)
            totalTasks.value = Math.max(0, totalTasks.value - 1)
        }
        // 从缓存中移除
        delete taskCache.value[taskId]
    }

    // WebSocket 进度更新
    function handleProgressUpdate(data) {
        const task = data.task
        if (!task || !task.id) return

        // 注册到缓存
        taskCache.value[task.id] = task

        // 检查任务是否在当前页面
        const existing = tasks.value.find(t => t.id === task.id)
        if (existing) {
            // 更新现有任务
            updateTask(task.id, task)
        } else if (currentPage.value === 1 && !currentOrphanOnly.value && isTaskVisibleUnderFilter(task)) {
            // 新任务且在第一页且符合过滤条件，添加到列表顶部
            addTask(task)
        }
    }

    // 判断任务是否应该在当前过滤器下显示
    function isTaskVisibleUnderFilter(task) {
        if (!task) return false

        const status = (task.status || '').toUpperCase()

        // 状态过滤
        if (currentFilter.value !== 'all') {
            const statusMatch = {
                'active': ['DOWNLOADING', 'PROCESSING', 'PENDING'].includes(status),
                'completed': status === 'COMPLETED',
                'error': status === 'ERROR',
                'cancelled': status === 'CANCELLED'
            }
            if (!statusMatch[currentFilter.value]) return false
        }

        // 博主过滤
        if (currentAuthorFilter.value && task.subscription_id !== currentAuthorFilter.value) {
            return false
        }

        // 平台过滤
        if (currentPlatformFilter.value !== 'all') {
            const taskPlatform = (task.source || 'others').toLowerCase()
            if (taskPlatform !== currentPlatformFilter.value) return false
        }

        // 仅手动任务
        if (currentManualOnly.value && task.subscription_id) {
            return false
        }

        // 仅孤儿任务依赖服务端文件存在性校验，前端无法在实时更新阶段准确判断
        if (currentOrphanOnly.value) {
            return false
        }

        // 搜索过滤
        if (searchQuery.value) {
            const query = searchQuery.value.toLowerCase()
            const title = (task.title || '').toLowerCase()
            const filename = (task.filename || '').toLowerCase()
            const author = (task.author_info?.nickname || '').toLowerCase()
            if (!title.includes(query) && !filename.includes(query) && !author.includes(query)) {
                return false
            }
        }

        return true
    }

    // 设置过滤器
    function setFilter(filter) {
        currentFilter.value = filter
        currentPage.value = 1
        fetchTasks()
    }

    function setAuthorFilter(authorId) {
        currentAuthorFilter.value = authorId
        currentPage.value = 1
        fetchTasks()
    }

    function setPlatformFilter(platform) {
        currentPlatformFilter.value = platform
        currentPage.value = 1
        fetchTasks()
    }

    function setManualOnly(value) {
        currentManualOnly.value = value
        currentPage.value = 1
        fetchTasks()
    }

    function setOrphanOnly(value) {
        currentOrphanOnly.value = value
        currentPage.value = 1
        fetchTasks()
    }

    function setSearchQuery(query) {
        searchQuery.value = query
        currentPage.value = 1
        fetchTasks()
    }

    // 重置所有过滤器
    function resetFilters() {
        currentFilter.value = 'all'
        currentAuthorFilter.value = ''
        currentPlatformFilter.value = 'all'
        currentManualOnly.value = false
        currentOrphanOnly.value = false
        searchQuery.value = ''
        currentPage.value = 1
        fetchTasks()
    }

    // 跳转到指定页
    function goToPage(page) {
        if (page < 1 || page > totalPages.value) return
        currentPage.value = page
        fetchTasks()
    }

    return {
        // State
        tasks,
        loading,
        error,
        currentPage,
        pageSize,
        totalTasks,
        currentFilter,
        currentAuthorFilter,
        currentPlatformFilter,
        currentManualOnly,
        currentOrphanOnly,
        searchQuery,
        authorList,
        taskCache,
        // Getters
        activeTasks,
        completedTasks,
        pendingTasks,
        errorTasks,
        cancelledTasks,
        stats,
        totalPages,
        hasActiveFilters,
        // Actions
        fetchTasks,
        fetchAuthors,
        updateTask,
        addTask,
        removeTask,
        handleProgressUpdate,
        isTaskVisibleUnderFilter,
        setFilter,
        setAuthorFilter,
        setPlatformFilter,
        setManualOnly,
        setOrphanOnly,
        setSearchQuery,
        resetFilters,
        goToPage
    }
})
