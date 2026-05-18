<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import Layout from './components/layout/Layout.vue'
import Toast from './components/common/Toast.vue'
import FeedbackWidget from './components/common/FeedbackWidget.vue'
import { useToast } from './composables/useToast'
import { useAuthStore } from './stores/auth'
import { useSystemStore } from './stores/system'
import DisclaimerModal from './components/common/DisclaimerModal.vue'
import Dialog from './components/common/Dialog.vue'
import { useDialog } from './composables/useDialog'

import { wsService } from './utils/websocket'

const route = useRoute()
const authStore = useAuthStore()
const systemStore = useSystemStore()
const toastRef = ref(null)
const { setToastInstance } = useToast()
const disclaimerRef = ref(null)
const dialogRef = ref(null)
const { setDialogInstance } = useDialog()
let unregisterGlobalMetrics = null
let stopAuthWatch = null
// 全局页面缓存白名单：除设置中心相关页面外，其他主要业务页面均启用缓存
const keepAliveInclude = [
  'Dashboard',
  'YoutubeBili',
  'ShortVideo',
  'Downloads',
  'BatchDownloadTasks',
  'Subscriptions',
  'Universal',
  'Netease',
  'Player',
  'LiveRecord',
  'LiveHighlights'
]

const showDisclaimer = () => {
  disclaimerRef.value?.open()
}

// 暴露给全局（侧边栏或头部使用）
window.showDisclaimer = showDisclaimer

// 使用 Store 中的响应式 Token，确保登录后能立即触发重绘
const showLayout = computed(() => {
  const hasToken = !!authStore.token
  const isLoginPage = route.path === '/login'
  
  // 如果没有 token 且不是在登录页，不显示布局（可能处于重定向中）
  if (!hasToken && !isLoginPage) return false
  
  // 如果当前是登录页，或者 meta 明确要求隐藏
  if (isLoginPage || route.meta.hideLayout) return false
  
  // 只有已登录且不是登录页才显示
  return true
})

// 初始化
onMounted(() => {
  if (toastRef.value) {
    setToastInstance(toastRef.value)
  }
  if (dialogRef.value) {
    setDialogInstance(dialogRef.value)
  }

  // 初始化主题
  systemStore.initTheme()

  // 初始化系统信息
  systemStore.fetchBuildVersion()
  systemStore.fetchCoreVersion()
  
  // 核心：监听登录状态变化，确保登录后立即初始化全局监控
  stopAuthWatch = watch(() => authStore.isAuthenticated, (isAuth) => {
    // 认证失效时立即清理全局 metrics 监听，避免重复注册
    if (!isAuth) {
      wsService.close('metrics')
      if (unregisterGlobalMetrics) {
        unregisterGlobalMetrics()
        unregisterGlobalMetrics = null
      }
      return
    }

    if (isAuth) {
      wsService.connect('metrics')
      // 1. 初始化公告/状态推送
      systemStore.initAnnouncementsWS()
      
      // 2. 注册全局指标监听器 (metrics 频道)
      // 这样无论是在哪个页面，Store 都能获取到最新的系统状态
      if (unregisterGlobalMetrics) {
        unregisterGlobalMetrics()
      }
      unregisterGlobalMetrics = wsService.onMessage((id, data) => {
        if (id === 'metrics' && data.type === 'metrics') {
          systemStore.handleGlobalMetrics(data.payload)
        }
      })
      
      // 3. 立即通过 HTTP 获取一次初始统计（作为 WebSocket 第一帧到达前的兜底）
      systemStore.fetchStorageUsage()
      systemStore.fetchLicenseStatus()
    }
  }, { immediate: true })

  window.addEventListener('theme-toggle-with-origin', onThemeToggleWithOrigin)
})

onUnmounted(() => {
  if (unregisterGlobalMetrics) {
    unregisterGlobalMetrics()
    unregisterGlobalMetrics = null
  }
  if (stopAuthWatch) {
    stopAuthWatch()
    stopAuthWatch = null
  }
  window.removeEventListener('theme-toggle-with-origin', onThemeToggleWithOrigin)
})

