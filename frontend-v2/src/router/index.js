import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { beginRouteLoading, endRouteLoading, cancelRouteLoading } from '@/composables/useRouteLoading'

// 路由配置
const routes = [
  {
    path: '/',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '仪表盘', requiresAuth: true }
  },
  {
    path: '/youtube-bili',
    name: 'youtube-bili',
    component: () => import('../views/YoutubeBili.vue'),
    meta: { title: '油管B站', requiresAuth: true }
  },
  {
    path: '/short-video',
    name: 'short-video',
    component: () => import('../views/ShortVideo.vue'),
    meta: { title: '某音某书', requiresAuth: true }
  },

  {
    path: '/downloads',
    component: () => import('@/views/Downloads.vue'),
    meta: { title: '下载管理', requiresAuth: true }
  },
  {
    path: '/batch-download-tasks',
    component: () => import('@/views/BatchDownloadTasks.vue'),
    meta: { title: '订阅系统任务', requiresAuth: true }
  },
  {
    path: '/subscriptions',
    component: () => import('@/views/Subscriptions.vue'),
    meta: { title: '视频订阅', requiresAuth: true }
  },
  {
    path: '/universal',
    component: () => import('@/views/Universal.vue'),
    meta: { title: '通用解析', requiresAuth: true }
  },
  {
    path: '/netease',
    component: () => import('@/views/Netease.vue'),
    meta: { title: '网易云音乐', requiresAuth: true }
  },

  {
    path: '/player',
    component: () => import('@/views/Player/index.vue'),
    meta: { title: '视频播放', requiresAuth: true }
  },

  {
    path: '/live-timeline/:subId?',
    name: 'live-timeline',
    component: () => import('@/views/LiveTimelineView.vue'),
    meta: { title: '直播回放', requiresAuth: true, noPadding: true }
  },
  {
    path: '/live-highlights',
    name: 'live-highlights',
    component: () => import('@/views/LiveHighlights.vue'),
    meta: { title: '高光切片', requiresAuth: true }
  },

  {
    path: '/live-record',
    component: () => import('@/views/LiveRecord.vue'),
    meta: { title: '直播订阅', requiresAuth: true }
  },
  {
    path: '/settings',
    component: () => import('@/views/Settings.vue'),
    meta: { title: '系统设置', requiresAuth: true, noPadding: true }
  },
  {
    path: '/settings/notifications/wechat',
    component: () => import('@/views/notifications/NotificationWechat.vue'),
    meta: { title: '微信机器人通知', requiresAuth: true }
  },
  {
    path: '/settings/notifications/serverchan',
    component: () => import('@/views/notifications/NotificationServerChan.vue'),
    meta: { title: 'Server酱³ 推送', requiresAuth: true }
  },
  {
    path: '/settings/notifications/bark',
    component: () => import('@/views/notifications/NotificationBark.vue'),
    meta: { title: 'Bark 推送', requiresAuth: true }
  },
  {
    path: '/settings/notifications/telegram',
    component: () => import('@/views/notifications/NotificationTelegram.vue'),
    meta: { title: 'Telegram 机器人', requiresAuth: true }
  },
  {
    path: '/feedback-progress',
    component: () => import('@/views/FeedbackProgress.vue'),
    meta: { title: '开发进度', requiresAuth: true }
  },
  {
    path: '/settings/api-token-guide',
    component: () => import('@/views/ApiTokenGuide.vue'),
    meta: { title: 'API Token 使用说明', requiresAuth: true }
  },
  {
    path: '/settings/telegram-bot-guide',
    component: () => import('@/views/TelegramBotGuide.vue'),
    meta: { title: 'Telegram Bot 功能介绍', requiresAuth: true }
  },
  {
    path: '/login',
    component: () => import('@/views/Login.vue'),
    meta: { hideLayout: true, title: '登录' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()
  const isPageSwitch = from.matched.length > 0 && to.fullPath !== from.fullPath

  if (isPageSwitch) {
    beginRouteLoading(to.path)
  }

  // 设置页面标题
  document.title = `${to.meta.title || 'Easy-VDL'} - Easy-VDL`

  // 认证检查：token 存在不代表有效，先做一次轻量校验
  let isAuthenticated = authStore.isAuthenticated
  if (isAuthenticated) {
    try {
      const valid = await authStore.verifyToken()
      if (!valid) {
        authStore.logout()
        isAuthenticated = false
      }
    } catch (e) {
      authStore.logout()
      isAuthenticated = false
    }
  }

  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)

  if (requiresAuth && !isAuthenticated) {
    // 需要登录但未认证
    next('/login')
  } else if (to.path === '/login' && isAuthenticated) {
    // 已登录但访问登录页，跳转到首页
    next('/')
  } else {
    next()
  }
})

router.afterEach((to, from, failure) => {
  if (failure) {
    cancelRouteLoading()
    return
  }
  endRouteLoading()
})

router.onError(() => {
  cancelRouteLoading()
})

export default router