function onThemeToggleWithOrigin(event) {
  const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
  const supportsViewTransition = typeof document.startViewTransition === 'function'
  const isLikelyMobile = Boolean(
    systemStore.isMobile ||
    window.matchMedia?.('(max-width: 768px)')?.matches ||
    window.matchMedia?.('(hover: none) and (pointer: coarse)')?.matches
  )
  if (prefersReducedMotion || !supportsViewTransition || isLikelyMobile) {
    systemStore.toggleTheme()
    return
  }

  const detail = event?.detail || {}
  const x = Number.isFinite(detail.x) ? detail.x : window.innerWidth - 36
  const y = Number.isFinite(detail.y) ? detail.y : 30

  const maxX = Math.max(x, window.innerWidth - x)
  const maxY = Math.max(y, window.innerHeight - y)
  const radius = Math.hypot(maxX, maxY)
  const isSwitchingToDark = systemStore.theme === 'light'
  const reverseClass = 'theme-reverse-transition'
  if (!isSwitchingToDark) {
    document.documentElement.classList.add(reverseClass)
  }
  const transition = document.startViewTransition(() => {
    systemStore.toggleTheme()
  })

  transition.ready.then(() => {
    const clipPath = [
      `circle(0px at ${x}px ${y}px)`,
      `circle(${radius}px at ${x}px ${y}px)`
    ]
    const anim = document.documentElement.animate(
      { clipPath: isSwitchingToDark ? clipPath : [...clipPath].reverse() },
      {
        duration: 1200,
        easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
        pseudoElement: isSwitchingToDark
          ? '::view-transition-new(root)'
          : '::view-transition-old(root)'
      }
    )
    anim.finished.finally(() => {
      document.documentElement.classList.remove(reverseClass)
    })
  }).catch(() => {
    document.documentElement.classList.remove(reverseClass)
    // 忽略动画阶段异常，主题已切换
  })
}
</script>

<template>
  <!-- 直接渲染 Layout 如果需要显示布局 -->
  <Layout v-if="showLayout">
    <router-view v-slot="{ Component, route }">
      <Transition name="page" mode="out-in">
        <Suspense timeout="0">
          <template #default>
            <keep-alive :include="keepAliveInclude">
              <component :is="Component" :key="route.path" />
            </keep-alive>
          </template>
          <template #fallback>
            <div class="route-fallback" aria-live="polite">
              <div class="route-fallback-title"></div>
              <div class="route-fallback-line"></div>
              <div class="route-fallback-line short"></div>
              <div class="route-fallback-cards">
                <div class="route-fallback-card"></div>
                <div class="route-fallback-card"></div>
                <div class="route-fallback-card"></div>
              </div>
            </div>
          </template>
        </Suspense>
      </Transition>
    </router-view>
  </Layout>
  
  <!-- 否则直接渲染页面及其自己的 router-view -->
  <router-view v-else />
  
  <!-- 全局Toast通知 -->
  <Toast ref="toastRef" />

  <!-- 免责声明 -->
  <DisclaimerModal ref="disclaimerRef" v-if="authStore.isAuthenticated" />

  <!-- 全局对话框 -->
  <Dialog ref="dialogRef" />
  
  <!-- 问题反馈组件 (请替换 form-id 为您的真实 Tally Form ID) 
       例如: form-id="3xR0jL"
       您可以在 Tally 发布后的 Share -> Link 中找到这一串字符
  -->
  <FeedbackWidget v-if="authStore.isAuthenticated && systemStore.hasLicense" headless form-id="ob2WdV" />
</template>

<style>
/* App 级别的样式已在 global.css 中定义 */
::view-transition-old(root),
::view-transition-new(root) {
  animation: none;
  mix-blend-mode: normal;
}

html.theme-reverse-transition::view-transition-old(root) {
  z-index: 2;
}

html.theme-reverse-transition::view-transition-new(root) {
  z-index: 1;
}

.route-fallback {
  min-height: 220px;
  padding: 8px;
}

.route-fallback-title,
.route-fallback-line,
.route-fallback-card {
  background: linear-gradient(90deg, rgba(231, 76, 60, 0.08), rgba(249, 203, 40, 0.18), rgba(231, 76, 60, 0.08));
  background-size: 200% 100%;
  animation: route-fallback-shimmer 1.15s linear infinite;
  border-radius: 10px;
}

.route-fallback-title {
  height: 22px;
  width: 220px;
  margin-bottom: 14px;
}

.route-fallback-line {
  height: 12px;
  width: 100%;
  margin-bottom: 10px;
}

.route-fallback-line.short {
  width: 62%;
  margin-bottom: 16px;
}

.route-fallback-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.route-fallback-card {
  height: 90px;
}

@keyframes route-fallback-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

/* 页面切换动画 */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.25s cubic-bezier(0.16, 1, 0.3, 1),
              transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.page-enter-from {
  opacity: 0;
  transform: translateY(12px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
